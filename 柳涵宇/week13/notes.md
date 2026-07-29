@"
# 产品落地页
这是一个用于介绍 AI 工作流工具的产品页面。

## 核心功能
- 渐进式加载 skills
- 根据请求自动路由
- 支持生成 HTML 页面
- 支持生成周报和闪卡

## 适用场景
- 个人知识管理
- 自动化内容生成
- 本地 agent 工具实验

## 常见问题
- 是否可以离线运行？可以，本地 harness 不依赖网络。
- 是否可以扩展新 skill？可以，新增 SKILL.md 和 adapter 即可。
"@ | Set-Content -Encoding UTF8 notes.md