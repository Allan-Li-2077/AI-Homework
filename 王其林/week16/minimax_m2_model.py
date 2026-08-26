"""MiniMax-M2 模型结构复现。

依据开源信息（ModelScope/HuggingFace 官方 modeling_minimax_m2.py 与 config.json）整理：
- 整体：标准 Transformer decoder-only + 细粒度 MoE（真实模型 229B 总参 / 10B 激活，62 层），
  回归全注意力（弃用 MiniMax-01/M1 的 Lightning Attention 线性注意力），架构与 Qwen3 高度相似
- 注意力：GQA（48 头 Q / 8 头 KV，head_dim=128）+ per-layer QK-Norm + Partial RoPE
  （rotary_dim=64：head_dim 中前 64 维旋转、后 64 维不旋转；theta=5000000）
- FFN：全部层均为 MoE（num_local_experts=256 个专家、top-8、无共享专家，
  专家中间维 intermediate_size=1536；shared_intermediate_size=0）
- MoE 路由：sigmoid 打分 → +e_score_correction_bias（仅参与 top-k 选择）→ top-k → 重新归一化，
  与 DeepSeek-V3 相同；与 Hy3（sigmoid 后不归一化、×router_scaling_factor）不同
- MTP：num_mtp_modules 个 NextN 层级联预测未来 token（config: use_mtp=true, mtp_transformer_layers=1）
- 词表 200064，max_position_embeddings 196608，tie_word_embeddings=False，权重支持 fp8 量化

运行：python minimax_m2_model.py（默认测试规模可单机 CPU 跑通前向与自回归续写）
"""

import math
from dataclasses import dataclass
from typing import Tuple, Optional

import torch
from torch import nn
import torch.nn.functional as F
import torch.distributed as dist


world_size = 1
rank = 0


@dataclass
class ModelArgs:
    """模型超参数，字段与 MiniMax-M2 config.json 一一对应（可 **config 直接构造）。
    默认值为单机可跑通的测试规模；真实 M2 配置：num_hidden_layers=62, num_local_experts=256。"""
    # 推理配置
    max_batch_size: int = 2
    max_seq_len: int = 2048
    # 与 config.json 对应
    vocab_size: int = 200064
    hidden_size: int = 3072
    intermediate_size: int = 1536      # MoE 专家中间维度（= ffn_dim）
    mlp_intermediate_size: int = 8192  # dense FFN 中间维度（主干全部 MoE，此字段保留与 config 对齐）
    num_hidden_layers: int = 4         # 真实值 62
    num_attention_heads: int = 48
    num_key_value_heads: int = 8
    head_dim: int = 128
    use_qk_norm: bool = True
    qk_norm_type: str = "per_layer"    # per_layer：每个 (head, dim) 有独立缩放参数
    # moe
    num_local_experts: int = 16        # 真实值 256
    num_experts_per_tok: int = 8
    shared_intermediate_size: int = 0  # 0 = 无共享专家
    scoring_func: str = "sigmoid"
    use_routing_bias: bool = True      # e_score_correction_bias（sigmoid 后加，仅参与选择）
    router_aux_loss_coef: float = 0.001
    # norm / rope
    rms_norm_eps: float = 1e-6
    rope_theta: float = 5000000.0
    rotary_dim: int = 64               # Partial RoPE：head_dim 中前 rotary_dim 维旋转
    max_position_embeddings: int = 196608
    # mtp
    use_mtp: bool = True
    num_mtp_modules: int = 1           # 真实值 3
    mtp_transformer_layers: int = 1    # 每个 MTP 模块内的 transformer 层数
    initializer_range: float = 0.02


class ParallelEmbedding(nn.Module):
    """词表维度切分的 embedding，每个 rank 持有 vocab_size // world_size 行。"""

    def __init__(self, vocab_size: int, dim: int):
        super().__init__()
        self.vocab_size = vocab_size
        self.dim = dim
        assert vocab_size % world_size == 0
        self.part_vocab_size = (vocab_size // world_size)
        self.vocab_start_idx = rank * self.part_vocab_size
        self.vocab_end_idx = self.vocab_start_idx + self.part_vocab_size
        self.weight = nn.Parameter(torch.empty(self.part_vocab_size, self.dim))

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        if world_size > 1:
            mask = (x < self.vocab_start_idx) | (x >= self.vocab_end_idx)
            x = x - self.vocab_start_idx
            x[mask] = 0
        y = F.embedding(x, self.weight)
        if world_size > 1:
            y[mask] = 0
            dist.all_reduce(y)
        return y


class Linear(nn.Module):
    """无切分线性层（MoE 专家、路由等使用）。"""

    def __init__(self, in_features: int, out_features: int, bias: bool = False, dtype=None):
        super().__init__()
        self.in_features = in_features
        self.out_features = out_features
        dtype = dtype or torch.get_default_dtype()
        self.weight = nn.Parameter(torch.empty(out_features, in_features, dtype=dtype))
        if bias:
            self.bias = nn.Parameter(torch.empty(out_features))
        else:
            self.register_parameter("bias", None)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return F.linear(x, self.weight, self.bias)


class ColumnParallelLinear(Linear):
    """按输出维度切分的线性层（TP），无需通信。"""

    def __init__(self, in_features: int, out_features: int, bias: bool = False, dtype=None):
        assert out_features % world_size == 0
        self.part_out_features = out_features // world_size
        super().__init__(in_features, self.part_out_features, bias, dtype)


class RowParallelLinear(Linear):
    """按输入维度切分的线性层（TP），输出需要 all_reduce 汇总。"""

    def __init__(self, in_features: int, out_features: int, bias: bool = False, dtype=None):
        assert in_features % world_size == 0
        self.part_in_features = in_features // world_size
        super().__init__(self.part_in_features, out_features, bias, dtype)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        y = F.linear(x, self.weight, None)
        if world_size > 1:
            y = y.float()
            dist.all_reduce(y)
        if self.bias is not None:
            y += self.bias
        return y.type_as(x)


class RMSNorm(nn.Module):
    def __init__(self, dim: int, eps: float = 1e-6):
        super().__init__()
        self.eps = eps
        self.weight = nn.Parameter(torch.ones(dim))

    def forward(self, x: torch.Tensor):
        x = x.float()
        y = x * torch.rsqrt(x.pow(2).mean(-1, keepdim=True) + self.eps)
        return y.type_as(self.weight) * self.weight


def precompute_freqs_cis(args: ModelArgs) -> torch.Tensor:
    """预计算 RoPE 复数频率。M2 为 Partial RoPE（rotary_dim=64 < head_dim=128）：
    仅生成 rotary_dim 个频率（32 个），对应 head 的前 64 维旋转；theta=5000000。"""
    dim = args.rotary_dim
    seqlen = args.max_seq_len
    base = args.rope_theta
    freqs = 1.0 / (base ** (torch.arange(0, dim, 2, dtype=torch.float32) / dim))
    t = torch.arange(seqlen)
    freqs = torch.outer(t, freqs)
    freqs_cis = torch.polar(torch.ones_like(freqs), freqs)
    return freqs_cis


def apply_rotary_emb(x: torch.Tensor, freqs_cis: torch.Tensor, rotary_dim: int) -> torch.Tensor:
    """Partial RoPE：head 的前 rotary_dim 维做复数旋转，后 head_dim - rotary_dim 维不旋转直接拼接。"""
    dtype = x.dtype
    x_rot, x_pass = x[..., :rotary_dim], x[..., rotary_dim:]
    x_rot = torch.view_as_complex(x_rot.float().view(*x_rot.shape[:-1], -1, 2))
    # 复数频率数量 = rotary_dim / 2
    freqs_cis = freqs_cis.view(1, x.size(1), 1, x_rot.size(-1))
    y_rot = torch.view_as_real(x_rot * freqs_cis).flatten(3)
    return torch.cat([y_rot.to(dtype), x_pass], dim=-1)


class Attention(nn.Module):
    """GQA 注意力 + per-layer QK-Norm + Partial RoPE。
    per-layer QK-Norm（M2 与 Qwen3 的主要差异）：Q/K 投影后、reshape 成多头之前，
    对整个拼接张量做 RMSNorm，缩放参数维度 = 头数 × head_dim，每个 (head, dim) 独立；
    区别于跨头共享一组 head_dim 参数的常规 QK-Norm。"""

    def __init__(self, args: ModelArgs):
        super().__init__()
        self.n_heads = args.num_attention_heads
        self.n_kv_heads = args.num_key_value_heads
        self.n_kv_groups = self.n_heads // self.n_kv_heads
        self.head_dim = args.head_dim
        self.rotary_dim = args.rotary_dim
        self.scaling = self.head_dim ** -0.5

        self.wq = ColumnParallelLinear(args.hidden_size, self.n_heads * self.head_dim)
        self.wk = ColumnParallelLinear(args.hidden_size, self.n_kv_heads * self.head_dim)
        self.wv = ColumnParallelLinear(args.hidden_size, self.n_kv_heads * self.head_dim)
        self.wo = RowParallelLinear(self.n_heads * self.head_dim, args.hidden_size)
        if args.use_qk_norm:
            # per_layer：RMSNorm 的缩放参数维度 = 头数 × head_dim（每个 (head, dim) 独立）
            self.q_norm = RMSNorm(self.n_heads * self.head_dim, args.rms_norm_eps)
            self.k_norm = RMSNorm(self.n_kv_heads * self.head_dim, args.rms_norm_eps)
        # KV cache 按 KV 头数量存储（GQA 的核心收益：cache 显存为 Q 头数的 1/6）
        self.register_buffer("k_cache", torch.zeros(args.max_batch_size, args.max_seq_len, self.n_kv_heads, self.head_dim), persistent=False)
        self.register_buffer("v_cache", torch.zeros(args.max_batch_size, args.max_seq_len, self.n_kv_heads, self.head_dim), persistent=False)

    def forward(self, x: torch.Tensor, start_pos: int, freqs_cis: torch.Tensor, mask: Optional[torch.Tensor]):
        bsz, seqlen, _ = x.size()
        end_pos = start_pos + seqlen
        q = self.wq(x)
        k = self.wk(x)
        v = self.wv(x)
        if self.q_norm is not None:
            # 在 reshape 成多头之前对整个拼接 Q/K 归一化（per_layer QK-Norm）
            q = self.q_norm(q)
            k = self.k_norm(k)
        q = q.view(bsz, seqlen, self.n_heads, self.head_dim)
        k = k.view(bsz, seqlen, self.n_kv_heads, self.head_dim)
        v = v.view(bsz, seqlen, self.n_kv_heads, self.head_dim)
        q = apply_rotary_emb(q, freqs_cis, self.rotary_dim)
        k = apply_rotary_emb(k, freqs_cis, self.rotary_dim)
        # 缓存 KV（仅 KV 头数量，读取时再复制对齐 Q 头）
        self.k_cache[:bsz, start_pos:end_pos] = k
        self.v_cache[:bsz, start_pos:end_pos] = v
        k = self.k_cache[:bsz, :end_pos]
        v = self.v_cache[:bsz, :end_pos]
        if self.n_kv_groups > 1:
            k = k.repeat_interleave(self.n_kv_groups, dim=2)
            v = v.repeat_interleave(self.n_kv_groups, dim=2)
        scores = torch.einsum("bshd,bthd->bsht", q, k) * self.scaling
        if mask is not None:
            scores += mask.unsqueeze(1)
        scores = scores.softmax(dim=-1, dtype=torch.float32).type_as(x)
        x = torch.einsum("bsht,bthd->bshd", scores, v)
        return self.wo(x.flatten(2))


class Expert(nn.Module):
    """单个 MoE 专家：SwiGLU FFN，中间维度 intermediate_size=1536。"""

    def __init__(self, dim: int, inter_dim: int):
        super().__init__()
        self.w1 = Linear(dim, inter_dim)
        self.w2 = Linear(inter_dim, dim)
        self.w3 = Linear(dim, inter_dim)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.w2(F.silu(self.w1(x)) * self.w3(x))


class Gate(nn.Module):
    """MoE 路由：sigmoid 打分 → +e_score_correction_bias（仅参与 top-k 选择）→ top-k → 重新归一化。
    与 DeepSeek-V3 相同的 renormalize 策略；与 Hy3（sigmoid 后不归一化、×router_scaling_factor）不同。
    e_score_correction_bias 是官方实现中的负载均衡校正项（register_buffer，不进入最终路由权重）。"""

    def __init__(self, args: ModelArgs):
        super().__init__()
        self.topk = args.num_experts_per_tok
        self.router = Linear(args.hidden_size, args.num_local_experts)
        if args.use_routing_bias:
            self.register_buffer("e_score_correction_bias", torch.zeros(args.num_local_experts))

    def forward(self, x: torch.Tensor) -> Tuple[torch.Tensor, torch.Tensor]:
        logits = self.router(x).float()
        routing_weights = logits.sigmoid()
        # bias 只影响 top-k 专家选择，最终路由权重取 sigmoid 原始分数
        scores_for_choice = routing_weights + self.e_score_correction_bias
        _, indices = scores_for_choice.topk(self.topk, dim=-1)
        top_weights = routing_weights.gather(1, indices)
        # 与 DeepSeek-V3 相同：选中分数重新归一化（Hy3 不做这一步）
        top_weights = top_weights / top_weights.sum(dim=-1, keepdim=True)
        return top_weights.type_as(x), indices


class MoE(nn.Module):
    """细粒度 MoE：256 个专家、top-8，无共享专家（shared_intermediate_size=0，与 Qwen3 相同）。"""

    def __init__(self, args: ModelArgs):
        super().__init__()
        self.dim = args.hidden_size
        self.n_routed_experts = args.num_local_experts
        self.gate = Gate(args)
        self.experts = nn.ModuleList([Expert(args.hidden_size, args.intermediate_size)
                                      for _ in range(args.num_local_experts)])

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        shape = x.size()
        x = x.view(-1, self.dim)
        top_weights, indices = self.gate(x)
        y = torch.zeros_like(x, dtype=torch.float32)
        counts = torch.bincount(indices.flatten(), minlength=self.n_routed_experts).tolist()
        for i in range(self.n_routed_experts):
            if counts[i] == 0:
                continue
            expert = self.experts[i]
            idx, top = torch.where(indices == i)
            y[idx] += expert(x[idx]) * top_weights[idx, top, None]
        if world_size > 1:
            dist.all_reduce(y)
        return y.type_as(x).view(shape)


class Block(nn.Module):
    """Decoder block：pre-norm 残差 + GQA 注意力 + MoE（M2 全部层均为 MoE，无 dense 前置层）。"""

    def __init__(self, layer_id: int, args: ModelArgs):
        super().__init__()
        self.attn = Attention(args)
        self.ffn = MoE(args)
        self.attn_norm = RMSNorm(args.hidden_size, args.rms_norm_eps)
        self.ffn_norm = RMSNorm(args.hidden_size, args.rms_norm_eps)

    def forward(self, x: torch.Tensor, start_pos: int, freqs_cis: torch.Tensor, mask: Optional[torch.Tensor]) -> torch.Tensor:
        x = x + self.attn(self.attn_norm(x), start_pos, freqs_cis, mask)
        x = x + self.ffn(self.ffn_norm(x))
        return x


class NextNLayer(nn.Module):
    """MTP（Multi-Token Prediction）层：将下一 token 的 embedding 与当前 hidden 拼接投影，
    再经过一个完整 decoder block（MoE），输出用于预测未来 token 的 hidden。
    与主层参数独立；config 中 mtp_transformer_layers=1 表示每个 MTP 模块含 1 个 transformer 层。"""

    def __init__(self, args: ModelArgs):
        super().__init__()
        self.proj = Linear(args.hidden_size * 2, args.hidden_size)
        self.ln1 = RMSNorm(args.hidden_size, args.rms_norm_eps)
        self.ln2 = RMSNorm(args.hidden_size, args.rms_norm_eps)
        self.decoder = Block(args.num_hidden_layers, args)
        self.ln3 = RMSNorm(args.hidden_size, args.rms_norm_eps)

    def forward(self, hidden_states: torch.Tensor, token_emb: torch.Tensor,
                freqs_cis: torch.Tensor, mask: Optional[torch.Tensor]) -> torch.Tensor:
        token_emb = self.ln1(token_emb)
        hidden_states = self.ln2(hidden_states)
        hidden_states = self.proj(torch.cat([token_emb, hidden_states], dim=-1))
        hidden_states = self.decoder(hidden_states, 0, freqs_cis, mask)
        return self.ln3(hidden_states)


class Transformer(nn.Module):
    """完整 MiniMax-M2 模型：embed → N 个 decoder block → norm → lm_head（+ MTP 级联模块）。
    tie_word_embeddings=False：lm_head 与 embedding 为独立参数。"""

    def __init__(self, args: ModelArgs):
        global world_size, rank
        world_size = dist.get_world_size() if dist.is_initialized() else 1
        rank = dist.get_rank() if dist.is_initialized() else 0
        super().__init__()
        self.args = args
        self.max_seq_len = args.max_seq_len
        self.vocab_size = args.vocab_size
        self.embed = ParallelEmbedding(args.vocab_size, args.hidden_size)
        self.layers = nn.ModuleList([Block(i, args) for i in range(args.num_hidden_layers)])
        self.norm = RMSNorm(args.hidden_size, args.rms_norm_eps)
        self.head = ColumnParallelLinear(args.hidden_size, args.vocab_size)
        self.nextn_layers = nn.ModuleList([NextNLayer(args) for _ in range(args.num_mtp_modules)])
        self.nextn_norm = RMSNorm(args.hidden_size, args.rms_norm_eps)
        self.register_buffer("freqs_cis", precompute_freqs_cis(args), persistent=False)
        self.apply(self._init_weights)

    def _init_weights(self, module: nn.Module):
        # 与 config 的 initializer_range=0.02 一致（注意用自定义 Linear，而非 torch.nn.Linear）
        if isinstance(module, Linear):
            nn.init.normal_(module.weight, std=self.args.initializer_range)
        elif isinstance(module, ParallelEmbedding):
            nn.init.normal_(module.weight, std=self.args.initializer_range)

    @torch.inference_mode()
    def forward(self, tokens: torch.Tensor, start_pos: int = 0):
        """推理模式：返回最后一个 token 的 logits（支持 prefill 与逐 token 续写）。"""
        seqlen = tokens.size(1)
        h = self.embed(tokens)
        freqs_cis = self.freqs_cis[start_pos:start_pos+seqlen]
        mask = None
        if seqlen > 1:
            mask = torch.full((seqlen, seqlen), float("-inf"), device=tokens.device).triu_(1)
        for layer in self.layers:
            h = layer(h, start_pos, freqs_cis, mask)
        h = self.norm(h)[:, -1]
        logits = self.head(h)
        if world_size > 1:
            all_logits = [torch.empty_like(logits) for _ in range(world_size)]
            dist.all_gather(all_logits, logits)
            logits = torch.cat(all_logits, dim=-1)
        return logits

    @torch.inference_mode()
    def nextn_forward(self, tokens: torch.Tensor):
        """训练模式：返回全序列 logits 与各 MTP 模块的未来 token logits。
        级联结构：第 i 个模块用前一个模块的输出预测第 i+1 个未来 token（与 DeepSeek MTP 同思路）。"""
        seqlen = tokens.size(1)
        h = self.embed(tokens)
        freqs_cis = self.freqs_cis[:seqlen]
        mask = torch.full((seqlen, seqlen), float("-inf"), device=tokens.device).triu_(1)
        for layer in self.layers:
            h = layer(h, 0, freqs_cis, mask)
        h = self.norm(h)
        logits = self.head(h)
        nextn_logits = []
        nh = h[:, :-1]
        token_emb = self.embed(tokens[:, 1:])
        fc = freqs_cis[1:]
        mk = mask[1:, 1:]
        for i, layer in enumerate(self.nextn_layers):
            nh = layer(nh, token_emb, fc, mk)
            nextn_logits.append(self.head(self.nextn_norm(nh)))
            if i < len(self.nextn_layers) - 1:
                nh = nh[:, :-1]
                token_emb = token_emb[:, 1:]
                fc = fc[1:]
                mk = mk[1:, 1:]
        return logits, nextn_logits


if __name__ == "__main__":
    torch.set_default_dtype(torch.bfloat16)
    torch.manual_seed(0)
    args = ModelArgs()
    x = torch.randint(0, args.vocab_size, (2, 128))
    model = Transformer(args)
    # 预填充：一次处理 128 个 token，返回最后一个 token 的 logits
    print("prefill logits:", model(x).size())
    # 续写：逐 token 生成，start_pos 递增以验证 KV cache 写入
    for i in range(128, 132):
        print(f"decode@{i}:", model(x[:, 0:1], i).size())
    # MTP：主模型全序列 logits + 各 MTP 模块预测的未来 token logits
    logits, nextn_logits = model.nextn_forward(x)
    print("train logits:", logits.size(), "nextn logits:", [n.size() for n in nextn_logits])
