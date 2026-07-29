from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

from .errors import SkillExecutionError
from .markdown import safe_slug
from .models import RunResult, TraceEvent
from .session import ProgressiveSkillHarness


class SkillExecutor:
    """Execution adapters for known local skill patterns."""

    def __init__(self, harness: ProgressiveSkillHarness):
        self.harness = harness

    def run(
        self,
        request: str,
        *,
        explicit_skill: str | None = None,
        resource_mode: str = "auto",
        output: str | Path | None = None,
        input_path: str | Path | None = None,
        title: str | None = None,
        word: str | None = None,
        svg: str | Path | None = None,
        dry_run: bool = False,
    ) -> RunResult:
        context = self.harness.build_context(request, explicit_skill=explicit_skill, resource_mode=resource_mode)
        loaded_skill = context["skill"]
        resources = context["resources"]
        skill_name = loaded_skill.meta.name
        if dry_run:
            return RunResult(
                skill=skill_name,
                returncode=0,
                stdout="dry-run: skill context built, no script executed",
                loaded_resources=resources,
                trace=list(self.harness.trace),
            )
        if skill_name == "flash-card":
            return self._run_flash_card(request, output=output, word=word, resources=resources)
        if skill_name == "baoyu-diagram":
            return self._run_diagram(request, output=output, svg=svg, resources=resources)
        if skill_name == "weekly-report":
            return self._run_weekly_report(request, output=output, input_path=input_path, resources=resources)
        if skill_name == "html-page":
            return self._run_html_page(request, output=output, input_path=input_path, title=title, resources=resources)
        return RunResult(
            skill=skill_name,
            returncode=0,
            stdout=f"No execution adapter for skill {skill_name!r}; context loaded only.",
            loaded_resources=resources,
            trace=list(self.harness.trace),
        )

    def _run_weekly_report(
        self,
        request: str,
        *,
        output: str | Path | None,
        input_path: str | Path | None,
        resources,
    ) -> RunResult:
        self.harness.load_skill("weekly-report")
        if input_path is None:
            raise SkillExecutionError("weekly-report requires --input <notes.txt>.")
        notes_path = Path(input_path)
        if not notes_path.is_absolute():
            notes_path = self.harness.cwd / notes_path
        notes_path = notes_path.resolve()
        if not notes_path.exists() or not notes_path.is_file():
            raise SkillExecutionError(f"Input notes file not found: {notes_path}")

        notes = notes_path.read_text(encoding="utf-8-sig")
        report = _render_weekly_report(notes, source=notes_path.name)
        out_path = Path(output).resolve() if output else (self.harness.cwd / "weekly-report.md").resolve()
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(report, encoding="utf-8")

        self.harness.trace.append(TraceEvent("execute", "render weekly report", str(notes_path)))
        return RunResult(
            skill="weekly-report",
            returncode=0,
            stdout=f"Generated weekly report: {out_path}\n",
            outputs=[out_path],
            loaded_resources=resources,
            trace=list(self.harness.trace),
        )

    def _run_html_page(
        self,
        request: str,
        *,
        output: str | Path | None,
        input_path: str | Path | None,
        title: str | None,
        resources,
    ) -> RunResult:
        skill = self.harness.load_skill("html-page")
        source_text = request
        source_label = "request"
        if input_path is not None:
            notes_path = Path(input_path)
            if not notes_path.is_absolute():
                notes_path = self.harness.cwd / notes_path
            notes_path = notes_path.resolve()
            if not notes_path.exists() or not notes_path.is_file():
                raise SkillExecutionError(f"Input notes file not found: {notes_path}")
            source_text = notes_path.read_text(encoding="utf-8-sig")
            source_label = notes_path.name

        page_title = title or _infer_html_title(source_text, request)
        sections = _parse_html_sections(source_text)
        if not sections:
            sections = [("Overview", [_condense_line(source_text)])]
        lead = _build_html_lead(source_text, request)
        out_path = Path(output).resolve() if output else (self.harness.cwd / f"{safe_slug(page_title)}.html").resolve()
        out_path.parent.mkdir(parents=True, exist_ok=True)
        html = _render_html_page(page_title, lead, source_label, sections)
        out_path.write_text(html, encoding="utf-8")
        self.harness.trace.append(TraceEvent("execute", "render html page", str(out_path)))
        return RunResult(
            skill="html-page",
            returncode=0,
            stdout=f"Generated HTML page: {out_path}\n",
            outputs=[out_path],
            loaded_resources=resources,
            trace=list(self.harness.trace),
        )

    def _run_flash_card(self, request: str, *, output: str | Path | None, word: str | None, resources) -> RunResult:
        skill = self.harness.load_skill("flash-card")
        target_word = (word or _extract_word(request) or "").lower()
        if not target_word:
            raise SkillExecutionError("Cannot infer English word. Pass --word <word>.")
        data_path = skill.meta.skill_dir / "data" / f"{target_word}.json"
        if not data_path.exists():
            raise SkillExecutionError(
                f"No flash-card data found for {target_word!r}: {data_path}. "
                "Create the JSON first or pass a word that exists under skill data/."
            )
        script_path = skill.meta.skill_dir / "scripts" / "make_flashcard.py"
        if not script_path.exists():
            raise SkillExecutionError(f"flash-card script not found: {script_path}")
        out_path = Path(output).resolve() if output else (self.harness.cwd / f"{target_word}.html").resolve()
        out_path.parent.mkdir(parents=True, exist_ok=True)
        command = [sys.executable, str(script_path), str(data_path), "-o", str(out_path)]
        self.harness.trace.append(TraceEvent("execute", "run flash-card script", str(script_path)))
        proc = subprocess.run(command, cwd=str(self.harness.cwd), text=True, capture_output=True)
        return RunResult(
            skill="flash-card",
            returncode=proc.returncode,
            command=command,
            stdout=proc.stdout,
            stderr=proc.stderr,
            outputs=[out_path] if out_path.exists() else [],
            loaded_resources=resources,
            trace=list(self.harness.trace),
        )

    def _run_diagram(self, request: str, *, output: str | Path | None, svg: str | Path | None, resources) -> RunResult:
        skill = self.harness.load_skill("baoyu-diagram")
        if svg is None:
            return RunResult(
                skill="baoyu-diagram",
                returncode=0,
                stdout=(
                    "baoyu-diagram instructions/resources loaded. "
                    "Provide --svg <file.svg> to execute the SVG to PNG converter adapter."
                ),
                loaded_resources=resources,
                trace=list(self.harness.trace),
            )
        svg_path = Path(svg).resolve()
        if not svg_path.exists():
            raise SkillExecutionError(f"SVG file not found: {svg_path}")
        script_path = skill.meta.skill_dir / "scripts" / "main.ts"
        bun = shutil.which("bun")
        if not bun:
            raise SkillExecutionError("bun runtime not found; install bun or run the converter manually as described in SKILL.md")
        command = [bun, str(script_path), str(svg_path), "--json"]
        if output:
            command.extend(["-o", str(Path(output).resolve())])
        self.harness.trace.append(TraceEvent("execute", "run baoyu-diagram SVG converter", str(script_path)))
        proc = subprocess.run(command, cwd=str(self.harness.cwd), text=True, capture_output=True)
        outputs: list[Path] = []
        if proc.returncode == 0:
            try:
                payload = json.loads(proc.stdout)
                if "output" in payload:
                    outputs.append(Path(payload["output"]).resolve())
            except json.JSONDecodeError:
                if output and Path(output).exists():
                    outputs.append(Path(output).resolve())
        return RunResult(
            skill="baoyu-diagram",
            returncode=proc.returncode,
            command=command,
            stdout=proc.stdout,
            stderr=proc.stderr,
            outputs=outputs,
            loaded_resources=resources,
            trace=list(self.harness.trace),
        )


def _extract_word(request: str) -> str | None:
    tokens = re.findall(r"[A-Za-z][A-Za-z'-]*", request)
    stop = {"flash", "card", "make", "create", "word", "for", "the", "a", "an", "html"}
    candidates = [t for t in tokens if t.lower() not in stop]
    return candidates[-1] if candidates else None


def _render_weekly_report(notes: str, *, source: str) -> str:
    items = _extract_note_items(notes)
    if not items:
        items = ["待补充本周工作事项"]

    buckets = {
        "本周完成": [],
        "进行中": [],
        "风险与问题": [],
        "下周计划": [],
    }
    for item in items:
        buckets[_classify_weekly_item(item)].append(_polish_weekly_item(item))

    for heading, placeholder in (
        ("本周完成", "待补充本周已完成的核心工作。"),
        ("进行中", "待补充仍在推进中的事项。"),
        ("风险与问题", "暂无明确风险；如有依赖、阻塞或待确认事项可继续补充。"),
        ("下周计划", "待补充下周计划与优先级。"),
    ):
        if not buckets[heading]:
            buckets[heading].append(placeholder)

    parts = [f"<!-- generated from {source} -->", "# 周报", ""]
    for heading in ("本周完成", "进行中", "风险与问题", "下周计划"):
        parts.append(f"## {heading}")
        parts.extend(f"- {item}" for item in buckets[heading])
        parts.append("")
    return "\n".join(parts).rstrip() + "\n"


def _extract_note_items(notes: str) -> list[str]:
    items: list[str] = []
    for raw in notes.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        line = re.sub(r"^[-*+]\s+", "", line)
        line = re.sub(r"^\d+[.)、]\s*", "", line)
        line = line.strip()
        if line:
            items.append(line)
    return items


def _classify_weekly_item(item: str) -> str:
    text = item.lower()
    risk_terms = ("风险", "问题", "阻塞", "blocked", "blocker", "bug", "延期", "依赖", "待确认", "失败")
    next_terms = ("下周", "计划", "next", "todo", "准备", "将", "继续", "后续")
    progress_terms = ("进行中", "推进", "开发中", "调研", "优化中", "in progress", "working", "处理中")
    done_terms = ("完成", "已", "上线", "修复", "实现", "交付", "发布", "completed", "finished", "fixed", "implemented")

    if any(term in text for term in risk_terms):
        return "风险与问题"
    if any(term in text for term in next_terms):
        return "下周计划"
    if any(term in text for term in progress_terms):
        return "进行中"
    if any(term in text for term in done_terms):
        return "本周完成"
    return "本周完成"


def _polish_weekly_item(item: str) -> str:
    item = item.strip().rstrip("。.;；")
    if not item:
        return "待补充"
    return item + "。"


def _infer_html_title(source_text: str, request: str) -> str:
    for text in (source_text, request):
        for line in text.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            stripped = re.sub(r"^#+\s*", "", stripped)
            stripped = re.sub(r"^[-*+]\s*", "", stripped)
            if stripped:
                return stripped[:60]
    return "HTML Page"


def _build_html_lead(source_text: str, request: str) -> str:
    lines = [line.strip() for line in source_text.splitlines() if line.strip() and not line.strip().startswith("#")]
    if lines:
        return lines[0]
    return request.strip() or "Self-contained HTML page generated by the harness."


def _parse_html_sections(source_text: str) -> list[tuple[str, list[str]]]:
    sections: list[tuple[str, list[str]]] = []
    current_title: str | None = None
    current_lines: list[str] = []
    has_heading = False

    for raw in source_text.splitlines():
        line = raw.rstrip()
        heading = re.match(r"^(#{1,3})\s+(.+?)\s*$", line)
        if heading:
            has_heading = True
            if current_title is not None:
                sections.append((current_title, _normalize_html_section_lines(current_lines)))
            current_title = heading.group(2).strip()
            current_lines = []
            continue
        current_lines.append(line)

    if current_title is not None:
        sections.append((current_title, _normalize_html_section_lines(current_lines)))

    if has_heading:
        return [(title, items or ["待补充"]) for title, items in sections]

    items = _normalize_html_section_lines(source_text.splitlines())
    if items:
        return [("Overview", items)]
    return []


def _normalize_html_section_lines(lines: list[str]) -> list[str]:
    items: list[str] = []
    buffer: list[str] = []
    for raw in lines:
        line = raw.strip()
        if not line:
            if buffer:
                items.append(" ".join(buffer).strip())
                buffer = []
            continue
        bullet = re.sub(r"^[-*+]\s+", "", line)
        bullet = re.sub(r"^\d+[.)、]\s*", "", bullet)
        if bullet != line or line.startswith("-") or line.startswith("*") or line[:1].isdigit():
            if buffer:
                items.append(" ".join(buffer).strip())
                buffer = []
            if bullet:
                items.append(bullet)
            continue
        buffer.append(line)
    if buffer:
        items.append(" ".join(buffer).strip())
    return [item for item in items if item]


def _condense_line(text: str) -> str:
    line = " ".join(part.strip() for part in text.splitlines() if part.strip())
    return line or "待补充内容"


def _render_html_page(title: str, lead: str, source_label: str, sections: list[tuple[str, list[str]]]) -> str:
    section_cards = "\n".join(_render_html_section(title, items) for title, items in sections)
    stat_section_count = len(sections)
    stat_item_count = sum(len(items) for _, items in sections)
    stat_word_count = len(re.findall(r"\w+", lead + " " + " ".join(item for _, items in sections for item in items)))
    return f"""<!DOCTYPE html>
<html lang=\"zh-CN\">
<head>
  <meta charset=\"UTF-8\">
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1.0\">
  <title>{html_escape(title)}</title>
  <style>
    :root {{
      color-scheme: light;
      --bg: #f4f6f8;
      --surface: #ffffff;
      --surface-2: #eef2f6;
      --text: #0f172a;
      --muted: #475569;
      --border: #d8e0ea;
      --accent: #2563eb;
      --accent-2: #0f766e;
      --shadow: 0 8px 24px rgba(15, 23, 42, 0.08);
      --radius: 10px;
      --maxw: 1120px;
    }}
    * {{ box-sizing: border-box; }}
    html, body {{ margin: 0; padding: 0; }}
    body {{
      font-family: Inter, \"Segoe UI\", Arial, sans-serif;
      background: var(--bg);
      color: var(--text);
      line-height: 1.5;
    }}
    .page {{ min-height: 100vh; display: flex; flex-direction: column; }}
    .shell {{ width: min(100% - 32px, var(--maxw)); margin: 0 auto; }}
    header, footer {{ background: var(--surface); border-bottom: 1px solid var(--border); }}
    footer {{ border-top: 1px solid var(--border); border-bottom: 0; margin-top: auto; }}
    .topbar, .footerbar {{
      display: flex; align-items: center; justify-content: space-between; gap: 16px; padding: 18px 0;
    }}
    .brand {{ display: flex; align-items: center; gap: 12px; min-width: 0; }}
    .brand-mark {{ width: 36px; height: 36px; border-radius: 9px; background: linear-gradient(135deg, var(--accent), var(--accent-2)); flex: 0 0 auto; }}
    .brand-text h1, .hero h2, .section h3 {{ margin: 0; line-height: 1.2; }}
    .brand-text p, .eyebrow, .meta, .supporting, .note {{ margin: 0; color: var(--muted); }}
    main {{ padding: 28px 0 40px; }}
    .hero {{
      display: grid; grid-template-columns: minmax(0, 1.5fr) minmax(280px, 0.9fr); gap: 20px; align-items: start; margin-bottom: 22px;
    }}
    .panel {{ background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius); box-shadow: var(--shadow); }}
    .hero-main, .hero-side, .section {{ padding: 24px; }}
    .eyebrow {{ font-size: 12px; text-transform: uppercase; letter-spacing: 0.08em; margin-bottom: 10px; }}
    .hero h2 {{ font-size: 34px; margin-bottom: 12px; }}
    .hero-copy {{ max-width: 62ch; color: var(--muted); margin-bottom: 18px; }}
    .actions {{ display: flex; flex-wrap: wrap; gap: 12px; }}
    .btn {{ display: inline-flex; align-items: center; justify-content: center; min-height: 40px; padding: 0 16px; border-radius: 8px; border: 1px solid transparent; font: inherit; cursor: pointer; }}
    .btn-primary {{ background: var(--accent); color: white; }}
    .btn-secondary {{ background: var(--surface-2); color: var(--text); border-color: var(--border); }}
    .stats {{ display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 12px; }}
    .stat {{ padding: 14px; background: var(--surface-2); border-radius: 8px; }}
    .stat strong {{ display: block; font-size: 24px; margin-bottom: 4px; }}
    .grid {{ display: grid; grid-template-columns: repeat(12, minmax(0, 1fr)); gap: 20px; margin-top: 20px; }}
    .section {{ grid-column: span 8; }}
    .sidebar {{ grid-column: span 4; padding: 24px; }}
    .section-card {{ padding: 16px; background: var(--surface-2); border-radius: 8px; margin-top: 16px; }}
    .section-card h3 {{ font-size: 18px; margin-bottom: 8px; }}
    .section-card ul {{ margin: 0; padding-left: 18px; color: var(--muted); }}
    .section-card p {{ margin: 0; color: var(--muted); }}
    .sidebar .card + .card {{ margin-top: 12px; }}
    .meta-row {{ display: flex; gap: 12px; flex-wrap: wrap; margin-top: 16px; }}
    .pill {{ display: inline-flex; align-items: center; min-height: 32px; padding: 0 12px; border-radius: 999px; background: var(--surface-2); color: var(--muted); font-size: 13px; }}
    @media (max-width: 920px) {{
      .hero, .section, .sidebar {{ grid-column: 1 / -1; }}
      .hero {{ grid-template-columns: 1fr; }}
      .stats {{ grid-template-columns: 1fr; }}
    }}
  </style>
</head>
<body>
  <div class=\"page\" id=\"top\">
    <header>
      <div class=\"shell topbar\">
        <div class=\"brand\">
          <div class=\"brand-mark\" aria-hidden=\"true\"></div>
          <div class=\"brand-text\">
            <h1>{html_escape(title)}</h1>
            <p class=\"meta\">根据 {html_escape(source_label)} 生成</p>
          </div>
        </div>
        <nav aria-label=\"主导航\">
          <a href=\"#content\">内容</a>
          <span aria-hidden=\"true\"> · </span>
          <a href=\"#summary\">概览</a>
        </nav>
      </div>
    </header>

    <main>
      <div class=\"shell\">
        <section class=\"hero\">
          <div class=\"panel hero-main\">
            <p class=\"eyebrow\">概览</p>
            <h2>{html_escape(title)}</h2>
            <p class=\"hero-copy\">{html_escape(lead)}</p>
            <div class=\"actions\">
              <button class=\"btn btn-primary\" type=\"button\">主要操作</button>
              <button class=\"btn btn-secondary\" type=\"button\">次要操作</button>
            </div>
            <div class=\"meta-row\" id=\"summary\">
              <span class=\"pill\">区块：{stat_section_count}</span>
              <span class=\"pill\">条目：{stat_item_count}</span>
              <span class=\"pill\">词数：{stat_word_count}</span>
            </div>
          </div>
          <aside class=\"panel hero-side\" aria-label=\"概览\">
            <p class=\"eyebrow\">概览</p>
            <div class=\"stats\">
              <div class=\"stat\"><strong>{stat_section_count}</strong><span class=\"meta\">区块</span></div>
              <div class=\"stat\"><strong>{stat_item_count}</strong><span class=\"meta\">条目</span></div>
              <div class=\"stat\"><strong>{stat_word_count}</strong><span class=\"meta\">词数</span></div>
            </div>
          </aside>
        </section>

        <div class=\"grid\" id=\"content\">
          <section class=\"panel section\">
            <p class=\"eyebrow\">内容</p>
            <h3>页面内容</h3>
            {section_cards}
          </section>

          <aside class=\"panel sidebar\">
            <p class=\"eyebrow\">说明</p>
            <div class=\"card section-card\">
              <ul>
                <li>单文件 HTML 输出</li>
                <li>仅使用内联 CSS</li>
                <li>响应式且自包含</li>
              </ul>
            </div>
            <div class=\"card section-card\">
              <h3>模板</h3>
              <p class=\"supporting\">此页面使用 html-page skill 的本地模板模式生成，可以直接在浏览器中打开。</p>
            </div>
          </aside>
        </div>
      </div>
    </main>

    <footer>
      <div class=\"shell footerbar\">
        <p class=\"note\">由 html-page 生成</p>
        <p class=\"note\"><a href=\"#top\">返回顶部</a></p>
      </div>
    </footer>
  </div>
</body>
</html>
"""


def _render_html_section(title: str, items: list[str]) -> str:
    if not items:
        return f'<div class="section-card"><h3>{html_escape(title)}</h3><p>待补充</p></div>'
    if len(items) == 1 and len(items[0]) > 120 and "\n" not in items[0]:
        body = f'<p>{html_escape(items[0])}</p>'
    else:
        body = "<ul>" + "".join(f"<li>{html_escape(item)}</li>" for item in items) + "</ul>"
    return f'<div class="section-card"><h3>{html_escape(title)}</h3>{body}</div>'


def html_escape(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )
