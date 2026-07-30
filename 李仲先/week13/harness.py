"""
可加载 SKILL 的 Harness —— 渐进式披露（Progressive Disclosure）版

核心思想：
  - 第一层（始终在 prompt 里）：只放每个 SKILL 的 name + description（目录/索引）
  - 第二层（按需加载）：模型判断相关后，调用 load_skill 工具获取完整 body
  - 模型驱动：由 LLM 看着目录自主决定加载哪个 SKILL，而非规则匹配

流程（Function Calling 循环）：
  1. system prompt = 基础指令 + SKILL 目录（仅 name+desc）
  2. 暴露 load_skill(name) 作为工具
  3. 用户提问 → 模型决定调用 load_skill → harness 返回 body → 模型按指令回答
  4. 无 API Key 时用 mock 模拟整个流程（本地关键词匹配替代模型决策）

SKILL 格式：
  skills/
  └── my-skill/
      └── SKILL.md          # YAML frontmatter (name, description, triggers) + Markdown 正文

使用方式：
  python harness.py list                           # 列出所有已加载的 SKILL
  python harness.py show code-review               # 查看某个 SKILL 详情
  python harness.py match "帮我审查一下代码"          # 规则匹配（仅用于调试/mock）
  python harness.py run "帮我写单元测试"             # 渐进式披露（有 Key 调 LLM，无 Key 走 mock）
  python harness.py run "帮我写测试" --mock          # 强制走 mock 模拟

环境变量（可选）：
  DEEPSEEK_API_KEY   有则调用真实 LLM，无则自动走 mock
  AGENT_MODEL         默认 deepseek-chat
"""

import os
import re
import sys
import json
import time
import argparse
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")

SKILLS_DIR = Path(__file__).parent / "skills"

COLORS = {
    "name":    "\033[1;36m",
    "desc":    "\033[2;37m",
    "trigger": "\033[33m",
    "body":    "\033[0m",
    "match":   "\033[1;32m",
    "prompt":  "\033[36m",
    "tool":    "\033[33m",
    "answer":  "\033[35m",
    "warn":    "\033[33m",
    "err":     "\033[31m",
    "reset":   "\033[0m",
    "bold":    "\033[1m",
    "dim":     "\033[2m",
}


def _c(color: str, text: str) -> str:
    return f"{COLORS[color]}{text}{COLORS['reset']}"


# ── SKILL 解析 ──────────────────────────────────────────────────────────────

@dataclass
class Skill:
    name: str
    description: str
    triggers: list[str] = field(default_factory=list)
    body: str = ""
    path: Path = field(default_factory=lambda: Path("."))

    def summary(self) -> str:
        trig = ", ".join(self.triggers) if self.triggers else "（无）"
        return (
            f"{_c('name', self.name)}  "
            f"{_c('desc', self.description[:60])}  "
            f"[{trig}]"
        )

    def detail(self) -> str:
        lines = [
            _c("bold", f"SKILL: {self.name}"),
            f"  路径:   {self.path}",
            f"  描述:   {self.description}",
            f"  触发词: {', '.join(self.triggers) if self.triggers else '（无）'}",
            f"  ── 正文 ──",
            self.body.strip(),
        ]
        return "\n".join(lines)


def parse_frontmatter(text: str) -> tuple[dict, str]:
    """解析 YAML frontmatter（不依赖 pyyaml）。"""
    if not text.startswith("---"):
        return {}, text

    end = text.find("---", 3)
    if end == -1:
        return {}, text

    fm_text = text[3:end].strip()
    body = text[end + 3:].strip()

    meta: dict = {}
    current_key: Optional[str] = None
    current_list: list[str] = []

    for line in fm_text.splitlines():
        line_stripped = line.strip()

        if line_stripped.startswith("- "):
            if current_key is not None:
                current_list.append(line_stripped[2:].strip())
            continue

        m = re.match(r"^(\w+)\s*:\s*(.*)", line_stripped)
        if m:
            if current_key is not None and current_list:
                meta[current_key] = current_list

            current_key = m.group(1)
            value = m.group(2).strip()
            if value:
                meta[current_key] = value
                current_list = []
            else:
                current_list = []
            continue

    if current_key is not None and current_list:
        meta[current_key] = current_list

    return meta, body


def load_skill(skill_dir: Path) -> Optional[Skill]:
    """从目录加载一个 SKILL（查找 SKILL.md 或 README.md）"""
    for fname in ("SKILL.md", "README.md"):
        md_path = skill_dir / fname
        if md_path.is_file():
            break
    else:
        return None

    text = md_path.read_text(encoding="utf-8")
    meta, body = parse_frontmatter(text)

    name = meta.get("name", skill_dir.name)
    description = meta.get("description", "")
    triggers = meta.get("triggers", [])
    if isinstance(triggers, str):
        triggers = [triggers]

    return Skill(
        name=name,
        description=description,
        triggers=triggers,
        body=body,
        path=skill_dir,
    )


# ── SKILL 注册表 ──────────────────────────────────────────────────────────

class SkillRegistry:
    def __init__(self):
        self._skills: dict[str, Skill] = {}

    def load_dir(self, directory: Path) -> int:
        count = 0
        if not directory.is_dir():
            return 0
        for child in sorted(directory.iterdir()):
            if child.is_dir():
                skill = load_skill(child)
                if skill is not None:
                    self._skills[skill.name] = skill
                    count += 1
        return count

    def get(self, name: str) -> Optional[Skill]:
        return self._skills.get(name)

    def list_skills(self) -> list[Skill]:
        return list(self._skills.values())

    def match(self, query: str, top_k: int = 3) -> list[tuple[Skill, float]]:
        """规则匹配（仅用于 mock 模拟模型决策 + 调试）。"""
        q = query.lower()
        q_chars = {ch for ch in q if ch.isalnum()}
        q_words = set(re.findall(r"[a-z]+", q))

        scored: list[tuple[Skill, float]] = []
        for skill in self._skills.values():
            skill_text = f"{skill.name} {skill.description} {' '.join(skill.triggers)}".lower()
            s_chars = {ch for ch in skill_text if ch.isalnum()}
            s_words = set(re.findall(r"[a-z]+", skill_text))

            score = 0.0
            for trig in skill.triggers:
                if trig.lower() in q:
                    score += 0.5
            if skill.name.lower() in q:
                score += 0.5
            if q_chars and s_chars:
                score += len(q_chars & s_chars) / len(q_chars | s_chars)
            if q_words and s_words:
                score += len(q_words & s_words) / len(q_words | s_words)

            if score > 0:
                scored.append((skill, score))

        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:top_k]


# ── 渐进式披露：System Prompt 只放目录 ─────────────────────────────────────

def build_catalog_system_prompt(registry: SkillRegistry) -> str:
    """
    第一层：只把每个 SKILL 的 name + description 放进 system prompt。
    完整 body 不在这里 —— 模型需要时自己调 load_skill 加载。
    """
    catalog_lines = []
    for skill in registry.list_skills():
        catalog_lines.append(f"  - {skill.name}: {skill.description}")

    return f"""你是一个智能助手。你可以使用以下 SKILL 来更好地回答问题。

## 可用 SKILL 目录
{chr(10).join(catalog_lines)}

## 使用规则
- 如果某个 SKILL 与用户问题相关，请调用 load_skill 工具加载它的完整指令
- 加载后，严格按照 SKILL 指令的流程工作
- 如果没有相关 SKILL，直接回答即可，不要强行加载
- 一次只加载最相关的一个 SKILL"""


def build_load_skill_tool(registry: SkillRegistry) -> list[dict]:
    """load_skill 工具的 function calling schema"""
    skill_names = [s.name for s in registry.list_skills()]
    return [
        {
            "type": "function",
            "function": {
                "name": "load_skill",
                "description": "加载某个 SKILL 的完整指令。先看目录判断哪个相关，再调用此工具。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "name": {
                            "type": "string",
                            "enum": skill_names,
                            "description": "要加载的 SKILL 名称",
                        }
                    },
                    "required": ["name"],
                },
            },
        }
    ]


def execute_load_skill(registry: SkillRegistry, name: str) -> str:
    """执行 load_skill 工具：返回该 SKILL 的完整 body（第二层披露）"""
    skill = registry.get(name)
    if skill is None:
        return f"错误：未找到 SKILL '{name}'"
    return skill.body.strip()


# ── LLM 客户端 ────────────────────────────────────────────────────────────

def get_llm_client_and_model(model: str = None):
    """返回 (client, model) 或 (None, None)"""
    api_key = os.getenv("DEEPSEEK_API_KEY") or os.getenv("DASHSCOPE_API_KEY")
    if not api_key:
        return None, None

    from openai import OpenAI

    if os.getenv("DEEPSEEK_API_KEY"):
        client = OpenAI(api_key=api_key, base_url="https://api.deepseek.com")
        model = model or os.getenv("AGENT_MODEL", "deepseek-chat")
    else:
        client = OpenAI(
            api_key=api_key,
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        )
        model = model or os.getenv("AGENT_MODEL", "qwen-max")
    return client, model


# ── 渐进式披露：真实 LLM 循环 ──────────────────────────────────────────────

def run_progressive(registry: SkillRegistry, user_query: str, model: str = None, max_steps: int = 5):
    """渐进式披露主循环：模型自主决定加载哪个 SKILL"""
    client, resolved_model = get_llm_client_and_model(model)

    if client is None:
        run_progressive_mock(registry, user_query)
        return

    messages = [
        {"role": "system", "content": build_catalog_system_prompt(registry)},
        {"role": "user", "content": user_query},
    ]
    tools = build_load_skill_tool(registry)

    print(f"\n{'='*60}")
    print(f"模式:   渐进式披露（真实 LLM）")
    print(f"模型:   {resolved_model}")
    print(f"问题:   {user_query}")
    print(f"{'='*60}")

    print(_c("prompt", "\n── 第一层：System Prompt（仅 SKILL 目录）──"))
    print(_c("dim", messages[0]["content"][:500]))
    print()

    start = time.time()
    loaded_skills: list[str] = []

    for step in range(1, max_steps + 1):
        response = client.chat.completions.create(
            model=resolved_model,
            messages=messages,
            tools=tools,
            tool_choice="auto",
            temperature=0,
        )
        msg = response.choices[0].message
        reason = response.choices[0].finish_reason

        # 模型决定直接回答
        if reason == "stop" or not msg.tool_calls:
            elapsed = time.time() - start
            print(f"\n{'─'*60}")
            if loaded_skills:
                print(_c("tool", f"本次加载了 SKILL: {', '.join(loaded_skills)}"))
            print(_c("answer", f"\n✅ 最终回答:\n{msg.content}"))
            print(f"\n共 {step} 步，耗时 {elapsed:.1f}s")
            return

        # 模型请求调用工具
        messages.append(msg)

        for tool_call in msg.tool_calls:
            tool_name = tool_call.function.name
            try:
                tool_args = json.loads(tool_call.function.arguments)
            except json.JSONDecodeError:
                tool_args = {}

            if tool_name == "load_skill":
                skill_name = tool_args.get("name", "")
                print(_c("tool", f"\n[Step {step}] 模型调用 load_skill({skill_name!r})"))

                # 第二层：返回完整 body
                skill_body = execute_load_skill(registry, skill_name)
                loaded_skills.append(skill_name)

                print(_c("prompt", f"  → 第二层：返回完整 body（{len(skill_body)} 字符）"))
                print(_c("dim", f"  {skill_body[:150]}..."))

                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": skill_body,
                })
            else:
                print(_c("warn", f"\n[Step {step}] 未知工具: {tool_name}"))
                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": f"未知工具: {tool_name}",
                })

    print(_c("warn", f"\n⚠️  已达最大步数 {max_steps}"))


# ── 渐进式披露：Mock 模拟（无 API Key） ────────────────────────────────────

def run_progressive_mock(registry: SkillRegistry, user_query: str):
    """
    无 API Key 时模拟渐进式披露流程：
    用规则匹配替代模型的 load_skill 决策，展示两层披露的完整交互。
    """
    print(f"\n{'='*60}")
    print(f"模式:   渐进式披露（Mock 模拟，无 API Key）")
    print(f"问题:   {user_query}")
    print(f"{'='*60}")

    # 第一层：system prompt 只有目录
    system_prompt = build_catalog_system_prompt(registry)
    print(_c("prompt", "\n── 第一层：System Prompt（仅 SKILL 目录，省 token）──"))
    print(_c("dim", system_prompt))
    print()

    # 模拟模型决策：用规则匹配替模型选 skill
    matches = registry.match(user_query, top_k=1)

    if not matches:
        print(_c("warn", "【模拟】模型判断：无相关 SKILL，直接回答"))
        print(_c("answer", "\n✅ （模拟）模型直接回答（未加载任何 SKILL）"))
        print(_c("warn", "\n⚠️  这是模拟输出。设置 DEEPSEEK_API_KEY 或 DASHSCOPE_API_KEY 可调用真实 LLM。"))
        return

    skill, score = matches[0]
    print(_c("tool", f"【模拟】模型看着目录判断：'{user_query}' 与 [{skill.name}] 最相关"))
    print(_c("tool", f"【模拟】模型调用 load_skill({skill.name!r})"))

    # 第二层：返回完整 body
    body = execute_load_skill(registry, skill.name)
    print(_c("prompt", f"\n── 第二层：load_skill 返回完整 body（{len(body)} 字符）──"))
    print(_c("dim", body))

    print(_c("answer", f"\n✅ （模拟）模型按 [{skill.name}] 指令生成回答"))
    print(_c("warn", "\n⚠️  这是模拟输出。设置 DEEPSEEK_API_KEY 或 DASHSCOPE_API_KEY 可调用真实 LLM。"))


# ── CLI ────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="可加载 SKILL 的 Harness（渐进式披露）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python harness.py list
  python harness.py show code-review
  python harness.py match "帮我审查一下代码"
  python harness.py run "帮我写单元测试"           # 有 Key 调 LLM，无 Key 走 mock
  python harness.py run "帮我审查代码" --mock       # 强制 mock
        """,
    )
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("list", help="列出所有已加载的 SKILL")

    show_p = sub.add_parser("show", help="查看某个 SKILL 详情")
    show_p.add_argument("name", help="SKILL 名称")

    match_p = sub.add_parser("match", help="规则匹配（调试/mock 用）")
    match_p.add_argument("query", help="匹配查询文本")
    match_p.add_argument("--top_k", type=int, default=3)

    run_p = sub.add_parser("run", help="渐进式披露执行")
    run_p.add_argument("query", help="用户问题")
    run_p.add_argument("--mock", action="store_true", help="强制 mock 模式（不调 LLM）")
    run_p.add_argument("--model", default=None, help="模型名称")
    run_p.add_argument("--max_steps", type=int, default=5)

    args = parser.parse_args()

    registry = SkillRegistry()
    count = registry.load_dir(SKILLS_DIR)

    if count == 0:
        print(_c("warn", f"未在 {SKILLS_DIR} 中找到任何 SKILL"))
        print("请确保 skills/ 目录下有子目录，每个子目录包含 SKILL.md")
        sys.exit(1)

    if args.command is None or args.command == "list":
        print(f"\n已加载 {count} 个 SKILL（目录: {SKILLS_DIR}）\n")
        for skill in registry.list_skills():
            print(f"  {skill.summary()}")
        print()

    elif args.command == "show":
        skill = registry.get(args.name)
        if skill is None:
            print(_c("err", f"未找到 SKILL: {args.name}"))
            sys.exit(1)
        print(skill.detail())

    elif args.command == "match":
        matches = registry.match(args.query, top_k=args.top_k)
        if not matches:
            print(_c("warn", "没有匹配到任何 SKILL"))
        else:
            print(f"\n查询: {_c('bold', args.query)}\n")
            for skill, score in matches:
                print(f"  {_c('match', f'{score:.2f}')}  {skill.summary()}")
            print()

    elif args.command == "run":
        if args.mock:
            run_progressive_mock(registry, args.query)
        else:
            run_progressive(registry, args.query, model=args.model, max_steps=args.max_steps)


if __name__ == "__main__":
    main()
