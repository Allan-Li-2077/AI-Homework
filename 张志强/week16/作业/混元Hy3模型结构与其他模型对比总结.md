# 混元 Hy3 模型结构与 DeepSeek、Qwen3.6-27B、Kimi、GLM 对比总结

## 1. Hy3 总体结构定位

混元 Hy3 是一个 **Decoder-only Causal LM**，整体结构可以概括为：

```text
input_ids
  ↓
token embedding
  ↓
80 层 Decoder Block
  ↓
final RMSNorm
  ↓
lm_head
  ↓
next token logits
```

核心配置如下：

```text
hidden_size              = 4096
num_hidden_layers         = 80
num_attention_heads       = 64
num_key_value_heads       = 8
head_dim                  = 128
vocab_size                = 120832
max_position_embeddings   = 262144
num_experts               = 192
num_experts_per_tok       = 8
num_shared_experts        = 1
moe_intermediate_size     = 1536
intermediate_size         = 13312
first_k_dense_replace     = 1
router_scaling_factor     = 2.826
```

结构上可以拆成三层理解：

```text
Hy3
├─ 主干：Decoder-only Transformer
├─ Attention：GQA Full Attention + QK RMSNorm + RoPE
└─ FFN：第 0 层 Dense MLP，第 1~79 层 MoE
```

---

## 2. Hy3 与 DeepSeek 的相似点和差异

### 2.1 相似点

Hy3 与 DeepSeek 最相似的是 **MoE 路由和专家组织方式**。

DeepSeek-V3 的关键配置：

```text
first_k_dense_replace = 3
n_routed_experts = 256
num_experts_per_tok = 8
n_shared_experts = 1
scoring_func = sigmoid
routed_scaling_factor = 2.5
norm_topk_prob = true
```

Hy3 的对应配置：

```text
first_k_dense_replace = 1
num_experts = 192
num_experts_per_tok = 8
num_shared_experts = 1
moe_router_use_sigmoid = true
router_scaling_factor = 2.826
route_norm = true
```

共同结构：

```text
MoE FFN
├─ 前几层 Dense
├─ 后续层 Sparse MoE
├─ routed experts
├─ shared experts
├─ 每 token top-8 experts
├─ sigmoid router
├─ top-k 权重归一化
└─ router scaling factor
```

因此，Hy3 的 MoE 更接近 DeepSeek 的 noaux / sigmoid router 路线。

### 2.2 差异点

DeepSeek 更激进地使用了 MLA 注意力结构：

```text
DeepSeek
├─ MLA attention
├─ q_lora_rank / kv_lora_rank
├─ qk_nope_head_dim + qk_rope_head_dim
├─ YaRN RoPE scaling
├─ 61 layers
├─ hidden_size = 7168
└─ 256 experts
```

Hy3 则是：

```text
Hy3
├─ 普通 GQA Full Attention
├─ 没有 q_lora / kv_lora
├─ 没有 nope/rope head 拆分
├─ default RoPE
├─ 80 layers
├─ hidden_size = 4096
└─ 192 experts
```

结论：

```text
Hy3 的 MoE 像 DeepSeek，但 Attention 不像 DeepSeek。
```

---

## 3. Hy3 与 Qwen3.6-27B 的相似点和差异

### 3.1 相似点

Qwen3.6-27B 的关键配置：

```text
hidden_size = 5120
num_hidden_layers = 64
num_attention_heads = 24
num_key_value_heads = 4
head_dim = 256
max_position_embeddings = 262144
rope_theta = 10000000
tie_word_embeddings = false
```

Hy3 的对应配置：

```text
hidden_size = 4096
num_hidden_layers = 80
num_attention_heads = 64
num_key_value_heads = 8
head_dim = 128
max_position_embeddings = 262144
rope_theta = 11158840
tie_word_embeddings = false
```

二者共同点：

```text
Decoder-only / Causal LM 主干
├─ Pre-Norm Transformer
├─ RMSNorm
├─ GQA
├─ RoPE 长上下文
├─ bf16
├─ KV cache
└─ embedding 与 lm_head 不共享
```

尤其是长上下文配置非常接近：

```text
Hy3:
    max_position_embeddings = 262144
    rope_theta ≈ 11.16M

Qwen3.6:
    max_position_embeddings = 262144
    rope_theta = 10M
```

### 3.2 差异点

Qwen3.6-27B 使用了 Linear Attention / Full Attention 混合结构：

```text
layer_types:
    linear_attention
    linear_attention
    linear_attention
    full_attention
    ...
```

也就是大致按如下节奏组织：

```text
3 层 Linear Attention + 1 层 Full Attention 循环
```

Hy3 没有这种混合注意力：

```text
Hy3:
    每层都是 Full Attention + MLP/MoE
```

结论：

```text
Hy3 的长上下文 GQA 主干像 Qwen3.6，
但 Hy3 没有 Qwen3.6 的 Linear Attention 混合层。
```

---

## 4. Hy3 与 Kimi 的相似点和差异

### 4.1 相似点

Kimi-K3 的关键配置：

```text
first_k_dense_replace = 1
num_experts = 896
num_experts_per_token = 16
num_shared_experts = 2
moe_router_activation_func = sigmoid
moe_renormalize = true
routed_scaling_factor = 1.0
```

Hy3 的对应配置：

```text
first_k_dense_replace = 1
num_experts = 192
num_experts_per_tok = 8
num_shared_experts = 1
moe_router_use_sigmoid = true
route_norm = true
router_scaling_factor = 2.826
```

二者最相似的是 MoE 层分布：

```text
第一层 Dense
后续层 MoE
sigmoid router
top-k experts
top-k weights renormalize
shared experts
```

这点上，Hy3 与 Kimi 比 DeepSeek / GLM 更接近，因为：

```text
Hy3:
    first_k_dense_replace = 1

Kimi:
    first_k_dense_replace = 1

DeepSeek / GLM:
    first_k_dense_replace = 3
```

### 4.2 差异点

Kimi 的 Attention 和激活函数更特殊：

```text
Kimi
├─ Linear Attention + Full Attention 混合
├─ MLA 风格注意力
├─ q_lora_rank / kv_lora_rank
├─ qk_nope_head_dim + qk_rope_head_dim
├─ hidden_act = situ
├─ 896 experts
├─ top-16 experts
├─ 2 shared experts
└─ max_position_embeddings = 1048576
```

Hy3 是：

```text
Hy3
├─ 标准 GQA Full Attention
├─ hidden_act = silu
├─ 192 experts
├─ top-8 experts
├─ 1 shared expert
└─ max_position_embeddings = 262144
```

结论：

```text
Hy3 的 MoE 层分布像 Kimi，
但 Attention、激活函数、专家规模不像 Kimi。
```

---

## 5. Hy3 与 GLM 的相似点和差异

### 5.1 相似点

GLM-5.2 的关键配置：

```text
first_k_dense_replace = 3
n_routed_experts = 256
num_experts_per_tok = 8
n_shared_experts = 1
scoring_func = sigmoid
routed_scaling_factor = 2.5
norm_topk_prob = true
num_nextn_predict_layers = 1
```

Hy3 的对应配置：

```text
first_k_dense_replace = 1
num_experts = 192
num_experts_per_tok = 8
num_shared_experts = 1
moe_router_use_sigmoid = true
router_scaling_factor = 2.826
route_norm = true
num_nextn_predict_layers = 1
```

共同点：

```text
MoE FFN
├─ top-8 routing
├─ sigmoid router
├─ shared expert = 1
├─ router scaling
├─ top-k 权重归一化
├─ 前置 Dense + 后续 Sparse
└─ MTP 配置字段存在
```

### 5.2 差异点

GLM-5.2 有 DSA / Indexer 结构：

```text
index_topk = 2048
index_topk_freq = 4
indexer_types = full / shared
GlmMoeDsaIndexer
DeepSeek Sparse Attention
```

同时 GLM 也更接近 DeepSeek/MLA 路线：

```text
q_lora_rank = 2048
kv_lora_rank = 512
qk_nope_head_dim = 192
qk_rope_head_dim = 64
```

Hy3 没有这些结构：

```text
Hy3
├─ 没有 DSA Indexer
├─ 没有 q_lora / kv_lora
├─ 没有 nope/rope head 拆分
└─ 没有 sparse attention indexer
```

结论：

```text
Hy3 的 MoE 路由像 GLM，
但没有 GLM 的 DSA 稀疏注意力和 MLA 结构。
```

---

## 6. 各模型共同点

Hy3、DeepSeek、Qwen3.6、Kimi、GLM 共同具备现代 Decoder-only 大模型的基础骨架：

```text
现代 Decoder-only 大模型共同骨架
├─ Causal LM
├─ Pre-Norm Block
├─ RMSNorm
├─ RoPE / 长上下文 RoPE
├─ bf16
├─ KV cache
├─ embedding 与 lm_head 不共享
└─ SwiGLU 或门控 FFN 变体
```

Hy3、DeepSeek、Kimi、GLM 还共享 MoE 大模型的典型结构：

```text
MoE 大模型共同骨架
├─ routed experts
├─ shared experts
├─ top-k expert selection
├─ router score normalization
├─ router scaling
└─ 前置 Dense 层稳定早期表示
```

Qwen3.6-27B 与 Hy3 的共同点主要不在 MoE，而在：

```text
长上下文 GQA Transformer 主干
├─ GQA
├─ RoPE 长上下文
├─ RMSNorm
├─ Causal LM
└─ embedding / lm_head 不共享
```

---

## 7. 横向对比总览

| 结构维度 | Hy3 | DeepSeek-V3 | Qwen3.6-27B | Kimi-K3 | GLM-5.2 |
|---|---|---|---|---|---|
| 模型范式 | Decoder-only Causal LM | Decoder-only Causal LM | Decoder/Conditional Generation | Conditional Generation | Decoder-only Causal LM |
| 总层数 | 80 | 61 | 64 | 93 | 78 |
| hidden size | 4096 | 7168 | 5120 | 7168 | 6144 |
| Attention 主体 | GQA Full Attention | MLA | Linear + Full 混合 | Linear + Full + MLA 风格 | MLA + DSA |
| KV heads | 8 | 128 | 4 | 96 | 64 |
| 最大上下文 | 262144 | 163840 | 262144 | 1048576 | 1048576 |
| RoPE 类型 | default | YaRN | default / mRoPE 配置 | MLA/Linear 体系内配置 | default + interleave |
| MoE | 是 | 是 | 否 | 是 | 是 |
| 前置 Dense 层 | 1 | 3 | 不适用 | 1 | 3 |
| 专家数 | 192 | 256 | 不适用 | 896 | 256 |
| 每 token 激活专家 | 8 | 8 | 不适用 | 16 | 8 |
| Shared experts | 1 | 1 | 不适用 | 2 | 1 |
| Router 激活 | sigmoid | sigmoid | 不适用 | sigmoid | sigmoid |
| Router scaling | 2.826 | 2.5 | 不适用 | 1.0 | 2.5 |
| QK Norm | 有 | MLA 内部范式不同 | 有类似 norm 设计 | MLA/Linear 内部范式不同 | MLA/DSA 内部范式不同 |
| tie word embeddings | false | false | false | false | false |

---

## 8. 按模块相似度排序

### 8.1 MoE 结构相似度

```text
Kimi ≈ DeepSeek ≈ GLM  >  Qwen3.6
```

原因：

```text
Hy3、Kimi、DeepSeek、GLM 都是 routed MoE + shared experts + sigmoid top-k router。
Qwen3.6-27B 不是 MoE 主体结构。
```

### 8.2 Attention 结构相似度

```text
Qwen3.6  >  DeepSeek / Kimi / GLM
```

原因：

```text
Hy3 是 GQA Full Attention。
Qwen3.6 至少在 GQA 和长上下文 RoPE 主干上更接近 Hy3。
DeepSeek / Kimi / GLM 更偏 MLA、Linear Attention、DSA 路线。
```

### 8.3 长上下文设计相似度

```text
Qwen3.6 ≈ Hy3  >  DeepSeek  >  Kimi / GLM
```

原因：

```text
Hy3 和 Qwen3.6 都是 262144 上下文，并且 rope_theta 都在 1e7 级别。
Kimi / GLM 虽然上下文更长，但 Attention 路线不同。
```

### 8.4 整体工程路线

```text
Hy3 ≈ DeepSeek/Kimi/GLM 风格 MoE + Qwen 风格长上下文 GQA 主干
```

---

## 9. 最终结论

混元 Hy3 不是单纯复制某一个模型路线，而是组合了几类成熟结构：

```text
Hy3
├─ FFN / MoE：更像 DeepSeek、Kimi、GLM
├─ Attention 主干：更像 Qwen3.6 的 GQA 长上下文 Transformer
├─ Dense / Sparse 层分布：最像 Kimi
├─ Router 范式：最像 DeepSeek / GLM / Kimi 的 sigmoid top-k MoE
└─ 不采用：MLA、DSA、Linear Attention 这类更激进的注意力结构
```

一句话概括：

```text
混元 Hy3 的 FFN/MoE 设计更接近 DeepSeek、Kimi、GLM；
Attention 主干更接近 Qwen 这种 GQA 长上下文 Transformer；
但它没有采用 DeepSeek/Kimi/GLM 的 MLA、DSA、Linear Attention 等激进注意力路线。
```