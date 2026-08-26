# MiniMax-M2 与原始 Transformer 架构对比报告

> 对比对象：**MiniMax-M2**（MiniMax 2025.10 开源，229B 总参数 / 10B 激活参数，62 层，回归全注意力）
> 基线：**原始 Transformer**（Vaswani et al., 2017, *Attention Is All You Need*）
> 依据：`config.json` 与官方 `modeling_minimax_m2.py`（ModelScope `MiniMax/MiniMax-M2`）、本目录 `minimax_m2_model.py`（结构复现实现）

---

## 1. 概述

MiniMax 的架构路线：**Text-01/M1（2025.1/6）** 采用 Lightning Attention 线性注意力 + Softmax Attention 混合（每 7 层线性 + 1 层 Softmax，456B/45.9B），而 **M2 全面回归全注意力**（官方博客《Why Did MiniMax M2 End Up as a Full Attention Model?》），保留 MoE 稀疏架构并把注意力方案收敛到与 Qwen3 高度相似的主流路线，仅保留两个个性化设计：**per-layer QK-Norm** 与 **Partial RoPE**。

M2 的核心数字（全部与 config.json 逐字段核对）：

| 项 | 值 | 项 | 值 |
|---|---|---|---|
| 总参 / 激活 | 229B / 10B（激活率 4.37%） | 层数 | 62（全部 MoE 层） |
| hidden_size | 3072 | 词表 | 200064 |
| 注意力 | GQA 48 Q 头 / 8 KV 头，head_dim=128 | 上下文 | 196608 |
| 专家 | 256 个，top-8，**无共享专家** | 专家中间维 | 1536 |
| 路由 | sigmoid + correction bias + **renormalize** | 精度 | bf16 / **fp8 量化** |
| MTP | use_mtp=true，num_mtp_modules=3 | 位置编码 | **Partial RoPE**（rotary_dim=64） |

---

## 2. 总体架构对比

| 维度 | Transformer (2017) | MiniMax-M2 (2025) | 变化性质 |
|---|---|---|---|
| 模型规模 | ~65M | 229B 总参 / 10B 激活 | 稀疏化扩展 |
| 层数 | 6 | 62 | 深度扩展 |
| hidden size | 512 | 3072 | 宽度扩展 |
| 注意力 | 8 头 MHA，head_dim=64 | **GQA**：48 Q / 8 KV，head_dim=128 | 结构替换 |
| 注意力内部 | 缩放点积 + 因果 mask | + **per-layer QK-Norm** + **Partial RoPE** + fp32 softmax + KV Cache | 增量优化 |
| FFN | ReLU 两层 MLP，d_ff=2048 | **SwiGLU 细粒度 MoE**：256 专家 top-8，无共享专家 | 结构替换 |
| 归一化 | LayerNorm（Post-LN） | **RMSNorm**（Pre-LN）+ per-layer QK-Norm | 结构替换 |
| 残差 | x + Sublayer(x) | x + Sublayer(LN(x))（Pre-LN 恒等路径） | 位置调整 |
| 位置编码 | 绝对正弦相加 | **Partial RoPE**（rotary_dim=64，theta=5e6） | 结构替换 |
| 词表 | ~37K | 200064（200K tokenizer） | 扩展 |
| 上下文 | 512 | 196608 | 384 倍 |
| 输出层 | 与 embedding 共享权重 | **独立 lm_head**（tie_word_embeddings=False） | 结构调整 |
| 预测目标 | 单 token | **MTP** 多 token 预测（3 模块级联） | 新增 |
| 数值精度 | fp32 | bf16 / **fp8**（weight_block_size 128×128） | 工程化 |

---

## 3. 逐模块优化点详解

### 3.1 Embedding 层

| 优化点 | 原始 Transformer | MiniMax-M2 | 动机与收益 |
|---|---|---|---|
| 位置信息 | 绝对位置编码加到 embedding 上（×√d_model 匹配幅度） | **无位置加法**，位置由 Partial RoPE 在注意力内部注入 | 位置与语义解耦、可外推 |
| 权重共享 | tie（输入输出共享参数） | `tie_word_embeddings=False`，lm_head 独立 | 分类器与词嵌入解耦 |
| 词表 | ~37K BPE | **200064**（200K 子词） | 多语言/代码覆盖，embedding 参数 615M |

### 3.2 注意力层：MHA → GQA + per-layer QK-Norm + Partial RoPE

**① GQA（Grouped-Query Attention）**

- 48 个 Q 头共享 8 组 KV 头（`num_key_value_groups=6`），KV cache 按 **8 头**存储，读取时 `repeat_interleave` 对齐；
- 收益：KV cache 显存降为 Q 头数的 1/6，长上下文（196608）部署成本大幅降低。

**② per-layer QK-Norm（M2 的标志性设计）**

- 常规 QK-Norm（Hy3、Qwen3 等）：Q/K 投影后先 reshape 成多头，再对每个 head 的 `head_dim` 做 RMSNorm——所有头**共享**同一组缩放参数；
- M2 的 per-layer 版本：Q/K 投影后**在 reshape 之前**对整个拼接张量做 RMSNorm，缩放参数维度 = **头数 × head_dim**（q_norm: 48×128=6144，k_norm: 8×128=1024）——**每个 (head, dim) 都有独立缩放参数**。

```
常规 QK-Norm:   q_proj → [B,S,6144] → view [B,S,48,128] → RMSNorm(weight:128，跨头共享) → RoPE
per-layer:      q_proj → [B,S,6144] → RMSNorm(weight:6144，每头每维独立) → view [B,S,48,128] → RoPE
```

收益：更细粒度的逐头尺度控制，训练更稳定（M2 与 Qwen3 的"main diff"）。

**③ Partial RoPE 与缩放**

- `rotary_dim=64 = head_dim × 0.5`：head 128 维中**前 64 维旋转（32 个频率）、后 64 维不旋转**；
- `rope_theta=5000000`（远超 10000），配合 196608 上下文；
- 对比 Hy3（全维 RoPE：128 维全部旋转、64 个频率）与 MiniMax-01（RoPE 应用于一半 head 维度，base=1e7）——M2 的"部分旋转"延续了 MiniMax 对 partial RoPE 的偏好。

**④ 数值精度与缓存**

- softmax 在 fp32 下计算（`dtype=torch.float32`）；
- KV cache 增量解码；`sliding_window=null`（无窗口注意力，与 Gemma-3/Mistral 不同）。

### 3.3 FFN 层：ReLU → SwiGLU；Dense → 256 专家 MoE（无共享专家）

**① SwiGLU 激活**

- `FFN(x) = (SiLU(xW₁) ⊙ xW₃) W₂`，乘性门控替代 ReLU 加性非线性，表达力与训练稳定性更好。

**② 细粒度 MoE 与稀疏度**

- 每层 256 个专家（SwiGLU，中间维 1536），每 token 激活 top-8；
- **无共享专家**（`shared_intermediate_size=0`）——与 Qwen3 相同，与 Hy3（1 个共享专家）、Qwen3-Next 不同；共享专家的作用（吸收公共知识、减专家冗余）由 256 个细粒度专家自身的容量承担；
- **激活率 4.37%**（10B/229B），是 Qwen3-235B（9.36%）的两倍稀疏——以更大总参换取更低计算成本；
- 对比 Hy3：M2 专家更小更密（256×1536 vs 192×1536 + 共享），总参相近（229B vs 295B）但激活更低（10B vs 21B）。

**③ 路由策略（与 Hy3 / DeepSeek-V3 三方对比）**

```
M2:      logits → sigmoid → +e_score_correction_bias → top-8 → 选中分数 renormalize
Hy3:     logits → +expert_bias → sigmoid → top-8 → ×router_scaling_factor(2.826)，不归一化
DSV3:    logits → sigmoid → top-8 → renormalize（无 bias 项）
```

| 机制 | M2 | 说明 |
|---|---|---|
| `scoring_func=sigmoid` | ✓ | 专家独立打分、非 softmax 竞争（三家一致） |
| `use_routing_bias=true` | ✓ | `e_score_correction_bias`（官方为 **buffer**）加到 **sigmoid 之后**的分数上，只影响 top-k 选择、不进权重——与 Hy3（sigmoid 前加）位置不同 |
| **renormalize** | ✓ | 选中分数除以 top-k 之和——与 DSV3 相同，与 Hy3 相反 |
| 辅助负载均衡损失 | ✓（`router_aux_loss_coef=0.001`，Switch 风格） | Hy3 完全无 aux loss（靠 expert_bias 均衡） |
| jitter noise | 支持（config 为 0） | 训练期路由噪声 |

> 结论：M2 的路由 = **DSV3 的 renormalize + 类 Hy3 的 bias 校正 + Switch 式 aux loss**，是三家方案的"集大成"。

### 3.4 归一化层：LayerNorm → RMSNorm，Post-LN → Pre-LN，per-layer QK-Norm

- **RMSNorm**：去均值中心化，`rms_norm_eps=1e-6`，计算量低、可算子融合；
- **Pre-LN**：`x + Sublayer(LN(x))` 恒等残差路径，62 层深堆叠稳定；
- **per-layer QK-Norm**：注意力内部再归一化，参数粒度细化到每个 (head, dim)（见 3.2②）。

### 3.5 残差连接

- 结构与 Hy3 一致（经典恒等残差，无 Hyper-Connections 等可学习残差变体）；层数 6 → 62。

### 3.6 位置编码：绝对正弦 → Partial RoPE

| 方面 | 绝对正弦编码 | Partial RoPE（M2） |
|---|---|---|
| 注入 | 与 embedding 相加 | Q/K 前 64 维复数旋转（相对位置） |
| 旋转范围 | — | head_dim 前 50%（rotary_dim=64） |
| 频率数 | — | 32 个（theta=5e6） |
| 外推 | 训练长度即上限 | 大 theta + 长上下文训练（196608） |

Partial RoPE 的取舍：只旋转一半维度 → 位置分辨率减半（建模能力略降），换取计算量下降与更平滑的长距离位置泛化；这是 MiniMax 从 Text-01 到 M2 一脉相承的设计。

### 3.7 输出层

- 独立 `lm_head`（`tie_word_embeddings=False`）；fp8 量化时 `lm_head` 与 `gate`、`e_score_correction_bias` 均列入 `modules_to_not_convert`（保持高精度）；
- 200064 类 softmax，logits 计算在 bf16 下进行（未强制 fp32，对比 Hy3 的 `enable_lm_head_fp32`）。

### 3.8 训练目标：MTP（Multi-Token Prediction）

- `use_mtp=true`、`num_mtp_modules=3`、`mtp_transformer_layers=1`：3 个 MTP 模块级联，第 i 个模块预测第 i+1 个未来 token（与 DeepSeek-V3 MTP、Hy3 NextN 同思路）；
- 收益：样本效率提升、推理时支撑投机解码；
- 注：官方 transformers 版 `modeling_minimax_m2.py` **未实现** MTP 分支（仅保留全注意力主干），本目录 `minimax_m2_model.py` 按 config 补充了教学实现。

### 3.9 精度与推理工程

| 项 | Transformer | M2 |
|---|---|---|
| 权重精度 | fp32 | bf16，**fp8 量化**（`weight_block_size=[128,128]` 块量化，gate/bias/lm_head 豁免） |
| KV Cache | 无 | 有（GQA 压缩至 1/6） |
| 并行 | 单卡 | TP/PP 规划内置（q/k/v 列切、o 行切、gate 复制、专家切分） |
| 初始化 | 论文默认 | `initializer_range=0.02` |

---

## 4. 横向对比：M2 vs Hy3 vs DeepSeek-V3（同代开源 MoE LLM）

| 维度 | MiniMax-M2 | 混元 Hy3 | DeepSeek-V3 |
|---|---|---|---|
| 规模 | 229B / 10B | 295B / 21B | 671B / 37B |
| 层数 / hidden | 62 / 3072 | 80 / 4096 | 61 / 7168 |
| 注意力 | GQA + per-layer QK-Norm | GQA + QK-Norm（跨头共享） | **MLA**（低秩潜在 KV） |
| RoPE | Partial（64/128） | 全维（128/128） | 全维 + 解耦（MLA 专用） |
| 专家 | 256 top-8，无共享 | 192 top-8 + 1 共享 | 256 top-8 + 1 共享 |
| 路由 | sigmoid + bias + **renormalize** + aux loss | sigmoid + bias，**不归一化** + ×factor | sigmoid，**renormalize** |
| MTP | ✓（3 模块） | ✓（1 层 NextN） | ✓（1 层） |
| 特色 | 回归全注意力、fp8 原生 | 256K 上下文 | MLA、DSA 后续演进 |

三家同代模型的路由设计差异是理解 MoE 的核心案例：**是否 renormalize**（DSV3/M2 vs Hy3）、**bias 加在 sigmoid 前/后**（Hy3 vs M2）、**是否用 aux loss**（M2 vs Hy3）——三种组合各有优劣，M2 选择了最"保守完整"的一套。

---

## 5. 演进总结

```
Transformer 2017 ───────────────────────────────►  MiniMax-M2 (2025)
  Embedding + 绝对位置 ────────────────►  Embedding + Partial RoPE（196K 上下文）
  MHA ─────────────────────────────────►  GQA + per-layer QK-Norm + KV Cache（cache 1/6）
  ReLU FFN ────────────────────────────►  SwiGLU + 256 专家 MoE（229B/10B，无共享专家）
  LayerNorm + Post-LN ─────────────────►  RMSNorm + Pre-LN（62 层稳定）
  共享输出层 / fp32 ───────────────────►  独立 lm_head / bf16 + fp8 量化
  单 token 预测 ───────────────────────►  MTP 3 模块级联
```

**一句话总结**：MiniMax-M2 是一次"回归主流"的架构收敛——放弃自研的 Lightning Attention（线性注意力）回到全 Softmax 注意力，在 GQA + RMSNorm + Pre-LN + SwiGLU + 细粒度 MoE 的现代基线上，用 **per-layer QK-Norm**（逐头独立归一化）和 **Partial RoPE**（半维旋转）保留差异化，并以 4.37% 的超低激活率 + fp8 原生量化把推理成本压到极致。相比 Hy3 的"激进稀疏"（192 专家 + 共享专家 + 不归一化路由），M2 是"保守工程"路线（256 专家 + renormalize + aux loss）的代表。

---

## 6. 参考

1. Vaswani et al., 2017. *Attention Is All You Need* (NeurIPS).
2. MiniMax 官方：MiniMax-M2 模型卡与 Tech Blog（*Why Did MiniMax M2 End Up as a Full Attention Model?*）。
3. ModelScope `MiniMax/MiniMax-M2`：`config.json`、`modeling_minimax_m2.py`、`configuration_minimax_m2.py`（transformers 4.57.1 生成）。
4. 本目录 `minimax_m2_model.py`（结构复现实现，含 Partial RoPE 复数实现、per-layer QK-Norm、MTP 级联）。
5. 横向参考：DeepSeek-V3（MLA/MTP）、混元 Hy3（本目录 `hy_v3_model.py`）、Qwen3 系列。
