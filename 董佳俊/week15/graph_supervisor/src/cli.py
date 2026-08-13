"""
CLI 演示入口（Windows 控制台 UTF-8 已修复）

用法：
  python cli.py                     # 默认跑「咖啡调研+计算+推文」主演示题
  python cli.py -q "你的问题"        # 自定义问题
  python cli.py --demo single|direct|chain|two   # 预设演示（展示各路由路径）
  python cli.py --serial            # 串行对照（eval 基线）
  python cli.py --save-trace        # 落盘 outputs/trace_<graph_id>.json
"""
import argparse
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from graph import run_graph

DEMOS = {
    "coffee": ("帮我调研一下中国咖啡市场现状，算一算近三年市场规模（2021年3817亿元、"
               "2022年4856亿元、2023年6188亿元）的年均增速，再写一篇 800 字左右的"
               "公众号推文，面向想开店创业的人"),
    "two": ("调研中国扫地机器人行业的市场规模与竞争格局；已知 2021-2023 年市场规模为 "
            "108/124/141 亿元，用工具计算同比增速和 CAGR"),
    "single": "调研一下中国扫地机器人行业竞争格局",
    "chain": "写一篇新能源汽车行业科普推文，先调研行业现状",
    "direct": "你好",
}

LINE = "=" * 62


def make_printer():
    """事件 → 终端演示打印。只打印关键事件，过程流细节看 Web 端。"""
    first = {"v": True}

    def on_event(ev):
        t = ev["type"]
        if t == "plan":
            print(f"\n[路由] {ev['route_note']}")
            print(f"[计划] graph_id={ev['graph_id']} plan_id={ev['plan_id']} "
                  f"task_type={ev['task_type']} 搜索={ev.get('search_mode', '-')}")
            if ev["stages"]:
                for i, st in enumerate(ev["stages"]):
                    parts = "  |  ".join(
                        f"{n['label']}({n['node_id']}, 依赖[{', '.join(n['depends_on']) or '无'}])"
                        for n in st)
                    print(f"  stage{i}: {parts}")
        elif t == "node_start":
            print(f"  ├─ {ev['label']}({ev['node_id']}) 开始…")
        elif t == "node_done":
            print(f"  └─ {ev['node_id']} 完成 status={ev['status']} 用时{ev['duration']}s")
        elif t == "supervisor":
            print("  ◆ supervisor 聚合中…" if ev["phase"] == "aggregate_start"
                  else "  ◆ supervisor 聚合完成")
        elif t == "stats" and ev.get("stages"):
            print(f"\n[并行统计]")
            for s in ev["stages"]:
                print(f"  stage{s['stage']}: 并行墙钟 {s['wall_clock']}s | "
                      f"串行需 {s['serial_sum']}s | 加速 {s['speedup']}x")
            print(f"  端到端: 墙钟 {ev['total_wall_clock']}s | 串行等效 "
                  f"{ev['total_serial_equiv']}s | 加速 {ev['total_speedup']}x"
                  f"（聚合={ev['aggregate']} 串行段 {ev['aggregate_duration']}s）")
        elif t == "final":
            if first["v"]:
                print(f"\n[最终交付] (plan {ev['plan_id']})\n{'-' * 62}")
                first["v"] = False
            print(ev["answer"])
    return on_event


def main():
    parser = argparse.ArgumentParser(description="图编排 Supervisor CLI 演示")
    parser.add_argument("-q", "--question", default=None, help="自定义问题")
    parser.add_argument("--demo", choices=list(DEMOS), default="coffee",
                        help="预设演示题（默认 coffee）")
    parser.add_argument("--serial", action="store_true", help="串行执行（并行收益对照基线）")
    parser.add_argument("--save-trace", action="store_true", help="落盘 trace JSON")
    args = parser.parse_args()

    question = args.question or DEMOS[args.demo]
    print(LINE)
    print(f"Q: {question[:52]}{'…' if len(question) > 52 else ''}")
    print(f"执行模式: {'串行(serial 基线)' if args.serial else '并行(ThreadPool)'}")
    print(LINE)

    r = run_graph(question, on_event=make_printer(), serial=args.serial,
                  save_trace=args.save_trace)
    print(f"\n{LINE}\n完成。graph_id={r['graph_id']} | "
          f"节点数={len(r['results'])} | 并行统计见上")


if __name__ == "__main__":
    main()
