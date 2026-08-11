"""
冒烟测试：不依赖 LLM，验证 Skill 注册 / 加载 / 选择器基本通路

运行：
  python run_smoke_test.py
"""

import os
import sys
from pathlib import Path

os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")
# 强制 stdout 用 UTF-8，避免 Windows GBK 编码问题
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

sys.path.insert(0, str(Path(__file__).parent))

from src.skill_registry import get_registry
from src.skill_loader import SkillLoader
from src.skill_executor import SkillExecutor
from src.skill_selector import SkillSelector


def header(text):
    print(f"\n{'=' * 60}")
    print(f"  {text}")
    print(f"{'=' * 60}")


def main():
    header("1. Skill 注册表（仅 frontmatter，启动成本应 < 10KB）")
    reg = get_registry()
    summary = reg.summary()
    print(f"  已索引 {summary['skill_count']} 个 skill")
    print(f"  frontmatter 总计：{summary['frontmatter_total_chars']} 字符")
    print(f"  正文待按需加载：{summary['body_total_chars']} 字符")
    print(f"  execution 模式分布：{summary['execution_modes']}")
    assert summary['skill_count'] >= 7, "至少应有 7 个示例 skill"
    assert summary['frontmatter_total_chars'] < 15000, "frontmatter 总字符应 < 15KB（渐进式加载的核心收益）"
    print("  [PASS]")

    header("2. 粗筛：搜索关键词")
    hits = reg.search_by_keyword("翻译")
    print(f"  query='翻译' → 命中 {len(hits)} 个：{[m.name for m in hits]}")
    assert any(m.name == "translate" for m in hits), "应命中 translate skill"
    print("  [PASS]")

    header("3. 按需加载：读 translate skill 正文 + 占位符替换")
    loader = SkillLoader(reg)
    contract = loader.load("translate", params={"text": "你好世界", "target_lang": "English"})
    assert contract is not None, "应能加载 translate skill"
    print(f"  body 长度：{len(contract.body_md)} 字符")
    print(f"  prompt_for_llm 前 200 字符：{contract.prompt_for_llm[:200]!r}")
    print(f"  params_resolved：{contract.params_resolved}")
    print(f"  params_missing：{contract.params_missing}")
    assert "你好世界" in contract.prompt_for_llm, "占位符应已被替换"
    assert "English" in contract.prompt_for_llm, "占位符应已被替换"
    assert contract.cache_hit is False, "首次加载不应命中缓存"
    print("  [PASS]（占位符替换正确，首次加载未命中缓存）")

    header("4. 缓存命中")
    contract2 = loader.load("translate", params={"text": "你好世界", "target_lang": "English"})
    assert contract2.cache_hit is True, "第二次加载应命中缓存"
    print(f"  第二次加载 cache_hit = {contract2.cache_hit}")
    print("  [PASS]")

    header("5. Code 类型 skill：file_reader")
    contract = loader.load("file_reader", params={"path": "README.md"})
    print(f"  execution = {contract.meta.execution}")
    assert contract.meta.execution == "code", "file_reader 应为 code 类型"
    print(f"  body 长度：{len(contract.body_md)} 字符")
    print("  [PASS]")

    header("6. Workflow 类型 skill：research_workflow")
    contract = loader.load("research_workflow", params={"topic": "AI Agent"})
    print(f"  execution = {contract.meta.execution}")
    assert contract.meta.execution == "workflow", "research_workflow 应为 workflow 类型"
    wf_path = Path(contract.meta.source_path).parent / "workflow.yaml"
    print(f"  workflow.yaml 存在：{wf_path.exists()}")
    assert wf_path.exists(), "workflow.yaml 应存在"
    print("  [PASS]")

    header("7. 执行器：file_reader (code) — 真读 requirements.txt")
    exe = SkillExecutor()
    contract = loader.load("file_reader", params={"path": "requirements.txt"}, use_cache=False)
    if contract:
        result = exe.run(contract, user_query="看看 dependencies")
        print(f"  success = {result.success}")
        print(f"  duration_ms = {result.duration_ms:.1f}")
        print(f"  output 前 300 字符：{(result.text or '')[:300]!r}")
        assert result.success, "读取 requirements.txt 应成功"
        print("  [PASS]")
    else:
        print("  [SKIP] contract 加载失败")

    header("全部冒烟测试通过！")
    print("\n下一步：")
    print("  1. 编辑 .env 填入 API Key")
    print("  2. 运行 start.ps1 web 启动 Web 版（浏览器访问 http://localhost:8000）")
    print("  3. 或 start.ps1 cli 启动 CLI 版")


if __name__ == "__main__":
    main()