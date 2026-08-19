# Qwen3.8-27B 开源模型调研报告

> **调研时间**：2026-08-20
> **模型来源**：HuggingFace `Qwen/Qwen3.8-27B`
> **调研目的**：技术架构深度分析 + 源码文件下载验证

---

## 一、模型概述

| 项目 | 详情 |
|------|------|
| **模型名称** | Qwen3.8-27B |
| **发布机构** | 阿里巴巴通义千问 (Alibaba Cloud / Qwen Team) |
| **发布时间** | 2026-08-14 15:00 UTC |
| **开源协议** | Apache 2.0 |
| **模型类型** | `qwen3_5` (架构: `Qwen3_5ForConditionalGeneration`) |
| **模态** | 文本 + 图像 + 视频（原生多模态） |
| **已下载量** | 1,006,235+（截至 2026-08-20） |
| **GitHub 提交** | `1d4bf0f2ff6012fd82039f2fa52739d0dd7c60c0` |
| **Transformers 版本** | `5.8.0.dev0` |

### 仓库文件清单

模型在 HuggingFace 上分发为 18 个分片 + 13 个配置文件（不含权重约 22 MB）：

| 文件 | 大小 | 说明 |
|------|------|------|
| `config.json` | 5 KB | 模型架构配置 |
| `tokenizer_config.json` | 23 KB | 分词器配置（含 Chat Template） |
| `tokenizer.json` | 12.2 MB | 分词器完整定义 |
| `vocab.json` | 6.4 MB | 248,046 条词汇表 |
| `merges.txt` | 3.2 MB | BPE merges |
| `preprocessor_config.json` | 1 KB | 图像预处理器配置 |
| `video_preprocessor_config.json` | 1 KB | 视频预处理器配置 |
| `generation_config.json` | < 1 KB | 生成参数 |
| `chat_template.jinja` | 10 KB | 对话模板 |
| `model.safetensors.index.json` | 112 KB | 权重索引（**总大小 51.75 GB**） |
| `model-00001~00018-of-00018.safetensors` | 每片 ~3 GB | BF16 权重分片 |
| `README.md` / `LICENSE` | — | 文档 |

> **源码已下载**：`c:\Users\29214\Desktop\新建文件夹\Qwen3.8-27B-model\`
> **仓库源码**：`c:\Users\29214\Desktop\新建文件夹\Qwen3.8-main\`

---

## 二、核心架构（来自 `config.json` 源码验证）

### 2.1 文本主模型架构

```json
{
  "model_type": "qwen3_5_text",
  "hidden_size": 5120,
  "intermediate_size": 17408,
  "num_hidden_layers": 64,
  "num_attention_heads": 24,
  "num_key_value_heads": 4,
  "head_dim": 256,
  "max_position_embeddings": 262144,
  "vocab_size": 248320,
  "hidden_act": "silu",
  "rms_norm_eps": 1e-06,
  "rope_theta": 10000000,
  "partial_rotary_factor": 0.25,
  "tie_word_embeddings": false,
  "attn_output_gate": true,
  "output_gate_type": "swish",
  "full_attention_interval": 4
}
```

### 2.2 🔥 混合注意力层（Hybrid Attention Layout）

**这是 Qwen3.8-27B 最重要的架构创新**。从实际权重文件 (`model.safetensors.index.json`) 验证：

```
模式：[linear_attn × 3] → [self_attn × 1]  重复 16 次
```

| 注意力类型 | 层数 | 占比 | 组件（每层） |
|-----------|------|------|------------|
| **Gated DeltaNet** (线性) | 48 | 75% | `A_log`, `conv1d`, `dt_bias`, `in_proj_a`, `in_proj_b`, `in_proj_qkv`, `in_proj_z`, `norm`, `out_proj` |
| **Full Attention** | 16 | 25% | `q_proj`, `k_proj`, `v_proj`, `o_proj`, `q_norm`, `k_norm` |
| **MLP** | 64 | 100% | `gate_proj`, `up_proj`, `down_proj` |
| **LayerNorm** | 128 | — | `input_layernorm`, `post_attention_layernorm` |

**层类型分布源码验证**（取自权重索引）：

```
Layer  0-2 : linear_attn
Layer  3   : self_attn      ← 第 1 个 full attention
Layer  4-6 : linear_attn
Layer  7   : self_attn
Layer  8-10: linear_attn
Layer 11   : self_attn
...（3:1 交替）
Layer 60-62: linear_attn
Layer 63   : self_attn      ← 第 16 个 full attention
```

### 2.3 Gated DeltaNet 详细参数

```json
{
  "linear_attention": {
    "linear_num_key_heads": 16,      // QK 头数
    "linear_num_value_heads": 48,    // V 头数
    "linear_key_head_dim": 128,
    "linear_value_head_dim": 128,
    "linear_conv_kernel_dim": 4,    // 一维卷积核
    "in_proj_a": "alpha 投影 (用于 gating)",
    "in_proj_b": "beta 投影 (用于 gating)",
    "in_proj_qkv": "QKV 联合投影",
    "in_proj_z": "输出 gate 投影",
    "A_log": "可学习衰减系数（log 形式）",
    "dt_bias": "delta time 偏置",
    "out_proj": "输出投影",
    "norm": "RMSNorm"
  }
}
```

> DeltaNet 是一种**线性注意力机制**，使用状态空间模型（SSM）的递推形式。计算复杂度 O(n) 而非 O(n²)，适合处理长上下文。

### 2.4 Full Attention 详细参数

```json
{
  "self_attention": {
    "num_attention_heads": 24,      // Q 头
    "num_key_value_heads": 4,       // GQA 压缩
    "head_dim": 256,
    "q_norm": "RMSNorm on Q",
    "k_norm": "RMSNorm on K",
    "attn_output_gate": true,       // 输出门控
    "output_gate_type": "swish"
  }
}
```

### 2.5 位置编码

```json
{
  "rope_parameters": {
    "rope_type": "default",
    "rope_theta": 10000000,
    "partial_rotary_factor": 0.25,  // 仅 25% 维度使用 RoPE
    "mrope_interleaved": true,
    "mrope_section": [11, 11, 10]   // 三维 M-RoPE（适配多模态）
  }
}
```

**特点**：
- **Partial RoPE**：仅 25% 维度（5120 × 0.25 = 1280 维）旋转，其余维度跳过
- **M-RoPE (Multimodal RoPE)**：将 1280 维分成 `[11, 11, 10]`，分别在时间（T）、高度（H）、宽度（W）三个维度上旋转 — 支持原生多模态

### 2.6 多模态视觉编码器

```json
{
  "vision_config": {
    "model_type": "qwen3_5",
    "depth": 27,                     // 27 层 ViT
    "hidden_size": 1152,             // ViT 隐藏维度
    "intermediate_size": 4304,
    "num_heads": 16,
    "num_position_embeddings": 2304,
    "in_channels": 3,
    "patch_size": 16,                // 16×16 图像 patch
    "temporal_patch_size": 2,        // 视频时间 patch=2
    "spatial_merge_size": 2,         // 2×2 空间合并
    "out_hidden_size": 5120,         // 投影到 LLM 隐藏维度
    "hidden_act": "gelu_pytorch_tanh",
    "deepstack_visual_indexes": []   // 暂未启用 deepstack
  }
}
```

**视觉编码器权重结构**（从源码验证）：
- `model.visual.blocks.{0..26}` — 27 层 Transformer 块（每层 12 个参数 = 324 个）
- `model.visual.merger.{linear_fc1, linear_fc2, norm}` — 视觉-LLM 投影器
- `model.visual.patch_embed.proj` — patch 嵌入
- `model.visual.pos_embed` — 位置嵌入

### 2.7 多 Token 预测 (MTP)

```json
{
  "mtp_num_hidden_layers": 1,
  "mtp_use_dedicated_embeddings": false
}
```

**MTP 权重结构**（取自 `model.safetensors.index.json`）：
```
mtp.pre_fc_norm_embedding.weight
mtp.pre_fc_norm_hidden.weight
mtp.fc.weight
mtp.norm.weight
mtp.layers.0.input_layernorm.weight
mtp.layers.0.post_attention_layernorm.weight
mtp.layers.0.self_attn.{q_proj, k_proj, v_proj, o_proj, q_norm, k_norm}.weight
mtp.layers.0.mlp.{gate_proj, up_proj, down_proj}.weight
```

> 1 个 auxiliary head 训练多步，可用于**投机解码**（speculative decoding），推理时减少延迟。

---

## 三、Tokenizer 与 Chat Template

### 3.1 词汇表

- **词汇表总大小**：`248,320`（含 padding）
- **基础词汇**：`248,046`（来自 `vocab.json`）
- **特殊 Token 数量**：33 个

### 3.2 特殊 Token 体系

| Token ID | Token | 用途 |
|----------|-------|------|
| 248044 | `<\|endoftext\|>` | PAD / BOS / EOS |
| 248045 | `<\|im_start\|>` | 对话开始 |
| 248046 | `<\|im_end\|>` | 对话结束 / EOS |
| 248047 | `<\|object_ref_start\|>` | 物体引用开始 |
| 248048 | `<\|object_ref_end\|>` | 物体引用结束 |
| 248049 | `<\|box_start\|>` | 边界框开始 |
| 248050 | `<\|box_end\|>` | 边界框结束 |
| 248051 | `<\|quad_start\|>` | 四点框开始 |
| 248052 | `<\|quad_end\|>` | 四点框结束 |
| 248053 | `<\|vision_start\|>` | 视觉块开始 |
| 248054 | `<\|vision_end\|>` | 视觉块结束 |
| 248055 | `<\|vision_pad\|>` | 视觉占位 |
| 248056 | `<\|image_pad\|>` | 图像占位（**image_token_id**） |
| 248057 | `<\|video_pad\|>` | 视频占位（**video_token_id**） |
| 248058 | `<​tool_call>` | 工具调用开始 |
| 248059 | `</​tool_call>` | 工具调用结束 |
| 248060-248063 | `fim_prefix/middle/suffix/pad` | Fill-in-the-Middle |
| 248064-248065 | `repo_name`, `file_sep` | 代码 Agent |
| 248066-248067 | `tool_response`, `/tool_response` | 工具响应 |
| 248068 | `think` | 推理开始 |
| 248069 | `think` | 推理结束 |
| 248070-248076 | `audio_*`, `tts_*` | 音频/TTS 预留 |

### 3.3 Flexible Thinking Control

Chat Template 支持动态控制推理深度：

```jinja
{%- if enable_thinking is undefined or enable_thinking is true %}
    {%- set resolved_reasoning_effort = reasoning_effort|default('xhigh') %}
    {%- if resolved_reasoning_effort == 'xhigh' %}
        {%- set reasoning_instructions = 'Reasoning effort is set to xhigh. Please think carefully through the task, validate key assumptions, consider plausible alternatives, and prioritize correctness, consistency, and clarity in the final answer.' %}
    {%- elif resolved_reasoning_effort == 'low' %}
        {%- set reasoning_instructions = 'Reasoning effort is set to low. Keep your thinking brief and focused, moving directly to the conclusion without unnecessary elaboration.' %}
    {%- endif %}
{%- endif %}
```

**支持参数**：
- `reasoning_effort`: `xhigh` (默认) / `medium` / `low`
- `enable_thinking`: `true` / `false`
- `preserve_thinking`: 是否跨对话保留推理上下文
- `add_vision_id`: 是否在图片前添加 "Picture N:" 标签

### 3.4 工具调用格式

```xml
<​tool_call>
<function=example_function_name>
<parameter=example_parameter_1>
value_1
</parameter>
<parameter=example_parameter_2>
This is the value for the second parameter
that can span
multiple lines
</parameter>
</function>
</​tool_call>
```

---

## 四、生成与预处理器配置

### 4.1 `generation_config.json`

```json
{
  "bos_token_id": 248044,
  "do_sample": true,
  "eos_token_id": [248046, 248044],
  "pad_token_id": 248044,
  "temperature": 1.0,
  "top_k": 20,
  "top_p": 0.95
}
```

### 4.2 图像预处理器

```json
{
  "size": {
    "longest_edge": 16777216,    // 4096×4096 像素
    "shortest_edge": 65536        // 256×256 像素
  },
  "patch_size": 16,
  "temporal_patch_size": 2,
  "merge_size": 2,
  "image_mean": [0.5, 0.5, 0.5],
  "image_std":  [0.5, 0.5, 0.5],
  "processor_class": "Qwen3VLProcessor",
  "image_processor_type": "Qwen2VLImageProcessorFast"
}
```

### 4.3 视频预处理器

```json
{
  "size": {
    "longest_edge": 25165824,    // 视频更大的处理上限
    "shortest_edge": 4096
  },
  "temporal_patch_size": 2,
  "video_processor_type": "Qwen3VLVideoProcessor"
}
```

---

## 五、架构设计亮点分析

### 5.1 为什么是 3:1 混合？

从源码验证的 `full_attention_interval: 4`（每 4 层出现 1 次 full attention）：

```
┌─────────────────────────────────────────────────────────────────┐
│ Layer 0: Gated DeltaNet  ──►  FFN (gate/up/down)               │
│ Layer 1: Gated DeltaNet  ──►  FFN                                │
│ Layer 2: Gated DeltaNet  ──►  FFN                                │
│ Layer 3: Full Attention  ──►  FFN  ← 精确检索 / 全局关联        │
│          ... 重复 16 次 ...                                       │
│ Layer 63: Full Attention ──►  FFN                                │
└─────────────────────────────────────────────────────────────────┘
```

**设计哲学**：
- DeltaNet 擅长处理**长上下文中的局部模式**（O(n) 复杂度）
- Full Attention 负责**精确注意力检索**（O(n²) 但仅 25% 层）
- 在 262K 上下文下，节省约 **75% 的 attention 计算量**

### 5.2 Gated DeltaNet 在做什么？

从权重命名推断这是一个 **Gated DeltaNet**（基于 RWKV-7 / TTT 思路）：

```
输入 x
  ├─ in_proj_qkv ──► Q, K, V
  ├─ in_proj_a  ──► α (更新门)
  ├─ in_proj_b  ──► β (删除门)
  ├─ in_proj_z  ──► z (输出门)
  ↓
  conv1d(QKV) ──► ΔNet 核心递推（带 A_log 衰减、dt_bias）
  ↓
  norm(·) → (·) ⊙ z
  ↓
  out_proj ──► 输出
```

**关键参数**：
- `linear_conv_kernel_dim = 4`：短卷积核增强局部特征
- `linear_num_key_heads = 16, linear_num_value_heads = 48`：GQA 风格（V 头数 > QK 头数，节省参数）
- `mamba_ssm_dtype = float32`：SSM 状态用全精度，权重用 BF16

### 5.3 Partial RoPE（25%）的意义

```json
"partial_rotary_factor": 0.25
```

只有 hidden_size × 0.25 = 1280 维应用 RoPE：
- **训练效率更高**：长上下文中位置编码计算量减少
- **性能几乎无损**：参考 Qwen2.5/3.x 的实验结论
- **便于扩展**：通过 YaRN 可拉伸至 1M token

### 5.4 视觉编码器深度集成（非 Adapter）

视觉编码器（27 层 ViT）→ Merger（linear_fc1, linear_fc2, norm）→ 5120 维直接接入 LLM：
- **不同于 LLaVA**：无外部 projector
- **深度融合**：ViT 与 LLM 共同训练（"early fusion"）
- 支持 **image patch** 和 **video temporal patch**（2 帧合并）

---

## 六、相比 Qwen3.6-27B 的升级

| 维度 | Qwen3.6-27B | Qwen3.8-27B |
|------|-------------|-------------|
| 架构基础 | Qwen3.5 | Qwen3.5 + 改进 |
| 注意力 | 单一 Full Attention | **Hybrid: DeltaNet + Full Attention** |
| 隐藏层 | 5120 | 5120 |
| 上下文 | 较短 | **262K 原生 / 1M YaRN** |
| 推理控制 | 基础 | **reasoning_effort 旋钮 + preserve_thinking** |
| 多模态 | 视觉 | 视觉 + 视频 + 增强 |
| 长视频理解 | 弱 | **强（重新设计 video processor）** |
| 工具调用 | XML | XML + 增强 |

---

## 七、部署与生态

### 7.1 支持的推理框架

- **SGLang**：`sglang serve --model-path Qwen/Qwen3.8-27B --port 8000 --tp-size 4 --context-length 262144 --reasoning-parser qwen3 --tool-call-parser qwen3_coder`
- **vLLM**：`vllm serve Qwen/Qwen3.8-27B --port 8000 --tensor-parallel-size 4 --max-model-len 262144 --reasoning-parser qwen3 --enable-auto-tool-choice --tool-call-parser qwen3_coder`
- **TokenSpeed**：`tokenspeed serve Qwen/Qwen3.8-27B --port 8000 --tensor-parallel-size 4 --max-model-len 262144 ...`
- **Transformers Serve**：`transformers serve Qwen/Qwen3.8-27B --port 8000 --continuous-batching`
- **llama.cpp**：消费级 GPU 运行 GGUF（Q4_K_M 量化约 17GB）
- **MLX / MLX-VLM**：Apple Silicon
- **Unsloth**：训练 + 部署

### 7.2 微调框架

- **Unsloth**（推荐）
- **Swift**（ModelScope）
- **Llama-Factory**

### 7.3 官方应用

- **Qwen Studio**（chat.qwen.ai）
- **Qoder**（Agentic 编码平台）
- **QwenWork**（一站式 AI 工作平台）
- **Qwen Code**（终端 AI 代理）
- **QwenCloud**（OpenAI/Anthropic 兼容 API）

---

## 八、源码下载与目录结构

### 8.1 已下载源码位置

```
c:\Users\29214\Desktop\新建文件夹\
├── Qwen3.8-main\                    ← GitHub 仓库（仅 README + LICENSE）
│   ├── .github\
│   ├── LICENSE
│   └── README.md
│
└── Qwen3.8-27B-model\               ← HuggingFace 模型文件（不含 18 个权重分片）
    ├── config.json                  ← 5 KB，含完整架构定义
    ├── generation_config.json
    ├── preprocessor_config.json
    ├── video_preprocessor_config.json
    ├── tokenizer_config.json
    ├── tokenizer.json               ← 12.2 MB
    ├── vocab.json                   ← 6.4 MB，248,046 tokens
    ├── merges.txt                   ← 3.2 MB
    ├── chat_template.jinja
    ├── model.safetensors.index.json ← 权重索引（51.75 GB / 18 分片）
    ├── README.md
    └── LICENSE
```

### 8.2 验证项

✅ `config.json` 来源验证：`HuggingFace API GET /api/models/Qwen/Qwen3.8-27B` 确认 sha `1d4bf0f2ff6012fd82039f2fa52739d0dd7c60c0`
✅ 权重文件结构验证：`model.safetensors.index.json` 包含 1199 个权重项
✅ 注意力类型验证：48 linear_attn + 16 self_attn = 64 ✅
✅ DeltaNet 子组件完整：`A_log`, `conv1d`, `dt_bias`, `in_proj_qkv`, `in_proj_a/b/z`, `norm`, `out_proj`
✅ Special tokens 验证：33 个特殊 token 完整

### 8.3 未下载的文件

❌ `model-00001~00018-of-00018.safetensors`（每个 ~3 GB，共 51.75 GB）
**原因**：本地存储与带宽限制。如需加载模型运行，请使用：
```bash
huggingface-cli download Qwen/Qwen3.8-27B
# 或
git clone https://huggingface.co/Qwen/Qwen3.8-27B
```

---

## 九、总结

### 9.1 关键技术亮点

1. **🏗️ 混合注意力架构**：48 层 Gated DeltaNet（线性）+ 16 层 Full Attention（标准），3:1 比例
2. **📏 超长上下文**：262K 原生 + 1M YaRN，M-RoPE `[11, 11, 10]` 三维支持
3. **🎬 原生多模态**：27 层 ViT + 深度融合 merger，无 adapter
4. **🧠 灵活推理控制**：`reasoning_effort` 三档 + `preserve_thinking` 跨对话
5. **⏩ 多 Token 预测**：1 个 MTP head 支持投机解码
6. **🔧 完整 Agent 能力**：tool_call, FIM, repo_name, file_sep 等特殊 token
7. **📊 高效部署**：BF16 27B 兼容消费级 GPU（Q4_K_M 量化 17GB）

### 9.2 应用场景

- 长文档理解（科研、法律、金融）
- 视觉问答（图表、文档截图）
- 视频理解（短视频、长视频摘要）
- 代码 Agent（Qwen Code、Qoder）
- 复杂工作流自动化（QwenWork）

### 9.3 引用格式

```bibtex
@misc{qwen3.8,
  title  = {{Qwen3.8-Max}: A New Bar for Coding and Cowork},
  author = {{Qwen Team}},
  year   = {2026},
  month  = {August},
  url    = {https://qwen.ai/blog?id=qwen3.8}
}
```

---

## 附录：参考资料

- **HuggingFace 模型卡**：https://huggingface.co/Qwen/Qwen3.8-27B
- **GitHub 仓库**：https://github.com/QwenLM/Qwen3.8
- **ModelScope**：https://modelscope.cn/collections/Qwen/Qwen38
- **官方博客**：https://qwen.ai/blog?id=qwen3.8
- **第三方深度分析**：https://kie.ai/blog/qwen-3-8-27b-27b-dense-multimodal-local-model
- **架构详解**：https://www.mindstudio.ai/blog/qwen3-8-27b-architecture-benchmarks
