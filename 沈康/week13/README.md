# Skill Harness

## 安装与运行

```powershell
python main.py                            # 加 -v 查看 DEBUG 日志
```

## 交互示例

```
>>> 给我做张 crazy 词的闪卡
[匹配 skill: flash-card] 开始执行 ...
[执行完成] 已为 crazy 生成闪卡，HTML 输出在 output/crazy.html 并已在浏览器打开。
>>> 给我做 meticulous 的闪卡
[匹配 skill: flash-card] 开始执行 ...
[执行完成] 已为新单词 meticulous 生成数据与闪卡，HTML 输出在 output/meticulous.html。
>>> 今天星期几
(未匹配 skill，进入普通对话)
今天是……
```