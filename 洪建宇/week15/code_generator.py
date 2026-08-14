"""代码生成 SubAgent。

根据需求描述中的关键词匹配预置代码模板，生成语法正确、带中文注释、可直接运行的
Python 代码片段。覆盖 5 类模板：HTTP API、数据处理脚本、CLI 工具、定时任务、
单元测试；匹配不到时返回通用函数骨架。仅使用标准库。
"""
from __future__ import annotations

import asyncio
import textwrap
from typing import Any, Callable, Dict, List, Optional, Tuple

from ..base import BaseSubAgent
from ...core.models import SubTask


# ---- 模板生成函数 ----
def _template_http_api(desc: str, framework: str) -> str:
    """HTTP API 模板：默认基于标准库 http.server，framework=flask 时使用 Flask。"""
    fw = (framework or "").lower()
    if fw == "flask":
        return textwrap.dedent('''
            from flask import Flask, jsonify, request

            app = Flask(__name__)


            @app.route("/api/items", methods=["GET"])
            def list_items():
                """查询示例资源列表。"""
                # 从查询参数读取分页信息
                page = int(request.args.get("page", 1))
                size = int(request.args.get("size", 10))
                items = [{"id": i, "name": f"item-{i}"} for i in range((page - 1) * size, page * size)]
                return jsonify({"page": page, "size": size, "items": items})


            @app.route("/api/items", methods=["POST"])
            def create_item():
                """创建示例资源。"""
                data = request.get_json(silent=True) or {}
                if not data.get("name"):
                    return jsonify({"error": "name 必填"}), 400
                return jsonify({"id": 1, "name": data["name"]}), 201


            if __name__ == "__main__":
                # 开发模式启动，生产环境建议使用 gunicorn
                app.run(host="0.0.0.0", port=8000, debug=True)
        ''').strip("\n")
    # 默认使用标准库 http.server，无需第三方依赖
    return textwrap.dedent('''
        import json
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


        class APIHandler(BaseHTTPRequestHandler):
            """基于标准库的简易 HTTP API 处理器。"""

            def _send_json(self, payload, status=200):
                """统一返回 JSON 响应。"""
                body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                """处理 GET /api/items 请求。"""
                if self.path.startswith("/api/items"):
                    items = [{"id": i, "name": f"item-{i}"} for i in range(10)]
                    self._send_json({"items": items, "count": len(items)})
                else:
                    self._send_json({"error": "not found"}, status=404)

            def do_POST(self):
                """处理 POST 请求，读取请求体并回显。"""
                length = int(self.headers.get("Content-Length", 0))
                raw = self.rfile.read(length) if length else b"{}"
                try:
                    data = json.loads(raw.decode("utf-8"))
                except json.JSONDecodeError:
                    self._send_json({"error": "无效的 JSON"}, status=400)
                    return
                self._send_json({"received": data, "created": True}, status=201)


        if __name__ == "__main__":
            server = ThreadingHTTPServer(("0.0.0.0", 8000), APIHandler)
            print("HTTP API 服务启动于 http://0.0.0.0:8000")
            server.serve_forever()
    ''').strip("\n")


def _template_data_processing(desc: str, framework: str) -> str:
    """数据处理脚本模板：读取 CSV/JSON、统计汇总、写出结果。"""
    return textwrap.dedent('''
        import csv
        import json
        from collections import Counter
        from pathlib import Path


        def load_records(path: str) -> list:
            """从 CSV 或 JSON 文件加载记录，返回 list[dict]。"""
            p = Path(path)
            if p.suffix.lower() == ".json":
                with p.open("r", encoding="utf-8") as f:
                    return json.load(f)
            with p.open("r", encoding="utf-8", newline="") as f:
                return list(csv.DictReader(f))


        def summarize(records: list, key: str = "category") -> dict:
            """按指定字段统计计数与数值汇总。"""
            counter = Counter()
            total_value = 0.0
            for r in records:
                counter[r.get(key, "unknown")] += 1
                try:
                    total_value += float(r.get("value", 0))
                except (TypeError, ValueError):
                    continue
            return {
                "group_counts": dict(counter),
                "total_value": total_value,
                "record_count": len(records),
            }


        def main(input_path: str, output_path: str) -> None:
            """数据处理主流程：读取、统计、写出结果。"""
            records = load_records(input_path)
            result = summarize(records, key="category")
            Path(output_path).write_text(
                json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            print(f"处理完成，共 {len(records)} 条记录 -> {output_path}")


        if __name__ == "__main__":
            main("input.csv", "output.json")
    ''').strip("\n")


def _template_cli_tool(desc: str, framework: str) -> str:
    """CLI 工具模板：基于 argparse 实现命令行参数解析与文件处理。"""
    return textwrap.dedent('''
        import argparse
        import sys
        from pathlib import Path


        def parse_args(argv=None):
            """解析命令行参数。"""
            parser = argparse.ArgumentParser(
                description="通用命令行工具：支持文件处理与统计"
            )
            parser.add_argument("input", help="输入文件路径")
            parser.add_argument("-o", "--output", default="output.txt", help="输出文件路径")
            parser.add_argument("-n", "--top", type=int, default=10, help="取前 N 行")
            parser.add_argument("-v", "--verbose", action="store_true", help="输出详细日志")
            return parser.parse_args(argv)


        def process_file(input_path: str, top: int) -> list:
            """读取文件并返回前 top 行。"""
            p = Path(input_path)
            if not p.exists():
                raise FileNotFoundError(f"文件不存在: {input_path}")
            with p.open("r", encoding="utf-8") as f:
                lines = [line.rstrip("\\n") for line in f]
            return lines[:top]


        def main(argv=None):
            """CLI 入口。"""
            args = parse_args(argv)
            if args.verbose:
                print(f"[INFO] 读取 {args.input}，取前 {args.top} 行", file=sys.stderr)
            lines = process_file(args.input, args.top)
            Path(args.output).write_text("\\n".join(lines), encoding="utf-8")
            print(f"已写入 {len(lines)} 行到 {args.output}")


        if __name__ == "__main__":
            main()
    ''').strip("\n")


def _template_scheduled_task(desc: str, framework: str) -> str:
    """定时任务模板：基于标准库实现固定间隔循环调度。"""
    return textwrap.dedent('''
        import time
        import logging
        from datetime import datetime

        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s [%(levelname)s] %(message)s",
        )
        logger = logging.getLogger("scheduler")


        def job():
            """定时执行的任务逻辑。"""
            logger.info("定时任务开始执行，当前时间 %s", datetime.now().isoformat())
            # 在此编写业务逻辑：数据同步、清理过期数据、发送提醒等
            result = {"processed": 0, "status": "ok"}
            logger.info("定时任务完成: %s", result)
            return result


        def run_every(interval_seconds: float, func, max_rounds=None):
            """按固定间隔循环执行任务（基于标准库）。"""
            rounds = 0
            while max_rounds is None or rounds < max_rounds:
                start = time.monotonic()
                try:
                    func()
                except Exception as e:  # 单次失败不影响后续调度
                    logger.error("任务执行失败: %s", e)
                elapsed = time.monotonic() - start
                sleep_time = max(0.0, interval_seconds - elapsed)
                time.sleep(sleep_time)
                rounds += 1


        if __name__ == "__main__":
            # 每 60 秒执行一次，演示运行 3 轮
            run_every(60, job, max_rounds=3)
    ''').strip("\n")


def _template_unit_test(desc: str, framework: str) -> str:
    """单元测试模板：基于 unittest 编写断言用例。"""
    return textwrap.dedent('''
        import unittest


        def add(a, b):
            """示例被测函数：加法。"""
            return a + b


        def divide(a, b):
            """示例被测函数：除法，除零抛错。"""
            if b == 0:
                raise ValueError("除数不能为零")
            return a / b


        class TestMathFunctions(unittest.TestCase):
            """数学函数单元测试。"""

            def test_add_positive(self):
                """测试正数相加。"""
                self.assertEqual(add(2, 3), 5)

            def test_add_negative(self):
                """测试负数相加。"""
                self.assertEqual(add(-1, -4), -5)

            def test_divide_normal(self):
                """测试正常除法。"""
                self.assertAlmostEqual(divide(10, 4), 2.5)

            def test_divide_by_zero(self):
                """测试除零应抛出 ValueError。"""
                with self.assertRaises(ValueError):
                    divide(1, 0)


        if __name__ == "__main__":
            unittest.main()
    ''').strip("\n")


def _template_skeleton(desc: str) -> str:
    """通用函数骨架：可运行，按业务需求替换实现。"""
    func_name = "process_task"
    # 清理描述中的换行，避免破坏生成的 docstring
    safe_desc = (desc or "通用处理函数").replace("\n", " ").replace("\r", " ").strip()
    safe_desc = safe_desc or "通用处理函数"
    return textwrap.dedent(f'''
        def {func_name}(input_data):
            """{safe_desc}"""
            # 默认实现：原样返回输入数据，请按业务需求替换为真实逻辑
            return {{"input": input_data}}


        if __name__ == "__main__":
            print({func_name}({{"sample": True}}))
    ''').strip("\n")


# 模板匹配规则：(关键词列表, 模板名, 生成函数)
_TEMPLATES: List[Tuple[List[str], str, Callable[[str, str], str]]] = [
    (["api", "http", "rest", "接口", "flask", "服务端"], "http_api", _template_http_api),
    (["数据", "处理", "csv", "json", "etl", "清洗", "统计", "data"], "data_processing", _template_data_processing),
    (["cli", "命令行", "argparse", "参数", "tool", "工具"], "cli_tool", _template_cli_tool),
    (["定时", "调度", "cron", "schedule", "周期", "定时任务"], "scheduled_task", _template_scheduled_task),
    (["测试", "unit", "test", "unittest", "pytest", "单元测试"], "unit_test", _template_unit_test),
]


def _match_template(description: str) -> Tuple[str, Optional[Callable[[str, str], str]]]:
    """根据描述关键词匹配模板，返回 (模板名, 生成函数)。无匹配返回 (generic, None)。"""
    text = (description or "").lower()
    best_name = "generic"
    best_fn: Optional[Callable[[str, str], str]] = None
    best_hits = 0
    for keywords, name, fn in _TEMPLATES:
        hits = sum(1 for kw in keywords if kw.lower() in text)
        if hits > best_hits:
            best_hits = hits
            best_name = name
            best_fn = fn
    if best_hits == 0:
        return "generic", None
    return best_name, best_fn


class CodeGeneratorAgent(BaseSubAgent):
    """代码生成 Agent：基于关键词匹配模板生成可运行 Python 代码。"""

    def __init__(self, max_concurrency: int = 5) -> None:
        super().__init__(
            name="code_generator_agent",
            capabilities="code_generation",
            max_concurrency=max_concurrency,
        )

    async def process(self, subtask: SubTask) -> Dict[str, Any]:
        # 模拟 IO 让出事件循环，使并行调度可观测（内置 Agent 为纯内存计算）
        await asyncio.sleep(0.1)
        # 容错：input_data 可能为 None 或非 dict
        data = subtask.input_data or {}
        if not isinstance(data, dict):
            data = {"description": str(data)}
        language = str(data.get("language", "python") or "python").strip().lower()
        description = str(data.get("description", "") or "").strip()
        framework = str(data.get("framework", "") or "").strip()

        template_name, fn = _match_template(description)

        # 非 python 语言：给出提示，但仍返回骨架
        if language != "python":
            code = _template_skeleton(description)
            code = f"# 提示：当前仅支持 python 模板生成，{language} 暂未提供专用模板，以下为通用骨架\n" + code
            return {
                "language": language,
                "description": description,
                "code": code,
                "template": "generic",
            }

        if fn is not None:
            code = fn(description, framework)
        else:
            code = _template_skeleton(description)

        return {
            "language": language,
            "description": description,
            "code": code,
            "template": template_name,
        }
