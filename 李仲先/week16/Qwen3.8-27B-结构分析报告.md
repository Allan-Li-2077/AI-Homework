# Qwen/Qwen3.8-27B 模型结构分析报告

> 数据来源：ModelScope 上 `Qwen/Qwen3.8-27B` 仓库的 `config.json`、`README.md` 与 `model.safetensors.index.json`（`transformers_version: 5.8.0.dev0`）。
> 分析日期：2026-08-21

---

## 1. 概述

Qwen3.8-27B 是千问（Qwen）3.8 代际中面向「紧凑、易部署」场景的稠密（非 MoE）原生多模态模型。它在 **Qwen3.5 架构**的基础上演进而来，是一个**因果语言模型 + 视觉编码器**的混合体，能够理解图像与视频，并支持灵活的思考（thinking）控制。

与常见的纯 Transformer 架构不同，Qwen3.8-27B 的核心语言模型采用 **「线性注意力（Gated DeltaNet）+ 全注意力（Gated Attention）」的混合结构**，并引入了 **多 Token 预测（MTP）** 模块，是典型的下一代高效长上下文架构。

---

## 2. 基本信息

| 项目 | 值 |
| --- | --- |
| 模型名称 | Qwen/Qwen3.8-27B（中文名：千问 3.8-27B） |
| 架构注册名 | `Qwen3_5ForConditionalGeneration` |
| `model_type` | `qwen3_5` |
| 模型类型 | 因果语言模型 + 视觉编码器（`image-text-to-text`） |
| 总参数量 | ≈ 27.8B（稠密，非 MoE） |
| 权重精度 | BF16（`bfloat16`），SSM 部分以 float32 计算 |
| 权重大小 | ≈ 55.6 GB（18 个 safetensors 分片，共 1199 个张量） |
| 许可证 | Apache-2.0 |
| 原生上下文长度 | 262,144（256K），可扩展至 1,000,000（1M） |
| 训练阶段 | 预训练 + 后训练（Post-training） |
| 词表大小 | 248,320（padding 后） |
| 兼容框架 | Transformers、vLLM、SGLang、TokenSpeed 等 |

---

## 3. 总体架构

Qwen3.8-27B 由三个顶层模块组成（对应 `config.json` 的顶层字段）：

```
Qwen3_5ForConditionalGeneration
├── model.language_model   ← 语言模型（qwen3_5_text）
│     ├── embed_tokens     词嵌入（不共享 / 未绑定）
│     ├── layers.0..63     64 层混合解码器
│     ├── norm             最终 RMSNorm
│     └── lm_head         输出投影（未绑定）
├── model.visual           ← 视觉编码器（qwen3_5）
│     ├── patch_embed      图像分块嵌入
│     ├── pos_embed        位置嵌入
│     ├── blocks.0..26     27 层 ViT
│     └── merger           视觉→文本空间投影
└── mtp                     ← 多 Token 预测模块（1 层）
```

- `language_model_only: false`，即**非纯语言模型**，是多模态模型。
- `tie_word_embeddings: false`：输入嵌入与输出 `lm_head` **不共享**。
- 特殊视觉 token：`vision_start_token_id=248053`、`vision_end_token_id=248054`、`image_token_id=248056`、`video_token_id=248057`。

---

## 4. 语言模型（Language Model）

语言模型是最核心的部分，约占总参数量的 **97%**。`text_config` 关键参数如下：

| 参数 | 值 |
| --- | --- |
| `hidden_size` | 5120 |
| `num_hidden_layers` | 64 |
| `intermediate_size` | 17,408 |
| `vocab_size` | 248,320 |
| `max_position_embeddings` | 262,144 |
| 激活函数 | `silu`（FFN 为 SwiGLU） |
| 归一化 | RMSNorm（`rms_norm_eps = 1e-6`） |
| 注意力 bias / dropout | 关闭（`false` / `0.0`） |
| `tie_word_embeddings` | `false` |

### 4.1 混合层布局（Hybrid Layout）

64 层并不是统一结构，而是按 **`[3×线性注意力 → 1×全注意力]`** 的周期重复（`full_attention_interval: 4`）：

```
16 × ( 3 × (Gated DeltaNet → FFN) → 1 × (Gated Attention → FFN) )
```

即 64 层中：
- **48 层**为 `linear_attention`（Gated DeltaNet）
- **16 层**为 `full_attention`（Gated Attention）

`config.json` 中的 `layer_types` 数组明确列出了这 64 层的类型分布（第 0、1、2 层为 linear_attention，第 3 层为 full_attention，以此类推）。

### 4.2 全注意力层：Gated Attention（16 层）

基于多头注意力（MHA）的 GQA（分组查询注意力）变体，并加入**门控**与 **QK 归一化**：

| 参数 | 值 |
| --- | --- |
| `num_attention_heads`（Q 头数） | 24 |
| `num_key_value_heads`（KV 头数） | 4（GQA 压缩比 6:1） |
| `head_dim` | 256 |
| RoPE 维度 | 64（= 256 × 0.25，部分旋转） |
| Q/K 归一化 | `q_norm`、`k_norm`（各 256 维） |
| 输出门控 | `attn_output_gate: true`，`output_gate_type: swish` |

每个全注意力层的权重张量（形状 `[out, in]`）：

| 张量 | 形状 | 说明 |
| --- | --- | --- |
| `q_proj` | `[12288, 5120]` | Q 投影（输出 2×，含门控分支） |
| `k_proj` | `[1024, 5120]` | K 投影（4 头 × 256） |
| `v_proj` | `[1024, 5120]` | V 投影（4 头 × 256） |
| `o_proj` | `[5120, 6144]` | 输出投影（24 头 × 256） |

> 说明：`head_dim=256` 属于**大 head 维**设计；`q_proj` 输出 12288 = 2 × 6144，多出的一半用于计算门控值，与 `attn_output_gate` 配合形成「Gated Attention」——这也是 Qwen3.5/3.8 代际引入的注意力门控机制。

### 4.3 线性注意力层：Gated DeltaNet（48 层）

线性注意力层是一个 **DeltaNet 风格的线性（RNN/SSM）注意力**，带有短卷积与门控，用于降低长序列的二次方计算/显存开销：

| 参数 | 值 |
| --- | --- |
| `linear_num_key_heads` | 16（Q/K 头数） |
| `linear_num_value_heads` | 48（V 头数） |
| `linear_key_head_dim` | 128 |
| `linear_value_head_dim` | 128 |
| `linear_conv_kernel_dim` | 4（短卷积核宽度） |
| `mamba_ssm_dtype` | `float32` |

每个线性注意力层的权重张量：

| 张量 | 形状 | 说明 |
| --- | --- | --- |
| `in_proj_qkv` | `[10240, 5120]` | 联合投影 Q+K+V（2048+6144+2048） |
| `in_proj_z` | `[6144, 5120]` | 门控 z（= 48×128，swish 门控） |
| `in_proj_a` | `[48, 5120]` | 输入门（A，按 V 头数 48） |
| `in_proj_b` | `[48, 5120]` | 输入门（B） |
| `conv1d` | `[10240, 1, 4]` | 短卷积（核宽 4） |
| `A_log` | `[48]` | SSM 状态矩阵 A（对数空间） |
| `dt_bias` | `[48]` | 时间步长偏置 |
| `norm` | `[128]` | 按 head_dim 的归一化 |
| `out_proj` | `[5120, 6144]` | 输出投影（48×128） |

> 该结构即 Qwen3-Next 提出的 **Gated DeltaNet**：以线性注意力/SSM 替代部分全注意力，实现线性复杂度的长上下文建模，同时用 swish 门控（`in_proj_z`）增强表达能力。

### 4.4 前馈网络（FFN）

每层（无论线性还是全注意力）都带一个标准的 **SwiGLU** FFN：

| 参数 | 值 |
| --- | --- |
| `gate_proj` / `up_proj` | 5120 → 17408 |
| `down_proj` | 17408 → 5120 |
| 激活函数 | `silu`（SwiGLU） |

### 4.5 位置编码（RoPE）

| 参数 | 值 |
| --- | --- |
| `rope_theta` | 10,000,000 |
| `partial_rotary_factor` | 0.25（仅对 25% 维度做旋转） |
| `rope_type` | `default`（多模态用 `mrope_interleaved`） |
| `mrope_section` | `[11, 11, 10]`（视觉多模态位置分区） |

采用**部分旋转（partial RoPE）**：每个 head 的 256 维中只有 64 维参与旋转，其余维度不旋转，兼顾位置感知与参数效率。

### 4.6 多 Token 预测（MTP）

`text_config` 中包含 MTP 配置：`mtp_num_hidden_layers: 1`、`mtp_use_dedicated_embeddings: false`。

权重索引中独立的 `mtp.*` 模块包含：
- `mtp.fc`（`[5120, 10240]`）：将拼接的 `[归一化隐藏态, 归一化嵌入]` 投影回隐层。
- `mtp.layers.0`：1 层全注意力 + SwiGLU FFN。
- 若干 RMSNorm（`mtp.norm`、`pre_fc_norm_embedding`、`pre_fc_norm_hidden`）。

MTP 在训练时让模型同时预测当前与后续 token，提升样本效率与推理时的投机解码能力（README 注明 "trained with multiple steps"）。

---

## 5. 视觉编码器（Vision Encoder）

`vision_config` 关键参数：

| 参数 | 值 |
| --- | --- |
| `depth` | 27 层 ViT |
| `hidden_size` | 1152 |
| `intermediate_size` | 4304 |
| `num_heads` | 16 |
| `patch_size` | 16 |
| `in_channels` | 3（RGB） |
| `num_position_embeddings` | 2304 |
| `out_hidden_size` | 5120（对齐语言模型隐层） |
| `spatial_merge_size` | 2（空间 2×2 合并） |
| `temporal_patch_size` | 2（视频时间维度分块） |
| 激活函数 | `gelu_pytorch_tanh` |

视觉编码器结构：
- `patch_embed.proj`：把图像切成 16×16 patch 并线性投影到 1152 维。
- `pos_embed`：2304 个可学习位置嵌入。
- `blocks.0..26`：27 层标准 Transformer 块（MHA + MLP + 两层 LayerNorm）。
- `merger`：将视觉特征从 1152 维投影到语言空间 5120 维。

`temporal_patch_size: 2` 与 `mrope_section` 表明模型原生支持**视频**输入；`spatial_merge_size: 2` 用于对 token 做空间合并以降低视觉 token 数量。`deepstack_visual_indexes: []` 表示未启用 DeepStack 视觉特征注入。

---

## 6. 参数规模核算（近似）

以下按 `config.json` 超参与张量形状估算，与权重文件实际大小（≈27.78B 参数）吻合。

| 模块 | 参数数量 | 占比 |
| --- | --- | --- |
| 词嵌入 `embed_tokens` + 输出 `lm_head`（未绑定） | ≈ 2.54B | ~9.2% |
| 16 × 全注意力层（含 FFN） | ≈ 5.96B | ~21.4% |
| 48 × 线性注意力层（含 FFN） | ≈ 18.40B | ~66.2% |
| MTP 模块（1 层） | ≈ 0.42B | ~1.5% |
| 视觉编码器（27 层 ViT + merger） | ≈ 0.45B | ~1.6% |
| **合计** | **≈ 27.8B** | 100% |

关键单项：
- 单层全注意力（含 FFN）：≈ 372M 参数
- 单层线性注意力（含 FFN）：≈ 383M 参数
- 词表相关（embed + lm_head，未绑定）：2 × 248,320 × 5120 ≈ 2.54B

---

## 7. 结构特点总结

1. **稠密（非 MoE）多模态**：约 27.8B 参数，兼具文本 + 图像 + 视频理解，`language_model_only: false`。
2. **混合注意力骨干**：64 层中 48 层为 **Gated DeltaNet**（线性注意力/SSM），16 层为 **Gated Attention**（全注意力），按 `3+1` 周期交替，兼顾长上下文效率与表达能力。
3. **门控机制**：全注意力层带输出门控（`attn_output_gate` + swish），线性层带 `in_proj_z` 门控，构成「Gated」家族核心。
4. **大 head 维 + GQA**：全注意力 `head_dim=256`、24 Q 头 / 4 KV 头（6:1 GQA）；线性注意力 48 V 头 / 16 QK 头，head_dim=128。
5. **QK-Norm 与部分 RoPE**：`q_norm`/`k_norm` 稳定训练；RoPE 仅旋转 25% 维度（64/256），`rope_theta=10M`。
6. **多 Token 预测（MTP）**：附带 1 层 MTP 模块，支持推理投机解码。
7. **超长上下文**：原生 256K，可扩展至 1M。
8. **未绑定嵌入**：`tie_word_embeddings: false`，输入嵌入与 `lm_head` 各自独立，配合 24.8 万的大词表。
9. **灵活的思考控制**：默认开启 thinking，可用 `reasoning_effort`（`xhigh`/`medium`/`low`）调节推理深度，`preserve_thinking` 保留历史推理上下文。

---

## 8. 参考

- ModelScope 模型页：`https://www.modelscope.cn/models/Qwen/Qwen3.8-27B`
- 配置文件：`config.json`、`generation_config.json`、`model.safetensors.index.json`
- Qwen 官方文档 / Qwen Cloud 概览：`https://www.qwencloud.com/models/qwen3.8-27b`
