# MiniMax-M3 结构特点

## 1. 结论概览

MiniMax-M3 是一个 **原生多模态、混合 Dense/MoE、基于 MiniMax Sparse Attention（MSA）的长上下文模型**。它仍然沿用 Transformer 自回归解码器的基本范式，但对两个最昂贵的部分做了重构：

1. 用 MSA/块稀疏注意力替代大部分层中的标准全注意力；
2. 用稀疏 MoE 替代大部分层的 Dense FFN，并保留少量 Dense 层与共享专家。

本文只讨论给定的 `MiniMax-M3_config.json` 对应版本。该配置的语言主干是 `MiniMaxM3SparseForCausalLM`，完整模型封装为 `MiniMaxM3SparseForConditionalGeneration`，同时包含 CLIP 风格视觉塔。

## 2. 从标准 Transformer 到 MiniMax-M3

标准 Transformer 解码器大致是：

```text
Token -> Dense Self-Attention -> Dense FFN -> Residual/Norm
```

MiniMax-M3 的语言主干变为：

```text
文本 token
  -> 前 3 个 Dense Transformer 层
  -> 后 57 个 MoE 层
       ├─ MSA 稀疏注意力：索引器选择相关 KV 块
       └─ MoE FFN：128 个专家中选 4 个 + 1 个共享专家
  -> LM Head
```

视觉输入则经过 3D patch embedding、CLIP 风格视觉 Transformer、patch merge 压缩和 6144 维投影，再与文本 token 一起送入语言主干。因此它不是“给文本模型外挂一个图片编码器”这么简单，而是通过统一语言主干进行多模态条件生成。

## 3. 关键结构参数

### 3.1 语言主干

| 结构部分 | 给定配置 | 结构含义 |
|---|---:|---|
| 模型类型 | `minimax_m3_vl` | 文本与视觉联合的自定义模型类型 |
| 语言层数 | 60 | 其中前 3 层 Dense、后 57 层为 MoE |
| 隐藏维度 | 6144 | 语言主干表示宽度 |
| 注意力头/KV 头 | 64 / 4 | GQA 形态，多个 query head 共享 KV |
| 每头维度 | 128 | Q/K/V 的基础 head 宽度 |
| RoPE | `rotary_dim=64`，`rope_theta=5000000` | 只对部分维度施加旋转位置编码 |
| 最大位置长度 | 1048576 | 原生 1M token 级上下文配置 |
| 激活函数 | `swigluoai` | SwiGLU-OAI 风格门控 FFN |
| MoE 专家数 | 128 个本地专家 | 扩大总参数容量 |
| 每 token 激活 | 4 个路由专家 + 1 个共享专家 | 稀疏计算 |
| 专家中间维度 | 3072 | 路由专家与共享专家的基础宽度 |
| Dense FFN 中间维度 | 12288 | 前 3 个 Dense 层使用更宽的统一 FFN |
| 路由函数 | sigmoid，启用 routing bias | 通过带偏置的门控分数选择专家 |
| MTP | 7 个 MTP module，1 个 next-token 预测层 | 为多 token 预测/推测式生成提供结构支持 |

### 3.2 MSA 稀疏注意力

| MSA 配置 | 数值 | 作用 |
|---|---:|---|
| sparse index dim | 128 | 用于检索相关 KV 块的索引表示维度 |
| index heads | 4 | 索引器的头数 |
| block size | 128 | KV 被划分为固定大小的块 |
| sparse top-k blocks | 16 | 每个 query/查询组只保留最相关的 16 个块 |
| local block | 1 | 保留局部邻域块，补足局部连续性 |
| score type | `max` | 采用块级最大分数进行筛选 |
| 启用层 | 第 4 层起 | 与 MoE 层调度一致，前 3 层保持 Dense |

配置中的 `sparse_attention_freq` 前 3 个值为 0、之后为 1；`sparse_disable_index_value` 也呈现同样的层级调度。这意味着 MSA 不是一个只在推理阶段套上的 mask，而是主干结构的一部分。

## 4. 结构演变的重点

### 4.1 从全注意力到 MSA 块稀疏注意力

全注意力需要让每个 query 访问全部历史 KV，序列长度增加时计算与访存压力迅速上升。MiniMax-M3 的 MSA 加入了一个“先检索、后注意力”的阶段：

```text
历史 KV -> 索引器计算块分数 -> 选 top-16 个 KV 块
                                      ↓
Query ----------------------> 只对选中的块做注意力
```

它与普通滑动窗口的区别是：不是只看固定邻近窗口，而是动态选择可能相关的历史块；与完全稀疏 mask 的区别是：模型显式学习/计算块级索引，再执行稀疏注意力。给定配置中 128 token 一个块、每次选 16 块，表示注意力候选范围被结构化地压缩。

MSA 还以 GQA（64 个 query head、4 个 KV head）为基础，进一步降低 KV 的存储与读取压力。官方资料强调了 KV 外层 gather 的硬件执行路径：同一个 KV 块尽量只读取一次，再聚合命中该块的 query，这使稀疏性有机会转化为实际吞吐收益。

### 4.2 从统一 Dense FFN 到 Dense/MoE 混合

MiniMax-M3 的前 3 层是 Dense，后 57 层是 MoE：

- 前 3 层先建立稳定、共享的通用表示；
- 后 57 层使用 128 个专家，每个 token 只路由到 4 个专家；
- 1 个共享专家向所有 token 提供稳定的通用变换；
- `use_routing_bias=true` 通过路由偏置改善专家负载/选择行为。

这比“每一层都放同样的 MoE”更细致：注意力稀疏化和 FFN 稀疏化从第 4 层同步出现，形成分阶段的计算预算分配。

### 4.3 原生多模态而非后接视觉适配器

配置中的视觉部分包括：

- 32 层视觉 Transformer，隐藏维度 1280，16 个视觉头；
- 14×14 patch size，最大图像尺寸 2016；
- 3D RoPE，支持视频帧维度；
- `patch_merge` 压缩，空间 merge size 为 2、时间 patch size 为 2；
- 视觉特征经过投影进入 6144 维语言空间；
- `vision_segment_max_frames=4` 表示视觉段处理有帧数上限配置；
- `process_image_mode=dynamic_res` 支持动态分辨率图像网格。

因此，MiniMax-M3 的 Transformer 演变包括“文本注意力的稀疏化”，也包括“视觉 token 的压缩与语言空间对齐”。视觉 token 压缩很重要，否则高分辨率图像/视频会迅速占满 1M 上下文。

## 5. 与 `model_code` 中其他模型的对比

| 模型 | 主要演变 | 与 MiniMax-M3 的差异 |
|---|---|---|
| GLM-5.2 | MoE + DSA，78 层、1M 上下文 | 同样把注意力稀疏化用于长上下文，但 MiniMax-M3 使用 MSA，并将稀疏调度与多模态视觉主干结合 |
| DeepSeek-V4-Flash/Pro | MoE + CSA/HCA 等压缩注意力 | 都采用压缩/稀疏 KV 的方向；MiniMax-M3 的配置明确给出 128-token block、top-16 block 和 4-head indexer |
| Qwen3.6-35B-A3B | Gated DeltaNet/Gated Attention + MoE | 同为混合注意力 + 稀疏 MoE，但 Qwen 更强调 DeltaNet/门控注意力混合，MiniMax-M3 更强调 MSA 的块检索与 GPU 执行路径 |
| Ling-3.0-flash | KDA 线性注意力 + 门控 MLA + 512 专家 | Ling 通过递归状态处理大多数层；MiniMax-M3 仍保留显式 KV 块检索，只对相关块做稀疏注意力 |
| Kimi-K3 | 视觉塔 + 语言模型的多模态结构 | 与 MiniMax-M3 一样包含视觉输入，但 MiniMax-M3 的主要创新集中在 MSA 与文本 MoE 层调度 |

从这些模型可以看出，Transformer 的“注意力演进”大致有三条路线：

1. 线性/递归状态路线：Ling、部分 Qwen 结构；
2. 压缩 KV/块稀疏路线：MiniMax-M3、GLM、DeepSeek；
3. 混合路线：在不同层交替使用不同注意力机制，以兼顾效率与精确检索。

## 6. 优势与代价

### 优势

- MSA 将百万级上下文的全量 KV 访问变成索引后 top-k 块访问；
- GQA 降低 KV 头数量，减小 KV cache；
- 128 专家、top-4 路由与共享专家提升总容量而控制每 token 计算量；
- 前 3 层 Dense 为训练和跨模态对齐提供稳定基础；
- patch merge、动态分辨率和 3D RoPE 使图像/视频输入更适合长上下文；
- 1M 位置长度与多 token 预测结构适合代码、长文档和 Agent 多轮轨迹。

### 代价

- MSA 的收益依赖索引器、块稀疏算子和 KV 外层 gather 的专用实现；普通 Dense Attention 后端可能无法获得预期速度；
- 稀疏 top-k 可能漏掉低频但关键的远距离信息，需要 Dense 起始层、局部块和训练策略共同补偿；
- MoE 推理受专家路由通信和显存分布影响，理论激活参数不等于单卡显存需求；
- 视觉塔、视频帧和语言主干同时存在，部署复杂度明显高于纯文本 Causal LM；
- `transformers` 配置只描述结构参数，完整 MSA 算子仍需要相应版本的自定义模型代码/推理框架。
