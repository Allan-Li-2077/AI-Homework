# 自定义/不支持的日志格式

仅当 `--format auto` 识别失败(`parse_error_rate` 偏高)且文件不属于 nginx/apache/JSON/应用日志时,才阅读本文档。

## 处理方法

1. 读取文件前约 20 行。
2. 编写一个小型一次性 Python 脚本(不要修改技能自带的脚本):逐行迭代、用正则匹配、累加 Counter、输出 JSON。可参考自带脚本的结构。

## 常见格式

- **IIS W3C**(`#Fields:` 头部、空格分隔):跳过以 `#` 开头的行;列顺序由头部定义——动态映射 `c-ip`、`cs-uri-stem`、`sc-status`、`time` 等字段。
- **syslog**:格式为 `^(?P<ts>[A-Z][a-z]{2} +\d+ \d{2}:\d{2}:\d{2}) (?P<host>\S+) (?P<proc>[^:]+): (?P<msg>.*)$`——没有状态码;按进程名或消息中的级别关键字计数。
- **klog/glog**(Kubernetes):行首为 `^[IWEF]\d{4} \d{2}:\d{2}:\d{2}`——第一个字符即级别(I/W/E/F)。
- **CSV 日志**:使用 `csv.DictReader`;先查看表头行确定列名。
