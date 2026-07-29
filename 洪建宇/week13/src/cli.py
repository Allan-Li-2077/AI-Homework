"""cli - FileSkill Harness 命令行接口（基于 argparse）。

子命令：
    list              列出所有可用 skill
    info  <skill>     查看某 skill 的详细元信息与依赖状态
    run   <skill> k=v ...   执行某 skill，参数以 key=value 形式传入
    check             检查所有 skill 的依赖安装状态
    unload <skill>    手动卸载已加载的 skill
    chat  "<自然语言>"   由大模型自动选择 skill 并填充参数后执行（单轮）
    qa    "<问题>"       问答模式：大模型多轮 ReAct 思考+调用工具解决问题

用法示例：
    python cli.py list
    python cli.py info compress_image
    python cli.py run compress_image input_path=a.jpg quality=70 max_width=1280
    python cli.py run compress_image input_path=a.jpg --unload
    python cli.py check
    python cli.py chat "把 a.jpg 压缩一下，质量70，最大宽度1280"
    python cli.py chat "帮我从 b.pdf 的第1到3页提取文本存到 b.txt"
    python cli.py qa "帮我把 a.jpg 压缩到最大宽度800，并告诉我压缩前后大小"
"""
import argparse
import json
import sys
from typing import List, Tuple

from harness import FileSkillHarness


def _parse_kv_params(items: List[str]) -> Tuple[dict, List[str]]:
    """把 ['k1=v1', 'k2=v2'] 解析为 dict。

    返回 (参数字典, 错误信息列表)。值保留为字符串，类型转换交给 harness。
    """
    params: dict = {}
    errors: List[str] = []
    for item in items:
        if "=" not in item:
            errors.append(f"参数格式错误（应为 key=value）: {item}")
            continue
        k, v = item.split("=", 1)
        params[k.strip()] = v.strip()
    return params, errors


def cmd_list(harness: FileSkillHarness, args: argparse.Namespace) -> None:
    skills = harness.list_skills()
    if not skills:
        print("（未发现任何 skill，请检查 skills/ 目录）")
        return
    print(f"共发现 {len(skills)} 个 skill：\n")
    # 表头
    print(f"{'名称':<20}{'类别':<10}{'已加载':<8}描述")
    print("-" * 72)
    for name, meta in skills.items():
        loaded = "是" if harness.is_loaded(name) else "否"
        category = meta.get("category", "-")
        desc = meta.get("description", "")
        print(f"{name:<20}{category:<10}{loaded:<8}{desc}")


def cmd_info(harness: FileSkillHarness, args: argparse.Namespace) -> None:
    meta = harness.get_skill_info(args.skill)
    if not meta:
        print(f"未找到 skill: {args.skill}", file=sys.stderr)
        sys.exit(1)

    print(f"名称: {meta['name']}")
    print(f"描述: {meta.get('description', '')}")
    print(f"类别: {meta.get('category', '-')}")
    print(f"依赖: {', '.join(meta.get('dependencies', [])) or '无'}")
    print(f"文件: {meta.get('file_path', '-')}")

    print("\n参数:")
    params = meta.get("params", {})
    if not params:
        print("  （无参数）")
    for pname, pinfo in params.items():
        req = "必填" if pinfo.get("required") else "可选"
        default = pinfo.get("default", "-")
        ptype = pinfo.get("type", "str")
        desc = pinfo.get("description", "")
        print(f"  --{pname:<14} [{ptype}/{req}] 默认={default}  {desc}")

    ok, missing = harness.check_dependencies(args.skill)
    if ok:
        print("\n依赖状态: 已就绪 ✓")
    else:
        print(f"\n依赖状态: 缺失 ✗ -> {', '.join(missing)}")
        print(f"安装命令: pip install {' '.join(missing)}")


def cmd_run(harness: FileSkillHarness, args: argparse.Namespace) -> None:
    meta = harness.get_skill_info(args.skill)
    if not meta:
        print(f"未找到 skill: {args.skill}", file=sys.stderr)
        sys.exit(1)

    params, errors = _parse_kv_params(args.params)
    if errors:
        for e in errors:
            print(e, file=sys.stderr)
        sys.exit(1)

    # 执行前依赖检查（给出友好提示，而非裸 ImportError）
    ok, missing = harness.check_dependencies(args.skill)
    if not ok:
        print(f"缺少依赖: {missing}", file=sys.stderr)
        print(f"请运行: pip install {' '.join(missing)}", file=sys.stderr)
        sys.exit(1)

    try:
        result = harness.execute(args.skill, **params)
    except Exception as e:
        print(f"执行失败: {e}", file=sys.stderr)
        sys.exit(1)

    # 输出结构化结果（JSON，便于下游脚本解析）
    print("\n执行结果:")
    print(json.dumps(result, ensure_ascii=False, indent=2))

    # 渐进式：执行后按需卸载，释放内存
    if args.unload:
        harness.unload_skill(args.skill)
        print(f"\n[已卸载 skill '{args.skill}' 以释放内存]")


def cmd_chat(harness: FileSkillHarness, args: argparse.Namespace) -> None:
    """自然语言驱动：大模型选 skill + 填参数，再交给 harness 执行。

    llm_router 仅在此命令被调用时才 import（渐进式加载），
    避免在不使用大模型时引入 urllib 网络调用相关开销。
    """
    from llm_router import route  # 局部 import：渐进式

    user_input = args.message
    skills_meta = harness.list_skills()
    if not skills_meta:
        print("未发现任何 skill，无法路由", file=sys.stderr)
        sys.exit(1)

    print(f"用户指令: {user_input}")
    print("正在请求大模型进行路由 ...")

    try:
        decision = route(user_input, skills_meta)
    except Exception as e:
        print(f"大模型路由失败: {e}", file=sys.stderr)
        sys.exit(1)

    skill_name = decision["skill"]
    params = decision.get("params", {})
    reason = decision.get("reason", "")

    print("\n大模型决策:")
    print(f"  skill : {skill_name}")
    print(f"  params: {json.dumps(params, ensure_ascii=False)}")
    if reason:
        print(f"  reason: {reason}")

    # 执行前依赖检查
    ok, missing = harness.check_dependencies(skill_name)
    if not ok:
        print(f"\n缺少依赖: {missing}", file=sys.stderr)
        print(f"请运行: pip install {' '.join(missing)}", file=sys.stderr)
        sys.exit(1)

    try:
        result = harness.execute(skill_name, **params)
    except Exception as e:
        print(f"执行失败: {e}", file=sys.stderr)
        sys.exit(1)

    print("\n执行结果:")
    print(json.dumps(result, ensure_ascii=False, indent=2))

    if args.unload:
        harness.unload_skill(skill_name)
        print(f"\n[已卸载 skill '{skill_name}' 以释放内存]")


def cmd_qa(harness: FileSkillHarness, args: argparse.Namespace) -> None:
    """问答模式：大模型多轮 ReAct，思考 -> 调用工具 -> 观察 -> 最终回答。

    与 chat 的区别：chat 是单轮（模型只选一次 skill 就执行结束），
    qa 是多轮循环，模型可连续调用多个工具并基于观察结果继续推理，
    直到给出最终答案。qa_router 仅在此命令被调用时才 import（渐进式）。
    """
    from qa_router import answer  # 局部 import：渐进式

    skills_meta = harness.list_skills()
    if not skills_meta:
        print("未发现任何 skill，无法问答", file=sys.stderr)
        sys.exit(1)

    print(f"用户提问: {args.question}\n")

    # 实时打印每一步推理过程，让用户看到模型的思考链
    def on_step(step: dict) -> None:
        it = step["iteration"]
        stype = step["type"]
        if stype == "call_tool":
            print(f"[轮 {it}] 思考: {step.get('thought', '')}")
            print(
                f"[轮 {it}] 调用工具: {step['tool']}  "
                f"参数: {json.dumps(step.get('params', {}), ensure_ascii=False)}"
            )
        elif stype == "observation":
            tag = "成功" if step.get("success") else "失败"
            print(f"[轮 {it}] 观察({tag}): {step.get('observation', '')}")
        elif stype == "final_answer":
            print(f"[轮 {it}] 思考: {step.get('thought', '')}")
            print(f"[轮 {it}] 产出最终答案")

    try:
        result = answer(
            args.question,
            skills_meta,
            harness,
            max_iterations=args.max_iterations,
            on_step=on_step,
        )
    except Exception as e:
        print(f"问答失败: {e}", file=sys.stderr)
        sys.exit(1)

    print("\n" + "=" * 60)
    print("最终回答:")
    print(result["answer"])
    print("=" * 60)
    print(f"共推理 {result['iterations']} 轮，记录 {len(result['steps'])} 个步骤")

    # 渐进式：结束时卸载本问答过程中可能加载的所有 skill
    if args.unload:
        for name in list(skills_meta.keys()):
            harness.unload_skill(name)
        print("[已卸载所有 skill 以释放内存]")


def cmd_check(harness: FileSkillHarness, args: argparse.Namespace) -> None:
    skills = harness.list_skills()
    if not skills:
        print("（未发现任何 skill）")
        return
    print(f"{'名称':<20}{'依赖':<28}状态")
    print("-" * 72)
    for name, meta in skills.items():
        deps = ", ".join(meta.get("dependencies", [])) or "无"
        ok, missing = harness.check_dependencies(name)
        status = "已就绪 ✓" if ok else "缺失 ✗: " + ", ".join(missing)
        print(f"{name:<20}{deps:<28}{status}")


def cmd_unload(harness: FileSkillHarness, args: argparse.Namespace) -> None:
    if not harness.is_loaded(args.skill):
        # 即便不在缓存，也尝试清理 sys.modules 残留
        if harness.unload_skill(args.skill):
            print(f"已从 sys.modules 清理 '{args.skill}'")
        else:
            print(f"skill '{args.skill}' 未加载，无需卸载")
        return
    harness.unload_skill(args.skill)
    print(f"已卸载 skill '{args.skill}'")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="file_skill_harness",
        description="FileSkill Harness - 渐进式文件处理工具箱",
    )
    parser.add_argument(
        "--skills-dir",
        default="skills",
        help="skill 目录路径（默认: skills）",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # list
    p_list = sub.add_parser("list", help="列出所有可用的 skill")
    p_list.set_defaults(func=cmd_list)

    # info
    p_info = sub.add_parser("info", help="查看某个 skill 的详细信息")
    p_info.add_argument("skill", help="skill 名称")
    p_info.set_defaults(func=cmd_info)

    # run
    p_run = sub.add_parser("run", help="执行某个 skill")
    p_run.add_argument("skill", help="skill 名称")
    p_run.add_argument(
        "params",
        nargs="*",
        help="参数列表，格式 key=value（如 input_path=a.jpg quality=70）",
    )
    p_run.add_argument(
        "--unload",
        action="store_true",
        help="执行完毕后卸载 skill 模块以释放内存（渐进式）",
    )
    p_run.set_defaults(func=cmd_run)

    # check
    p_check = sub.add_parser("check", help="检查所有 skill 的依赖安装状态")
    p_check.set_defaults(func=cmd_check)

    # unload
    p_unload = sub.add_parser("unload", help="手动卸载已加载的 skill")
    p_unload.add_argument("skill", help="skill 名称")
    p_unload.set_defaults(func=cmd_unload)

    # chat（大模型路由）
    p_chat = sub.add_parser(
        "chat",
        help="用自然语言描述需求，由大模型自动选 skill 并填参数后执行",
    )
    p_chat.add_argument(
        "message",
        help='自然语言指令，如 "把 a.jpg 压缩一下质量70"',
    )
    p_chat.add_argument(
        "--unload",
        action="store_true",
        help="执行完毕后卸载 skill 模块以释放内存（渐进式）",
    )
    p_chat.set_defaults(func=cmd_chat)

    # qa（大模型多轮 ReAct 问答）
    p_qa = sub.add_parser(
        "qa",
        help="问答模式：大模型多轮思考+调用工具解决问题（ReAct）",
    )
    p_qa.add_argument(
        "question",
        help='你的问题，如 "帮我把 a.jpg 压缩到最大宽度800并告诉我压缩前后大小"',
    )
    p_qa.add_argument(
        "--max-iterations",
        type=int,
        default=8,
        help="最大推理轮数，防止死循环（默认 8）",
    )
    p_qa.add_argument(
        "--unload",
        action="store_true",
        help="问答结束后卸载所有已加载 skill 以释放内存",
    )
    p_qa.set_defaults(func=cmd_qa)

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    harness = FileSkillHarness(skills_dir=args.skills_dir)
    args.func(harness, args)


if __name__ == "__main__":
    main()
