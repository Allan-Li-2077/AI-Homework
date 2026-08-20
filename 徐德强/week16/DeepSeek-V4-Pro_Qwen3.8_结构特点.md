# DeepSeek-V4-Pro-0813 与 Qwen3.8 结构特点汇总

## 1. 任务目标

基于当前本地文件夹材料，分别汇总两个开源模型的结构特点：

- `ds_v4pro_0813`：DeepSeek-V4-Pro-0813
- `qwen3.8`：Qwen3.8-27B

信息来源分为三类：

- 本地官方配置与 README：作为主要依据。
- 本地工程配置/第三方整理文档：作为辅助依据，会单独标注。
- 外部链接材料。

## 2. DeepSeek-V4-Pro-0813 结构特点

### 2.1 模型定位

DeepSeek-V4-Pro-0813 是 DeepSeek-V4-Pro 的正式发布版本。README 中说明，它继承 DeepSeek-V4-Pro Preview 的模型结构，并外挂 DSpark speculative decoding module，用于提升推理吞吐和生产环境表现。

从仓库内容看，该目录不仅包含模型配置、tokenizer 和 safetensors index，也包含 `encoding` 与 `inference` 两套工程文件，说明该版本的发布重点不仅是权重本身，还包括专用提示词编码、工具调用格式和本地推理路径。

### 2.2 基础 Transformer / MoE 结构

`config.json` 显示该模型架构为：

- `architectures`: `DeepseekV4ForCausalLM`
- `model_type`: `deepseek_v4`
- 隐藏维度：`hidden_size = 7168`
- 层数：`num_hidden_layers = 61`
- 注意力头数：`num_attention_heads = 128`
- KV 头数：`num_key_value_heads = 1`
- 单头维度：`head_dim = 512`
- 激活函数：`silu`
- 词表大小：`vocab_size = 129280`
- 权重不共享：`tie_word_embeddings = false`

MoE 部分是该模型的核心结构特征之一：

- 路由专家数：`n_routed_experts = 384`
- 共享专家数：`n_shared_experts = 1`
- 每个 token 激活专家数：`num_experts_per_tok = 6`
- MoE 中间维度：`moe_intermediate_size = 3072`
- 路由缩放：`routed_scaling_factor = 2.5`
- top-k 归一化：`norm_topk_prob = true`
- 路由方法：`topk_method = noaux_tc`
- 打分函数：`scoring_func = sqrtsoftplus`

这说明 DeepSeek-V4-Pro-0813 是大规模 MoE 模型，每个 token 只激活部分专家，以在参数容量和推理成本之间做折中。

### 2.3 注意力与长上下文设计

配置中给出的上下文长度为：

- `max_position_embeddings = 1048576`
- `rope_scaling.type = yarn`
- `rope_scaling.factor = 16`
- `original_max_position_embeddings = 65536`
- `sliding_window = 128`

这表明模型以 64K 原生位置长度为基础，通过 YaRN 位置扩展支持百万级上下文窗口。同时配置中存在 `compress_rope_theta = 160000` 与 `compress_ratios`，且压缩比例在 61 层中呈现大量 `128 / 4` 交替，最后有若干 `0`，说明模型内部对部分层的位置信息或缓存形态做了压缩/分层处理。

注意力相关还有一组 index 参数：

- `index_n_heads = 64`
- `index_head_dim = 128`
- `index_topk = 1024`
- `num_hash_layers = 3`

这些字段显示模型存在额外的索引/哈希辅助机制，可能服务于长上下文检索、压缩注意力或缓存选择。不过当前本地目录没有完整官方建模源码说明这些字段的精确计算路径，因此报告中只应保守表述为“配置层面存在索引/哈希相关结构参数”。

### 2.4 LoRA / 低秩相关结构

配置中包含：

- `q_lora_rank = 1536`
- `o_lora_rank = 1024`
- `o_groups = 16`

这说明该模型在 Q 投影和 O 投影附近带有低秩结构参数。由于当前本地文件缺少完整官方 `modeling.py`，不宜进一步断言这些低秩参数的具体训练或推理实现方式。

### 2.5 量化与专家精度

配置中显示：

- 主精度：`torch_dtype = bfloat16`
- 专家精度：`expert_dtype = fp4`
- 量化方式：`quant_method = fp8`
- FP8 格式：`fmt = e4m3`
- 动态激活量化：`activation_scheme = dynamic`
- 权重量化块大小：`weight_block_size = [128, 128]`

这说明 DeepSeek-V4-Pro-0813 的发布形态强调高效推理：整体有 FP8 量化配置，MoE 专家侧还出现 FP4 字段。`inference/README (2).md` 也说明，如果要使用 FP8，可以删除 `config.json` 中的 `"expert_dtype": "fp4"` 并在转换时指定 `--expert-dtype fp8`。

### 2.6 DSpark speculative decoding

README 明确写到该版本在 DeepSeek-V4-Pro Preview 结构基础上外挂 DSpark speculative decoding module。配置中对应字段包括：

- `num_nextn_predict_layers = 1`
- `dspark_block_size = 5`
- `dspark_target_layer_ids = [58, 59, 60]`
- `dspark_markov_rank = 512`
- `dspark_noise_token_id = 128799`

vLLM 启动说明中建议加入：

```bash
--speculative-config '{"method":"dspark","num_speculative_tokens":7,"draft_sample_method":"greedy"}'
```

SGLang 启动说明中使用：

```bash
--speculative-algorithm DSPARK
```

因此 DSpark 是 DeepSeek-V4-Pro-0813 的重要工程结构特征：它不是单独外部 draft 模型，而是从同一 checkpoint 中启用推测解码模块，目标是降低延迟、提高解码效率。

### 2.7 Prompt 编码、Thinking 与工具调用

DeepSeek-V4-Pro-0813 没有提供 Jinja 格式 chat template，而是在 `encoding` 目录中提供专用编码脚本。`encoding/README (1).md` 说明该编码支持：

- 多轮对话
- 工具调用
- extended thinking / reasoning
- quick instruction tasks
- OpenAI-compatible message 到模型输入字符串的转换
- 模型文本输出到结构化 message 的解析

工具调用使用 DSML 格式，核心标记包括：

- `<｜DSML｜tool_calls>`
- `<｜DSML｜invoke name="...">`
- `<｜DSML｜parameter ...>`
- `<tool_result>...</tool_result>`

Thinking 使用 `<think>...</think>` 表达。`reasoning_effort` 支持：

- `low`
- `high`
- `max`

其中 high/max 通过在 prompt 开头加入文本前缀来提高推理强度，而不是改变模型结构本身。

### 2.8 本地推理工程

`inference` 目录提供权重转换和推理脚本：

- `convert.py`
- `generate.py`
- `kernel.py`
- `model.py`

说明文档给出的运行方式包括：

- 先把 Hugging Face 权重转换为项目内部格式。
- 再通过 `torchrun` 启动交互式推理或批量推理。
- 支持多机多卡推理。

这说明该发布包面向大规模部署和工程验证，推理路径不仅依赖 Transformers，也提供了自有转换和生成脚本。

### 2.9 DeepSeek 小结

DeepSeek-V4-Pro-0813 的结构关键词可以概括为：

- 大规模 MoE：384 routed experts，每 token 激活 6 个专家。
- 百万上下文：通过 YaRN 与压缩/索引相关配置支持 1M 级上下文。
- GQA 极端压缩：128 个 attention heads，但只有 1 个 KV head。
- 量化友好：配置中同时出现 FP8 主量化和 FP4 expert dtype。
- DSpark 推测解码：同 checkpoint 内启用 next-token / next-n 风格推测模块。
- 专用 Agent 编码：无 Jinja chat template，使用 encoding 脚本和 DSML 工具调用格式。

## 3. Qwen3.8-27B 结构特点

### 3.1 模型定位

Qwen3.8-27B 是 Qwen3.8 系列中的 27B 开源模型。README 中将其定义为：

- Causal Language Model with Vision Encoder
- native vision-language model
- 支持文本、图像、视频输入
- 支持 thinking control
- 面向 coding、professional work、research、long-horizon agentic tasks

本地目录包含模型配置、tokenizer、chat template、图像/视频 processor 配置、safetensors index 与第三方整理文档，材料比 DeepSeek 目录更偏 Hugging Face / Transformers 标准多模态模型发布形态。

### 3.2 总体结构：Dense + 混合注意力

`config.json` 显示该模型为：

- `architectures`: `Qwen3_5ForConditionalGeneration`
- `model_type`: `qwen3_5`
- `language_model_only = false`
- 文本模型类型：`qwen3_5_text`
- 参数规模：README 标注为 27B
- 隐藏维度：`hidden_size = 5120`
- 层数：`num_hidden_layers = 64`
- FFN 中间维度：`intermediate_size = 17408`
- 词表大小：`vocab_size = 248320`
- 权重不共享：`tie_word_embeddings = false`

本地 `qwen3.8-27b.yml` 明确标注该模型不是 MoE，因为配置中没有 `num_experts` 或 `num_experts_per_tok` 字段。因此 Qwen3.8-27B 应按 dense 模型理解：参数常驻，不走专家路由。

### 3.3 Gated DeltaNet 与 Gated Attention 交替结构

README 给出的隐藏层布局是：

```text
16 × (3 × (Gated DeltaNet → FFN) → 1 × (Gated Attention → FFN))
```

对应到 `config.json` 中的字段：

- `num_hidden_layers = 64`
- `full_attention_interval = 4`
- `layer_types` 按 3 个 `linear_attention` + 1 个 `full_attention` 重复

因此该模型不是 64 层全量传统 self-attention，而是混合结构：

- 48 层 linear attention / Gated DeltaNet 风格层
- 16 层 full attention / Gated Attention 层

这类结构的意义是：用大部分线性注意力层降低长上下文成本，再周期性插入全注意力层增强全局建模能力。

### 3.4 Gated DeltaNet 参数

配置中与线性注意力/Gated DeltaNet 相关的字段包括：

- `linear_num_key_heads = 16`
- `linear_num_value_heads = 48`
- `linear_key_head_dim = 128`
- `linear_value_head_dim = 128`
- `linear_conv_kernel_dim = 4`
- `mamba_ssm_dtype = float32`

README 也写明：

- V 方向 linear attention heads 为 48
- QK 方向 linear attention heads 为 16
- head dimension 为 128

这说明 Qwen3.8-27B 在 48 个线性注意力层中使用类似 recurrent-state / DeltaNet 的序列建模方式，以降低长上下文下的 KV cache 压力。

### 3.5 Gated Attention / GQA 参数

全注意力层相关参数包括：

- `num_attention_heads = 24`
- `num_key_value_heads = 4`
- `head_dim = 256`
- `partial_rotary_factor = 0.25`
- README 中说明 RoPE 维度为 64

由于只有每 4 层中的 1 层是 full attention，真正产生传统 KV cache 长度增长压力的是 16 层 full attention，而不是全部 64 层。这个点在本地 `qwen3.8-27b.yml` 中也特别标注：如果按 64 层全部 full attention 估算 KV，会高估约 4 倍。

### 3.6 长上下文与 RoPE / M-RoPE

Qwen3.8-27B 的原生上下文配置为：

- `max_position_embeddings = 262144`
- README 标注可扩展到 1,000,000 tokens
- `rope_theta = 10000000`
- `rope_parameters.mrope_interleaved = true`
- `rope_parameters.mrope_section = [11, 11, 10]`
- `partial_rotary_factor = 0.25`

README 建议当任务超过 262K 原生上下文时，可以通过 YaRN 扩展到 1M，例如设置：

```json
{
  "rope_type": "yarn",
  "factor": 4.0,
  "original_max_position_embeddings": 262144
}
```

因此 Qwen3.8-27B 的长上下文结构特点是：原生 262K，结合混合注意力降低长上下文成本，需要更长上下文时再通过 YaRN 扩展。

### 3.7 多模态结构

Qwen3.8-27B 是原生视觉语言模型。`config.json` 中 `language_model_only = false`，并包含 `vision_config`，说明模型发布包内包含视觉编码器配置。

视觉塔参数包括：

- `vision_config.depth = 27`
- `vision_config.hidden_size = 1152`
- `vision_config.num_heads = 16`
- `vision_config.intermediate_size = 4304`
- `vision_config.patch_size = 16`
- `vision_config.temporal_patch_size = 2`
- `vision_config.spatial_merge_size = 2`
- `vision_config.out_hidden_size = 5120`

特殊 token 包括：

- `vision_start_token_id = 248053`
- `vision_end_token_id = 248054`
- `image_token_id = 248056`
- `video_token_id = 248057`

图像预处理配置：

- processor class：`Qwen3VLProcessor`
- image processor：`Qwen2VLImageProcessorFast`
- `patch_size = 16`
- `temporal_patch_size = 2`
- `merge_size = 2`

视频预处理配置：

- processor class：`Qwen3VLProcessor`
- video processor：`Qwen3VLVideoProcessor`
- 默认 `longest_edge = 25165824`
- README 建议长视频任务可把 video preprocessor 的 `longest_edge` 调到 `469762048`，以支持更高帧率和更长视频理解。

### 3.8 MTP 与推理特征

文本配置中包含：

- `mtp_num_hidden_layers = 1`
- `mtp_use_dedicated_embeddings = false`

README 写到 MTP 即 Multi-Token Prediction，并说明该模型 “trained with multiple steps”。本地 `qwen3.8-27b.yml` 也提到部分权重形态中存在 `mtp.safetensors` 或嵌入式 MTP head。

因此 Qwen3.8-27B 也具备多 token 预测相关结构，用于提升生成效率或推理阶段的 token 预测能力。但具体启用方式依赖推理框架和权重变体。

### 3.9 Thinking 与 preserved thinking

README 显示 Qwen3.8-27B 默认开启 thinking，可通过请求参数控制：

- `enable_thinking`
- `reasoning_effort`
- `preserve_thinking`

README 示例中 `reasoning_effort` 支持：

- `xhigh`
- `medium`
- `low`

`preserve_thinking` 默认开启，用于保留历史消息中的 thinking blocks。官方说明它对 agent 场景中的上下文连续性、减少重复推理和 KV cache 利用有帮助。

这部分更偏服务接口和推理策略，不是模型层数/参数意义上的结构，但它是 Qwen3.8 面向 Agent 工作流的重要机制。

### 3.10 第三方资料中关于 Qwen3.8-Max 的补充

本地 `qwen3-8-max.md` 是第三方整理文档，主题是 Qwen3.8-Max，而不是 Qwen3.8-27B。因此它不能直接替代 27B 开源模型的结构配置。

该文档中可作为系列背景的信息包括：

- Qwen3.8-Max 被描述为 2.4T 总参数、95B 激活参数的 MoE 模型。
- 支持图像和视频输入，原生多模态。
- 支持 1M 上下文和 131K 最大输出。
- 面向 Coding、professional work、Agent、工具调用等场景。
- 强调跨 Harness 稳定性、长任务能力、Function Calling、结构化输出、Web Search、Code Interpreter。
- `reasoning_effort` 和 `preserve_thinking` 被视为长链路 Agent 能力的重要接口。

需要注意：这些信息主要说明 Qwen3.8-Max 的产品与系列能力，不应直接写成 Qwen3.8-27B 的模型结构参数。Qwen3.8-27B 的结构仍以本地 `config.json` 和 README 为准。

### 3.11 Qwen3.8 小结

Qwen3.8-27B 的结构关键词可以概括为：

- Dense 27B：非 MoE，参数常驻。
- 混合注意力：48 层 Gated DeltaNet / linear attention + 16 层 Gated Attention / full attention。
- 长上下文友好：原生 262K，上限可通过 YaRN 扩展到 1M。
- 原生多模态：内置视觉塔，支持图像和视频输入。
- M-RoPE：配置中包含 `mrope_interleaved` 与 `mrope_section`。
- MTP：包含 1 层 Multi-Token Prediction 相关配置。
- Thinking 控制：默认 thinking，支持 reasoning effort 和 preserved thinking。

