"""腾讯混元 Hy3（Hunyuan Hy3 / Hunyuan-A13B 同架构）模型结构复现。

依据开源信息（HuggingFace 官方 modeling_hunyuan.py 实现与 hy_v3_config.json）整理：
- 整体：标准 Transformer decoder-only + 细粒度 MoE（真实模型 295B 总参 / 21B 激活）
- 注意力：GQA（64 头 Q / 8 头 KV，head_dim=128）+ QK-Norm + 全维 RoPE（theta=11158840）
- FFN：前 first_k_dense_replace 层为 dense SwiGLU（intermediate_size=13312），
  其余层为 MoE（num_experts=192 个专家、top-8、1 个共享专家，专家中间维 1536）
- MoE 路由：route_norm → router 打分 → +expert_bias → sigmoid → top-k → ×router_scaling_factor，
  与 DeepSeek 不同，sigmoid 分数不做重新归一化
- MTP：num_nextn_predict_layers 个 NextN 层，融合下一 token embedding 与当前 hidden 预测未来 token
- 词表 120832，max_position_embeddings 262144，tie_word_embeddings=False

运行：python hy_v3_model.py（默认测试规模可单机 CPU 跑通前向与自回归续写）
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
    """模型超参数，字段与 hy_v3_config.json 一一对应（可 **config 直接构造）。
    默认值为单机可跑通的测试规模；真实 Hy3 配置：num_hidden_layers=80, num_experts=192。"""
    # 推理配置
    max_batch_size: int = 2
    max_seq_len: int = 2048
    # 与 hy_v3_config.json 对应
    vocab_size: int = 120832
    hidden_size: int = 4096
    intermediate_size: int = 13312        # dense FFN 中间维度
    moe_intermediate_size: int = 1536     # 每个专家中间维度（= expert_hidden_dim）
    num_hidden_layers: int = 4            # 真实值 80
    first_k_dense_replace: int = 1        # 前 K 层使用 dense FFN，其余层使用 MoE
    num_attention_heads: int = 64
    num_key_value_heads: int = 8
    head_dim: int = 128
    qk_norm: bool = True
    # moe
    num_experts: int = 16                 # 真实值 192
    num_experts_per_tok: int = 8
    num_shared_experts: int = 1
    moe_router_enable_expert_bias: bool = True
    moe_router_use_sigmoid: bool = True
    router_scaling_factor: float = 2.826
    route_norm: bool = True
    # norm / rope
    rms_norm_eps: float = 1e-5
    rope_theta: float = 11158840.0
    max_position_embeddings: int = 262144
    # mtp
    num_nextn_predict_layers: int = 1
    initializer_range: float = 0.006


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
    """无切分线性层（MoE 专家、共享专家、路由等使用）。"""

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
    """预计算 RoPE 复数频率。Hy3 的 rope_type 为 default：全 head_dim 旋转，
    theta=11158840（远超默认 10000，用于支撑 256K 长上下文）。"""
    dim = args.head_dim
    seqlen = args.max_seq_len
    base = args.rope_theta
    freqs = 1.0 / (base ** (torch.arange(0, dim, 2, dtype=torch.float32) / dim))
    t = torch.arange(seqlen)
    freqs = torch.outer(t, freqs)
    freqs_cis = torch.polar(torch.ones_like(freqs), freqs)
    return freqs_cis


def apply_rotary_emb(x: torch.Tensor, freqs_cis: torch.Tensor) -> torch.Tensor:
    dtype = x.dtype
    x = torch.view_as_complex(x.float().view(*x.shape[:-1], -1, 2))
    freqs_cis = freqs_cis.view(1, x.size(1), 1, x.size(-1))
    y = torch.view_as_real(x * freqs_cis).flatten(3)
    return y.to(dtype)


class Attention(nn.Module):
    """GQA 注意力 + QK-Norm：Q/K 投影后对每个 head 的 head_dim 做 RMSNorm 再旋转，
    与 MLA（DeepSeek）不同，Hy3 不做低秩压缩，KV 头直接复制对齐 Q 头。"""

    def __init__(self, args: ModelArgs):
        super().__init__()
        self.n_heads = args.num_attention_heads
        self.n_kv_heads = args.num_key_value_heads
        self.n_kv_groups = self.n_heads // self.n_kv_heads
        self.head_dim = args.head_dim
        self.scaling = self.head_dim ** -0.5

        self.wq = ColumnParallelLinear(args.hidden_size, self.n_heads * self.head_dim)
        self.wk = ColumnParallelLinear(args.hidden_size, self.n_kv_heads * self.head_dim)
        self.wv = ColumnParallelLinear(args.hidden_size, self.n_kv_heads * self.head_dim)
        self.wo = RowParallelLinear(self.n_heads * self.head_dim, args.hidden_size)
        if args.qk_norm:
            self.q_norm = RMSNorm(self.head_dim, args.rms_norm_eps)
            self.k_norm = RMSNorm(self.head_dim, args.rms_norm_eps)
        self.register_buffer("k_cache", torch.zeros(args.max_batch_size, args.max_seq_len, self.n_heads, self.head_dim), persistent=False)
        self.register_buffer("v_cache", torch.zeros(args.max_batch_size, args.max_seq_len, self.n_heads, self.head_dim), persistent=False)

    def forward(self, x: torch.Tensor, start_pos: int, freqs_cis: torch.Tensor, mask: Optional[torch.Tensor]):
        bsz, seqlen, _ = x.size()
        end_pos = start_pos + seqlen
        q = self.wq(x).view(bsz, seqlen, self.n_heads, self.head_dim)
        k = self.wk(x).view(bsz, seqlen, self.n_kv_heads, self.head_dim)
        v = self.wv(x).view(bsz, seqlen, self.n_kv_heads, self.head_dim)
        if self.q_norm is not None:
            q = self.q_norm(q)
            k = self.k_norm(k)
        q = apply_rotary_emb(q, freqs_cis)
        k = apply_rotary_emb(k, freqs_cis)
        # GQA：将 KV 头复制 n_kv_groups 份，与 Q 头一一对应
        if self.n_kv_groups > 1:
            k = k.repeat_interleave(self.n_kv_groups, dim=2)
            v = v.repeat_interleave(self.n_kv_groups, dim=2)
        self.k_cache[:bsz, start_pos:end_pos] = k
        self.v_cache[:bsz, start_pos:end_pos] = v
        scores = torch.einsum("bshd,bthd->bsht", q, self.k_cache[:bsz, :end_pos]) * self.scaling
        if mask is not None:
            scores += mask.unsqueeze(1)
        scores = scores.softmax(dim=-1, dtype=torch.float32).type_as(x)
        x = torch.einsum("bsht,bthd->bshd", scores, self.v_cache[:bsz, :end_pos])
        return self.wo(x.flatten(2))


class MLP(nn.Module):
    """Dense SwiGLU FFN（前 first_k_dense_replace 层使用）。"""

    def __init__(self, dim: int, inter_dim: int):
        super().__init__()
        self.w1 = ColumnParallelLinear(dim, inter_dim)
        self.w2 = RowParallelLinear(inter_dim, dim)
        self.w3 = ColumnParallelLinear(dim, inter_dim)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.w2(F.silu(self.w1(x)) * self.w3(x))


class Gate(nn.Module):
    """MoE 路由：route_norm → router 打分 → +expert_bias → sigmoid/softmax → top-k → ×router_scaling_factor。
    与 DeepSeek 的差异：分数不重新归一化（sigmoid 独立打分），
    expert_bias 只参与 top-k 专家选择，不进入最终路由权重。"""

    def __init__(self, args: ModelArgs):
        super().__init__()
        self.topk = args.num_experts_per_tok
        self.use_sigmoid = args.moe_router_use_sigmoid
        self.scaling_factor = args.router_scaling_factor
        self.router = Linear(args.hidden_size, args.num_experts)
        self.route_norm = RMSNorm(args.hidden_size, args.rms_norm_eps) if args.route_norm else nn.Identity()
        if args.moe_router_enable_expert_bias:
            self.expert_bias = nn.Parameter(torch.zeros(args.num_experts, dtype=torch.float32))
        else:
            self.register_parameter("expert_bias", None)

    def forward(self, x: torch.Tensor) -> Tuple[torch.Tensor, torch.Tensor]:
        logits = self.router(self.route_norm(x)).float()
        if self.expert_bias is not None:
            logits = logits + self.expert_bias
        scores = logits.sigmoid() if self.use_sigmoid else logits.softmax(dim=-1)
        top_scores, indices = scores.topk(self.topk, dim=-1)
        top_scores = top_scores * self.scaling_factor
        return top_scores.type_as(x), indices


class Expert(nn.Module):
    """单个 MoE 专家：SwiGLU FFN，中间维度 moe_intermediate_size=1536。"""

    def __init__(self, dim: int, inter_dim: int):
        super().__init__()
        self.w1 = Linear(dim, inter_dim)
        self.w2 = Linear(inter_dim, dim)
        self.w3 = Linear(dim, inter_dim)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.w2(F.silu(self.w1(x)) * self.w3(x))


class MoE(nn.Module):
    """细粒度 MoE：gate 为每个 token 路由 top-k 个专家，外加所有 token 都经过的共享专家。"""

    def __init__(self, args: ModelArgs):
        super().__init__()
        self.dim = args.hidden_size
        self.n_routed_experts = args.num_experts
        self.gate = Gate(args)
        self.experts = nn.ModuleList([Expert(args.hidden_size, args.moe_intermediate_size)
                                      for _ in range(args.num_experts)])
        self.shared_experts = nn.ModuleList([Expert(args.hidden_size, args.moe_intermediate_size)
                                             for _ in range(args.num_shared_experts)])

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        shape = x.size()
        x = x.view(-1, self.dim)
        top_scores, indices = self.gate(x)
        y = torch.zeros_like(x, dtype=torch.float32)
        counts = torch.bincount(indices.flatten(), minlength=self.n_routed_experts).tolist()
        for i in range(self.n_routed_experts):
            if counts[i] == 0:
                continue
            expert = self.experts[i]
            idx, top = torch.where(indices == i)
            y[idx] += expert(x[idx]) * top_scores[idx, top, None]
        if world_size > 1:
            dist.all_reduce(y)
        for shared in self.shared_experts:
            y += shared(x)
        return y.type_as(x).view(shape)


class Block(nn.Module):
    """Decoder block：pre-norm 残差 + GQA 注意力 + FFN（前 K 层 dense，其余 MoE）。"""

    def __init__(self, layer_id: int, args: ModelArgs):
        super().__init__()
        self.attn = Attention(args)
        self.ffn = MLP(args.hidden_size, args.intermediate_size) if layer_id < args.first_k_dense_replace else MoE(args)
        self.attn_norm = RMSNorm(args.hidden_size, args.rms_norm_eps)
        self.ffn_norm = RMSNorm(args.hidden_size, args.rms_norm_eps)

    def forward(self, x: torch.Tensor, start_pos: int, freqs_cis: torch.Tensor, mask: Optional[torch.Tensor]) -> torch.Tensor:
        x = x + self.attn(self.attn_norm(x), start_pos, freqs_cis, mask)
        x = x + self.ffn(self.ffn_norm(x))
        return x


class NextNLayer(nn.Module):
    """MTP（Multi-Token Prediction）层：将下一 token 的 embedding 与当前 hidden 拼接投影，
    再经过一个完整 decoder block，输出用于预测未来 token 的 hidden。
    与主层参数独立；官方实现中该层使用 MoE FFN。"""

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
    """完整 Hy3 模型：embed → N 个 decoder block → norm → lm_head（+ NextN MTP 层）。
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
        self.nextn_layers = nn.ModuleList([NextNLayer(args) for _ in range(args.num_nextn_predict_layers)])
        self.nextn_norm = RMSNorm(args.hidden_size, args.rms_norm_eps)
        self.register_buffer("freqs_cis", precompute_freqs_cis(args), persistent=False)
        self.apply(self._init_weights)

    def _init_weights(self, module: nn.Module):
        # 与 config 的 initializer_range=0.006 一致（注意用自定义 Linear，而非 torch.nn.Linear）
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
        """训练模式：返回全序列 logits 与各 NextN 层的未来 token logits（用于 MTP 多 token 预测损失）。
        第 i 个 NextN 层用位置 0..s-2 的 hidden 与位置 1..s-1 的 embedding 预测第 i+1 个未来 token。"""
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
        for layer in self.nextn_layers:
            nh = layer(nh, token_emb, freqs_cis[1:], mask[1:, 1:])
            nextn_logits.append(self.head(self.nextn_norm(nh)))
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
    # MTP：主模型全序列 logits + NextN 层预测的未来 token logits
    logits, nextn_logits = model.nextn_forward(x)
    print("train logits:", logits.size(), "nextn logits:", [n.size() for n in nextn_logits])
