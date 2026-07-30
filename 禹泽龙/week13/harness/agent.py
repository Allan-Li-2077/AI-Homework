"""Harness Agent：接收用户问题 → 匹配 skill → 调用 function call → 返回结果"""

from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .registry import SkillRegistry
from .skill import Skill, extract_functions_from_skill


# ------------------------------------------------------------------ #
#  LLM Provider 配置（来自原有 agent_skill.py）                        #
# ------------------------------------------------------------------ #
PROVIDERS: dict[str, dict] = {
    "deepseek": {
        "api_key_env": "DEEPSEEK_API_KEY",
        "base_url":    "https://api.deepseek.com",
        "chat_model":  "deepseek-chat",
        "display_name": "DeepSeek V4 Flash",
    },
    "qwen": {
        "api_key_env": "DASHSCOPE_API_KEY",
        "base_url":    "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "chat_model":  "qwen-plus",
        "display_name": "Qwen Plus (DashScope)",
    },
}


def get_provider() -> str:
    return os.getenv("LLM_PROVIDER", "deepseek").lower()


def get_chat_client() -> tuple[Any, str]:
    """返回 (client, model_name)，由 LLM_PROVIDER 环境变量决定"""
    from openai import OpenAI

    provider = get_provider()
    if provider not in PROVIDERS:
        raise ValueError(f"未知 LLM_PROVIDER='{provider}'，可选：{list(PROVIDERS)}")
    cfg = PROVIDERS[provider]
    api_key = os.getenv(cfg["api_key_env"])
    if not api_key:
        raise EnvironmentError(
            f"使用 {cfg['display_name']} 需要设置环境变量 {cfg['api_key_env']}"
        )
    client = OpenAI(api_key=api_key, base_url=cfg["base_url"])
    return client, cfg["chat_model"]


# ------------------------------------------------------------------ #
#  数据结构                                                            #
# ------------------------------------------------------------------ #
@dataclass
class AgentConfig:
    system_prompt: str = (
        "你是一个 AI 助手。当用户提出问题时，如果匹配到某个 skill，"
        "你会调用对应的 function 来完成任务。先推理，再调用 tool。"
    )
    max_turns: int = 10


# ------------------------------------------------------------------ #
#  Harness Agent 主类                                                 #
# ------------------------------------------------------------------ #
class HarnessAgent:
    """
    渐进式加载的 Agent：
    1. 启动时只注册 skill name + description（不加载完整内容）
    2. 用户提问时，根据 query 匹配相关 skill 并加载完整内容
    3. 大模型决定是否调用 function call
    4. 执行 function，返回结果给大模型，循环直到完成
    """

    def __init__(
        self,
        skills_root: str | Path,
        llm_client: Any = None,
        model_name: str = "",
        config: AgentConfig | None = None,
    ):
        self.registry = SkillRegistry(skills_root)

        if llm_client is not None:
            self.llm_client = llm_client
            self.model_name = model_name
        else:
            # 懒加载：未传入 client 时自动用 get_chat_client() 初始化
            self.llm_client, self.model_name = get_chat_client()

        self.config = config or AgentConfig()
        self.messages: list[dict] = []
        self._system_prompt_sent = False

    # ------------------------------------------------------------------ #
    #  核心对话循环                                                       #
    # ------------------------------------------------------------------ #
    def chat(self, user_message: str) -> str:
        """处理用户消息，返回最终回答"""
        # 首次对话：插入 system prompt
        if not self._system_prompt_sent:
            self.messages.insert(0, {"role": "system", "content": self.config.system_prompt})
            self._system_prompt_sent = True

        self.messages.append({"role": "user", "content": user_message})

        for turn in range(self.config.max_turns):
            response = self._call_llm()

            # tool_calls 可能在 message 上，也可能不存在，用 getttr 安全访问
            message = getattr(response, "message", None)
            tool_calls = getattr(message, "tool_calls", None) if message else None

            if tool_calls:
                # 先把 assistant 的 tool_calls 加到消息历史（content 省略，不能是 null）
                assistant_msg: dict[str, Any] = {
                    "role": "assistant",
                    "tool_calls": [
                        {"id": tc.id, "type": "function", "function": {"name": tc.function.name, "arguments": tc.function.arguments}}
                        for tc in tool_calls
                    ],
                }
                self.messages.append(assistant_msg)
                # 再加 tool 结果
                tool_results = self._execute_tool_calls(tool_calls)
                for tc, tr in zip(tool_calls, tool_results):
                    tc_id = getattr(tc, "id", None) or f"call_{id(tc)}"
                    self.messages.append({
                        "role": "tool",
                        "tool_call_id": tc_id,
                        "content": json.dumps(tr, ensure_ascii=False),
                    })
                continue

            # 无 tool call：取文本回复
            assistant_text = getattr(message, "content", None) or ""
            self.messages.append({"role": "assistant", "content": assistant_text})
            return assistant_text

        return "（已达到最大轮次限制）"

    def _call_llm(self) -> Any:
        """调用 LLM，动态注入已加载 skills 的 function definitions"""
        functions = self._build_functions()

        messages_payload = []
        for m in self.messages:
            msg: dict[str, Any] = {"role": m["role"]}
            if "content" in m and m["content"] is not None:
                msg["content"] = m["content"]
            if m["role"] == "tool" and "tool_call_id" in m:
                msg["tool_call_id"] = m["tool_call_id"]
            if m["role"] == "assistant" and "tool_calls" in m:
                msg["tool_calls"] = m["tool_calls"]
            messages_payload.append(msg)
        payload: dict[str, Any] = {
            "model": self.model_name,
            "messages": messages_payload,
        }
        if functions:
            payload["tools"] = functions
            payload["tool_choice"] = "auto"

        response = self.llm_client.chat.completions.create(**payload)
        return response.choices[0]

    def _build_functions(self) -> list[dict]:
        """
        从已加载的 skills 中提取 function definitions，
        转换为 OpenAI tool 格式：{"type": "function", "function": {...}}
        """
        tools = []
        for skill in self.registry.list_skills():
            if skill.is_loaded:
                for fn in extract_functions_from_skill(skill):
                    fn_copy = dict(fn)
                    fn_name = fn_copy.pop("name")
                    fn_desc = fn_copy.pop("description", "")
                    fn_params = fn_copy.pop("parameters", {})
                    fn_copy.pop("source_skill", None)
                    fn_copy.pop("type", None)   # type 只留在外层，不进 function
                    tools.append({
                        "type": "function",
                        "function": {
                            "name": fn_name,
                            "description": fn_desc,
                            "parameters": fn_params,
                            **fn_copy,
                        },
                    })
        return tools

    # ------------------------------------------------------------------ #
    #  Tool 执行                                                          #
    # ------------------------------------------------------------------ #
    def _execute_tool_calls(self, tool_calls: list) -> list[dict]:
        """执行 tool_calls，返回结果列表（与 tool_calls 顺序对应）"""
        results = []
        for tc in tool_calls:
            # OpenAI SDK: tc.function.name, tc.function.arguments
            fn_name = tc.function.name
            raw_args = tc.function.arguments
            args = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
            skill = self._find_skill_by_function(fn_name)

            if not skill:
                results.append({
                    "status": "error",
                    "error": f"未找到 function '{fn_name}' 的定义",
                })
                continue

            result = self._execute_skill_function(skill, fn_name, args)
            results.append({
                "status": "ok",
                "result": result,
            })
        return results

    def _find_skill_by_function(self, fn_name: str) -> Skill | None:
        for skill in self.registry.list_skills():
            if not skill.is_loaded:
                continue
            funcs = extract_functions_from_skill(skill)
            if any(f.get("name") == fn_name for f in funcs):
                return skill
        return None

    def _execute_skill_function(self, skill: Skill, fn_name: str, args: dict) -> Any:
        """执行 skill 中定义的函数，路由到 skill/scripts/ 下的脚本"""
        scripts_dir = skill.path / "scripts"
        if not scripts_dir.exists():
            return {"error": f"skill '{skill.name}' 没有 scripts 目录"}

        for pattern in [f"{fn_name}.py", f"run_{fn_name}.py", "main.py", "main.ts"]:
            script_path = scripts_dir / pattern
            if script_path.exists():
                return self._run_script(script_path, args, skill.name)

        return {"error": f"在 skill '{skill.name}' 中未找到 '{fn_name}' 对应的脚本"}

    def _run_script(self, script_path: Path, args: dict, skill_name: str) -> dict:
        """通过 subprocess 运行脚本，传入 JSON 参数"""
        suffix = script_path.suffix
        cmd: list[str]

        if suffix == ".ts":
            # baoyu-diagram 用 bun/npx bun 运行
            bun_x = self._resolve_bun_x()
            cmd = [bun_x, str(script_path)]
        else:
            cmd = ["python", str(script_path)]

        try:
            result = subprocess.run(
                cmd,
                input=json.dumps(args),
                capture_output=True,
                text=True,
                timeout=120,
            )
            if result.returncode == 0 and result.stdout.strip():
                try:
                    return json.loads(result.stdout.strip())
                except Exception:
                    return {"output": result.stdout.strip()}
            else:
                return {"error": result.stderr.strip() or f"exit code {result.returncode}"}
        except subprocess.TimeoutExpired:
            return {"error": "脚本执行超时（120s）"}
        except FileNotFoundError:
            return {"error": f"未找到运行命令: {cmd[0]}"}
        except Exception as e:
            return {"error": str(e)}

    @staticmethod
    def _resolve_bun_x() -> str:
        """解析 bun 运行时路径，与 baoyu-diagram SKILL.md 约定一致"""
        import shutil
        if shutil.which("bun"):
            return "bun"
        if shutil.which("npx"):
            return "npx -y bun"
        raise EnvironmentError(
            "需要安装 bun 或确保 npx 可用（用于运行 baoyu-diagram skill）"
        )

    # ------------------------------------------------------------------ #
    #  Skill 懒加载触发                                                   #
    # ------------------------------------------------------------------ #
    def prepare_skills_for_query(self, query: str) -> None:
        """根据用户问题预加载相关 skills 的完整内容"""
        relevant = self.registry.find_relevant_skills(query)
        for skill in relevant:
            skill.load()

    # ------------------------------------------------------------------ #
    #  辅助                                                               #
    # ------------------------------------------------------------------ #
    def list_all_skills(self) -> list[dict]:
        """返回所有 skill 的 name + description（不加载完整内容）"""
        return [
            {"name": s.name, "description": s.description}
            for s in self.registry.list_skills()
        ]
