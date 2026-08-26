# Ling-3.0-flash 结构特点

## 1. 结论概览

Ling-3.0-flash 不是在标准 Transformer 的全注意力层上简单增加 MoE，而是把 Transformer 解码器改造成 **混合线性注意力（hybrid-linear attention）+ 稀疏 MoE** 的结构。它的核心思路是：

大多数层使用 Kimi Delta Attention（KDA）承担低成本的序列状态更新，少数层使用门控 MLA 保留高精度的全局内容检索能力；每个 MoE 层再只激活少量专家。

根据给定配置，模型使用 `BailingMoeV3ForCausalLM`，共 42 层、隐藏维度 2560、最大位置长度 262144、BF16 权重，词表大小 157184。公开模型信息将其概括为约 124B 总参数、约 5.1B 激活参数的混合线性 MoE 模型。本文讨论的对象始终是 `Ling-3.0-flash`，不是 Ling 的其他版本。

## 2. 从标准 Transformer 到 Ling-3.0-flash

标准自回归 Transformer 的典型层可以抽象为：

```text
Token -> Self-Attention -> FFN -> Residual/Norm -> next layer
```

Ling-3.0-flash 将其改成：

```text
Token
  -> 2 个 Dense 层
  -> 35 个 KDA 线性注意力层 + 7 个门控 MLA 层（5:1 交错）
  -> 稀疏 MoE FFN（512 个路由专家中选 8 个，并叠加 1 个共享专家）
  -> Causal LM Head
```

这里的“线性”重点在注意力的序列处理方式，而不是把所有层都变成普通线性层。KDA 以递归状态/局部卷积形式压缩历史信息，避免每个新 token 都与完整历史 token 做二次复杂度的注意力；MLA 层则周期性地提供更强的全局信息读取能力。

## 3. 关键结构参数

| 结构部分 | 给定配置/公开模型信息 | 结构含义 |
|---|---:|---|
| 模型类型 | `bailing_hybrid` | 自定义的混合注意力语言模型，而非标准 `LlamaForCausalLM` |
| 层数 | 42 | 采用固定层级调度 |
| 隐藏维度 | 2560 | 主干 token 表示宽度 |
| 注意力头数 | 32 | 门控 MLA 的注意力头规模 |
| KDA/MLA 比例 | 35 个 KDA + 7 个门控 MLA | 约 5:1，KDA 负责效率，MLA 负责全局建模 |
| Dense 层 | 前 2 层 | 在路由稀疏化之前提供稳定的基础表示 |
| 路由专家 | 512 个 | 大规模专家池，增加总容量 |
| 每 token 激活专家 | 8 个路由专家 + 1 个共享专家 | 稀疏计算，激活参数远小于总参数 |
| 专家中间维度 | 768 | 单个专家较窄，依靠专家数量扩展容量 |
| Dense FFN 中间维度 | 6144 | Dense 层保留更宽的通用变换能力 |
| 最大位置长度 | 262144 | 原生 256K 级上下文 |
| 位置编码 | RoPE，`rope_theta=6000000`，旋转维度 64 | 与 MLA 的部分旋转位置编码配合 |
| 路由评分 | sigmoid；`topk_method=noaux_tc`；路由器 FP32 | 采用非 softmax 的门控分数与稳定路由计算 |
| 短卷积 | `short_conv_kernel_size=4` | 为线性注意力提供局部混合能力 |
| 下一 token 预测 | 1 个 NextN/MTP 层 | 训练/推理中支持额外的多 token 预测路径 |

其中，配置中的 `first_k_dense_replace=2` 表明前两层不替换为稀疏 MoE；第 3 层以后进入混合结构。`num_experts=512`、`num_experts_per_tok=8` 与 `num_shared_experts=1` 共同构成稀疏专家 FFN，而不是 512 个专家同时参与每个 token 的计算。

## 4. 结构演变的重点

### 4.1 从全注意力变成 KDA/MLA 混合注意力

传统 Transformer 的瓶颈是注意力需要保存并访问不断增长的 KV 序列。Ling-3.0-flash 用 KDA 层处理大部分序列更新：

- KDA 通过递归状态和短卷积吸收历史信息，推理时不必让每个 query 访问完整历史；
- 配置中的 `short_conv_kernel_size=4` 对应局部邻域混合；
- `kda_safe_gate=true`、`kda_lower_bound=-5.0` 表明 KDA 的门控更新具有安全下界/稳定性约束；
- 7 个门控 MLA 层作为“高精度全局检索点”，避免线性注意力完全丢失远距离精确匹配能力。

因此它不是“只追求线性复杂度”，而是在效率和精确检索之间进行结构化折中。

### 4.2 从密集 FFN 变成大专家池稀疏 MoE

标准 Transformer 的 FFN 对所有 token 使用同一组参数。Ling-3.0-flash 将大部分 FFN 换成：

```text
hidden state -> router -> 512 个专家中选择 8 个 -> 加权合并
                                     + 1 个共享专家
```

这样做的结果是：总参数量可以很大，但单 token 的计算只访问一小部分专家。共享专家负责稳定的通用知识，路由专家负责更细的模式/领域分工。`expert_swiglu_limit_list` 与 `share_expert_swiglu_limit_list` 还允许不同深度使用不同的 SwiGLU 限幅配置，体现了“按层调节专家”的进一步演变。

### 4.3 门控 MLA 的细粒度拆分

配置将 query/key 的表示拆成 `qk_nope_head_dim=128` 与 `qk_rope_head_dim=64` 两部分，并设置 `use_qk_norm=true`、`gated_attention_proj_granularity_type=head_wise`。这说明门控 MLA 并非简单复用标准 Q/K/V 投影，而是把不带位置编码和带 RoPE 的分量分开，再以 head-wise 粒度控制注意力投影。

## 5. 与 `model_code` 中其他模型的对比

| 模型 | 主干变化 | 与 Ling-3.0-flash 的差异 |
|---|---|---|
| Qwen3.6-35B-A3B | Gated DeltaNet 与 Gated Attention 混合，256 专家、8 路由 + 1 共享 | 思路最接近：都用混合注意力和稀疏 MoE；Ling 采用 KDA/门控 MLA、512 专家和 5:1 层级配比 |
| GLM-5.2 | MoE + DSA（稀疏注意力），78 层、1M 上下文 | GLM 更偏向稀疏块注意力；Ling 更偏向 KDA 线性状态更新，并用少量 MLA 做全局补偿 |
| DeepSeek-V4-Flash/Pro | MoE + CSA/HCA 等混合压缩注意力 | 都把注意力压缩/稀疏化作为长上下文关键；Ling 的差异是显式采用 KDA 与 MLA 的交错堆叠 |
| Kimi-K3 | 多模态 Transformer，视觉塔与语言主干分离 | Kimi-K3 的重点是多模态输入；Ling-3.0-flash 给定配置是纯文本 Causal LM |
| Qwen3.6-27B | Dense/多模态路线 | 不依赖 Ling 这种 512 专家的大规模稀疏路由 |

这组对比可以看出，开源模型的演进不是单一方向：Qwen/DeepSeek/GLM 更强调不同形式的稀疏或压缩注意力，Ling 则把“线性状态模型式注意力”和“少量高质量全局注意力”组合成一个固定混合主干。

## 6. 优势与代价

### 优势

- KDA 层降低长序列训练和解码的历史访问成本；
- MLA 层保留远距离精确检索能力；
- 512 专家扩大总容量，但每 token 只激活 8 个路由专家；
- 2 个 Dense 起始层和 1 个共享专家增强训练初期与通用能力的稳定性；
- 256K 上下文、KDA 状态和稀疏 MoE 适合长程 Agent/代码任务。

### 代价

- KDA、门控 MLA 和自定义 BailingMoeV3 不是标准 Transformers 原生层，推理需要对应的自定义实现/后端；
- MoE 的实际速度不仅取决于 FLOPs，还受专家并行、路由通信和显存带宽影响；
- 线性注意力并不等价于完整 KV 注意力，精确长距离检索主要依赖 7 个 MLA 层的补偿；
- 若推理框架只支持标准 Attention/MLP，不能直接从配置文件推断出可用的高效实现。
