# 牛客网拉取详细说明

## URL 规律

- 题库题：`https://www.nowcoder.com/practice/<questionId>`
- 题号前缀：通常为 `NC<number>`，但页面路径是纯数字

## 已知坑

- **登录门槛**：部分题目需要登录才能看完整题面
- **反爬**：浏览器开发者工具查看 `XHR` 时常带自定义 header `HostReferer` / `tn-token`，缺一个可能 400
- **题面结构**：HTML 结构经常变，选择器不固定
- **样例**：以 `<pre>` 块成对出现，但顺序不一定规范

## 建议

遇到解析失败时：
1. 用浏览器手动打开题目确认页面有正常题面
2. 检查 Cookie 是否过期
3. 实在不行走 `fetch_generic.py` 通用抓取
