# Qwen3.8-27B 与其他主流模型架构对比

> 数据来源：各模型 HuggingFace 官方 `config.json` 与 README（详见 `model_code/` 目录）
> 对比对象：Qwen3.8-27B、Qwen3.6-27B、Qwen3.6-35B-A3B、DeepSeek-V3、DeepSeek-V4（Flash/Pro）、Kimi-K3、GLM-5.2

---

## 1. 总览表

| 项目 | Qwen3.8-27B | Qwen3.6-27B | Qwen3.6-35B-A3B | DeepSeek-V3 | DeepSeek-V4-Flash | DeepSeek-V4-Pro | Kimi-K3 | GLM-5.2 |
|---|---|---|---|---|---|---|---|---|
| 厂商 | 阿里 Qwen | 阿里 Qwen | 阿里 Qwen | DeepSeek | DeepSeek | DeepSeek | 月之暗面 | Z.ai |
| 发布时间 | 2026-08 | 2026 上半年 | 2026 上半年 | 2024-12 | 2026 | 2026 | 2026 | 2026 |
| 总参数量 | **27B** | 27B | 35B | 671B | 284B | 1.6T | **2.8T** | ~615B |
| 激活参数量 | 27B（Dense） | 27B（Dense） | 3B | ~37B | 13B | 49B | 104B | ~52B |
| 稀疏化类型 | 无（Dense） | 无（Dense） | MoE | MoE | MoE | MoE | MoE | MoE |
| 层数 | 64 | 64 | 40 | 61 | 43 | 61 | 93 | 78 |
| Hidden Size | 5120 | 5120 | 2048 | 7168 | 4096 | 7168 | 7168 | 6144 |
| 上下文长度 | 262K（可扩 1M） | 262K（可扩 1M） | 262K（可扩 1M） | 163K | **1M** | **1M** | **1M** | **1M** |
| 视觉能力 | ✅ 原生多模态 | ✅ 原生多模态 | ✅ 原生多模态 | ❌ 文本 | ❌ 文本 | ❌ 文本 | ✅ 原生多模态 | ❌ 文本 |
| 注意力机制 | 混合注意力 | 混合注意力 | 混合注意力 | MLA | CSA+HCA | CSA+HCA | KDA+MLA | DSA+MLA |
| 线性/稀疏注意层 | Gated DeltaNet | Gated DeltaNet | Gated DeltaNet | — | CSA 压缩 | CSA 压缩 | KDA（69层） | DSA（每4层共享Indexer） |
| MTP/多token预测 | ✅ 1 层 | ✅ 1 层 | ✅ 1 层 | ✅ 1 层 | ✅ 1 层 | ✅ 1 层 | ❌ | ✅ 1 层 |
| 量化发布 | FP8 | FP8 | FP8 | FP8 | FP4+FP8 | FP4+FP8 | MXFP4 | BF16 |
| 许可证 | Apache-2.0 | Apache-2.0 | Apache-2.0 | MIT | MIT | MIT | 自定义 | MIT |

---

## 2. 注意力机制核心差异

注意力是本次对比中差异最大、最能体现"架构演进"的部分。

### 2.1 Qwen3.8-27B：Gated DeltaNet + Gated Attention 混合

采用**层级混合注意力**：每 4 层为一个周期，前 3 层用 **Gated DeltaNet**（线性注意力），第 4 层用 **Gated Attention**（全注意力）。

- 布局公式：`16 × (3 × (Gated DeltaNet → FFN) → 1 × (Gated Attention → FFN))`，共 64 层
- **Gated DeltaNet**（线性注意力，48 层）：
  - 线性 V 头 48 个，QK 头 16 个，头维 128
  - 线性卷积核 `linear_conv_kernel_dim=4`（短卷积窗口注入局部信息）
  - 推理复杂度 O(1) 每 token 每层（不随上下文增长），KV 缓存为常数大小
- **Gated Attention**（全注意力，16 层）：
  - Q 头 24 个，KV 头 4 个，头维 256
  - `partial_rotary_factor=0.25`（仅 25% 的通道注入 RoPE）
  - 每 4 层一次全注意力，负责全局信息检索与跨位置建模

> 结构定位：Qwen3.8-27B 与 Qwen3.6-27B 的架构**完全相同**（都是 `qwen3_5` 模型类型），差异主要在训练数据与后训练。Qwen3.8 的价值是"2026 年 8 月的最新版本"，架构沿革自 Qwen3.5 的混合注意力方案。

### 2.2 DeepSeek-V3：MLA（Multi-head Latent Attention）

- 128 个 Q 头、128 个 KV 头（全 KV，无线性注意力）
- **MLA 低秩压缩**：KV 先压缩到 `kv_lora_rank=512` 的低秩空间再投影回 128 维，大幅减少 KV 缓存
- Q 侧同样使用低秩 `q_lora_rank=1536` + RoPE 分离维度
- 每层都是全注意力（MHA 形式），无稀疏/线性混合

### 2.3 DeepSeek-V4：CSA + HCA 压缩稀疏注意力

- **CSA（Compressed Sparse Attention）**：用可学习 Indexer 为每个 query 选择 top-k 个 key（Flash 取 512，Pro 取 1024），只在稀疏子集上做注意力
- **HCA（Heavily Compressed Attention）**：对历史 token 做重度压缩（`compress_ratios` 含 4 与 128 两档），进一步缩小 KV 与计算量
- 单 KV 头（`num_key_value_heads=1`），`head_dim=512`
- 效果：1M 上下文下单 token 推理 FLOPs 仅为 V3.2 的 27%、KV 缓存为 10%

### 2.4 Kimi-K3：KDA（Kimi Delta Attention）

- 93 层中 69 层为 **KDA 线性注意力**、24 层为 Gated MLA
- KDA：96 头、头维 128、短卷积 `short_conv_kernel_size=4`，引入 Delta 规则做状态更新
- **AttnRes（Attention Residuals）**：`attn_res_block_size=12`，每 12 层把注意力结果作为残差注入，解决深层信号衰减
- MLA 侧：`q_lora_rank=1536`、`kv_lora_rank=512`，与 DeepSeek 思路同源但叠加了门控输出

### 2.5 GLM-5.2：DSA（Deep Sparse Attention）+ IndexShare

- 每 4 层一个周期，3 层稀疏 DSA + 1 层全注意力（`indexer_types` 中 `full` 每 4 层出现一次）
- **IndexShare**：跨 4 层共享同一个 Indexer（复用稀疏检索的索引），1M 上下文下每 token FLOPs 降低 2.9×
- MLA 式低秩：`q_lora_rank=2048`、`kv_lora_rank=512`，`head_dim=192`
- Indexer 每层取 top-2048 个 key，`index_topk_freq=4`

### 2.6 注意力对比小结

| 机制 | 代表模型 | 核心思想 | 复杂度（长上下文） |
|---|---|---|---|
| Gated DeltaNet（线性） | Qwen3.8/3.6 | 状态空间模型式线性递归 + 门控 + 短卷积 | 每 token 常数时间/常数 KV |
| MLA（低秩注意） | DeepSeek-V3、GLM-5.2 | KV 低秩压缩 | KV 减 ~93%，计算仍随长度增长 |
| CSA/HCA（压缩稀疏） | DeepSeek-V4 | Indexer 选 top-k + 重度压缩 | KV 与 FLOPs 大幅降低 |
| KDA（Delta 线性注意） | Kimi-K3 | Delta 规则线性递归 + 注意残差 | 每 token 常数时间 |
| DSA + IndexShare | GLM-5.2 | 稀疏检索 + 共享索引器 | FLOPs 降 2.9× |

---

## 3. FFN / MoE 差异

| 模型 | FFN 类型 | 专家数 | 每 token 激活 | 共享专家 | MoE 中间维 | 特点 |
|---|---|---|---|---|---|---|
| Qwen3.8-27B | Dense（SwiGLU） | — | — | — | 17408 | 纯 Dense，无路由 |
| Qwen3.6-35B-A3B | MoE | 256 | 8 + 1 共享 | 1 | 512 | 极小专家，激活仅 3B |
| DeepSeek-V3 | MoE | 256（分 8 组） | 8 | 1 | 2048 | 分组 topk（组内选 4），sigmoid 路由 |
| DeepSeek-V4 | MoE | Flash 256 / Pro 384 | 6 | 1 | Flash 2048 / Pro 3072 | sqrtsoftplus 打分，FP4 专家权重 |
| Kimi-K3 | LatentMoE | **896** | 16 | 2 | 3072 | Stable LatentMoE，激活 104B |
| GLM-5.2 | MoE | 256 | 8 | 1 | 2048 | 与 V3 类似，组数为 1 |

要点：
- **Qwen3.8-27B 是唯一走纯 Dense 路线的旗舰**，把容量集中到 27B 全参激活上；其余模型（除 Qwen3.6-27B）全部采用 MoE 稀疏化。
- Kimi-K3 专家规模最大（896 个），激活专家最多（16 个），激活参数也最大（104B）。
- DeepSeek-V4 把 MoE 专家权重直接发布为 **FP4**，是量化粒度最激进的。

---

## 4. MTP / 多 token 预测

| 模型 | MTP 层数 | 用途 |
|---|---|---|
| Qwen3.8-27B | 1 | 训练目标 + 推测解码加速 |
| Qwen3.6-35B-A3B | 1（multi-step 训练） | 同上 |
| DeepSeek-V3 | 1（`num_nextn_predict_layers=1`） | 训练目标 + 自推测解码（领先者） |
| DeepSeek-V4 | 1 | 同上 |
| Kimi-K3 | 0（无） | — |
| GLM-5.2 | 1 | 推测解码，接受长度提升最高 20% |

Qwen3.8 延续了 DeepSeek-V3 开创的 MTP（Multi-Token Prediction）路线：既作为训练时的多 token 预测目标（提升样本效率），又在推理时配合推测解码加速生成。

---

## 5. 位置编码与长上下文策略

| 模型 | RoPE θ | RoPE 维度比例 | 扩展策略 |
|---|---|---|---|
| Qwen3.8-27B | 10,000,000 | 0.25（partial） | 原生 262K，支持扩到 1M；mRoPE（图像/视频多模态） |
| DeepSeek-V3 | 10,000 | 全量 | YaRN（factor 40，163K） |
| DeepSeek-V4 | 10,000（压缩侧 160,000） | 全量 | YaRN（factor 16，1M）+ CSA 压缩 |
| Kimi-K3 | 默认 | 全量 | 1M |
| GLM-5.2 | 8,000,000 | 全量 | 1M，IndexShare 降 FLOPs |

- Qwen 系使用**超大 θ（1e7）+ 部分旋转（25%）**，配合混合注意力天然适合长上下文。
- DeepSeek 系 θ 较小但通过 YaRN 外推 + V4 的压缩注意力覆盖 1M。
- GLM-5.2 的 θ 高达 8e6，是文本模型中最高的之一。

---

## 6. 多模态能力对比

| 模型 | 视觉编码器 | 模态支持 | 架构类型 |
|---|---|---|---|
| Qwen3.8-27B | Qwen3.5 Vision（27 层，hidden 1152，patch 16×16，含时间维 patch 2） | **图像 + 视频 + 文本** | 原生多模态（编码器直连 LLM） |
| Qwen3.6-27B | 同上 | 图像 + 视频 + 文本 | 同上 |
| Qwen3.6-35B-A3B | 同上 | 图像 + 视频 + 文本 | 同上 |
| Kimi-K3 | 自研 VT（27 层，patch 14，1024 hidden） | 图像 + 视频 + 文本 | 原生多模态 agentic |
| DeepSeek-V3/V4 | 无 | 文本 | — |
| GLM-5.2 | 无 | 文本 | — |

Qwen3.8-27B 与 Kimi-K3 是目前开源阵营中**原生多模态 + 大上下文**的代表（都能看视频）。

---

## 7. Qwen3.8 的定位与核心差异总结

1. **Dense 路线的坚持者**：在大家都在做 MoE（从 35B-A3B 到 2.8T 的 K3）时，Qwen3.8-27B 用 27B 全参数 Dense + 混合注意力，主打中小规模低成本部署与完整激活容量。

2. **线性注意力（Gated DeltaNet）+ 全注意力的 3:1 混合**：与 GLM-5.2 的"3 稀疏 + 1 全量"模式结构相似，但 Qwen 用状态空间式线性注意力（常数 KV），GLM 用稀疏检索（索引 top-k），两者是两种不同的长上下文降本路径。

3. **相对自身（Qwen3.6）无架构变化**：`Qwen3.8-27B` 与 `Qwen3.6-27B` 的 `text_config` 完全一致，均为 `qwen3_5` 模型类型。差异在训练数据、后训练（thinking 保留、agentic 编码能力增强）与发布版本。

4. **与 DeepSeek 系列的对比**：Qwen 用"线性递归"换长上下文效率，DeepSeek 用"低秩 + 压缩稀疏"；前者 KV 恒为常数，后者 KV 随 topk 增长但语义检索更精确。

5. **与 Kimi-K3 的对比**：K3 走"极大 MoE（2.8T）+ Delta 线性注意 + 注意残差"路线，激活 104B 冲击推理上限；Qwen3.8 走"小 Dense + 线性注意"路线，强调单卡可部署。二者激活参数差约 4 倍，属于不同量级的产品定位。

---

## 8. 文件索引

- `model_code/Qwen_Qwen3.8-27B_config.json` — Qwen3.8-27B 配置
- `model_code/modeling_qwen3_5.py` — Qwen3.8-27B 实际建模源码（transformers `qwen3_5` 模块）
- `model_code/configuration_qwen3_5.py` — 对应配置类源码
- `model_code/qwen38_readme.md` — Qwen3.8-27B 官方模型卡
- `model_code/*_config.json` — 其余各模型配置
- `model_code/*_readme.md` — 其余各模型官方 README
- `tech_reports/` — DeepSeek-V3/V4、GLM-5、Kimi-K3 等技术报告 PDF
