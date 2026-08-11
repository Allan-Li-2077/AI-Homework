"""对比优化前后的 skill token 消耗。

任务：模拟 TRAE 的 skill 路由过程。
- 把 skill 文本作为 system prompt 的一部分喂给大模型
- 给定一组用户天气查询场景
- 对比"原始版 skill"和"优化版 skill"的 token 消耗

运行：
    # 估算模式（无需 API key，用本地估算，标注 real_usage=False）
    python compare.py

    # 真实模式（用 API 返回的真实 token 数）
    $env:LLM_API_KEY="sk-xxx"; $env:LLM_BASE_URL="https://open.bigmodel.cn/api/paas/v4"; $env:LLM_MODEL="glm-4-flash"; python compare.py
"""

from __future__ import annotations

import sys

from llm import LLMClient
from skills_text import ORIGINAL_SKILL, OPTIMIZED_SKILL, ROUTER_SYSTEM


# 对比查询场景：覆盖中文、英文、混合、不相关
SCENARIOS = [
    "北京今天天气怎么样？",
    "查一下上海天气",
    "Tokyo weather please",
    "广州天河区天气预报",
    "shanghai 的湿度是多少",   # 不直接命中但应识别
    "帮我订个闹钟",            # 不相关，应返回 skill=none
]


def run_once(client: LLMClient, skill_text: str, user_msg: str):
    """单次路由调用，返回 ChatResult。"""
    system = ROUTER_SYSTEM.format(skill=skill_text)
    return client.chat(system=system, user=user_msg)


def main() -> int:
    client = LLMClient()
    mode = "真实 API" if client.config.has_key else "本地估算（无 API key）"
    print(f"=== skill token 消耗对比 ===")
    print(f"模型/模式：{client.config.model}  [{mode}]")
    print(f"场景数：{len(SCENARIOS)}")
    print()

    # 表头
    header = f"{'场景':<28} {'原始prompt':>10} {'优化prompt':>10} {'节省':>8}"
    print(header)
    print("-" * len(header))

    orig_total_prompt = opt_total_prompt = 0
    orig_total_completion = opt_total_completion = 0
    orig_total = opt_total = 0
    sample_orig = sample_opt = None

    for msg in SCENARIOS:
        r_orig = run_once(client, ORIGINAL_SKILL, msg)
        r_opt = run_once(client, OPTIMIZED_SKILL, msg)

        orig_total_prompt += r_orig.prompt_tokens
        opt_total_prompt += r_opt.prompt_tokens
        orig_total_completion += r_orig.completion_tokens
        opt_total_completion += r_opt.completion_tokens
        orig_total += r_orig.total_tokens
        opt_total += r_opt.total_tokens

        saved = r_orig.prompt_tokens - r_opt.prompt_tokens
        sign = "+" if saved >= 0 else ""
        # 截断中文场景到 24 显示宽度（粗略，中文2字符宽）
        display = msg if len(msg) <= 14 else msg[:13] + "…"
        print(f"{display:<28} {r_orig.prompt_tokens:>10} {r_opt.prompt_tokens:>10} {sign}{saved:>7}")

        if sample_orig is None:
            sample_orig, sample_opt = r_orig, r_opt

    n = len(SCENARIOS)
    print("-" * len(header))
    print(f"{'合计 prompt_tokens':<28} {orig_total_prompt:>10} {opt_total_prompt:>10} {orig_total_prompt-opt_total_prompt:>+8}")
    print(f"{'合计 completion_tokens':<28} {orig_total_completion:>10} {opt_total_completion:>10} {orig_total_completion-opt_total_completion:>+8}")
    print(f"{'合计 total_tokens':<28} {orig_total:>10} {opt_total:>10} {orig_total-opt_total:>+8}")
    print()

    avg_orig = orig_total / n
    avg_opt = opt_total / n
    saved_pct = (orig_total - opt_total) / orig_total * 100 if orig_total else 0
    print(f"平均每轮 token：原始 {avg_orig:.0f}  →  优化 {avg_opt:.0f}")
    print(f"优化后每轮节省：{avg_orig-avg_opt:.0f} token（{saved_pct:.1f}%）")
    print()

    # 展示一次样例输出
    print("=== 样例输出（首个场景）===")
    print(f"用户：{SCENARIOS[0]}")
    print(f"[原始 skill] 模型回答：{sample_orig.content}")
    print(f"[优化 skill] 模型回答：{sample_opt.content}")
    print(f"数据来源：{'API 真实返回' if sample_orig.real_usage else '本地估算'}")

    if not client.config.has_key:
        print()
        print("提示：当前为估算模式。配置环境变量后可获取真实 token 数：")
        print('  $env:LLM_API_KEY="sk-xxx"')
        print('  $env:LLM_BASE_URL="https://open.bigmodel.cn/api/paas/v4"')
        print('  $env:LLM_MODEL="glm-4-flash"')
    return 0


if __name__ == "__main__":
    sys.exit(main())
