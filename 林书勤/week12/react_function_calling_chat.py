"""
react_function_calling_chat.py — 多轮对话 ReAct Agent

核心改进：从单轮问答到多轮对话记忆

架构设计：
  1. 对话记忆持久化
     - 将 messages 从局部变量提升为实例属性
     - 跨用户轮次保留完整对话历史
  
  2. 单轮 ReAct 循环保持不变
     - 每轮用户输入仍执行完整的工具调用循环
     - Thought → Action → Observation → Answer
  
  3. 上下文累积
     - 工具调用结果写入历史
     - 最终回答写入历史
     - 下一轮自动获得前序信息
  
  4. 命令行交互界面（REPL）
     - 持续接收用户输入
     - 支持多轮连续对话
     - 提供历史重置功能

应用场景：
  - 数据查询 + 深度分析
  - 多维度对比研究
  - 探索式金融调研
  - 基于上下文的追问

技术栈：
  - OpenAI SDK: LLM 调用
  - FAISS: 向量数据库（用于代码检索工具）
  - Sentence-Transformers: 文本嵌入
  - AKShare: A股数据源

使用方式：
  python react_function_calling_chat.py
  python react_function_calling_chat.py --max_steps 8

依赖安装：
  pip install openai faiss-cpu sentence-transformers akshare
  export DEEPSEEK_API_KEY="sk-xxx"
"""

import os
import json
import time
import logging
import argparse
from typing import Generator, List, Dict

from openai import OpenAI

os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")

logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger(__name__)

# client = OpenAI(
#     api_key=os.getenv("DASHSCOPE_API_KEY"),
#     base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
# )
# MODEL = os.getenv("AGENT_MODEL", "qwen-max")
client = OpenAI(
    api_key=os.getenv("DEEPSEEK_API_KEY"),
    base_url="https://api.deepseek.com",
)
MODEL = os.getenv("AGENT_MODEL", "deepseek-v4-flash")

FC_SYSTEM_PROMPT = """你是一个专业的 A 股金融分析助手，正在与用户进行多轮对话。

核心能力：
  • 股票代码查询：通过公司名称获取股票代码
  • 财务指标分析：查询市盈率、营收、利润等关键指标
  • 股价追踪：获取实时或历史股价数据
  • 数值计算：使用计算器进行精确运算

工作流程规则：
  1. 数据查询顺序
     - 必须先使用 company_lookup 获取股票代码
     - 再使用 financial_indicator 或 stock_price 查询具体数据
  
  2. 计算规范
     - 所有数值计算必须调用 calculator 工具
     - 严禁心算或估算
  
  3. 回答要求
     - Final Answer 必须引用具体数据来源
     - 明确标注查询的时间点或时间范围
     - 数据无法获取时，清晰说明原因
  
  4. 多轮对话
     - 结合对话历史理解用户意图
     - 追问时可以引用之前的查询结果
     - 若历史信息已足够，避免重复查询

数据来源声明：
  所有财务数据来自 AKShare 公开接口，仅供学习研究使用。
"""


class ChatAgent:
    """
    支持多轮对话的 ReAct Agent
    
    核心特性：
      - 对话记忆：持久化保存完整对话历史
      - ReAct 循环：每轮执行 Reasoning → Acting → Observing
      - 上下文累积：自动关联前序信息
    
    与单轮模式的关键区别：
      单轮：messages 在函数内部创建，调用结束即销毁
      多轮：messages 作为实例属性，跨调用持久保留
    
    属性：
      max_steps: 单轮最大工具调用步数（防止无限循环）
      messages: 对话历史列表（包含 system/user/assistant/tool 消息）
    
    方法：
      chat(user_input): 处理一轮用户输入，返回生成器
      reset(): 清空对话历史（保留 system prompt）
    """

    def __init__(self, max_steps: int = 10, system_prompt: str = FC_SYSTEM_PROMPT):
        self.max_steps = max_steps
        # 对话记忆：system + 历次 user/assistant/tool 消息持久保留
        self.messages: List[Dict] = [
            {"role": "system", "content": system_prompt},
        ]

    def chat(self, user_input: str) -> Generator[dict, None, None]:
        """
        处理一轮用户输入，生成逐步执行结果
        
        执行流程：
          1. 将用户输入追加到历史
          2. 进入 ReAct 循环：
             - 调用 LLM 判断是否需要工具
             - 若需要：执行工具 → 回填结果 → 继续循环
             - 若不需要：返回最终答案 → 结束
          3. 将最终答案写入历史
        
        Yield 结构：
          {
            "step": 当前步骤编号,
            "type": "action" | "final" | "max_steps",
            "thought": 思考过程（Function Calling 版内部，不可见）,
            "action": 工具名称（type=action 时）,
            "action_input": 工具参数（type=action 时）,
            "observation": 工具返回结果（type=action 时）,
            "answer": 最终答案（type=final 时）
          }
        
        特性：
          - 生成器模式：支持流式输出和中间步骤监控
          - 自动历史管理：无需手动维护 messages
          - 异常容错：工具参数错误时返回友好提示
        """
        from tools import TOOLS_MAP, TOOLS_SCHEMA

        # 记录本轮用户输入到对话历史
        self.messages.append({"role": "user", "content": user_input})

        for step in range(1, self.max_steps + 1):
            response = client.chat.completions.create(
                model=MODEL,
                messages=self.messages,
                tools=TOOLS_SCHEMA,
                tool_choice="auto",
                temperature=0,
            )
            msg    = response.choices[0].message
            reason = response.choices[0].finish_reason

            # 模型决定直接回答（无工具调用）—— 本轮结束
            if reason == "stop" or not msg.tool_calls:
                answer = msg.content or "（模型返回空内容）"
                # 把最终回答写回历史，作为下一轮上下文
                self.messages.append({"role": "assistant", "content": answer})
                yield {
                    "step":   step,
                    "type":   "final",
                    "thought": "",
                    "answer": answer,
                }
                return

            # 模型请求调用工具：先把 assistant 的 tool_calls 消息入历史
            self.messages.append(msg)

            for tool_call in msg.tool_calls:
                tool_name = tool_call.function.name
                try:
                    tool_args = json.loads(tool_call.function.arguments)
                except json.JSONDecodeError:
                    tool_args = {}

                tool_fn = TOOLS_MAP.get(tool_name)
                if tool_fn is None:
                    observation = f"未知工具 '{tool_name}'"
                else:
                    try:
                        observation = tool_fn(**tool_args)
                    except TypeError as e:
                        observation = f"工具参数错误: {e}"

                yield {
                    "step":         step,
                    "type":         "action",
                    "thought":      "",   # Function Calling 版 Thought 在模型内部，不可见
                    "action":       tool_name,
                    "action_input": tool_args,
                    "observation":  str(observation),
                }

                # 工具结果入历史，供模型下一跳消费
                self.messages.append({
                    "role":         "tool",
                    "tool_call_id": tool_call.id,
                    "content":      str(observation),
                })

        yield {
            "step":   self.max_steps + 1,
            "type":   "max_steps",
            "answer": f"已达最大步数 {self.max_steps}，未能得出最终答案",
        }

    def reset(self):
        """
        清空对话历史，重新开始会话
        
        保留：system prompt（第一条消息）
        清除：所有 user/assistant/tool 消息
        
        使用场景：
          - 切换话题时避免上下文干扰
          - 对话过长导致 token 超限
          - 用户明确要求"重新开始"
        """
        self.messages = [{"role": "system", "content": self.messages[0]["content"]}]


# ── CLI 打印（复用 react_function_calling 的彩色输出） ────────────────────────

COLORS = {
    "thought": "\033[36m",
    "action":  "\033[33m",
    "obs":     "\033[32m",
    "final":   "\033[1;93m",   # 加粗亮黄，黑色背景下清晰可读
    "error":   "\033[31m",
    "reset":   "\033[0m",
}

def _c(color: str, text: str) -> str:
    return f"{COLORS[color]}{text}{COLORS['reset']}"


def chat_and_print(agent: ChatAgent, user_input: str):
    """
    执行一轮对话并格式化输出
    
    输出格式：
      - 工具调用步骤：带颜色的 Thought/Action/Observation
      - 最终答案：加粗高亮显示
      - 统计信息：步数、耗时
    
    参数：
      agent: ChatAgent 实例
      user_input: 用户输入文本
    
    返回：
      无（直接打印到控制台）
    """
    start = time.time()
    for step_data in agent.chat(user_input):
        stype = step_data["type"]

        if stype == "action":
            print(f"\n[Step {step_data['step']}]")
            print(_c("thought", "🧠 Thought: （模型内部推理，Function Calling 版不可见）"))
            print(_c("action",  f"🔧 Action:  {step_data['action']}"))
            print(_c("action",  f"   Input:   {json.dumps(step_data['action_input'], ensure_ascii=False)}"))
            print(_c("obs",     f"👁  Obs:     {step_data['observation'][:300]}"))

        elif stype == "final":
            elapsed = time.time() - start
            print(f"\n{'─'*60}")
            print(_c("final", f"\n✅ Final Answer:\n{step_data['answer']}"))
            print(f"\n共 {step_data['step']} 步，耗时 {elapsed:.1f}s")

        elif stype in ("error", "max_steps"):
            print(_c("error", f"\n⚠️  {step_data.get('answer', '')}"))


def main():
    parser = argparse.ArgumentParser(description="多轮对话版 Function Calling ReAct Agent")
    parser.add_argument("--max_steps", type=int, default=10, help="每轮最大工具调用步数")
    args = parser.parse_args()

    agent = ChatAgent(max_steps=args.max_steps)

    print("=" * 60)
    print("A股金融分析助手 · 多轮对话模式")
    print(f"模型: {MODEL}  实现: Function Calling (Multi-turn)")
    print("输入 exit 或 quit 退出；输入 reset 清空对话历史")
    print("=" * 60)

    while True:
        try:
            question = input("\n你: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n再见！")
            break

        if not question:
            continue
        if question.lower() in ("exit", "quit", "退出"):
            print("再见！")
            break
        if question.lower() == "reset":
            agent.reset()
            print(_c("final", "🔁 对话历史已清空"))
            continue

        chat_and_print(agent, question)


if __name__ == "__main__":
    main()
