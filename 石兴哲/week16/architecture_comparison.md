# 五家开源旗舰大模型架构综合对比报告

> **对比对象**（截至 2026-08-19 最新开源旗舰）：DeepSeek V4-Pro、Kimi K2.6、智谱 GLM-5.2、阿里 Qwen3.5-397B-A17B、腾讯混元 Hy3（Hunyuan-3）。
> **依据**：各模型 `config.json` + 建模代码（`model_code/` 下）+ 官方技术报告（`reports/` 下）。文件行号引用均以仓库根目录为基准。

---

## 核心结论（TL;DR）

1. **注意力机制已不是"MLA vs GQA"的简单二分**，而是分化为四条路线：DeepSeek V4 的 **CSA/HCA 压缩稀疏**（弃纯 MLA）、GLM-5 的 **MLA + DSA 稀疏**、Qwen3.5 的 **Gated DeltaNet 线性 + softmax 混合**、混元的 **GQA**。只有 Kimi K2.6 仍坚持**纯 MLA**。
2. **MoE 全面收敛到"共享专家 + top-k 路由"范式**，但专家规模、激活数、路由打分函数、细粒度各不同。
3. **残差/归一化都收敛到 pre-norm + RMSNorm**，唯一例外是 DeepSeek V4 的 **mHC（流形约束超连接）**，把残差升级为可学习的多路加权。
4. **位置编码全部是 RoPE 家族**，但 `rope_theta` 相差 3 个数量级（10000 → 11,158,840），长上下文模型普遍抬 theta 或叠加 YaRN/NTK 外推。
5. **训练侧差异集中在优化器与 RL 基础设施**：Muon（DeepSeek V4 与 Kimi 各自改造）、全国产算力（GLM）、异步 RL、原生量化训练（Kimi INT4 / DeepSeek FP4）等。

---

## 1. 注意力机制（原"MLA 实现"维度 → 重构为"注意力演进"）

### 1.1 纯 MLA 的原始实现（DeepSeek V3/R1 · Kimi K2 系列）

MLA（Multi-head Latent Attention）的核心是把 KV 投影到低秩 latent 空间，缓存的是 `kv_lora_rank + qk_rope_head_dim` 维而不是 `num_heads × head_dim` 维。

以 DeepSeek-V3.2 的 `inference/model.py` 为参照（`model_code/deepseek/reference/v3.2/model.py:498-531`）：

```python
class MLA(nn.Module):
    self.wq_a  = Linear(dim, q_lora_rank)              # Q 低秩投影
    self.q_norm = RMSNorm(q_lora_rank)
    self.wq_b  = ColumnParallelLinear(q_lora_rank, n_heads * qk_head_dim)
    self.wkv_a = Linear(dim, kv_lora_rank + qk_rope_head_dim)   # KV 低秩投影 + 独立 RoPE 维
    self.kv_norm = RMSNorm(kv_lora_rank)
    self.wkv_b = ColumnParallelLinear(kv_lora_rank, n_heads * (qk_nope_head_dim + v_head_dim))
```

关键点：
- **Q 走低秩**：`dim → q_lora_rank(1536) → n_heads×192`，`qk_head_dim = qk_nope(128) + qk_rope(64)`。
- **KV 走低秩**：`dim → (kv_lora_rank=512 + qk_rope=64) → n_heads×(qk_nope=128 + v_head=128)`。
- **RoPE 解耦**：只有 `qk_rope_head_dim=64` 这一维施加 RoPE，其余维（nope）不参与旋转（`model.py:563-566`）。
- **缓存收益**：每 token 只缓存 `512 + 64 = 576` 维，而非 MHA 的 `128×128=16384` 维（V3 报告）。

**Kimi K2 系列**复用了同一套 MLA（K2.6 的 `modeling_deepseek.py:630-680` 结构几乎一致，`q_a_layernorm:668`、`kv_a_layernorm:678`），但做了两处改动：① 注意力头从 128 减到 **64**（`config.json`），降低长上下文 agent 场景的推理延迟；② `rope_theta` 从 10000 抬到 **50000** 并叠加 YaRN 外推（见 §4）。

### 1.2 DeepSeek V4：弃纯 MLA → CSA/HCA 压缩稀疏

V4 是注意力改动最大的一家。config 里 `num_key_value_heads=1`、`head_dim=512`，**已无 `kv_lora_rank`**（`model_code/deepseek/v4-pro/config.json`）。即：**保留 Q 的低秩投影（`q_lora_rank=1536`），但 KV 不再做 latent 压缩，改为单 KV 头 + 直接投影**（`model.py:460` 的 `self.wkv = Linear(dim, head_dim)`），再叠加两级压缩稀疏。

核心新增三类组件（`model_code/deepseek/v4-pro/model.py`）：

| 组件 | 行号 | 作用 |
|---|---|---|
| `Compressor` | `model.py:279` | 用学习到的门控池化把连续 `ratio` 个 token 的 KV 压成 1 条；`ratio=4` 用重叠窗口（CSA），`ratio=128` 用非重叠（HCA） |
| `Indexer` | `model.py:380` | 轻量"闪电索引器"，对压缩后的 KV 打分，选出 top-k 位置做稀疏注意力（`index_topk`） |
| `Attention` | `model.py:436` | MLA 残壳 + 滑动窗口（最近 128 个原始 token）+ 按层压缩的 KV |

**按层混合压缩**由 `compress_ratios` 决定（`model.py:65`）：
```
compress_ratios = (0, 0, 4, 128, 4, 128, 4, 0)   # 0=纯滑窗, 4=CSA, 128=HCA
```
即部分层只做滑窗、部分层做 4:1 压缩稀疏（CSA，用于精确定位细节）、部分层做 128:1 压缩稠密（HCA，用于全局语义）。`index_topk`：Pro=1024、Flash=512（`config.json:index_topk`）。

**收益**：1M 上下文时，V4-Pro 推理 FLOPs 仅为 V3.2 的 27%、KV cache 仅 10%（V4 技术报告）。

### 1.3 GLM-5.2：保留 MLA，叠加 DSA 稀疏索引

GLM 走的是"**MLA 不动 + 稀疏化**"的折中路线，架构 `glm_moe_dsa`（继承自 DeepSeek-V3.2 的实现）。

- **MLA 完整保留**：`q_lora_rank=2048`、`kv_lora_rank=512`、`qk_nope=192`、`qk_rope=64`、`v_head_dim=256`（`model_code/glm/glm-5.2/config.json`），`q_a_layernorm:343`、`kv_a_layernorm:351`（`modeling_glm_moe_dsa.py`）。
- **叠加 DSA**：`GlmMoeDsaIndexer`（`modeling_glm_moe_dsa.py:186-255`）用 `index_n_heads=32`、`index_head_dim=128` 的轻量头，选出 `index_topk=2048` 个 token 做稀疏注意力。
- **独有：IndexCache（跨层索引复用）**：`skip_topk = config.indexer_types[layer_idx] == "shared"`（`modeling_glm_moe_dsa.py:366`），相邻层 70–100% 选中的 token 相同，因此把层分成 Full（自己算索引）/Shared（复用上一层索引）两类，砍掉约 75% 的索引计算（GLM-5 报告）。

与 DeepSeek V4 的关键区别：**GLM 稀疏化的是"原始 token 的选择"（DSA top-k），KV cache 仍保留完整 MLA 压缩态；V4 是"先压缩 KV 再对压缩块做稀疏"**。

### 1.4 Qwen3.5：Gated DeltaNet 线性注意力 + softmax 混合

Qwen3.5 走第三条路：**把 75% 的层换成线性注意力**，只保留 1/4 层做标准 softmax 注意力。

- `layer_types` 按 **3 个 `linear_attention` + 1 个 `full_attention`** 周期重复（`full_attention_interval=4`，`config.json`）。
- 线性层 = **Gated DeltaNet**（`modeling_qwen3_5_moe.py:385` 的 `Qwen3_5MoeGatedDeltaNet`），核心是 delta rule 递推（`torch_recurrent_gated_delta_rule`，`:332`）：
  ```python
  delta = (v_t - kv_mem) * beta_t          # :374，beta = sigmoid(b) :496
  S_t = exp(g_t)·S_{t-1} + k_t ⊗ delta      # g 为负对数衰减
  o_t = S_t^T @ q_t
  ```
  状态矩阵 `S` 固定大小（如 128×128/头），`O(1)` 显存、`O(L)` 计算，带 L2 norm（`chunk_gated_delta_rule` 融合核，`:250`）+ 深度卷积（`linear_conv_kernel_dim=4`）。
- softmax 层 = 标准 GQA（`num_attention_heads=32`、`num_key_value_heads=2`，即 **GQA 16:1**），加输出门控与 partial RoPE（`Qwen3_5MoeAttention:628`）。

**收益**：256K 上下文解码吞吐比 Qwen3-Max 高约 19×；周期性 full-attention 层保留了线性模型缺失的精确检索能力。

### 1.5 混元 Hy3 / A13B：标准 GQA + QK-Norm

混元没走 MLA/稀疏/线性路线，用**标准 GQA + 归一化增强**：

- **Hy3**：`num_attention_heads=64`、`num_key_value_heads=8`（**GQA 8:1**），`head_dim=128`（`config.json`）；`HYV3Attention`（`modeling_hy_v3.py:210`）额外加了 **`q_norm`/`k_norm`（RMSNorm，`:235-236`）**，与 `qk_norm: true` 对应——QK-Norm 是稳定长上下文训练/注意力熵的常见手段。
- **A13B**：32 头/8 KV 头（**GQA 4:1**），`use_qk_norm: true`（`config.json`），并支持 **CLA（Cross-Layer Attention）** 进一步压缩 KV。

### 注意力机制对比总表

| 模型 | 机制 | 头配置 | 关键参数 | 稀疏/压缩 |
|---|---|---|---|---|
| DeepSeek V3/R1 | 纯 MLA | 128 头 | q_lora 1536, kv_lora 512 | 无（V3.2 加 DSA） |
| **DeepSeek V4-Pro** | MLA 残壳 + CSA/HCA | **1 KV 头**, head_dim 512 | q_lora 1536, 无 kv_lora | 4:1 / 128:1 压缩 + topk 1024 |
| **Kimi K2.6** | 纯 MLA | 64 头 | q_lora 1536, kv_lora 512 | 无 |
| **GLM-5.2** | MLA + DSA | 64 头 | q_lora 2048, kv_lora 512 | topk 2048 + IndexCache |
| **Qwen3.5-397B** | GatedDeltaNet + softmax | 32 头/2 KV（GQA16） | 75% 线性层 | 线性 O(n) + 1/4 全注意力 |
| **混元 Hy3** | 标准 GQA | 64 头/8 KV（GQA8） | head_dim 128 + QK-Norm | 无 |

---

## 2. FFN / MoE 层

五家旗舰**全是稀疏 MoE**（无一家用纯 dense FFN 做旗舰），差异在专家规模、激活数、路由和细粒度。

| 模型 | 总/激活参数 | 专家数（路由+共享） | top-k | FFN 隐层 | 激活函数 | 路由打分 |
|---|---|---|---|---|---|---|
| DeepSeek V3/R1 | 671B/37B | 256 + 1 | 8 | 2048 | SwiGLU(silu) | sigmoid |
| **DeepSeek V4-Pro** | 1.6T/49B | 384 + 1 | 6 | 3072 | SwiGLU(silu) | **sqrtsoftplus**, norm_topk_prob |
| **Kimi K2.6** | ~1T/32B | 384 + 1 | 8 | 2048 | SwiGLU(silu) | sigmoid, routed_scaling 2.827 |
| **GLM-5.2** | ~750B/40B | 256 + 1 | 8 | 2048 | SwiGLU(silu) | 分组 top-k（norm_topk_prob） |
| **Qwen3.5-397B** | 397B/17B | 512 + 共享 | 10 | 1024 | SwiGLU(silu) | 共享专家 1024 |
| **混元 Hy3** | 295B/21B | 192 + 1 | 8 | 1536 | SwiGLU(silu) | **sigmoid + expert bias + route_norm** |

共同点与差异：

- **共享专家是标配**：五家都保留 1 个（Qwen 额外有 `shared_expert_intermediate_size=1024`）始终激活的共享专家，负责通用知识，路由专家负责专门化。
- **激活函数统一 SwiGLU（silu）**：`hidden_act: silu` 在各 config 中一致；GLM 的 MoE gate 走"分组 top-k"（先按组打分再组内选，`GlmMoeDsaMoE:498-526`），Qwen 亦然。
- **路由打分函数分化**：DeepSeek V4 用 `sqrtsoftplus`（`config.json:scoring_func`，报告称比 sigmoid 更利于专家均衡）；Kimi/Hy3 用 sigmoid；Hy3 额外有 `moe_router_enable_expert_bias` + `route_norm`（路由权重归一化，`config.json`）。
- **细粒度 MoE**：混元 A13B 是"细粒度"代表——`moe_intermediate_size` 是**逐层 32 元素列表**（`config.json`），每个专家 FFN 更小（3072），用更多专家（64）换取更细的负载均衡；Hy3 回到粗粒度（`expert_hidden_dim=1536` 统一）。
- **dense 层前置**：`first_k_dense_replace` 表示前 K 层用 dense FFN（DeepSeek V3/V4/GLM 用 3 或 1、Kimi 用 1、Hy3 用 1），前几层不路由，保证浅层语义稳定。

---

## 3. 残差 / 归一化方式

### 3.1 主流：pre-norm + RMSNorm（五家中的四家）

除 DeepSeek V4 外，其余全部采用 **pre-LayerNorm 结构 + RMSNorm**：
- Kimi：`DeepseekV3RMSNorm`（`modeling_deepseek.py:94`）
- GLM：`GlmMoeDsaRMSNorm`（`modeling_glm_moe_dsa.py:48`），每层 `input_layernorm` + `post_attention_layernorm`（`:605-606`），标准 pre-norm
- Qwen：`rms_norm_eps=1e-06`（config），pre-norm
- 混元：`HYV3RMSNorm`（`modeling_hy_v3.py:46`）

残差都是简单的 `x + Sublayer(x)` 恒等短路。

### 3.2 DeepSeek V4 的例外：mHC（Manifold-Constrained Hyper-Connections）

V4 把残差升级为**可学习的多路超连接**（`model_code/deepseek/v4-pro/model.py:647-668`）：

```python
class Block(nn.Module):
    # 不再是一条残差流，而是维持 hc_mult 份隐状态副本（hc_mult=4）
    # hc_pre:  用 Sinkhorn 学出的 pre-weights 把 hc 份合并为 1 份
    # hc_post: 用学到的 post-weights + 组合矩阵把 1 份扩展回 hc 份
```

实现上，`hc_split_sinkhorn`（`kernel.py:372`）把残差映射矩阵投影到 **Birkhoff 多胞形（双随机矩阵）**，用 **Sinkhorn-Knopp 迭代**（`hc_sinkhorn_iters=20`，`config.json`）保证谱范数 ≤ 1，从而约束信号传播的数值稳定性。这是"残差连接的谱范数约束"思路在万亿参数 MoE 上的首次落地（V4 报告）。

### 3.3 历史溯源：DeepNorm → RMSNorm

- **GLM-130B（2022）**提出 **DeepNorm**（`reports/glm/GLM-130B_DeepNorm.pdf`，arXiv:2210.02414），用残差缩放的"后置归一化变体"稳定千亿 dense 模型训练。
- 但 GLM-4 之后智谱**已回归标准 RMSNorm pre-norm**（GLM-5 的 `GlmMoeDsaRMSNorm`），DeepNorm 成为历史。
- 说明：**归一化收敛到 RMSNorm pre-norm 是行业共识**，真正的差异点转移到了"残差是否可学习"（V4 的 mHC）和"注意力内部的 QK-Norm / route-norm"（Hy3）。

---

## 4. 位置编码实现方式

五家**全部基于 RoPE**，但 `rope_theta` 与旋转范围策略差异巨大，是长上下文能力的关键分水岭。

| 模型 | rope_theta | 长上下文外推 | partial rotary | 备注 |
|---|---|---|---|---|
| DeepSeek V3/R1 | 10,000 | 原生 128K | 64/192（nope+rope 分头） | 标准 RoPE |
| **DeepSeek V4-Pro** | 10,000（+rope_scaling） | 原生 **1M** | **64/512 = 1/8** | 压缩 KV 用 `compress_rope_theta=160000` |
| **Kimi K2.6** | **50,000** | **YaRN**（factor 64）→ 256K | 64/192 | `rope_scaling.type=yarn` |
| **GLM-5.2** | **8,000,000** | 原生 **1M** | 64/256 = 1/4 | 高位 theta 直接撑 1M |
| **Qwen3.5-397B** | **10,000,000** | 原生 256K→1M | **0.25**（partial_rotary_factor） | + mRoPE（多模态交错） |
| **混元 Hy3** | **11,158,840** | 原生 256K | 全维 | `qk_norm` 稳定长序列 |
| 混元 A13B | 10,000 | **NTK 外推**（α=50→1000）→ 256K | 全维 | 三阶段长上下文预训练 |

关键观察：

1. **theta 抬升三个数量级**：从 DeepSeek 的 `10000` 到 GLM/Qwen/混元的 `8M~11M`。高位 theta 让 RoPE 频率变慢、旋转周期变长，直接支撑百万级上下文（GLM-5.2、Qwen3.5、Hy3 均原生 256K~1M）。
2. **partial rotary（部分维旋转）成新趋势**：DeepSeek V4 只对 512 维中的 64 维（1/8）旋转（`rope_head_dim=64`，`model.py:60`）；Qwen 用 `partial_rotary_factor=0.25`；GLM 用 `qk_rope=64 / qk_head_dim=256`（1/4）。**只旋转小部分维度**，其余维保持"无位置"或"绝对位置"，是提升长上下文泛化的经验技巧。
3. **外推策略三分**：Kimi 走 **YaRN**（`rope_scaling` + `rope_theta=50000`，`config.json`）；A13B 走 **NTK**（`rope_theta` 不变、按 α 缩放频率）；新一代（V4/GLM/Qwen/Hy3）直接**抬 theta 原生长上下文**，不再需要外推。
4. **线性注意力对位置的特殊处理**：Qwen3.5 的 Gated DeltaNet 里没有显式 RoPE，而是用**带衰减的递推状态**（`g` 负对数衰减 + 深度卷积 `linear_conv_kernel_dim=4`）隐式编码顺序——这是线性注意力与 softmax 注意力在"位置"上的根本分叉。

---

## 5. 各自独特的创新点

### DeepSeek V4
- **mHC 超连接**（§3.2）：Birkhoff/Sinkhorn 约束的可学习残差。
- **Muon 优化器**：万亿参数 MoE 首次用 Muon 替代 AdamW（嵌入/输出头/RMSNorm 仍用 AdamW），源自 Kimi K2 的思路并进一步改造。
- **FP4 QAT**：训练阶段就对 MoE 专家权重 + indexer 的 QK 路径做 FP4 量化感知训练。
- **训练稳定技巧**：Anticipatory Routing（loss 尖峰时用历史参数 θ_{t-Δt} 解耦路由）+ SwiGLU Clamping（线性输出截断到 [−10,10]）。
- **后训练范式**：Specialist-then-Distill——先分域（数学/代码/agent/指令）SFT+GRPO 养专家，再 on-policy 蒸馏（reverse KL）合并成单一模型。

### Kimi K2 系列
- **MuonClip / QK-Clip**：在 Muon 上引入按头 QK 权重裁剪，训练全程零 loss spike（万亿参数首次）。
- **原生 INT4 量化**：压缩张量（compressed-tensors）4-bit，且 `ignore` 掉注意力/共享专家/MLP/lm_head（`config.json:quantization_config`）——量化感知训练内置，发布即 INT4。
- **MoonViT 视觉编码器**：400M，`vision_config` 里 `video_attn_type=spatial_temporal`，原生图像+视频；`use_unified_vision_chunk` 统一视觉分块（`config.json`）。
- **300 并发子 Agent / 12000 步自主**：K2.6 的 agent 能力工程（不是架构，但影响训练数据与 RL 设计）。
- **YaRN + rope_theta=50000** 的 256K 长上下文。

### 智谱 GLM-5
- **全栈国产算力**：华为昇腾 + MindSpore 从零训练，零 NVIDIA 依赖；同时支持摩尔线程/海光/寒武纪/昆仑芯/沐曦/燧原七家国产芯片。
- **IndexCache**：跨层复用稀疏索引，砍 75% 索引计算（§1.3）。
- **异步 RL 框架 "slime"**：轨迹生成与训练解耦，最大化 GPU 利用率。
- **"三个 thinking 模式"**：Interleaved / Preserved / Turn-level，对应不同 agent 场景的思考控制。
- **28.5T tokens 训练**，比 GLM-4.5 的 23T 提升。

### 阿里 Qwen3.5
- **早融合多模态**：文本/图像/视频在预训练期就融合（SigLIP-2 编码 + **DeepStack** 多中层视觉注入），而非后期拼接。
- **250K 词表 + 201 语言**：低资源语言编码效率提升 10–60%。
- **Gated DeltaNet 混合**：线性注意力工业化的代表（§1.4）。
- **多 token 预测（MTP）**：`mtp_num_hidden_layers=1`（config），加速训练与投机解码。

### 腾讯混元 Hy3 / A13B
- **快慢思考双模式路由**：一个模型内 `fast thinking`（`/no_think`）+ `slow thinking`（`/think`）双推理模式（A13B 报告）。
- **细粒度 MoE**（A13B）：逐层专家 FFN 尺寸列表 + 专家级差异化学习率。
- **QK-Norm + route-norm + expert bias** 的稳定性组合（Hy3，§1.5/§2）。
- **三阶段长上下文预训练**（A13B）：4K 基础 → 8K 退火 → NTK 外推至 32K→256K。

---

## 6. 文件索引

- 完整下载清单与来源：见 [SOURCES.md](SOURCES.md)
- 代码：`model_code/{deepseek,kimi,glm,qwen,hunyuan}/`
- 论文/报告：`reports/{deepseek,kimi,glm,qwen,hunyuan}/`
