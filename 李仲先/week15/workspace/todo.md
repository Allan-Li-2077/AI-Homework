# Week15 待办

- [ ] 支持 dispatch_agent 并行委派多个 sub-agent
- [ ] explore sub-agent 只能读，不能写
- [ ] general sub-agent 可用 calculator
- [ ] sub-agent 失败时主 agent 应能感知并重试

## 预算
单次任务预算：max_steps=6，token 上限约 8000。
两个 sub-agent 并行的总开销约为单次的 1.2 倍。
