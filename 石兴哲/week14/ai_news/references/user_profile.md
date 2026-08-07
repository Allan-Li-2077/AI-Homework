# 用户偏好配置

> 本文件定义 AI News Skill 的个性化参数。
> **覆盖不减少**：所有 AI 前沿领域都会收录，但高权重领域优先排序、优先进入 Top 摘要。
> 修改此文件后，下次执行即生效。

---

## 一、关注领域权重

每个领域分配 1-5 的权重，影响排序但不影响是否收录（排除类除外）。

### 重点领域（权重 ×2.0 — 最高优先展示）

| 领域 | 关键词 |
|------|--------|
| **LLM 训练与推理优化** | 训练、微调、推理、量化、LoRA、QLoRA、vLLM、llama.cpp、GGUF、KV cache、分布式训练、speculative decoding |
| **低显存部署 (≤8GB VRAM)** | 8GB、low VRAM、memory efficient、量化部署、本地推理、edge deployment、onnx、mlx |
| **Agent 架构** | Agent、multi-agent、tool use、function calling、planning、autonomous、orchestration、MCP |
| **RAG 与知识增强** | RAG、retrieval、embedding、向量数据库、knowledge base、hybrid search、GraphRAG |
| **中文 LLM 生态** | Qwen、DeepSeek、ChatGLM、Baichuan、Yi、通义千问、文心一言、Moonshot、Kimi、MiniMax |
| **开源模型发布** | open source、open weight、Apache、MIT、GPL、CodeLlama、Gemma、Llama、Mistral、Falcon |

### 关注领域（权重 ×1.0 — 标准展示）

| 领域 | 关键词 |
|------|--------|
| **多模态模型** | vision、image generation、video generation、Sora、Stable Diffusion、DALL-E、VLM |
| **AI Safety 与对齐** | safety、alignment、red team、RLHF、DPO、constitutional AI、jailbreak |
| **模型压缩与量化** | quantization、pruning、distillation、sparsity、INT4、INT8、AWQ、GPTQ |
| **强化学习** | RLHF、GRPO、PPO、reward model、RL for reasoning、decision-making |
| **具身智能与机器人** | embodied、robot、manipulation、navigation、ROS、sim-to-real |

### 一般关注（权重 ×0.5 — 择要展示）

| 领域 | 关键词 |
|------|--------|
| **计算机视觉** | detection、segmentation、recognition、ViT、DINO、SAM |
| **AI 芯片与硬件** | GPU、TPU、NPU、H100、B200、Apple Silicon、Edge AI、Neural Engine、Blackwell |
| **AI 政策与监管** | regulation、EU AI Act、policy、governance、export control |
| **AI 教育** | education、course、tutorial、MOOC、learning path |

### 排除领域（权重 ×0 — 不收录）

| 领域 | 原因 |
|------|------|
| **纯营销软文** | 无实质技术或产品内容 |
| **NFT/Web3/Crypto** | 除非与 AI 直接相关（如 AI+crypto 基础设施） |
| **纯金融分析/股价** | 投资建议不属于资讯简报范畴 |
| **招聘信息** | 单个公司的招聘帖 |
| **非技术类 AI 伦理争论** | 纯观点而无新研究/新政策的伦理讨论 |

---

## 二、信息来源偏好

| 偏好维度 | 设置 |
|---------|------|
| **信任优先级** | S 级官方源 > A 级可信聚合 > B 级第三方 > （不入级永不收录） |
| **语言** | 中英文均可，原始链接指向原文语言（不引用翻译版） |
| **付费墙** | 排除需付费订阅才能读全文的来源（摘要有足够信息则保留） |
| **地理偏好** | 全球覆盖，对中国 AI（Qwen/DeepSeek）和开源社区额外关注 |
| **内容形态** | 优先：官方公告/技术报告/论文/开源代码 > 媒体解读 > 个人观点 |

---

## 三、输出偏好

| 参数 | 设置 |
|------|------|
| **每日条目数** | 20-30 条（绝不超过 30 条，宁缺毋滥） |
| **摘要长度** | 每条 2-3 句中文摘要 |
| **链接要求** | 所有链接指向原始语言版本，不引用翻译站 |
| **排序规则** | 权重 5 领域优先 → 权重 4 → 然后按可信度 + 新鲜度综合排序 |
| **论文偏好** | 有开源代码 > 已被顶会接收 > 有显著 Benchmark 提升 |
| **产品偏好** | 有可用 Demo/GitHub 仓库 > 有清晰产品页面 > 仅新闻稿 |

---

## 四、已知偏差校正

以下偏差来自 AI 资讯生态系统的系统性问题，需主动校正：

| 偏差 | 表现 | 校正措施 |
|------|------|---------|
| **OpenAI 主导偏差** | 媒体过度报道 OpenAI，占比可能 >40% | 显式限制 OpenAI 相关条目 ≤5 条/日，为其他公司留出空间 |
| **NLP 主导偏差** | NLP/LLM 论文数量远超 CV/RL/Security | 每日至少 2 条来自非 NLP 领域（CV/RL/Robotics/Security） |
| **英文主导偏差** | 中文社区的重要发布可能被英文媒体忽略 | 每次执行必扫描 Qwen Blog + DeepSeek 官方公告 |
| **新鲜度偏差** | 可能过分关注"新"而忽略"重要但非新" | 持续追踪栏目补足长线话题（如 GPT-5 进展汇总） |
| **GitHub Stars 偏差** | 高 Star 项目不等于高质量 | 产品类必须看代码实际可用性，不只看 Star 数 |

---

## 五、持续追踪话题

以下话题是用户的长期关注点，每次简报的「持续追踪」栏目更新最新进展：

1. **GPT-5 / Orion 进展** — 关注 OpenAI 官方和 Sam Altman 公开发言
2. **DeepSeek 下一代模型** — 关注 DeepSeek 官方公告和 arxiv 技术报告
3. **Qwen3 进展** — 关注 Qwen Blog 更新
4. **本地推理工具链演进** — llama.cpp / Ollama / vLLM / MLX 重大更新
5. **开源 Agent 框架竞合** — LangChain / AutoGen / CrewAI / Dify 动态
6. **8GB VRAM 可用模型** — 新发布的小模型/量化方案（≤8B 参数、量化后 ≤6GB）
