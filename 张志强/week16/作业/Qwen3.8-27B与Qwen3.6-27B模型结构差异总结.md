# Qwen3.8-27B 与 Qwen3.6-27B 模型结构差异总结

qwen3_5 架构代码
64 层 Text Decoder
48 层 Gated DeltaNet linear attention
16 层 Gated full attention
每 4 层一个 full attention
Vision Encoder depth = 27
hidden_size = 5120
context = 262144
MRoPE
MTP = 1
Sparse MoE FFN


## 1. 结论概览

基于当前目录中的两份配置文件对比：

```text
第十六周/model_code/Qwen_Qwen3.6-27B_config.json
第十六周/model_code/Qwen_Qwen3.8-27B_config.json
```

可以得出一个明确结论：

```text
Qwen3.8-27B 相比 Qwen3.6-27B，
在 config 层面没有看到模型结构变化。
```

也就是说：

```text
没有新增新的 Attention 类型
没有新增新的 Decoder 层结构
没有改变 Vision Encoder
没有改变 hidden size / 层数 / head 数
没有改变 RoPE / MRoPE 参数
没有改变 MTP 配置
没有改变 vocab size
```

唯一显式不同的是：

```text
transformers_version:
  Qwen3.6-27B = 4.57.1
  Qwen3.8-27B = 5.8.0.dev0
```

因此，更严谨的判断是：

```text
Qwen3.8-27B 不是在 Qwen3.6-27B 基础上做了可见的结构升级，
而更像是同一模型结构模板下的权重、训练、后训练或框架适配版本升级。
```

---

## 2. 顶层架构对比

| 配置项 | Qwen3.6-27B | Qwen3.8-27B | 是否变化 |
|---|---|---|---|
| `architectures` | `Qwen3_5ForConditionalGeneration` | `Qwen3_5ForConditionalGeneration` | 无变化 |
| `model_type` | `qwen3_5` | `qwen3_5` | 无变化 |
| `language_model_only` | `false` | `false` | 无变化 |
| `tie_word_embeddings` | `false` | `false` | 无变化 |
| `transformers_version` | `4.57.1` | `5.8.0.dev0` | 有变化 |

说明：

```text
两者都复用 qwen3_5 这一套模型实现。
从配置上看，Qwen3.8-27B 没有切换到新的 qwen3_8 模型代码。
```

---

## 3. Text Decoder 主体结构对比

| 配置项 | Qwen3.6-27B | Qwen3.8-27B | 是否变化 |
|---|---:|---:|---|
| `text_config.model_type` | `qwen3_5_text` | `qwen3_5_text` | 无变化 |
| `num_hidden_layers` | 64 | 64 | 无变化 |
| `hidden_size` | 5120 | 5120 | 无变化 |
| `intermediate_size` | 17408 | 17408 | 无变化 |
| `num_attention_heads` | 24 | 24 | 无变化 |
| `num_key_value_heads` | 4 | 4 | 无变化 |
| `head_dim` | 256 | 256 | 无变化 |
| `vocab_size` | 248320 | 248320 | 无变化 |
| `max_position_embeddings` | 262144 | 262144 | 无变化 |
| `dtype` | `bfloat16` | `bfloat16` | 无变化 |
| `hidden_act` | `silu` | `silu` | 无变化 |
| `rms_norm_eps` | `1e-6` | `1e-6` | 无变化 |

结论：

```text
Text Decoder 的主体骨架完全一致。
两者都是 64 层、hidden size 5120、上下文 262K 的 Decoder 模型。
```

---

## 4. Attention 结构对比

两者的 `layer_types` 完全一致，都是：

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
48 层 linear_attention
16 层 full_attention
full_attention_interval = 4
```

| 配置项 | Qwen3.6-27B | Qwen3.8-27B | 是否变化 |
|---|---:|---:|---|
| `full_attention_interval` | 4 | 4 | 无变化 |
| `attention_bias` | `false` | `false` | 无变化 |
| `attention_dropout` | 0.0 | 0.0 | 无变化 |
| `attn_output_gate` | `true` | `true` | 无变化 |
| `output_gate_type` | `swish` | `swish` | 无变化 |

结论：

```text
Qwen3.8-27B 没有在 Qwen3.6-27B 的基础上新增 Attention 类型。
两者都是相同的 Hybrid Attention 结构：
大部分层使用 linear_attention，周期性插入 full_attention。
```

---

## 5. Linear Attention / Gated DeltaNet 对比

| 配置项 | Qwen3.6-27B | Qwen3.8-27B | 是否变化 |
|---|---:|---:|---|
| `linear_conv_kernel_dim` | 4 | 4 | 无变化 |
| `linear_key_head_dim` | 128 | 128 | 无变化 |
| `linear_value_head_dim` | 128 | 128 | 无变化 |
| `linear_num_key_heads` | 16 | 16 | 无变化 |
| `linear_num_value_heads` | 48 | 48 | 无变化 |
| `mamba_ssm_dtype` | `float32` | `float32` | 无变化 |

结论：

```text
Gated DeltaNet / linear attention 的配置没有变化。
因此，Qwen3.8-27B 没有在 3.6 的基础上增强或替换 linear attention 模块。
```

---

## 6. RoPE / MRoPE 位置编码对比

| 配置项 | Qwen3.6-27B | Qwen3.8-27B | 是否变化 |
|---|---:|---:|---|
| `partial_rotary_factor` | 0.25 | 0.25 | 无变化 |
| `rope_theta` | 10000000 | 10000000 | 无变化 |
| `rope_type` | `default` | `default` | 无变化 |
| `mrope_interleaved` | `true` | `true` | 无变化 |
| `mrope_section` | `[11, 11, 10]` | `[11, 11, 10]` | 无变化 |

结论：

```text
Qwen3.8-27B 没有新增新的位置编码方案。
它和 Qwen3.6-27B 一样使用 Partial RoPE + MRoPE。
```

---

## 7. MTP 配置对比

| 配置项 | Qwen3.6-27B | Qwen3.8-27B | 是否变化 |
|---|---:|---:|---|
| `mtp_num_hidden_layers` | 1 | 1 | 无变化 |
| `mtp_use_dedicated_embeddings` | `false` | `false` | 无变化 |

结论：

```text
MTP 配置没有变化。
Qwen3.8-27B 没有在配置中增加额外 MTP 层。
```

---

## 8. Vision Encoder 对比

| 配置项 | Qwen3.6-27B | Qwen3.8-27B | 是否变化 |
|---|---:|---:|---|
| `vision_config.model_type` | `qwen3_5` | `qwen3_5` | 无变化 |
| `depth` | 27 | 27 | 无变化 |
| `hidden_size` | 1152 | 1152 | 无变化 |
| `intermediate_size` | 4304 | 4304 | 无变化 |
| `num_heads` | 16 | 16 | 无变化 |
| `num_position_embeddings` | 2304 | 2304 | 无变化 |
| `out_hidden_size` | 5120 | 5120 | 无变化 |
| `patch_size` | 16 | 16 | 无变化 |
| `spatial_merge_size` | 2 | 2 | 无变化 |
| `temporal_patch_size` | 2 | 2 | 无变化 |

结论：

```text
Vision Encoder 完全一致。
Qwen3.8-27B 没有在 Qwen3.6-27B 基础上增加新的视觉编码层、patch 策略或输出维度。
```

---

## 9. Token 配置对比

| 配置项 | Qwen3.6-27B | Qwen3.8-27B | 是否变化 |
|---|---:|---:|---|
| `bos_token_id` | 248044 | 248044 | 无变化 |
| `eos_token_id` | 248044 | 248044 | 无变化 |
| `image_token_id` | 248056 | 248056 | 无变化 |
| `video_token_id` | 248057 | 248057 | 无变化 |
| `vision_start_token_id` | 248053 | 248053 | 无变化 |
| `vision_end_token_id` | 248054 | 248054 | 无变化 |
| `vocab_size` | 248320 | 248320 | 无变化 |

结论：

```text
Tokenizer 相关结构参数没有变化。
从 config 看，Qwen3.8-27B 没有扩词表或新增特殊 token。
```

---

## 10. Qwen3.8 在 Qwen3.6 基础上增加了什么？

从当前 config 文件能直接确认的是：

```text
结构层面：没有确认到新增内容。
```

唯一显式新增 / 变化项是：

```text
transformers_version 从 4.57.1 变为 5.8.0.dev0
```

这个变化表示：

```text
Qwen3.8-27B 可能面向更新版本的 Transformers 代码进行适配。
```

但它不等价于模型结构升级。

因此不能写成：

```text
Qwen3.8 在 Qwen3.6 基础上增加了某个新结构模块。
```

更准确应该写成：

```text
Qwen3.8-27B 在公开 config 中没有表现出结构新增。
它可能是在同一架构模板下，通过权重、训练数据、继续预训练、后训练、RL、对齐策略或推理框架适配获得版本提升。
```

---

## 11. 可能变化但 config 不能证明的部分

以下变化是可能存在的，但不能仅凭当前 config 文件证明：

```text
1. 预训练数据变化
2. 继续训练数据变化
3. 后训练 / SFT 数据变化
4. RL 或偏好对齐策略变化
5. 多模态数据配比变化
6. 代码能力、Agent 能力、工具调用能力增强
7. 权重 checkpoint 更新
8. 推理框架或 kernels 适配升级
```

这些需要额外证据：

```text
官方 README
release note
technical report
benchmark 对比
权重 metadata
训练说明
```

当前 `model_code` 目录里没有 Qwen3.8 单独技术报告，因此不能把这些推测当成结构事实。

---

## 12. 最终结论

最终可以总结为：

```text
Qwen3.8-27B 和 Qwen3.6-27B 在当前 config 中结构完全一致。
Qwen3.8 没有在 Qwen3.6 的基础上增加可见的新模型结构。
它们都使用 qwen3_5 架构代码，都是 64 层 Hybrid Attention + Vision Encoder + MTP 的多模态模型。
```

更简洁地说：

```text
Qwen3.8-27B 相比 Qwen3.6-27B，
不是结构升级，而更像同结构下的训练 / 权重 / 后训练 / 框架适配升级。
Qwen3.8-27B与Qwen3.6-27B在核心模型架构上几乎完全相同。两者的主要差异在于训练策略、后训练方式以及是否为原生多模态模型
```
