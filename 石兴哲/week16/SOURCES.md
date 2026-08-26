# 下载文件来源索引（SOURCES）

> 本目录收录 5 家开源旗舰大模型的**架构代码 + 配置文件 + README**（不含 tokenizer、不含权重），以及官方技术报告/关键历史论文。所有文件均来自 HuggingFace 仓库、HuggingFace Transformers 库 `main` 分支、arXiv 或官方仓库。数据核实于 **2026-08-19**。

## 版本清单

| 厂商 | 最新旗舰 | HF 仓库 | 关键参考版 |
|---|---|---|---|
| DeepSeek | V4-Pro / V4-Flash | `deepseek-ai/DeepSeek-V4-Pro` `-Flash` | V3.2（MLA+DSA）、R1（纯 MLA） |
| Kimi | K2.6 / K2.7-Code | `moonshotai/Kimi-K2.6` `-K2.7-Code` | K2-Instruct（MLA 初代） |
| GLM | GLM-5.2 / GLM-5 | `zai-org/GLM-5.2` `-5` | —（GLM-130B 论文入 reports） |
| Qwen | Qwen3.5-397B-A17B / 35B-A3B | `Qwen/Qwen3.5-397B-A17B` `-35B-A3B` | —（Qwen3 报告入 reports） |
| 混元 | Hy3（Hunyuan-3） | `tencent/Hy3` | A13B（论文最完整） |

## 代码文件来源

### DeepSeek
- `model_code/deepseek/v4-pro/*` ← `https://huggingface.co/deepseek-ai/DeepSeek-V4-Pro/resolve/main/{config.json, README.md, generation_config.json, inference/model.py, inference/kernel.py, inference/config.json}`
- `model_code/deepseek/v4-flash/{config.json, README.md, generation_config.json}` ← `https://huggingface.co/deepseek-ai/DeepSeek-V4-Flash/...`
- `model_code/deepseek/reference/v3.2/{config.json, README.md, model.py, kernel.py}` ← `https://huggingface.co/deepseek-ai/DeepSeek-V3.2/...`（`model.py`=`inference/model.py`，`kernel.py`=`inference/kernel.py`）
- `model_code/deepseek/reference/r1/{config.json, README.md, modeling_deepseek.py, configuration_deepseek.py}` ← `https://huggingface.co/deepseek-ai/DeepSeek-R1/...`

### Kimi
- `model_code/kimi/k2.6/{config.json, README.md, modeling_kimi_k25.py, configuration_kimi_k25.py, modeling_deepseek.py, configuration_deepseek.py}` ← `https://huggingface.co/moonshotai/Kimi-K2.6/...`
- `model_code/kimi/k2.7-code/{config.json, README.md}` ← `https://huggingface.co/moonshotai/Kimi-K2.7-Code/...`
- `model_code/kimi/reference/k2/{config.json, README.md, modeling_deepseek.py, configuration_deepseek.py}` ← `https://huggingface.co/moonshotai/Kimi-K2-Instruct/...`

### GLM（建模代码不在 HF 仓库，取自 transformers 库）
- `model_code/glm/{glm-5.2,glm-5}/{config.json, README.md, generation_config.json}` ← `https://huggingface.co/zai-org/GLM-5.2/...`、`.../GLM-5/...`
- `model_code/glm/*/modeling_glm_moe_dsa.py` + `configuration_glm_moe_dsa.py` ← `https://raw.githubusercontent.com/huggingface/transformers/main/src/transformers/models/glm_moe_dsa/...`

### Qwen（建模代码不在 HF 仓库，取自 transformers 库）
- `model_code/qwen/{qwen3.5-397b,qwen3.5-35b-a3b}/{config.json, README.md, generation_config.json}` ← `https://huggingface.co/Qwen/Qwen3.5-397B-A17B/...`、`.../Qwen3.5-35B-A3B/...`
- `model_code/qwen/*/modeling_qwen3_5_moe.py` + `configuration_qwen3_5_moe.py` ← `.../transformers/models/qwen3_5_moe/...`
- `model_code/qwen/*/modeling_qwen3_next.py` + `configuration_qwen3_next.py` ← `.../transformers/models/qwen3_next/...`（含 GatedDeltaNet）

### 混元
- `model_code/hunyuan/hy3/{config.json, README.md, README_CN.md, generation_config.json}` ← `https://huggingface.co/tencent/Hy3/...`
- `model_code/hunyuan/hy3/{modeling_hy_v3.py, configuration_hy_v3.py}` ← `.../transformers/models/hy_v3/...`（仓库内无核心建模代码）
- `model_code/hunyuan/reference/a13b/{config.json, README.md, modeling_hunyuan.py, configuration_hunyuan.py, hunyuan.py}` ← `https://huggingface.co/tencent/Hunyuan-A13B-Pretrain/...`

## 论文 / 技术报告来源（reports/）

| 本地文件 | 来源 |
|---|---|
| `reports/deepseek/DeepSeek-V4_technical_report.pdf` | arXiv:2606.19348 |
| `reports/deepseek/DeepSeek-V3_technical_report.pdf` | arXiv:2412.19437 |
| `reports/deepseek/DeepSeek-V2_MLA.pdf` | arXiv:2405.04434（MLA 起源） |
| `reports/deepseek/DeepSeek-R1.pdf` | arXiv:2501.12948 |
| `reports/kimi/Kimi-K2_technical_report.pdf` | arXiv:2507.20534 |
| `reports/glm/GLM-5_technical_report.pdf` | arXiv:2602.15763 |
| `reports/glm/GLM-130B_DeepNorm.pdf` | arXiv:2210.02414 |
| `reports/qwen/Qwen3_technical_report.pdf` | arXiv:2505.09388 |
| `reports/hunyuan/Hunyuan-Large.pdf` | arXiv:2411.02265 |
| `reports/hunyuan/Hunyuan-A13B_technical_report.pdf` | 官方仓库 `Tencent-Hunyuan/Hunyuan-A13B/report/` |

> 注：**Qwen3.5 无 arXiv 技术报告**，官方文档见 `https://qwen.ai/blog?id=qwen3.5` 与 HF 文档 `huggingface.co/docs/transformers/model_doc/qwen3_5`；本目录以其 config + 建模代码 + Qwen3 报告为参考。
