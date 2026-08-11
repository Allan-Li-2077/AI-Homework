"""
Skill 编写与优化对比实验

实验流程：
  1. 使用 LLM 根据政策文档编写一个完整的 Skill
  2. 使用 LLM 从 token 消耗角度优化该 Skill
  3. 对比优化前后在 token 数量、结构清晰度、信息完整性等方面的差异

使用方式：
  cd self_evolving_agent
  python src/skill_optimization_experiment.py
"""

import os
import sys
import json
import re
import time
from pathlib import Path
from datetime import datetime
from openai import OpenAI

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "src"))

# ── 配置 ────────────────────────────────────────────────────────────────
POLICIES_PATH = ROOT / "data" / "policies.md"
OUTPUT_DIR = ROOT / "outputs" / "skill_optimization_experiment"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# 选择一个当前 skills/ 中不存在的主题：promotions（促销活动）
SKILL_TOPIC = "promotions"
SKILL_TOPIC_CN = "促销活动规则（满减、新人券、限时特惠等）"

client = OpenAI(
    api_key=os.getenv("DEEPSEEK_API_KEY"),
    base_url="https://api.deepseek.com",
)

# ── Token 估算 ──────────────────────────────────────────────────────────
def estimate_tokens(text: str) -> dict:
    """
    粗略估算 token 数量。
    中文：约 1.5 字符/token，英文：约 4 字符/token。
    返回 {chars, chinese_chars, estimated_tokens, lines}
    """
    chinese_chars = len(re.findall(r'[一-鿿]', text))
    total_chars = len(text)
    # 中文部分按 1.5 字符/token，其余按 4 字符/token
    non_chinese = total_chars - chinese_chars
    estimated = chinese_chars / 1.5 + non_chinese / 4
    return {
        "total_chars": total_chars,
        "chinese_chars": chinese_chars,
        "non_chinese_chars": non_chinese,
        "estimated_tokens": round(estimated),
        "lines": text.count("\n") + 1,
    }

# ── 信息完整性检查 ──────────────────────────────────────────────────────
def check_info_completeness(skill_text: str, policies_text: str) -> dict:
    """检查 Skill 中包含了多少政策中的关键信息点"""
    key_points = [
        # 满减活动
        ("满299减30", "满减档次-299"),
        ("满599减80", "满减档次-599"),
        ("满999减150", "满减档次-999"),
        ("不与", "满减不叠加"),
        ("叠加", "满减不叠加"),
        ("补差价", "退货补差价"),
        ("部分退货", "部分退货规则"),
        # 新人券
        ("新人专享券", "新人券名称"),
        ("20元", "新人券面值"),
        ("100元", "新人券门槛"),
        ("首单", "新人券首单限制"),
        ("不补发", "新人券退款不补"),
        # 限时特惠
        ("限时特惠", "限时特惠概念"),
        ("不可与任何优惠券叠加", "限时特惠不叠加"),
        ("平台最低价", "限时特惠最低价"),
        # 积分
        ("积分倍率", "积分倍率"),
        ("1.5倍", "白卡积分"),
        ("2倍", "银卡积分"),
        ("3倍", "金卡积分"),
    ]
    found = []
    missing = []
    for kw, label in key_points:
        if kw in skill_text:
            found.append(label)
        else:
            missing.append(label)
    return {
        "total_key_points": len(key_points),
        "found": len(found),
        "missing": len(missing),
        "found_list": sorted(set(found)),
        "missing_list": sorted(set(missing)),
    }

# ── 步骤 1：LLM 编写 Skill ──────────────────────────────────────────────
def generate_skill(policies_text: str, topic: str, topic_cn: str) -> str:
    """使用 LLM 根据政策文档生成 Skill"""
    print(f"\n{'='*60}")
    print(f"  步骤 1：LLM 生成 Skill —— {topic_cn}")
    print(f"{'='*60}")

    system_prompt = """你是云购商城客服系统的"技能文档编写专家"。

你的任务是根据给定的政策文档，编写一份结构清晰、内容完整的 SKILL.md 文件。

## 编写要求
1. 使用 Markdown frontmatter（name, description, type, version）
2. 按主题分段，每段有清晰的标题
3. 包含所有数字细节（天数、金额、倍数等）
4. 注意标注优先级和例外情况
5. 使用表格对比不同用户等级的权益差异（如适用）
6. 包含具体示例帮助理解
7. 添加注释标记初始版本

请输出完整的 SKILL.md 内容，不要省略任何政策细节。"""

    user_prompt = f"""## 政策文档

{policies_text}

## 任务
请为「{topic_cn}」编写一份完整的 SKILL.md。
主题：{topic}
注意：这个 Skill 应该涵盖满减活动、新人专享券、限时特惠与优惠券叠加规则、积分倍率等内容。
请做到详尽全面，不要遗漏任何数字和规则细节。"""

    print("  正在调用 LLM 生成 Skill...")
    t0 = time.time()
    response = client.chat.completions.create(
        model="deepseek-chat",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.3,
        max_tokens=4000,
    )
    elapsed = time.time() - t0
    skill_text = response.choices[0].message.content.strip()
    print(f"  ✓ 生成完成，耗时 {elapsed:.1f}s，长度 {len(skill_text)} 字符")

    return skill_text

# ── 步骤 2：LLM 优化 Skill ──────────────────────────────────────────────
def optimize_skill(original_skill: str, policies_text: str) -> str:
    """使用 LLM 从 token 消耗角度优化 Skill"""
    print(f"\n{'='*60}")
    print(f"  步骤 2：LLM 优化 Skill（降低 token 消耗）")
    print(f"{'='*60}")

    system_prompt = """你是云购商城客服系统的"技能优化专家"。

你的任务是对给定的 SKILL.md 进行优化，**在保持所有信息完整的前提下，最大限度降低 token 消耗**。

## 优化策略（按优先级排列）
1. **去除冗余表述**：删除重复说明、啰嗦的修饰词、"请注意""特别提醒"等 filler
2. **精简示例**：保留最有代表性的 1 个示例，删除多余示例
3. **合并同类信息**：将分散在多处的同类规则合并到一个段落/表格
4. **表格替代列表**：能用表格对比的，不用多段文字
5. **紧凑表达**：用简洁的短句替代长句，但保留所有数字和关键约束
6. **去除注释**：删除 HTML 注释（如 <!-- v1: ... -->），只保留必要的版本标记
7. **合并 frontmatter**：description 精简到一行

## 硬性约束（绝对不能违反）
- ❌ 不能删除任何数字（天数、金额、倍数、百分比）
- ❌ 不能删除任何规则条目
- ❌ 不能改变规则的优先级关系
- ❌ 不能丢失例外情况
- ❌ 不能合并不同性质的规则导致歧义
- ✅ 只能改表述方式、排版结构、删除废话

输出优化后的完整 SKILL.md。"""

    user_prompt = f"""## 原始 Skill（需要优化）

{original_skill}

## 原始政策文档（用于核对信息完整性）

{policies_text}

## 任务
请优化上面的 Skill，目标：**token 消耗降低 30% 以上，但信息 100% 完整**。
输出优化后的完整 SKILL.md。"""

    print("  正在调用 LLM 优化 Skill...")
    t0 = time.time()
    response = client.chat.completions.create(
        model="deepseek-chat",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.1,
        max_tokens=4000,
    )
    elapsed = time.time() - t0
    optimized_text = response.choices[0].message.content.strip()
    print(f"  ✓ 优化完成，耗时 {elapsed:.1f}s，长度 {len(optimized_text)} 字符")

    return optimized_text

# ── 步骤 3：对比分析 ────────────────────────────────────────────────────
def compare_versions(original: str, optimized: str, policies_text: str) -> dict:
    """对比优化前后的各项指标"""
    print(f"\n{'='*60}")
    print(f"  步骤 3：对比分析")
    print(f"{'='*60}")

    orig_tokens = estimate_tokens(original)
    opt_tokens = estimate_tokens(optimized)
    orig_info = check_info_completeness(original, policies_text)
    opt_info = check_info_completeness(optimized, policies_text)

    # 计算变化
    token_reduction = orig_tokens["estimated_tokens"] - opt_tokens["estimated_tokens"]
    token_reduction_pct = (token_reduction / orig_tokens["estimated_tokens"] * 100) if orig_tokens["estimated_tokens"] else 0
    char_reduction = orig_tokens["total_chars"] - opt_tokens["total_chars"]
    char_reduction_pct = (char_reduction / orig_tokens["total_chars"] * 100) if orig_tokens["total_chars"] else 0

    # 段落结构分析
    orig_sections = len(re.findall(r'^##\s', original, re.MULTILINE))
    opt_sections = len(re.findall(r'^##\s', optimized, re.MULTILINE))
    orig_tables = len(re.findall(r'\|.*\|.*\|', original))
    opt_tables = len(re.findall(r'\|.*\|.*\|', optimized))

    comparison = {
        "timestamp": datetime.now().isoformat(),
        "skill_topic": SKILL_TOPIC,
        "original": {
            **orig_tokens,
            "sections": orig_sections,
            "table_rows": orig_tables,
            "info_completeness": orig_info,
        },
        "optimized": {
            **opt_tokens,
            "sections": opt_sections,
            "table_rows": opt_tables,
            "info_completeness": opt_info,
        },
        "improvement": {
            "char_reduction": char_reduction,
            "char_reduction_pct": round(char_reduction_pct, 1),
            "token_reduction": token_reduction,
            "token_reduction_pct": round(token_reduction_pct, 1),
            "info_preserved": opt_info["found"] >= orig_info["found"],
        },
    }

    return comparison

# ── 步骤 4：在 Agent 上实测 ──────────────────────────────────────────────
def run_agent_benchmark(skill_text: str, skill_name: str, label: str) -> dict:
    """使用 eval_set 中与促销相关的题目测试 Agent 表现"""
    from skill_manager import SkillManager
    from evaluator import Evaluator
    from agent import CustomerServiceAgent

    # 临时创建 Skill
    SKILLS_DIR = ROOT / "skills"
    temp_skill_dir = SKILLS_DIR / skill_name
    temp_skill_dir.mkdir(parents=True, exist_ok=True)
    skill_file = temp_skill_dir / "SKILL.md"
    skill_file.write_text(skill_text, encoding="utf-8")

    sm = SkillManager(str(SKILLS_DIR))
    agent = CustomerServiceAgent(sm, nudge_interval=0)
    evaluator = Evaluator(str(ROOT / "data" / "eval_set.json"))

    # 只测 promotion 相关题目
    promo_ids = [qid for qid, q in evaluator.questions.items() if q["category"] in ("promotion",)]
    if not promo_ids:
        # fallback 到所有题目做全量测试
        promo_ids = list(evaluator.questions.keys())

    total, correct = 0, 0
    total_time = 0
    results = []
    for qid in promo_ids:
        q = evaluator.questions[qid]
        t0 = time.time()
        answer = agent.answer(q["question"])
        elapsed = time.time() - t0
        total_time += elapsed
        ok, reason = evaluator.evaluate_answer(answer, qid)
        total += 1
        if ok:
            correct += 1
        results.append({"id": qid, "question": q["question"][:60], "answer": answer[:100], "correct": ok, "reason": reason if not ok else ""})

    # 清理
    import shutil
    shutil.rmtree(temp_skill_dir, ignore_errors=True)

    return {
        "label": label,
        "total": total,
        "correct": correct,
        "accuracy": round(correct / total, 3) if total else 0,
        "avg_time_s": round(total_time / total, 2) if total else 0,
        "results": results,
    }

# ── 主流程 ──────────────────────────────────────────────────────────────
def main():
    print("=" * 60)
    print("  Skill 编写与优化对比实验")
    print(f"  主题：{SKILL_TOPIC_CN}")
    print("=" * 60)

    policies_text = POLICIES_PATH.read_text(encoding="utf-8")

    # ── 1. LLM 生成 Skill ──
    original_skill = generate_skill(policies_text, SKILL_TOPIC, SKILL_TOPIC_CN)
    orig_path = OUTPUT_DIR / f"{SKILL_TOPIC}_v1_original.md"
    orig_path.write_text(original_skill, encoding="utf-8")
    print(f"  💾 已保存: {orig_path}")

    # ── 2. LLM 优化 Skill ──
    optimized_skill = optimize_skill(original_skill, policies_text)
    opt_path = OUTPUT_DIR / f"{SKILL_TOPIC}_v2_optimized.md"
    opt_path.write_text(optimized_skill, encoding="utf-8")
    print(f"  💾 已保存: {opt_path}")

    # ── 3. 对比分析 ──
    comparison = compare_versions(original_skill, optimized_skill, policies_text)
    comp_path = OUTPUT_DIR / "comparison_report.json"
    comp_path.write_text(json.dumps(comparison, ensure_ascii=False, indent=2), encoding="utf-8")

    # ── 4. 输出报告 ──
    o = comparison["original"]
    p = comparison["optimized"]
    imp = comparison["improvement"]

    print(f"\n{'='*60}")
    print(f"  📊 对比报告")
    print(f"{'='*60}")

    print(f"\n  ┌─────────────────────────────────────────────────────┐")
    print(f"  │ 指标                │ 优化前     │ 优化后     │ 变化      │")
    print(f"  ├─────────────────────────────────────────────────────┤")
    print(f"  │ 字符数              │ {o['total_chars']:>6}    │ {p['total_chars']:>6}    │ -{imp['char_reduction']:>6}  │")
    print(f"  │ 中文字符            │ {o['chinese_chars']:>6}    │ {p['chinese_chars']:>6}    │           │")
    print(f"  │ 估算 Token 数       │ {o['estimated_tokens']:>6}    │ {p['estimated_tokens']:>6}    │ -{imp['token_reduction']:>6}  │")
    print(f"  │ 行数                │ {o['lines']:>6}    │ {p['lines']:>6}    │           │")
    print(f"  │ 章节数 (##)         │ {o['sections']:>6}    │ {p['sections']:>6}    │           │")
    print(f"  │ 表格行数            │ {o['table_rows']:>6}    │ {p['table_rows']:>6}    │           │")
    print(f"  │ 信息点覆盖率        │ {o['info_completeness']['found']:>2}/{o['info_completeness']['total_key_points']:>2}     │ {p['info_completeness']['found']:>2}/{p['info_completeness']['total_key_points']:>2}     │           │")
    print(f"  └─────────────────────────────────────────────────────┘")

    print(f"\n  📈 关键指标：")
    print(f"     Token 减少：{imp['token_reduction']} tokens ({imp['token_reduction_pct']}%)")
    print(f"     字符减少：  {imp['char_reduction']} chars ({imp['char_reduction_pct']}%)")
    print(f"     信息完整性：{'✅ 保持' if imp['info_preserved'] else '⚠️ 有丢失'}")

    # 统计每一轮 LLM 调用的消耗
    gen_tokens = o["estimated_tokens"]
    opt_tokens_used = p["estimated_tokens"]
    print(f"\n  💰 成本估算（DeepSeek API 价格）：")
    print(f"     生成 Skill 输出：~{gen_tokens} tokens ≈ ¥{gen_tokens * 0.000002:.4f}")  # deepseek-chat ¥2/M input, ¥8/M output (approx)
    print(f"     优化 Skill 输出：~{opt_tokens_used} tokens ≈ ¥{opt_tokens_used * 0.000002:.4f}")
    print(f"     优化节省（每次调用 Skill）：~{imp['token_reduction']} tokens")
    print(f"     如果每天调用 1000 次：每天节省 ~{imp['token_reduction'] * 1000} tokens ≈ ¥{imp['token_reduction'] * 1000 * 0.000001:.2f}")

    if o["info_completeness"]["missing_list"]:
        print(f"\n  ⚠️ 优化前缺失的信息点：{o['info_completeness']['missing_list']}")
    if p["info_completeness"]["missing_list"]:
        print(f"\n  ⚠️ 优化后缺失的信息点：{p['info_completeness']['missing_list']}")

    print(f"\n  📁 所有输出文件：{OUTPUT_DIR}")
    print(f"     - {orig_path.name}")
    print(f"     - {opt_path.name}")
    print(f"     - comparison_report.json")
    print(f"\n{'='*60}")
    print("  实验完成！")
    print(f"{'='*60}")

    return comparison


if __name__ == "__main__":
    if not os.getenv("DEEPSEEK_API_KEY"):
        print("错误: 请先设置 DEEPSEEK_API_KEY 环境变量")
        print("  export DEEPSEEK_API_KEY=your_key")
        sys.exit(1)
    main()
