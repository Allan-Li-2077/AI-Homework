# -*- coding: utf-8 -*-
"""
MiniMax M3 / MSA (MiniMax Sparse Attention) 结构讲解代码
==========================================================

本文件用精简的 PyTorch 实现，逐步拆解 M3 的核心结构（与真实 config 一一对应）：

1. Index Branch   —— 轻量索引分支：为每个 GQA 组打分，block max-pooling 后 top-k 选块
2. Main Branch    —— 标准 GQA softmax attention，但只关注被选中的 KV 块
3. 强制 Local Block —— query 所在块始终被选中，保证局部连续性
4. MoE FFN        —— sigmoid 路由 + routing bias + 共享专家 + routed_scaling_factor
5. 层布局          —— 前几层 dense + 全注意力，之后 MoE + MSA 稀疏注意力

资料对应关系（本目录 MiniMaxAI_MiniMax-M3_config.json）：
    num_attention_heads=64, num_key_value_heads=4, head_dim=128
    sparse_index_dim=128, sparse_num_index_heads=4,
    sparse_topk_blocks=16, sparse_block_size=128, sparse_score_type=max
    num_local_experts=128, num_experts_per_tok=4, scoring_func=sigmoid,
    use_routing_bias=true, routed_scaling_factor=2.0

说明：为了能在 CPU 上快速运行，这里的维度是"缩小版"，但结构与真实 M3 完全同构。
运行方式：python minimax_m3_msa_modeling.py
"""

import json
import math
from pathlib import Path

import torch
import torch.nn as nn
import torch.nn.functional as F

torch.manual_seed(42)


# ---------------------------------------------------------------------------
# 0. 配置：缩小版（可运行）与真实 M3 配置（仅用于打印对照）
# ---------------------------------------------------------------------------
class MSAConfig:
    """MSA 层的结构配置（字段名与官方 config.json 对齐）"""

    def __init__(self, hidden_size, num_attention_heads, num_key_value_heads,
                 head_dim, sparse_index_dim, sparse_topk_blocks, sparse_block_size):
        self.hidden_size = hidden_size
        self.num_attention_heads = num_attention_heads        # H_q
        self.num_key_value_heads = num_key_value_heads        # H_kv（GQA 组数）
        self.head_dim = head_dim                              # d_h
        self.sparse_index_dim = sparse_index_dim              # d_idx
        self.sparse_num_index_heads = num_key_value_heads     # 每 GQA 组一个 index query 头
        self.sparse_topk_blocks = sparse_topk_blocks          # k
        self.sparse_block_size = sparse_block_size            # Bk


# 演示用缩小版配置：保持 64Q/4KV = 16:1 的 GQA 配比
DEMO_CFG = MSAConfig(
    hidden_size=64,
    num_attention_heads=8,
    num_key_value_heads=2,
    head_dim=16,
    sparse_index_dim=16,
    sparse_topk_blocks=3,
    sparse_block_size=8,
)


def load_real_config():
    """读取同目录下的真实 M3 config.json（基于脚本位置定位，任意目录执行都不会出错）"""
    cfg_path = Path(__file__).parent / "MiniMaxAI_MiniMax-M3_config.json"
    if not cfg_path.exists():
        return None
    with open(cfg_path, "r", encoding="utf-8") as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# 1. RMSNorm（use_gemma_norm=true：权重以 1 + w 的形式生效，Gemma 风格）
# ---------------------------------------------------------------------------
class GemmaRMSNorm(nn.Module):
    def __init__(self, dim, eps=1e-6):
        super().__init__()
        self.eps = eps
        self.weight = nn.Parameter(torch.zeros(dim))  # 初始化为 0，等效初始增益为 1

    def forward(self, x):
        rms = x.pow(2).mean(-1, keepdim=True).add(self.eps).rsqrt()
        return x * rms * (1.0 + self.weight)  # gemma 风格：(1 + w) 而不是 w


# ---------------------------------------------------------------------------
# 2. Index Branch：轻量索引分支（MSA 的"初筛器"）
#    - 每个 GQA 组一个 index query 头（共 H_kv 个），参数量极小
#    - 全局共享一个 index key 头（所有组共用同一份 K^idx）
#    - token 级打分 -> block max-pooling -> top-k 选块 -> 强制 local block
# ---------------------------------------------------------------------------
class IndexBranch(nn.Module):
    def __init__(self, cfg: MSAConfig):
        super().__init__()
        self.cfg = cfg
        # index query：H_kv 个头，每个头 d_idx 维
        self.index_q_proj = nn.Linear(
            cfg.hidden_size, cfg.num_key_value_heads * cfg.sparse_index_dim, bias=False)
        # index key：全局共享 1 个头（注意：没有按组拆分，这是省参数的关键）
        self.index_k_proj = nn.Linear(cfg.hidden_size, cfg.sparse_index_dim, bias=False)

    def forward(self, x):
        """
        输入:  x  [B, N, hidden]
        输出:  selected [B, H_kv, N, k]  每个 query 每组选中的块编号
        """
        cfg = self.cfg
        B, N, _ = x.shape
        Bk, k = cfg.sparse_block_size, cfg.sparse_topk_blocks
        num_blocks = N // Bk
        assert N % Bk == 0, "演示中要求序列长度能被块大小整除"

        # ---- token 级打分：S_ij = q_i^idx · k_j^idx / sqrt(d_idx) ----
        q_idx = self.index_q_proj(x).view(
            B, N, cfg.num_key_value_heads, cfg.sparse_index_dim).transpose(1, 2)  # [B,H_kv,N,d_idx]
        k_idx = self.index_k_proj(x)                                              # [B,N,d_idx]（组间共享）
        scores = torch.matmul(q_idx, k_idx.transpose(1, 2)) / math.sqrt(cfg.sparse_index_dim)
        # [B, H_kv, N, N]

        # ---- causal mask：query 不能看到未来的 token ----
        causal = torch.ones(N, N, dtype=torch.bool, device=x.device).tril()
        scores = scores.masked_fill(~causal, float("-inf"))

        # ---- block max-pooling：块内取最大值，聚合成块级分数 ----
        # sparse_score_type=max：只要块内有 1 个 token 强相关，整个块就能被召回
        block_scores = scores.view(B, cfg.num_key_value_heads, N, num_blocks, Bk).amax(dim=-1)
        # [B, H_kv, N, num_blocks]

        # ---- 强制 local block：query 自身所在的块必须被选中 ----
        local_block = torch.arange(N, device=x.device) // Bk          # [N]
        block_scores.scatter_(
            dim=-1,
            index=local_block.view(1, 1, -1, 1).expand(B, cfg.num_key_value_heads, N, 1),
            src=torch.full_like(block_scores[..., :1], float("inf")),
        )

        # ---- top-k 选块 ----
        _, selected = block_scores.topk(k, dim=-1)                    # [B, H_kv, N, k]
        return selected, block_scores


# ---------------------------------------------------------------------------
# 3. Main Branch：标准 GQA softmax attention，但只算被选中的 KV 块
#    （真实 kernel 用 gather 把选中块拼成连续 KV；这里为了讲解清晰用 mask 实现，
#      二者数学上完全等价）
# ---------------------------------------------------------------------------
class MiniMaxSparseAttention(nn.Module):
    def __init__(self, cfg: MSAConfig):
        super().__init__()
        self.cfg = cfg
        self.index_branch = IndexBranch(cfg)
        H_q, H_kv, d = cfg.num_attention_heads, cfg.num_key_value_heads, cfg.head_dim
        self.q_proj = nn.Linear(cfg.hidden_size, H_q * d, bias=False)
        self.k_proj = nn.Linear(cfg.hidden_size, H_kv * d, bias=False)
        self.v_proj = nn.Linear(cfg.hidden_size, H_kv * d, bias=False)
        self.o_proj = nn.Linear(H_q * d, cfg.hidden_size, bias=False)

    def forward(self, x, use_sparse=True):
        cfg = self.cfg
        B, N, _ = x.shape
        H_q, H_kv, d = cfg.num_attention_heads, cfg.num_key_value_heads, cfg.head_dim
        Bk, k = cfg.sparse_block_size, cfg.sparse_topk_blocks
        num_blocks = N // Bk
        group_size = H_q // H_kv

        # ---- 主分支的 Q/K/V（标准 GQA） ----
        q = self.q_proj(x).view(B, N, H_q, d).transpose(1, 2)   # [B,H_q,N,d]
        kk = self.k_proj(x).view(B, N, H_kv, d).transpose(1, 2)  # [B,H_kv,N,d]
        v = self.v_proj(x).view(B, N, H_kv, d).transpose(1, 2)   # [B,H_kv,N,d]

        # ---- causal 全注意力 logits（sparse 模式下再叠加选块 mask） ----
        logits = torch.matmul(q, kk.repeat_interleave(group_size, dim=1).transpose(2, 3))
        logits = logits / math.sqrt(d)                            # [B,H_q,N,N]
        causal = torch.ones(N, N, dtype=torch.bool, device=x.device).tril()
        mask = causal.clone()

        selected = None
        if use_sparse:
            # ---- Index Branch 选块 ----
            selected, _ = self.index_branch(x)                    # [B,H_kv,N,k]

            # ---- 把"选中的块"展开成 token 级 attend mask ----
            # block j 被选中 => 该块内所有 token (j*Bk .. j*Bk+Bk-1) 可见
            onehot = torch.zeros(B, H_kv, N, num_blocks, device=x.device)
            onehot.scatter_(-1, selected, 1.0)                    # [B,H_kv,N,num_blocks]
            token_mask = onehot.repeat_interleave(Bk, dim=-1)     # [B,H_kv,N,N]
            token_mask = token_mask.repeat_interleave(group_size, dim=1)  # [B,H_q,N,N]
            mask = mask & token_mask.bool()

        logits = logits.masked_fill(~mask, float("-inf"))
        attn = logits.softmax(dim=-1)
        out = torch.matmul(attn, v.repeat_interleave(group_size, dim=1))  # [B,H_q,N,d]
        out = out.transpose(1, 2).reshape(B, N, H_q * d)
        return self.o_proj(out), attn, selected


# ---------------------------------------------------------------------------
# 4. MoE FFN：sigmoid 路由 + routing bias + top-k + 共享专家 + routed_scaling_factor
#    （对应 config: num_local_experts=128, num_experts_per_tok=4, n_shared_experts=1,
#      scoring_func=sigmoid, use_routing_bias=true, routed_scaling_factor=2.0；
#      演示中把专家数缩小为 8 / top-2）
# ---------------------------------------------------------------------------
class ExpertFFN(nn.Module):
    """单个专家的 SwiGLU FFN（演示用标准 SwiGLU 近似 swigluoai）"""

    def __init__(self, hidden, intermediate):
        super().__init__()
        self.gate = nn.Linear(hidden, intermediate, bias=False)
        self.up = nn.Linear(hidden, intermediate, bias=False)
        self.down = nn.Linear(intermediate, hidden, bias=False)

    def forward(self, x):
        return self.down(F.silu(self.gate(x)) * self.up(x))


class MiniMaxMoE(nn.Module):
    def __init__(self, hidden, num_experts=8, top_k=2, intermediate=32,
                 routed_scaling_factor=2.0):
        super().__init__()
        self.top_k = top_k
        self.routed_scaling_factor = routed_scaling_factor
        # use_routing_bias=true：路由带偏置，配合 sigmoid 做负载均衡
        self.router = nn.Linear(hidden, num_experts, bias=True)
        self.experts = nn.ModuleList(ExpertFFN(hidden, intermediate)
                                     for _ in range(num_experts))
        # n_shared_experts=1：所有 token 必过的共享专家
        self.shared_expert = ExpertFFN(hidden, intermediate)

    def forward(self, x):
        # scoring_func=sigmoid：注意不做全局 softmax，各组打分相互独立
        scores = torch.sigmoid(self.router(x))                    # [B*N, E]
        topk_val, topk_idx = scores.topk(self.top_k, dim=-1)
        topk_w = topk_val / topk_val.sum(-1, keepdim=True).clamp_min(1e-9)
        topk_w = topk_w * self.routed_scaling_factor              # 缓解训练/推理激活差异

        y = torch.zeros_like(x)
        for e, expert in enumerate(self.experts):                 # 演示用逐专家累加
            hit = (topk_idx == e)
            if not hit.any():
                continue
            w = torch.where(hit, topk_w, torch.zeros_like(topk_w)).sum(-1, keepdim=True)
            y = y + w * expert(x)
        y = y + self.shared_expert(x)                             # 共享专家输出直接相加
        return y, topk_idx


# ---------------------------------------------------------------------------
# 5. 单个 Transformer 层 + 层布局（moe_layer_freq / sparse_attention_freq）
# ---------------------------------------------------------------------------
class MiniMaxM3Block(nn.Module):
    def __init__(self, cfg: MSAConfig, is_moe: bool, is_sparse: bool):
        super().__init__()
        self.is_sparse = is_sparse
        self.attn_norm = GemmaRMSNorm(cfg.hidden_size)
        self.ffn_norm = GemmaRMSNorm(cfg.hidden_size)
        self.attn = MiniMaxSparseAttention(cfg)
        if is_moe:
            self.ffn = MiniMaxMoE(cfg.hidden_size)
        else:
            # dense_intermediate_size = 4 × 单专家宽度（与真实配置 12288 = 4×3072 同理）
            self.ffn = ExpertFFN(cfg.hidden_size, 128)

    def forward(self, x):
        attn_out, attn_weights, selected = self.attn(x, use_sparse=self.is_sparse)
        x = x + attn_out                                          # 注意力残差
        ffn_out = self.ffn(self.ffn_norm(x))
        if isinstance(ffn_out, tuple):                            # MoE 额外返回路由结果
            ffn_out = ffn_out[0]
        x = x + ffn_out                                           # FFN 残差
        return x, selected


def build_demo_model(cfg: MSAConfig):
    """按真实布局建 4 层演示模型：第 0 层 dense+全注意力，第 1~3 层 MoE+MSA
    （真实 M3：前 3 层 dense+全注意力，后 57 层 MoE+MSA）"""
    moe_freq = [0, 1, 1, 1]
    sparse_freq = [0, 1, 1, 1]
    return nn.ModuleList([
        MiniMaxM3Block(cfg, is_moe=bool(moe_freq[i]), is_sparse=bool(sparse_freq[i]))
        for i in range(4)
    ])


# ---------------------------------------------------------------------------
# 6. 理论复杂度对比（用真实 M3 参数，N=1M）
# ---------------------------------------------------------------------------
def print_theory():
    cfg = load_real_config()
    if cfg is None:
        print("（未找到真实 config.json，跳过理论对比）")
        return
    t = cfg["text_config"]
    s = t["sparse_attention_config"]
    H_q, H_kv = t["num_attention_heads"], t["num_key_value_heads"]
    d_h, d_idx = t["head_dim"], s["sparse_index_dim"]
    k, Bk = s["sparse_topk_blocks"], s["sparse_block_size"]
    N = 1_048_576  # 1M 上下文

    # 全注意力：QK^T 与 attn·V 各 2 次乘加
    full = 4 * H_q * d_h * N * N
    # MSA：index 打分（H_kv 头 × d_idx）+ 主分支只算 k*Bk 个 KV
    msa = 2 * H_kv * d_idx * N * N + 4 * H_q * d_h * N * (k * Bk)

    print("\n===== 理论复杂度对比（真实 M3 配置，N = 1M） =====")
    print(f"全注意力 FLOPs ≈ {full:.3e}")
    print(f"MSA FLOPs      ≈ {msa:.3e}  (index 分支 {2 * H_kv * d_idx * N * N:.3e}"
          f" + 主分支 {4 * H_q * d_h * N * (k * Bk):.3e})")
    print(f"注意力 FLOPs 减少约 {full / msa:.1f}× （论文实测 28.4×，口径略有差异）")
    print(f"主分支每个 query 只需看 k×Bk = {k * Bk} 个 token，与总长度 N 无关")


# ---------------------------------------------------------------------------
# 7. 主流程
# ---------------------------------------------------------------------------
def main():
    print("===== MiniMax M3 / MSA 结构演示 =====\n")

    # ---- 打印真实配置要点 ----
    real = load_real_config()
    if real is not None:
        t, s = real["text_config"], real["text_config"]["sparse_attention_config"]
        print("[真实 M3 配置] hidden=%d, 层数=%d, %d Q头/%d KV头, head_dim=%d, 上下文=%d"
              % (t["hidden_size"], t["num_hidden_layers"], t["num_attention_heads"],
                 t["num_key_value_heads"], t["head_dim"], t["max_position_embeddings"]))
        print("[MSA] index_dim=%d, index头=%d, top-k块=%d, 块大小=%d, score=%s, local_block=%d"
              % (s["sparse_index_dim"], s["sparse_num_index_heads"],
                 s["sparse_topk_blocks"], s["sparse_block_size"],
                 s["sparse_score_type"], s["sparse_local_block"]))
        print("[MoE] %d 路由专家选 %d + %d 共享专家, scoring=%s, routing_bias=%s\n"
              % (t["num_local_experts"], t["num_experts_per_tok"], t["n_shared_experts"],
                 t["scoring_func"], t["use_routing_bias"]))

    cfg = DEMO_CFG
    B, N = 1, cfg.sparse_block_size * 8   # 64 个 token，共 8 个块
    x = torch.randn(B, N, cfg.hidden_size)

    layers = build_demo_model(cfg)

    # ---- 逐层前向，观察布局 ----
    h = x
    for i, layer in enumerate(layers):
        h, selected = layer(h)
        mode = "MSA 稀疏注意力 + MoE" if layer.is_sparse else "全注意力 + Dense FFN"
        print(f"Layer {i}: {mode}")
        if selected is not None:
            # 打印中间一个 query 的选块结果，验证 local block 必被选中
            q_pos = N // 2
            sel = selected[0, 0, q_pos].tolist()
            print(f"  query@{q_pos} (所在块 {q_pos // cfg.sparse_block_size}) "
                  f"选中的块: {sorted(sel)}")

    print(f"\n输出形状: {tuple(h.shape)}")

    # ---- 同一组权重下，稀疏 vs 全注意力的输出一致性对照 ----
    print("\n===== 稀疏 vs 全注意力对照（同一权重） =====")
    attn = layers[1].attn
    out_sparse, _, selected = attn(x, use_sparse=True)
    out_full, attn_full, _ = attn(x, use_sparse=False)
    cos = F.cosine_similarity(out_sparse.flatten(), out_full.flatten(), dim=0)
    print(f"稀疏/全注意力输出余弦相似度: {cos.item():.4f}")
    print("（稀疏模式只看 top-k 块，信息有损；真实模型靠 KL 对齐损失训练 indexer，"
          "使选块后的分布逼近全注意力分布）")

    # ---- 展示 indexer 的召回质量：全注意力最关注的 token 是否落在选中块里 ----
    q_pos = N // 2
    top_tokens = attn_full[0, 0, q_pos].topk(5).indices.tolist()
    sel_blocks = set(selected[0, 0, q_pos].tolist())
    hit = sum(1 for p in top_tokens if p // cfg.sparse_block_size in sel_blocks)
    print(f"query@{q_pos} 全注意力 top5 token: {top_tokens}，"
          f"其中 {hit}/5 落在 MSA 选中的块内")

    # ---- 理论复杂度对比 ----
    print_theory()


if __name__ == "__main__":
    main()
