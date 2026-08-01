import json
import os
import re
from pathlib import Path
from openai import OpenAI

BASE_DIR = Path(__file__).parent


def load_env(path: Path):
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


load_env(BASE_DIR / ".env")

API_KEY = os.getenv("LLM_API_KEY", "").strip()
if not API_KEY:
    raise RuntimeError("请打开项目根目录下的 .env，填写 LLM_API_KEY")

MODEL = os.getenv("LLM_MODEL", "deepseek-chat")
client = OpenAI(
    api_key=API_KEY,
    base_url=os.getenv("LLM_BASE_URL", "https://api.deepseek.com"),
)

SKILLS = {
    "daily_report": {
        "schema": {
            "name": "daily_report",
            "description": "用户要求写今天的日报、当日工作总结时使用",
            "input": {"request": "用户提供的当天工作信息"},
        },
        "path": BASE_DIR / "skills" / "daily_report.md",
        "tool": "write_daily_report",
        "prefix": "嘎嘎嘎，我是日报",
    },
    "weekly_report": {
        "schema": {
            "name": "weekly_report",
            "description": "用户要求写本周周报、每周工作总结时使用",
            "input": {"request": "用户提供的一周工作信息"},
        },
        "path": BASE_DIR / "skills" / "weekly_report.md",
        "tool": "write_weekly_report",
        "prefix": "嘎嘎嘎，我是周报",
    },
}

AGENT_SYSTEM = f"""你是一个 ReAct Agent。

你当前只能看到 SKILL Schema，看不到完整 SKILL：
{json.dumps([v['schema'] for v in SKILLS.values()], ensure_ascii=False, indent=2)}

内部动作：
- load_skill：按需加载某个完整 SKILL

业务工具：
- write_daily_report
- write_weekly_report

规则：
1. 先判断应使用哪个 SKILL。
2. 使用业务工具前，必须先调用 load_skill 加载对应 SKILL。
3. 加载后再调用对应业务工具。
4. 业务工具返回报告后，Final Answer 必须原样复制工具结果。
5. 每次只执行一个动作。

严格使用以下格式之一：
Thought: 简短说明当前判断
Action: load_skill
Action Input: {{"skill": "daily_report 或 weekly_report"}}

Thought: 简短说明当前判断
Action: write_daily_report 或 write_weekly_report
Action Input: {{"request": "交给报告工具的完整需求"}}

Thought: 简短说明已经完成
Final Answer: 原样复制工具结果
"""


def preview_skill(text: str) -> str:
    lines = text.splitlines()
    if len(lines) <= 8:
        return text
    return "\n".join(lines[:4] + ["...完整内容已加载，控制台省略中间部分..."] + lines[-3:])


def parse_action(text: str):
    action_match = re.search(r"^Action:\s*(.+)$", text, re.MULTILINE)
    input_match = re.search(r"^Action Input:\s*(.+)$", text, re.MULTILINE | re.DOTALL)
    if not action_match:
        return None, None
    action = action_match.group(1).strip()
    raw = input_match.group(1).strip() if input_match else "{}"
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        payload = {"request": raw.strip('"')}
    return action, payload


def call_agent(messages):
    resp = client.chat.completions.create(
        model=MODEL,
        messages=messages,
        stop=["Observation:"],
        temperature=0,
    )
    return resp.choices[0].message.content.strip()


def call_report_tool(skill_text: str, request: str) -> str:
    resp = client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": skill_text},
            {"role": "user", "content": request},
        ],
        temperature=0.3,
    )
    return resp.choices[0].message.content.strip()


def run(user_input: str):
    messages = [
        {"role": "system", "content": AGENT_SYSTEM},
        {"role": "user", "content": user_input},
    ]
    loaded = {}

    print("\n[初始披露] Agent 只收到两个 SKILL Schema，没有收到完整 SKILL。")

    for step in range(1, 8):
        text = call_agent(messages)
        print(f"\n[Agent 第 {step} 步]\n{text}")
        messages.append({"role": "assistant", "content": text})

        if "Final Answer:" in text:
            return

        action, payload = parse_action(text)

        if action == "load_skill":
            skill_name = payload.get("skill", "")
            config = SKILLS.get(skill_name)
            if not config:
                observation = f"加载失败：不存在 SKILL {skill_name}"
            else:
                skill_text = config["path"].read_text(encoding="utf-8")
                loaded[skill_name] = skill_text
                print(f"\n[程序按需读取完整 SKILL：{skill_name}]\n{preview_skill(skill_text)}")
                observation = f"已加载完整 SKILL：{skill_name}\n\n{skill_text}"

        elif action in {"write_daily_report", "write_weekly_report"}:
            skill_name = "daily_report" if action == "write_daily_report" else "weekly_report"
            if skill_name not in loaded:
                observation = f"执行失败：必须先加载 {skill_name}"
            else:
                request = payload.get("request", user_input)
                body = call_report_tool(loaded[skill_name], request)
                observation = f"{SKILLS[skill_name]['prefix']}\n{body}"
                print(f"\n[业务工具返回，固定开头由程序拼接]\n{observation}")

        else:
            observation = f"未知动作：{action}"

        messages.append({"role": "user", "content": f"Observation:\n{observation}"})

    print("\n超过最大执行步数。")


if __name__ == "__main__":
    while True:
        try:
            user_input = input("\n你：").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if user_input.lower() in {"exit", "quit"}:
            break
        if user_input:
            run(user_input)
