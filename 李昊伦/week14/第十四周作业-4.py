"""
CRM 推账金额核对脚本 v2
优化点：
  1. 多币种支持（USD / VND 分别核对）
  2. 逐笔匹配（按凭证编号+汇总号）
  3. 四舍五入差异自动识别
  4. 自动生成结构化报告
  5. 无硬编码路径，命令行传参或自动查找
"""

import sys
import os
import glob
from datetime import datetime
from pathlib import Path

import pandas as pd


# ── 工具函数 ────────────────────────────────────────────────────────

def find_file(directory: str, keyword: str) -> str | None:
    """在目录中查找文件名包含关键词的 Excel 文件"""
    for ext in ("*.xlsx", "*.xls", "*.XLSX", "*.XLS"):
        for f in glob.glob(os.path.join(directory, ext)):
            if keyword in os.path.basename(f):
                return f
    return None


def fmt_amount(val: float, currency: str = "USD") -> str:
    """格式化金额，VND 不保留小数"""
    if currency == "VND":
        return f"{val:,.0f}"
    return f"{val:,.2f}"


# ── 核心逻辑 ────────────────────────────────────────────────────────

def load_settlement(path: str) -> pd.DataFrame:
    """读取当月结算数据"""
    df = pd.read_excel(path)
    if "金额" not in df.columns:
        raise ValueError(f"当月结算数据缺少'金额'列，可用列: {list(df.columns)}")
    # 检测币种列
    currency_col = None
    for col in df.columns:
        if "币种" in str(col) or "currency" in str(col).lower():
            currency_col = col
            break
    df["_currency"] = df[currency_col] if currency_col else "USD"
    df["_amount"] = pd.to_numeric(df["金额"], errors="coerce").fillna(0)
    return df


def load_sap(path: str) -> pd.DataFrame:
    """读取 SAP 入账数据"""
    df = pd.read_excel(path)
    required = ["业务类型", "应收"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError(f"SAP数据缺少列: {missing}，可用列: {list(df.columns)}")
    # 检测币种列
    currency_col = None
    for col in df.columns:
        if "币种" in str(col) or "currency" in str(col).lower():
            currency_col = col
            break
    df["_currency"] = df[currency_col] if currency_col else "USD"
    df["_amount"] = pd.to_numeric(df["应收"], errors="coerce").fillna(0)
    return df


def summary_stats(df: pd.DataFrame, amount_col: str = "_amount") -> dict:
    """计算正负金额统计"""
    pos = df[df[amount_col] > 0][amount_col].sum()
    neg = df[df[amount_col] < 0][amount_col].sum()
    return {"positive": pos, "negative": neg, "negative_abs": abs(neg), "net": pos + neg}


def compare_amounts(sap_val: float, settlement_val: float, label: str, currency: str) -> dict:
    """比较两组金额，返回差异信息"""
    diff = abs(sap_val - settlement_val)
    pct = (diff / abs(settlement_val) * 100) if settlement_val != 0 else 0
    # VND 允许四舍五入差异 ≤3
    threshold = 3 if currency == "VND" else 0.01
    ok = diff <= threshold
    return {
        "label": label,
        "sap": sap_val,
        "settlement": settlement_val,
        "diff": diff,
        "pct": pct,
        "ok": ok,
        "currency": currency,
    }


def match_vouchers(settlement_df: pd.DataFrame, sap_df: pd.DataFrame) -> dict:
    """逐笔匹配：按凭证编号+汇总号"""
    # 查找凭证编号和汇总号列
    def find_col(df, keywords):
        for col in df.columns:
            for kw in keywords:
                if kw in str(col):
                    return col
        return None

    s_voucher = find_col(settlement_df, ["凭证编号", "凭证号", "voucher"])
    s_summary = find_col(settlement_df, ["汇总号", "汇总"])
    p_voucher = find_col(sap_df, ["凭证编号", "凭证号", "voucher"])
    p_summary = find_col(sap_df, ["汇总号", "汇总"])

    if not all([s_voucher, p_voucher]):
        return {"matched": 0, "total_settlement": len(settlement_df), "total_sap": 0,
                "only_settlement": 0, "only_sap": 0, "match_rate": 0, "skipped": True}

    # 构建组合键
    if s_summary and p_summary:
        s_keys = set(zip(settlement_df[s_voucher].astype(str), settlement_df[s_summary].astype(str)))
        p_keys = set(zip(sap_df[p_voucher].astype(str), sap_df[p_summary].astype(str)))
    else:
        s_keys = set(settlement_df[s_voucher].astype(str))
        p_keys = set(sap_df[p_voucher].astype(str))

    matched = s_keys & p_keys
    only_s = s_keys - p_keys
    only_p = p_keys - s_keys

    return {
        "matched": len(matched),
        "total_settlement": len(s_keys),
        "total_sap": len(p_keys),
        "only_settlement": len(only_s),
        "only_sap": len(only_p),
        "match_rate": len(matched) / len(s_keys) * 100 if s_keys else 0,
        "skipped": False,
    }


# ── 主流程 ──────────────────────────────────────────────────────────

def run_reconciliation(directory: str) -> str:
    """执行完整核对，返回报告文本"""
    lines = []
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # 查找文件
    settlement_path = find_file(directory, "当月结算数据")
    sap_path = find_file(directory, "SAP")

    if not settlement_path or not sap_path:
        missing = []
        if not settlement_path: missing.append("当月结算数据")
        if not sap_path: missing.append("SAP")
        return f"错误: 未找到文件 {', '.join(missing)}，请确认目录 {directory} 中有对应 Excel 文件"

    lines.append("=" * 60)
    lines.append(f"    CRM入账准确性核对报告（v2 自动化）")
    lines.append(f"    生成时间: {ts}")
    lines.append(f"    结算文件: {os.path.basename(settlement_path)}")
    lines.append(f"    SAP文件:  {os.path.basename(sap_path)}")
    lines.append("=" * 60)

    # 加载数据
    try:
        s_df = load_settlement(settlement_path)
        p_df = load_sap(sap_path)
    except Exception as e:
        return f"数据加载失败: {e}"

    lines.append(f"\n[1] 文件基本信息")
    lines.append(f"  当月结算数据: {len(s_df)} 行")
    lines.append(f"  SAP入账数据:  {len(p_df)} 行")

    # 按币种分组核对
    currencies = sorted(set(s_df["_currency"].unique()) | set(p_df["_currency"].unique()))
    all_ok = True
    comparison_results = []

    for cur in currencies:
        s_cur = s_df[s_df["_currency"] == cur]
        p_cur = p_df[p_df["_currency"] == cur]

        if s_cur.empty and p_cur.empty:
            continue

        lines.append(f"\n[2] {cur} 核对")
        lines.append("-" * 40)

        # 结算数据统计
        s_stats = summary_stats(s_cur)
        lines.append(f"  结算正数: {fmt_amount(s_stats['positive'], cur)} ({len(s_cur[s_cur['_amount'] > 0])}笔)")
        lines.append(f"  结算负数: {fmt_amount(s_stats['negative'], cur)} ({len(s_cur[s_cur['_amount'] < 0])}笔)")

        # SAP 数据统计
        lsyt = p_cur[p_cur["业务类型"] == "LSYT"]
        lsytr = p_cur[p_cur["业务类型"] == "LSYTR"]
        lsyt_sum = lsyt["_amount"].sum()
        lsytr_sum = lsytr["_amount"].sum()

        lines.append(f"  SAP LSYT:  {fmt_amount(lsyt_sum, cur)} ({len(lsyt)}行)")
        lines.append(f"  SAP LSYTR: {fmt_amount(lsytr_sum, cur)} ({len(lsytr)}行)")

        # 比较
        r1 = compare_amounts(lsytr_sum, s_stats["negative_abs"], "LSYTR vs 结算负数", cur)
        r2 = compare_amounts(lsyt_sum, s_stats["positive"], "LSYT vs 结算正数", cur)
        comparison_results.extend([r1, r2])

        for r in [r1, r2]:
            status = "PASS" if r["ok"] else "FAIL"
            if not r["ok"]:
                all_ok = False
            lines.append(f"\n  {r['label']}:")
            lines.append(f"    SAP:        {fmt_amount(r['sap'], cur)}")
            lines.append(f"    结算:       {fmt_amount(r['settlement'], cur)}")
            lines.append(f"    差异:       {fmt_amount(r['diff'], cur)} ({r['pct']:.6f}%)  [{status}]")

    # 逐笔匹配
    voucher_result = match_vouchers(s_df, p_df)
    lines.append(f"\n[3] 逐笔匹配")
    lines.append("-" * 40)
    if voucher_result["skipped"]:
        lines.append("  跳过（未找到凭证编号列）")
    else:
        lines.append(f"  结算组合数: {voucher_result['total_settlement']}")
        lines.append(f"  SAP组合数:  {voucher_result['total_sap']}")
        lines.append(f"  成功匹配:   {voucher_result['matched']}")
        lines.append(f"  匹配率:     {voucher_result['match_rate']:.1f}%")
        if voucher_result["only_settlement"] > 0:
            lines.append(f"  仅在结算中: {voucher_result['only_settlement']}（可能遗漏）")
            all_ok = False
        if voucher_result["only_sap"] > 0:
            lines.append(f"  仅在SAP中:  {voucher_result['only_sap']}（可能多余）")

    # 结论
    lines.append(f"\n[4] 核对结论")
    lines.append("=" * 40)
    if all_ok:
        lines.append("  ★ [PASS] 入账准确 ★")
        lines.append("  金额核对一致，凭证覆盖完整。")
    else:
        lines.append("  ★ [WARN] 存在差异 ★")
        lines.append("  请检查上述 FAIL 项，确认差异原因。")

    lines.append("=" * 60)
    return "\n".join(lines)


# ── 入口 ────────────────────────────────────────────────────────────

if __name__ == "__main__":
    if len(sys.argv) > 1:
        target_dir = sys.argv[1]
    else:
        target_dir = os.path.dirname(os.path.abspath(__file__))
        # 如果在 v2/ 下，往上找
        if os.path.basename(target_dir) == "v2":
            target_dir = os.path.dirname(target_dir)

    report = run_reconciliation(target_dir)
    print(report)

    # 保存报告
    report_path = os.path.join(target_dir, f"CRM核对报告_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt")
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(report)
    print(f"\n报告已保存: {report_path}")
