# Skill Harness

## 安装与运行

```powershell
python main.py                            # 加 -v 查看 DEBUG 日志
```

## 交互示例

```
>>> 记一下 abandon 这个单词
[匹配 skill: word-memo] 开始执行 ...
[执行完成] 已经为你生成了关于单词 'hello' 的记忆卡片。

>>> 记一下 hello 这个单词，但是以后我只想要例句只有3个
[匹配 skill: word-memo] 开始执行 ...
[执行完成] 已经为你生成了关于单词 'hello' 的记忆卡片。
[skill 进化] 已根据本次使用自动优化 skill「word-memo」的渲染配置（example 数量下限 5→3；原因：根据用户需求减少例句数量至3个），旧配置已备份为 .skill_versions/word-memo/0002_config.json
```

## 目录约定

- `output/`：所有产物文件（HTML 卡片等）统一输出到此目录，启动时自动创建。
- `.skill_versions/`：skill **自进化**功能的历史版本备份。每次成功执行一个 skill 后，
  harness 会让模型评估该 skill 的**渲染配置 `config.json`** 是否值得优化（如版面顺序、
  各版块数量下限、可选版块显隐）。模型只输出**结构化指令**（枚举 op + 标量参数），由 harness
  做 schema 校验后应用；若确有改动，会**先把旧版 `config.json` 按序号累加备份**到
  `.skill_versions/<skill名>/NNNN_config.json`（`0001_config.json`、`0002_config.json` ……），
  再写回新配置，用户下次提问即按新配置渲染。该目录由首次进化时自动创建，纯 JSON 备份，
  可随时手动清理或用于回溯对比。
  > 之所以改配置而非改写 SKILL.md 正文：结构化指令的所有值都是整数/布尔/短枚举，JSON 里
  > 不存在多行字符串字段，从根上消除了"模型用换行哨兵把整份说明压成一行乱码"的损坏风险。