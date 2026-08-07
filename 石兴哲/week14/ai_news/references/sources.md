# 权威信源清单

> 本文档定义 AI News Skill 使用的全部信息源。每个源均经过筛选：必须是**一手或准一手**来源，
> 能追溯到信息的原始出处。明确排除自媒体、公众号、知乎、CSDN 等二次加工平台。

---

## 信源评级标准

| 评级 | 定义 | 典型来源 |
|------|------|---------|
| **S** | 官方一手信源 — 信息直接来自创造者 | 公司官方博客、arxiv 原文、GitHub 官方仓库、顶会 proceedings |
| **A** | 半官方/高度可信信源 — 权威机构发布 | HuggingFace 官方、Papers With Code、The Batch 手动精选 |
| **B** | 声誉良好的第三方 — 用于交叉验证 | 知名科技媒体、Product Hunt 官方 |
| **不入级** | 二次加工/不可溯源 — 明确排除 | 微信公众号、知乎专栏、微博、CSDN、掘金、个人博客、Twitter 个人账号 |

## 使用说明

- **每日扫描**：所有 S 级 + A 级信源
- **交叉验证用**：B 级信源仅用于核对确认，不作为初始发现来源
- **每月审核**：检查各源的一手信息占比，变质者降级或移除

---

## 一、工业界动态（10个源）

### S 级 — 官方一手博客

| # | 名称 | URL | 覆盖领域 | 更新频率 | 备注 |
|---|------|-----|---------|---------|------|
| 1 | **OpenAI Blog** | https://openai.com/news | GPT/Sora/API/Safety | 每周 1-3 篇 | 行业最重要的声音源，所有 LLM 从业者必读 |
| 2 | **Anthropic Blog** | https://www.anthropic.com/blog | Claude/Safety/Alignment | 每周 1-2 篇 | AI Safety 领域最权威的一手来源 |
| 3 | **Google DeepMind** | https://deepmind.google/discover/blog | Gemini/Alpha系列/基础研究 | 每周 2-3 篇 | 兼具学术深度与工业影响力 |
| 4 | **Meta AI Blog** | https://ai.meta.com/blog | Llama/开源/具身智能 | 每周 1-2 篇 | 开源 LLM 生态核心驱动者 |
| 5 | **Microsoft AI Blog** | https://blogs.microsoft.com/ai | Copilot/Azure AI/Phi | 每周 1-2 篇 | 生态整合视角，企业级 AI 落地 |
| 6 | **Hugging Face Blog** | https://huggingface.co/blog | 开源模型/工具链/社区 | 每周 2-4 篇 | 开源社区风向标，覆盖全面 |
| 7 | **Mistral AI Blog** | https://mistral.ai/news | 开源模型/产品发布 | 每 1-2 周 1 篇 | 欧洲 LLM 代表，开源+商业双轨 |
| 8 | **Qwen Blog (Alibaba)** | https://qwenlm.github.io/blog | Qwen 系列/技术报告 | 每月 1-2 篇 | 中文 LLM 核心玩家，技术报告质量高 |
| 9 | **NVIDIA Technical Blog (AI)** | https://developer.nvidia.com/blog/category/artificial-intelligence | GPU/CUDA/推理优化 | 每周 2-4 篇 | 硬件+推理优化一手源，对 8GB VRAM 用户有价值 |
| 10 | **Apple ML Research** | https://machinelearning.apple.com | 端侧 AI/隐私/多模态 | 每月 1-2 篇 | 端侧部署视角，与低资源推理用户相关 |

### A 级 — 可信聚合/精选

| # | 名称 | URL | 覆盖领域 | 更新频率 | 备注 |
|---|------|-----|---------|---------|------|
| — | **The Batch** | https://www.deeplearning.ai/the-batch | AI 全领域 | 每周 1 期 | Andrew Ng 团队手动筛选+解读，比算法聚合质量高一个量级 |

---

## 二、学术论文（10个源）

### S 级 — 论文首发地

| # | 名称 | URL | 覆盖领域 | 更新频率 | 备注 |
|---|------|-----|---------|---------|------|
| 1 | **arXiv cs.CL** | https://arxiv.org/list/cs.CL/new | NLP/LLM | 每日 ~50-100 篇 | NLP 论文最大集散地 |
| 2 | **arXiv cs.LG** | https://arxiv.org/list/cs.LG/new | 机器学习 | 每日 ~80-150 篇 | 最大分类，需强过滤 |
| 3 | **arXiv cs.AI** | https://arxiv.org/list/cs.AI/new | AI 通用 | 每日 ~60-100 篇 | Agent/搜索/规划方向 |
| 4 | **arXiv cs.CV** | https://arxiv.org/list/cs.CV/new | 计算机视觉 | 每日 ~100-200 篇 | 量最大，仅关注高影响力 |
| 5 | **OpenReview** | https://openreview.net | 顶会评审中论文 | 按会议周期 | ICLR/NeurIPS/ICML 评审透明化，含评审意见 |
| 6 | **ACL Anthology** | https://aclanthology.org | NLP 全量 | 按会议周期 | ACL/EMNLP/NAACL/*CL 全量论文 |
| 7 | **PMLR (ICML等)** | https://proceedings.mlr.press | ML 会议 | 按会议周期 | ICML/AISTATS/CoRL 等 60+ 会议正式论文 |

### A 级 — 可信发现/过滤层

| # | 名称 | URL | 覆盖领域 | 更新频率 | 备注 |
|---|------|-----|---------|---------|------|
| 8 | **HuggingFace Daily Papers** | https://huggingface.co/papers | AI 全领域 | 每日 | 社区投票精选，每条可追溯到 arxiv。发现层，非原始源 |
| 9 | **Papers With Code** | https://paperswithcode.com | 有代码的论文 | 每日 | 代码+Benchmark 验证，复现性筛选 |
| 10 | **Semantic Scholar Trending** | https://www.semanticscholar.org | 高引论文 | 每日 | 引文网络发现，快速定位有影响力的新论文 |

### B 级 — 辅助参考

| # | 名称 | URL | 覆盖领域 | 更新频率 | 备注 |
|---|------|-----|---------|---------|------|
| — | **CVF Open Access (CVPR/ICCV)** | https://openaccess.thecvf.com | CV 顶会 | 按会议周期 | 仅交叉验证时使用 |
| — | **NeurIPS Proceedings** | https://papers.nips.cc | ML 顶会 | 按会议周期 | 仅交叉验证时使用 |

---

## 三、产品与开源项目（5个源）

| # | 名称 | URL | 类型 | 评级 | 备注 |
|---|------|-----|------|------|------|
| 1 | **Product Hunt AI** | https://www.producthunt.com/topics/artificial-intelligence | 新产品首发 | B | 创作者直接发布，需交叉验证 |
| 2 | **GitHub Trending (Python, weekly)** | https://github.com/trending/python?since=weekly | 开源项目 | B | AI/ML 项目筛选 |
| 3 | **YC Launch** | https://www.ycombinator.com/launches | 创业公司 | B | YC 孵化 AI 公司首发 |
| 4 | **HuggingFace Models (trending)** | https://huggingface.co/models?sort=trending | 新模型发布 | A | 社区验证的模型发布 |
| 5 | **各大公司 Changelog/Release** | (具体 URL 见各公司开发者页面) | API/产品更新 | S | 官方发布，最高可信度 |

---

## 四、已知排除列表（不入级，永不收录）

以下类型的信息源**明确排除**，不因任何理由收录：

| 排除类型 | 示例 | 排除原因 |
|---------|------|---------|
| 微信公众号 | 机器之心、量子位、新智元 | 二次加工，无法追溯原始来源，标题党严重 |
| 知乎专栏 | 所有 AI 相关专栏 | 个人观点为主，无编辑审核，质量参差 |
| 个人博客/Substack | 除官方团队外的个人 | 无法验证作者资质，可能是纯推测 |
| Twitter/X 个人账号 | KOL 个人账号 | 即使知名研究者，tweet 未经审核非正式发布 |
| CSDN/掘金/简书 | 所有 AI 教程/新闻 | 搬运为主，错误率高 |
| 视频平台 | B站/YouTube AI 频道 | 非文字源，难以检索和引用 |
| 付费墙源 | The Information 等 | 无法获取全文，摘要不足以做判断 |

---

## 五、用户专项关注源（额外补充）

以下源对用户的特定需求（8GB VRAM、本地推理、开源模型、Agent 开发）有独特价值：

| 名称 | URL | 专项价值 | 评级 |
|------|-----|---------|------|
| **llama.cpp Releases** | https://github.com/ggerganov/llama.cpp/releases | 本地推理引擎更新，直接影响 8GB VRAM 可用性 | S |
| **Unsloth Blog** | https://unsloth.ai/blog | QLoRA/高效微调技术，对低显存训练至关重要 | A |
| **vLLM Blog** | https://blog.vllm.ai | 高性能推理框架更新 | A |
| **Ollama Blog** | https://ollama.com/blog | 桌面端本地推理工具更新 | A |
| **LangChain Blog** | https://blog.langchain.dev | Agent 框架官方动态 | A |
| **LlamaIndex Blog** | https://www.llamaindex.ai/blog | RAG 框架官方动态 | A |
