"""
Skill 执行器（Stage 2 + Stage 3）。

Stage 2：``SkillMeta.load_body`` 懒加载完整 SKILL.md body。
Stage 3：构造 system prompt，tool-calling 循环执行自然语言执行流程，
逐个 dispatch 工具并把结果以 ``role=tool`` 回灌，遇 ``finish`` 立即返回 summary。
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

from . import tools as T
from .llm import LLM
from .loader import SkillMeta

log = logging.getLogger("harness.executor")

__all__ = ["Executor"]

MAX_ITERS = 12

EXECUTOR_SYSTEM = """你是一个 skill 执行器。你的任务是按照下方 SKILL.md 的执行流程，调用提供的工具逐步完成用户请求。

【当前 skill】{skill_name}
【skill 目录】{skill_dir}（相对于项目根 {root}）
【入口脚本】{entry_hint}
【统一输出目录】{output_dir}（相对于项目根；所有产物文件必须放在这里）

【SKILL.md 内容】
{body}

【工具说明】
- list_dir(path): 列出项目根下某目录的文件/子目录。path 相对项目根，默认 "."。
- read_file(path): 读文本文件。不存在会返回错误信息（可用于判断文件是否存在）。
- write_file(path, content): 写文本文件，path 相对项目根，自动建父目录。
- run_command(command): 执行命令。command 为字符串或列表，cwd 为项目根。运行 python 脚本时用 "python <脚本路径> <参数>"。
- open_in_browser(path): 用默认浏览器打开项目根下的本地文件。
- finish(summary): 任务完成后调用，summary 是给用户的中文总结。

【执行约束】
1. 所有路径都相对项目根 {root} 给出（如 ".skill/flash-card/data/crazy.json"）。
2. 优先用 list_dir / read_file 检查所需数据是否已存在；已存在则直接复用，不要重复生成。
3. 严格按 SKILL.md 的执行流程步骤执行，不要跳步、不要编造脚本路径（按 SKILL.md 中给出的命令运行）。
4. 每一步只调用必要的工具；工具结果会反馈给你，据此继续。
5. 全部完成后必须调用 finish，summary 用中文说明做了什么、产出文件在哪里。

【统一输出目录规则（优先级最高，覆盖 SKILL.md 的默认输出位置）】
6. 所有给用户的产物文件（HTML、图片、文档等），必须输出到项目根下的 "{output_dir}/" 目录，绝不允许输出到项目根目录本身或其他位置。
7. 运行脚本时，若脚本支持输出路径参数（如 `-o` / `--output`），必须显式填入 "{output_dir}/<文件名>"。
   示例（flash-card）：不要用默认输出，改为：
     python .skill/flash-card/scripts/make_flashcard.py .skill/flash-card/data/<word>.json -o {output_dir}/<word>.html
8. 使用 open_in_browser 打开产物时，路径也要写 "{output_dir}/<文件名>"。
9. 若 SKILL.md 写"输出到当前工作目录 / 输出到项目根"，一律视为输出到 "{output_dir}/" 目录。
"""


class Executor:
    """带工具的 agent tool-calling 执行循环。"""

    def __init__(self, llm: LLM, root: Path, output_dirname: str = "output"):
        self.llm = llm
        self.root = root
        self.output_dirname = output_dirname
        self.output_dir = root / output_dirname

    def run(self, skill: SkillMeta, user_input: str) -> str:
        """加载 skill body（Stage 2）并执行（Stage 3），返回给用户的总结。"""
        self.output_dir.mkdir(parents=True, exist_ok=True)
        body = skill.load_body()
        skill_dir = (
            skill.dir.relative_to(self.root).as_posix()
            if skill.dir.resolve() != self.root.resolve()
            else "."
        )
        sys_prompt = EXECUTOR_SYSTEM.format(
            skill_name=skill.name,
            skill_dir=skill_dir,
            entry_hint=skill.entry or "(未声明)",
            output_dir=self.output_dirname,
            body=body,
            root=self.root.resolve().as_posix(),
        )
        messages: list[dict] = [
            {"role": "system", "content": sys_prompt},
            {"role": "user", "content": user_input},
        ]

        for i in range(MAX_ITERS):
            try:
                resp = self.llm.chat(messages, tools=T.SCHEMAS, temperature=0.2)
            except Exception as e:  # noqa: BLE001
                log.error("executor LLM call failed: %s", e)
                return f"执行中断：LLM 调用失败 ({type(e).__name__}: {e})"

            msg = resp.choices[0].message
            # 手工构造 assistant 消息，确保 tool_calls 结构正确回传
            assistant_msg: dict = {"role": "assistant", "content": msg.content}
            if msg.tool_calls:
                assistant_msg["tool_calls"] = [
                    tc.model_dump(exclude_none=True) for tc in msg.tool_calls
                ]
            messages.append(assistant_msg)

            if not msg.tool_calls:
                # 没调工具直接回文本——视为提前结束
                return msg.content or "(executor 无输出)"

            for tc in msg.tool_calls:
                name = tc.function.name
                args = self._parse_args(tc.function.arguments)
                result = self._dispatch(name, args)
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": result,
                })
                if name == "finish":
                    return str(args.get("summary", "(已完成)"))

        log.warning("[stage3] hit MAX_ITERS=%d, force stop", MAX_ITERS)
        return "(达到最大迭代次数，执行中止)"

    @staticmethod
    def _parse_args(raw: str | None) -> dict:
        if not raw:
            return {}
        try:
            return json.loads(raw)
        except json.JSONDecodeError as e:
            # 常见故障：LLM 在长 JSON-in-JSON 的 content 里写了非法转义（如 \' 或裸换行）。
            # 严格 loads 会整段丢弃，逼模型重试、白烧 token。这里先尝试宽松修复。
            recovered = Executor._recover_args(raw)
            if recovered is not None:
                log.warning("tool arguments not strict JSON (%s), recovered leniently", e)
                return recovered
            log.warning("tool arguments not valid JSON (%s): %.200r", e, raw)
            return {}

    @staticmethod
    def _recover_args(raw: str) -> dict | None:
        """宽松修复非法 JSON 的 tool arguments。

        策略：把最常见的两类非法转义就地清洗后重试 ``json.loads``：
          1. ``\\'`` → ``'``（单引号本不需要转义，JSON 规范里非法）；
          2. 其余落单的 ``\\x``（x 不是合法转义字符）→ 去掉反斜杠。
        仅在能解析成 dict 时返回，否则返回 None。
        """
        import re

        cleaned = raw.replace("\\'", "'")
        # 合法 JSON 转义字符集合：" \ / b f n r t u；其余落单反斜杠去掉
        cleaned = re.sub(r'\\(?!["\\/bfnrtu])', "", cleaned)
        try:
            data = json.loads(cleaned)
        except json.JSONDecodeError:
            return None
        return data if isinstance(data, dict) else None


    def _dispatch(self, name: str, args: dict) -> str:
        """分发到具体工具；异常转字符串反馈给 LLM 自我纠正。"""
        root = self.root
        try:
            if name == "list_dir":
                return T.list_dir(args.get("path", "."), root=root)
            if name == "read_file":
                return T.read_file(args.get("path", ""), root=root)
            if name == "write_file":
                return T.write_file(args.get("path", ""), args.get("content", ""), root=root)
            if name == "run_command":
                return T.run_command(args.get("command") or args.get("cmd"), root=root)
            if name == "open_in_browser":
                return T.open_in_browser(args.get("path", ""), root=root)
            if name == "finish":
                return "OK"
            return f"ERROR: unknown tool {name}"
        except Exception as e:  # noqa: BLE001
            return f"ERROR: {type(e).__name__}: {e}"
