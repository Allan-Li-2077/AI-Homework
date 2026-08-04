"""
交互式 REPL
启动时加载所有 skill 元数据
"""
from __future__ import annotations

import logging
from pathlib import Path

from .executor import Executor
from .llm import LLM
from .loader import SkillRegistry
from .selector import Selector

log = logging.getLogger("harness.cli")

__all__ = ["REPL"]

_HISTORY_LIMIT = 20


_OUTPUT_DIRNAME = "output"


class REPL:
    def __init__(self, root: Path):
        self.root = root
        self.output_dir = root / _OUTPUT_DIRNAME
        self.llm = LLM()
        self.registry = SkillRegistry(root)
        self.selector = Selector(self.llm, self.registry)
        self.executor = Executor(self.llm, root, output_dirname=_OUTPUT_DIRNAME)
        self.history: list[dict] = []

    def start(self):
        self.output_dir.mkdir(parents=True, exist_ok=True)
        log.info("output dir ready: %s", self.output_dir)
        print("正在加载 skills ...")
        skills = self.registry.load_all()
        print(f"已加载 {len(skills)} 个 skill：")
        for s in skills:
            print(f"  - {s.name}  (kind={s.kind}, manual={s.manual})")
        print("输入 /help 查看命令，/quit 退出。\n")

        while True:
            try:
                line = input(">>> ").strip()
            except (EOFError, KeyboardInterrupt):
                print("\nbye")
                break
            if not line:
                continue
            if line.startswith("/"):
                if not self.handle_command(line):
                    break
                continue
            self.handle_user(line)

    def handle_command(self, line: str) -> bool:
        """处理 / 命令。返回 False 表示退出 REPL。"""
        parts = line.split(maxsplit=1)
        cmd = parts[0]
        rest = parts[1] if len(parts) > 1 else ""
        if cmd in ("/quit", "/exit"):
            print("bye")
            return False
        if cmd == "/help":
            print("命令：/skills  /reload  /show <name>  /help  /quit")
        elif cmd == "/skills":
            for s in self.registry.all():
                print(f"  {s.index_line()}")
        elif cmd == "/reload":
            self.registry.load_all()
            print(f"已重新扫描 .skill/，共 {len(self.registry.names())} 个 skill")
        elif cmd == "/show":
            if not rest:
                print("用法：/show <skill-name>")
            else:
                m = self.registry.get(rest.strip())
                if m:
                    print(m.load_body())
                else:
                    print(f"未找到 skill: {rest}")
        else:
            print(f"未知命令: {cmd}（/help 查看可用命令）")
        return True

    def handle_user(self, user_input: str):
        skill = self.selector.select(user_input, self.history)
        if skill is None:
            print("(未匹配 skill，进入普通对话)")
            print(self.plain_chat(user_input))
            return
        print(f"[匹配 skill: {skill.name}] 开始执行 ...")
        summary = self.executor.run(skill, user_input)
        print(f"[执行完成] {summary}")
        # 只把用户请求 + 摘要回灌历史，不回灌 tool trace，避免污染上下文
        self.history.append({"role": "user", "content": user_input})
        self.history.append({"role": "assistant", "content": f"[skill:{skill.name}] {summary}"})

    def plain_chat(self, user_input: str) -> str:
        self.history.append({"role": "user", "content": user_input})
        messages = [{"role": "system", "content": "你是一个通用助手。"}] + self.history
        try:
            resp = self.llm.chat(messages, temperature=0.3)
        except Exception as e:  # noqa: BLE001
            self.history.append({"role": "assistant", "content": f"(调用失败: {e})"})
            return f"(调用失败: {e})"
        reply = resp.choices[0].message.content or ""
        self.history.append({"role": "assistant", "content": reply})
        if len(self.history) > _HISTORY_LIMIT:
            self.history = self.history[-_HISTORY_LIMIT:]
        return reply
