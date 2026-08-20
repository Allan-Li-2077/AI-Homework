# Qwen3.8-27B 模型结构分析

Qwen3.8-27B 的结构分析结果，同样适用于 Qwen3.6-27B。
因为两者在当前 config 中的模型结构参数完全一致。它们是同一结构模板下的两个模型版本。

## 1. 结论概览

Qwen3.8-27B 是一个面向长上下文和多模态任务的 **Hybrid Attention + MoE Decoder** 模型。

它不是传统的每层都使用 Full Attention 的 Transformer，而是采用：

```text
Vision Encoder
+ 64 层 Text Decoder
+ 48 层 Gated DeltaNet linear attention
+ 16 层 Gated full attention
+ 每层后接 Sparse MoE FFN
+ Partial RoPE / MRoPE
+ MTP
```

一句话概括：

```text
Qwen3.8-27B 更接近 Kimi K3 的混合注意力路线，
同时保留了 DeepSeek / GLM 这类新一代长上下文 MoE 模型的通用工程范式。
```

---

## 2. Qwen3.8-27B 的整体模型结构

Qwen3.8-27B 可以拆成两个主体模块：

```text
Qwen3.8-27B
├── Vision Encoder
│   ├── ViT-style patch encoder
│   ├── depth = 27
│   ├── hidden_size = 1152
│   ├── out_hidden_size = 5120
│   └── 输出对齐到语言模型 hidden_size
│
└── Text Decoder
    ├── hidden_size = 5120
    ├── num_hidden_layers = 64
    ├── vocab_size = 248320
    ├── context = 262144
    ├── block pattern:
    │   └── 每 4 层一个 full_attention，其余 3 层是 linear_attention
    │
    └── 每层结构:
        ├── RMSNorm
        ├── Token Mixer
        │   ├── linear_attention 层: Gated DeltaNet
        │   └── full_attention 层: Gated Attention
        ├── residual
        ├── RMSNorm
        ├── Sparse MoE FFN
        └── residual
```

---

## 3. Text Decoder 层结构

Qwen3.8-27B 的 64 层不是统一结构，而是周期性混合结构：

```text
16 × (
  linear_attention
  linear_attention
  linear_attention
  full_attention
)
```

也就是：

```text
64 层里：
48 层 linear_attention
16 层 full_attention
```

这个设计的目的：

```text
长上下文成本下降
+ 周期性 full attention 保留全局建模能力
```

和传统 Transformer 对比：

```text
传统 Transformer:
每层都是 full attention，长上下文成本高

Qwen3.8:
大多数层用线性注意力处理长序列
少数层用 full attention 做全局信息校正
```

---

## 4. 关键结构参数

### 4.1 Text Decoder

| 模块 | Qwen3.8-27B |
|---|---|
| 架构名 | `Qwen3_5ForConditionalGeneration` |
| 文本模型类型 | `qwen3_5_text` |
| 层数 | 64 |
| hidden size | 5120 |
| FFN intermediate size | 17408 |
| 激活函数 | `silu` |
| RMSNorm eps | `1e-6` |
| attention heads | 24 |
| KV heads | 4 |
| head dim | 256 |
| max context | 262144 |
| RoPE theta | 10000000 |
| partial rotary factor | 0.25 |
| vocab size | 248320 |
| MTP | `mtp_num_hidden_layers = 1` |

### 4.2 Linear Attention / Gated DeltaNet

| 参数 | 值 |
|---|---|
| linear key heads | 16 |
| linear value heads | 48 |
| linear key head dim | 128 |
| linear value head dim | 128 |
| conv kernel | 4 |
| dtype | `mamba_ssm_dtype = float32` |
| output gate | `attn_output_gate = true` |
| gate type | `swish` |

### 4.3 Vision Encoder

| 模块 | Qwen3.8-27B |
|---|---|
| vision depth | 27 |
| vision hidden size | 1152 |
| vision heads | 16 |
| patch size | 16 |
| temporal patch size | 2 |
| spatial merge size | 2 |
| output hidden size | 5120 |
| image token id | 248056 |
| video token id | 248057 |

说明：视觉侧输出 `out_hidden_size = 5120`，正好对齐文本侧 hidden size，所以这是一个原生多模态结构，不是简单外挂。

---

## 5. Qwen3.8-27B 的新技术点

### 5.1 Hybrid Attention：线性注意力 + 全注意力混合

这是 Qwen3.8-27B 最关键的新结构。

```text
16 × (
  Gated DeltaNet
  Gated DeltaNet
  Gated DeltaNet
  Full Attention
)
```

核心价值：

```text
大多数层降低长上下文计算成本
少数层保留完整全局信息交互
```

这说明 Qwen3.8 并不是完全放弃 Full Attention，而是把 Full Attention 变成周期性全局校正层。

---

### 5.2 Gated DeltaNet：主要 Token Mixer

`linear_attention` 层实际使用的是 `Qwen3_5MoeGatedDeltaNet`。

可以抽象为：

```text
输入 token 序列
→ causal conv 局部混合
→ gated delta rule 递推状态更新
→ output gate 控制输出
→ 投影回 hidden_size
```

它的目的：

```text
用递推状态承载历史信息
避免每个 token 都和全部历史 token 做二次复杂度 attention
```

这对 262K 长上下文非常关键。

---

### 5.3 Gated Attention：全注意力层加输出门控

Qwen3.8 的 full attention 也不是普通 MHA/GQA，而是带输出门控。

配置表现为：

```text
attn_output_gate = true
output_gate_type = swish
```

结构可以理解为：

```text
attention_output × learned_gate
```

意义：

```text
不是让 attention 输出无条件进入 residual
而是让模型按 token / channel 决定 attention 信息通过多少
```

这有助于 linear attention 和 full attention 混合时保持稳定。

---

### 5.4 Partial RoPE + MRoPE

Qwen3.8 配置里有：

```text
partial_rotary_factor = 0.25
rope_theta = 10000000
mrope_interleaved = true
mrope_section = [11, 11, 10]
```

#### Partial RoPE

它不是对整个 head dim 都做 RoPE，而是只对一部分维度做位置旋转。

```text
head_dim = 256
partial_rotary_factor = 0.25
实际 RoPE 维度约为 64
```

意义：

```text
一部分维度编码位置
一部分维度保留内容表达
```

#### MRoPE

`mrope_section = [11, 11, 10]` 说明它支持多维位置编码拆分，适合图像 / 视频中的时间、高度、宽度位置表达。

```text
文本位置: 1D
图像/视频位置: Time + Height + Width
```

---

### 5.5 原生 Vision Encoder 接入语言模型

Qwen3.8 配置中：

```text
language_model_only = false
```

并且存在完整 `vision_config`。

它的多模态链路可以理解为：

```text
图片 / 视频
→ Vision Encoder
→ 映射到 5120 hidden size
→ 和文本 token 一起进入 Decoder
```

这说明它不是把图片转文字后再输入语言模型，而是原生视觉 token 接入语言模型。

---

### 5.6 Sparse MoE FFN

每个 decoder layer 后面接的是 `SparseMoeBlock`，不是普通 dense MLP。

结构为：

```text
hidden_states
→ router 选 top-k experts
→ routed experts 计算
→ shared expert 补充通用能力
→ routed output + shared output
```

价值：

```text
总参数可以变大
但每个 token 只激活一部分专家
推理成本不会线性跟总参数增长
```

---

## 6. 与 DeepSeek 类似的结构

Qwen3.8-27B 与 DeepSeek 最相似的是 MoE 大模型工程范式。

| 结构点 | Qwen3.8-27B | DeepSeek |
|---|---|---|
| Decoder-only 主体 | 是 | 是 |
| MoE FFN | 是 | 是 |
| Routed experts + shared expert | 代码支持 routed experts + shared expert | DeepSeek 明确有 routed experts + shared expert |
| RMSNorm | 是 | 是 |
| 激活函数 | `silu` | `silu` |
| attention bias | false | false |
| attention dropout | 0 | 0 |
| MTP | `mtp_num_hidden_layers = 1` | `num_nextn_predict_layers = 1` |
| 长上下文 | 262K | V3 163K，V4 1M |
| 词嵌入不共享 | `tie_word_embeddings = false` | `tie_word_embeddings = false` |

但注意力主干不同：

```text
DeepSeek:
MLA / CSA / HCA / sparse attention 路线

Qwen3.8:
Gated DeltaNet linear attention + periodic full attention 路线
```

---

## 7. 与 Kimi 类似的结构

Qwen3.8-27B 和 Kimi K3 的相似度最高，尤其是 Hybrid Attention 设计。

Kimi K3：

```text
69 KDA + 24 Gated MLA
```

Qwen3.8-27B：

```text
48 Gated DeltaNet + 16 Gated Attention
```

核心相似点：

```text
大部分层使用线性 / delta attention
少数层周期性使用 full attention / MLA
```

| 结构点 | Qwen3.8-27B | Kimi K3 |
|---|---|---|
| 原生多模态 | 是 | 是 |
| 线性注意力为主 | Gated DeltaNet | KDA |
| 周期性 full attention | 每 4 层 1 次 | 配置中 full attention 周期性出现 |
| Attention output gate | 有 | 有 |
| 长上下文 | 262K | 1M |
| MoE | 是 | 是 |
| shared expert | 代码支持 | 2 个 shared experts |
| RMSNorm | 是 | 是 |
| 视觉编码器 | 有 | MoonViT-V2 |

本质相似点：

```text
都是“线性注意力主导 + 全注意力补偿”的长上下文路线。
```

---

## 8. 与 GLM 类似的结构

Qwen3.8-27B 与 GLM-5.2 的相似点主要是长上下文、高效注意力、MoE 和 MTP。

| 结构点 | Qwen3.8-27B | GLM-5.2 |
|---|---|---|
| Decoder-only | 是 | 是 |
| MoE FFN | 是 | 是 |
| RMSNorm | 是 | 是 |
| SiLU | 是 | 是 |
| RoPE | MRoPE / partial rotary | RoPE interleave |
| 长上下文 | 262K | 1M |
| 周期性结构 | 每 4 层 full attention | sparse attention / indexer 周期性共享 |
| MTP | 1 层 | 1 层 |
| attention bias/dropout | false / 0 | false / 0 |

但二者长上下文路线不同：

```text
GLM:
DSA / IndexShare
通过 indexer 选择 top-k 历史 token，减少 1M context 下的注意力成本

Qwen3.8:
Gated DeltaNet + periodic full attention
通过线性注意力替代大部分 full attention，减少长上下文成本
```

---

## 9. 相同点总结

Qwen3.8、DeepSeek、Kimi、GLM 的共同趋势是：

```text
1. 都在从传统 Dense Transformer 走向稀疏化 / 混合化
2. 都使用 MoE 扩大总参数，但控制每 token 激活成本
3. 都面向长上下文，至少支持 100K+ 级别上下文
4. 都使用 RMSNorm、SiLU/SwiGLU 类结构、RoPE 类位置编码
5. 都不再满足于普通 full attention，而是引入高效注意力结构
6. 都有 speculative decoding / MTP 类推理加速设计
```

---

## 10. 最终判断

如果按技术相似度排序：

```text
最像 Kimi：
  Hybrid Attention 结构非常接近。
  都是 linear attention / delta attention 为主，周期性 full attention 补偿。

其次像 DeepSeek：
  MoE、MTP、RMSNorm、SiLU、长上下文、大模型 decoder 工程范式相似。

再是 GLM：
  长上下文和高效注意力目标一致，
  但 GLM 是 DSA / IndexShare，Qwen 是 Gated DeltaNet + periodic full attention。
```

最终结论：

```text
Qwen3.8-27B 的核心新技术是：
用 Gated DeltaNet 替代大部分 full attention，
把 full attention 变成周期性全局校正层，
再叠加 MoE、多模态 MRoPE、Vision Encoder 和 MTP，
形成一个面向长上下文与多模态任务的高效 Decoder 架构。
```