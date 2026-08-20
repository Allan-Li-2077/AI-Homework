# -*- coding: utf-8 -*-
"""
10 个开源模型架构参数雷达图对比

基于各模型官方论文与技术报告整理的真实模型数据。

对比维度（7 轴）：
  1. 总参数量（Total Params）         —— 模型规模
  2. 激活参数效率（Active Efficiency） —— 激活占比越小得分越高
  3. 上下文长度（Context Length）     —— 长上下文能力
  4. 专家数量（MoE Experts）          —— MoE 稀疏容量
  5. 层数（Layer Count）              —— 模型深度
  6. 注意力创新指数（Attention Innov.）—— 结构创新程度（主观打分 1-5）
  7. 多模态能力（Multimodal Cap.）    —— 多模态能力等级（主观打分 0-4）

按技术路线分成 3 个子图 + 1 张全局总览。
"""

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import rcParams
from math import log10
import os
import csv

# ============================================================
# 0. Windows 中文字体兼容
# ============================================================
rcParams["font.sans-serif"] = [
    "Microsoft YaHei", "SimHei", "SimSun",
    "Noto Sans CJK SC", "WenQuanYi Zen Hei", "Arial Unicode MS",
    "DejaVu Sans",
]
rcParams["axes.unicode_minus"] = False

# ============================================================
# 1. 原始数据表（所有参数均已通过公开信息验证）
# ============================================================
# 字段: [模型名, 总参数(B), 激活参数(B), 上下文长度(K), 专家数, 层数,
#        注意力创新分(1-5), 多模态能力分(0-4), 系列分组]
#
# 注意力创新分说明：
#   1 = 标准 GQA / 常规注意力
#   2 = 纯 MLA / 低秩压缩
#   3 = 线性注意力 + 少量全注意力混合（Gated DeltaNet / KDA）
#   4 = Lightning Attention 大规模落地 + 块间递推
#   5 = CSA/HCA 压缩稀疏 + mHC 超连接（仅 V4 系列，本次未包含）
#
# 多模态能力分说明：
#   0 = 纯文本
#   1 = 外挂式视觉塔
#   2 = 原生多模态 + 视频支持
#   3 = 异构多模态 MoE / 预训练期融合
#   4 = 理解 + 生成 双路径解耦

DATA = [
    # ---------- DeepSeek 系列 ----------
    ["DeepSeek-V3",        671,  37.0, 128,     256, 61, 2, 0, "DeepSeek 系 (MLA+MoE)"],
    ["DeepSeek-R1",        671,  37.0, 128,     256, 61, 2, 0, "DeepSeek 系 (MLA+MoE)"],
    # ---------- Qwen 系列 ----------
    ["Qwen3-Next-80B-A3B",   80,   3.9, 262,     512, 48, 3, 0, "Qwen 系 (线性+Full 混合)"],
    # ---------- Kimi / Ling / MiniMax 系列 ----------
    ["Kimi K2",           1000,  32.0, 128,     384, 61, 2, 0, "Kimi/Ling/MiniMax 系 (KDA/Lightning/MLA)"],
    ["Ling-3.0-flash",     124,   5.1, 262,     512, 42, 3, 0, "Kimi/Ling/MiniMax 系 (KDA/Lightning/MLA)"],
    ["MiniMax-01",         456,  45.9, 1000,      32, 80, 4, 0, "Kimi/Ling/MiniMax 系 (KDA/Lightning/MLA)"],
    ["MiniMax-M1",         456,  45.9, 1000,      32, 80, 4, 0, "Kimi/Ling/MiniMax 系 (KDA/Lightning/MLA)"],
    # ---------- 其他特色模型 ----------
    ["Hunyuan-A13B",        80,  13.0, 256,      64, 32, 2, 0, "其他特色 (混元/ERNIE/Janus)"],
    ["ERNIE 4.5",          300,  47.0, 128,     128, 54, 1, 3, "其他特色 (混元/ERNIE/Janus)"],
    ["Janus-Pro-7B",         7,   7.0,   4,       0, 16, 1, 4, "其他特色 (混元/ERNIE/Janus)"],
]

# 列索引
C_NAME, C_TPARAM, C_APARAM, C_CTX, C_EXP, C_LAY, C_ATT, C_MM, C_GROUP = range(9)

# 7 个对比维度的显示名
AXIS_LABELS = [
    "总参数量\n(Total Params)",
    "激活效率\n(Active Efficiency)",
    "上下文长度\n(Context Length)",
    "MoE 专家数\n(Expert Count)",
    "模型层数\n(Layer Count)",
    "注意力创新\n(Attention Innov.)",
    "多模态能力\n(Multimodal Cap.)",
]

# ============================================================
# 2. 归一化函数
# ============================================================
def log_norm(values):
    """对数归一化，适合跨数量级的参数（参数量、上下文、专家数）。0 值取 0。"""
    vals = np.asarray(values, dtype=float)
    nonzero = vals[vals > 0]
    if len(nonzero) == 0:
        return np.zeros_like(vals)
    log_min = log10(nonzero.min())
    log_max = log10(nonzero.max())
    out = np.zeros_like(vals)
    for i, v in enumerate(vals):
        if v <= 0:
            out[i] = 0.0
        else:
            out[i] = (log10(v) - log_min) / max(log_max - log_min, 1e-9)
    return out

def linear_norm(values, reverse=False):
    """线性归一化到 [0,1]。reverse=True 表示原始值越小得分越高。"""
    vals = np.asarray(values, dtype=float)
    vmin, vmax = vals.min(), vals.max()
    if vmax == vmin:
        return np.full_like(vals, 0.5)
    if not reverse:
        return (vals - vmin) / (vmax - vmin)
    return (vmax - vals) / (vmax - vmin)

def build_scores(rows):
    """把每一行原始数据映射为 7 维 [0,1] 得分。"""
    tparams   = [r[C_TPARAM] for r in rows]
    aparams   = [r[C_APARAM] for r in rows]
    ctxs      = [r[C_CTX]    for r in rows]
    experts   = [r[C_EXP]    for r in rows]
    layers    = [r[C_LAY]    for r in rows]
    att_score = [r[C_ATT]    for r in rows]
    mm_score  = [r[C_MM]     for r in rows]

    # 激活效率：ratio = 激活/总参，越小越稀疏→得分越高
    ratios = [a / max(t, 1e-9) for a, t in zip(aparams, tparams)]

    s0 = log_norm(tparams)
    s1 = linear_norm(ratios, reverse=True)
    s2 = log_norm(ctxs)
    s3 = log_norm(experts)
    s4 = linear_norm(layers)
    s5 = linear_norm(att_score)
    s6 = linear_norm(mm_score)

    scores = np.stack([s0, s1, s2, s3, s4, s5, s6], axis=1)
    return scores


# ============================================================
# 3. 雷达图绘制函数
# ============================================================
def _set_r_axis(ax, r_max=1.0, n_ticks=5):
    r_max = min(1.0, r_max * 1.12)
    ticks = np.linspace(0, r_max, n_ticks + 1)
    ax.set_ylim(0, r_max)
    ax.set_yticks(ticks)
    ax.set_yticklabels([f"{t:.1f}" for t in ticks], fontsize=7, color="#666")
    ax.tick_params(axis="y", pad=3)
    ax.set_rlabel_position(180 / 7)

def radar_subplot(ax, group_name, model_rows, group_scores, colors, linestyles):
    N = len(AXIS_LABELS)
    angles = np.linspace(0, 2 * np.pi, N, endpoint=False).tolist()
    angles += angles[:1]

    ax.set_theta_offset(np.pi / 2)
    ax.set_theta_direction(-1)
    ax.set_facecolor("#fbfbfd")
    ax.set_xticks(angles[:-1])
    ax.set_xticklabels(AXIS_LABELS, fontsize=9, fontweight="semibold", color="#333")
    ax.yaxis.grid(True, linestyle=":", linewidth=0.7, color="#aaa")
    ax.xaxis.grid(True, linestyle="-", linewidth=0.8, color="#ccc")

    peak = float(group_scores.max()) if group_scores.size > 0 else 1.0
    _set_r_axis(ax, r_max=max(peak, 0.4))

    for idx, row in enumerate(model_rows):
        s = group_scores[idx].tolist()
        s += s[:1]
        color = colors[idx % len(colors)]
        ls = linestyles[idx % len(linestyles)]
        ax.plot(angles, s, color=color, linestyle=ls, linewidth=2.0,
                label=row[C_NAME], zorder=3)
        ax.fill(angles, s, color=color, alpha=0.10, zorder=2)
        for a, v in zip(angles[:-1], s[:-1]):
            ax.text(a, v + 0.02, f"{v:.2f}", ha="center", va="bottom",
                    fontsize=6.5, color=color, zorder=4)

    ax.set_title(group_name, fontsize=12, fontweight="bold",
                 pad=16, color="#1f2937")
    ax.legend(loc="upper right", bbox_to_anchor=(1.38, 1.15),
              fontsize=8, framealpha=0.9, edgecolor="#ddd")


# ============================================================
# 4. 分组配色方案（4 组独立色系，组内深浅区分）
# ============================================================
# 每个分组使用一个独立色系：
#   DeepSeek 系    → 红色系 (Red)
#   Qwen 系        → 蓝色系 (Blue)
#   Kimi/Ling/MiniMax 系 → 绿色系 (Emerald/Teal)
#   其他特色       → 紫色系 (Purple/Violet)
# 组内模型用同色系不同深浅 + 不同线型区分

GROUP_COLOR_FAMILIES = {
    "DeepSeek 系 (MLA+MoE)": [
        "#b91c1c",  # red-700  (深红)
        "#f87171",  # red-400  (浅红)
    ],
    "Qwen 系 (线性+Full 混合)": [
        "#1d4ed8",  # blue-700 (深蓝)
    ],
    "Kimi/Ling/MiniMax 系 (KDA/Lightning/MLA)": [
        "#047857",  # emerald-700 (深翠绿)
        "#0d9488",  # teal-600    (青绿)
        "#10b981",  # emerald-500 (中翠绿)
        "#6ee7b7",  # emerald-300 (浅翠绿)
    ],
    "其他特色 (混元/ERNIE/Janus)": [
        "#6d28e9",  # violet-700 (深紫)
        "#a855f7",  # purple-500  (中紫)
        "#c084fc",  # purple-400  (浅紫)
    ],
}

# 各组代表色（用于全局图 legend 分组标识）
GROUP_REPRESENTATIVE_COLOR = {
    "DeepSeek 系 (MLA+MoE)":               "#dc2626",  # 红
    "Qwen 系 (线性+Full 混合)":             "#2563eb",  # 蓝
    "Kimi/Ling/MiniMax 系 (KDA/Lightning/MLA)": "#059669",  # 绿
    "其他特色 (混元/ERNIE/Janus)":           "#9333ea",  # 紫
}

LINESTYLES = ["-", "--", "-.", ":"]

def _get_group_shades(group_name):
    """获取某个分组的组内色系深浅列表"""
    return GROUP_COLOR_FAMILIES.get(group_name, ["#475569"])


def main():
    os.chdir(os.path.dirname(os.path.abspath(__file__)))

    # --- 按分组拆分数据 ---
    groups = {}
    for row in DATA:
        groups.setdefault(row[C_GROUP], []).append(row)

    ordered_groups = [
        "DeepSeek 系 (MLA+MoE)",
        "Qwen 系 (线性+Full 混合)",
        "Kimi/Ling/MiniMax 系 (KDA/Lightning/MLA)",
        "其他特色 (混元/ERNIE/Janus)",
    ]

    # --- 组内归一化得分 ---
    group_scores_map = {}
    for g in ordered_groups:
        rows = groups.get(g, [])
        group_scores_map[g] = build_scores(rows) if rows else np.array([])

    # --- 画分组子图 ---
    n_groups_with_data = sum(1 for g in ordered_groups if groups.get(g))
    nrows = (n_groups_with_data + 1) // 2
    fig1, axes = plt.subplots(nrows, 2, figsize=(16, 8 * nrows),
                              subplot_kw=dict(polar=True))
    if nrows == 1:
        axes = axes.reshape(1, -1)

    fig1.suptitle(
        "10 个开源模型架构参数雷达图（按技术路线分组，组内归一化对比）\n"
        "2026-08-20 — 4 组独立色系：红=DeepSeek / 蓝=Qwen / 绿=Kimi系 / 紫=其他",
        fontsize=13, fontweight="bold", y=0.98, color="#111827",
    )

    ax_idx = 0
    for g in ordered_groups:
        rows = groups.get(g)
        if not rows:
            continue
        ax = axes.flatten()[ax_idx]
        scores = group_scores_map[g]
        shades = _get_group_shades(g)
        # 组内循环使用深浅色 + 线型
        colors = [shades[i % len(shades)] for i in range(len(rows))]
        lss = [LINESTYLES[i % len(LINESTYLES)] for i in range(len(rows))]
        radar_subplot(ax, g, rows, scores, colors, lss)
        ax_idx += 1

    # 隐藏空子图
    total_axes = nrows * 2
    for i in range(ax_idx, total_axes):
        axes.flatten()[i].set_visible(False)

    fig1.tight_layout(rect=[0, 0, 1, 0.95])
    out1 = "model_radar_grouped.png"
    fig1.savefig(out1, dpi=160, bbox_inches="tight", facecolor="white")
    print(f"已保存分组雷达图: {out1}")
    plt.close(fig1)

    # --- 全局归一化总览图 ---
    all_scores = build_scores(DATA)
    fig2, ax = plt.subplots(figsize=(15, 14), subplot_kw=dict(polar=True))
    fig2.suptitle(
        "10 个开源模型架构参数雷达图（全局归一化总览）\n"
        "2026-08-20 — 同色系=同分组，线型区分组内模型",
        fontsize=13, fontweight="bold", y=0.96, color="#111827",
    )

    # 为每个模型分配颜色：使用其所在分组的代表色
    # 组内模型用不同线型区分
    model_colors = []
    model_lss = []
    group_counters = {}  # 记录每组已出现几个模型
    for row in DATA:
        g = row[C_GROUP]
        idx_in_group = group_counters.get(g, 0)
        shades = _get_group_shades(g)
        # 组内用深浅色 + 线型双重区分
        model_colors.append(shades[idx_in_group % len(shades)])
        model_lss.append(LINESTYLES[idx_in_group % len(LINESTYLES)])
        group_counters[g] = idx_in_group + 1

    N = len(AXIS_LABELS)
    angles = np.linspace(0, 2 * np.pi, N, endpoint=False).tolist()
    angles += angles[:1]

    ax.set_theta_offset(np.pi / 2)
    ax.set_theta_direction(-1)
    ax.set_facecolor("#fbfbfd")
    ax.set_xticks(angles[:-1])
    ax.set_xticklabels(AXIS_LABELS, fontsize=10, fontweight="semibold", color="#222")
    ax.yaxis.grid(True, linestyle=":", linewidth=0.7, color="#aaa")
    ax.xaxis.grid(True, linestyle="-", linewidth=0.8, color="#ccc")

    _set_r_axis(ax, r_max=float(all_scores.max()))

    for idx, row in enumerate(DATA):
        s = all_scores[idx].tolist() + [all_scores[idx][0]]
        ax.plot(angles, s, color=model_colors[idx],
                linestyle=model_lss[idx],
                linewidth=2.0, label=row[C_NAME], alpha=0.85, zorder=3)
        ax.fill(angles, s, color=model_colors[idx], alpha=0.06, zorder=2)

    # 分组图例：用代表色块标注各分组
    from matplotlib.lines import Line2D
    legend_handles = []
    # 先添加模型线条
    for idx, row in enumerate(DATA):
        legend_handles.append(
            Line2D([0], [0], color=model_colors[idx],
                   linestyle=model_lss[idx], linewidth=2.0,
                   label=f"  {row[C_NAME]}")
        )
    # 再添加分组色块分隔
    group_legend = ax.legend(handles=legend_handles,
                             loc="upper right", bbox_to_anchor=(1.65, 1.15),
                             ncol=1, fontsize=8.5, framealpha=0.9,
                             edgecolor="#ddd", title="模型（同色=同分组）",
                             title_fontsize=9)
    # 添加第二个 legend 显示分组代表色
    group_handles = []
    for g in ordered_groups:
        if groups.get(g):
            group_handles.append(
                Line2D([0], [0], color=GROUP_REPRESENTATIVE_COLOR[g],
                       linewidth=4.0, marker="s", markersize=10,
                       label=g)
            )
    ax.add_artist(group_legend)
    ax.legend(handles=group_handles,
              loc="lower right", bbox_to_anchor=(1.65, 0.0),
              ncol=1, fontsize=8, framealpha=0.9,
              edgecolor="#ddd", title="分组色系",
              title_fontsize=9)

    fig2.tight_layout(rect=[0, 0, 1, 0.93])
    out2 = "model_radar_overall.png"
    fig2.savefig(out2, dpi=160, bbox_inches="tight", facecolor="white")
    print(f"已保存全局总览雷达图: {out2}")
    plt.close(fig2)

    # --- 原始数据 + 得分表 CSV ---
    outcsv = "model_scores.csv"
    with open(outcsv, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        header = ["模型名", "总参数(B)", "激活参数(B)", "上下文(K)",
                  "专家数", "层数", "注意力创新分", "多模态分",
                  "系列",
                  "得分_总参", "得分_激活效率", "得分_上下文", "得分_专家数",
                  "得分_层数", "得分_注意力创新", "得分_多模态"]
        w.writerow(header)
        for i, row in enumerate(DATA):
            s = all_scores[i]
            w.writerow([
                row[C_NAME], row[C_TPARAM], row[C_APARAM], row[C_CTX],
                row[C_EXP], row[C_LAY], row[C_ATT], row[C_MM], row[C_GROUP],
                f"{s[0]:.4f}", f"{s[1]:.4f}", f"{s[2]:.4f}", f"{s[3]:.4f}",
                f"{s[4]:.4f}", f"{s[5]:.4f}", f"{s[6]:.4f}",
            ])
    print(f"已保存原始数据+得分表: {outcsv}")


if __name__ == "__main__":
    main()
