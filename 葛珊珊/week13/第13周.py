"""harness.registry — L1 元数据层

启动时扫描 skills_dir 下每个 Skill 的 manifest.json，
构建内存索引（不读 SKILL.md 正文）。
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class SkillMeta:
    name: str
    version: str
    description: str
    triggers: list[str]
    inputs: list[str]
    outputs: list[str]
    dependencies: dict
    entry: str
    resource_index: list[dict]
    path: Path                       # skill 根目录
    manifest_path: Path              # manifest.json 全路径
    manifest: dict = field(default_factory=dict)
    extra: dict = field(default_factory=dict)


class SkillRegistry:
    """Skill 元数据注册表。

    用法:
        reg = SkillRegistry(Path("./skills"))
        reg.scan()
        for s in reg.list():
            print(s.name, s.version)
    """

    def __init__(self, skills_dir: Path) -> None:
        self.skills_dir = skills_dir
        self._skills: dict[str, SkillMeta] = {}

    def scan(self) -> int:
        """全量扫描 manifest.json，返回扫到的 Skill 数。

        注意：只读 manifest.json，绝不读 SKILL.md / references/。
        """
        self._skills.clear()
        if not self.skills_dir.exists():
            return 0
        for entry in sorted(self.skills_dir.iterdir()):
            if not entry.is_dir():
                continue
            manifest_path = entry / "manifest.json"
            if not manifest_path.exists():
                continue
            try:
                meta = self._parse(manifest_path, entry)
            except Exception as e:  # noqa: BLE001
                # 单个 skill 解析失败不影响整体
                continue
            self._skills[meta.name] = meta
        return len(self._skills)

    @staticmethod
    def _parse(manifest_path: Path, skill_dir: Path) -> SkillMeta:
        with open(manifest_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        known_keys = {
            "name", "version", "description", "triggers", "inputs",
            "outputs", "dependencies", "entry", "resource_index",
        }
        extra = {k: v for k, v in data.items() if k not in known_keys}
        return SkillMeta(
            name=data["name"],
            version=data.get("version", "0.0.0"),
            description=data.get("description", ""),
            triggers=data.get("triggers", []),
            inputs=data.get("inputs", []),
            outputs=data.get("outputs", []),
            dependencies=data.get("dependencies", {}),
            entry=data.get("entry", ""),
            resource_index=data.get("resource_index", []),
            path=skill_dir,
            manifest_path=manifest_path,
            manifest=data,
            extra=extra,
        )

    def list(self) -> list[SkillMeta]:
        return list(self._skills.values())

    def get(self, name: str) -> Optional[SkillMeta]:
        return self._skills.get(name)

    def names(self) -> list[str]:
        return list(self._skills.keys())

    def scan_with_timing(self) -> tuple[int, float]:
        """扫描并返回耗时（毫秒）。"""
        t0 = time.perf_counter()
        n = self.scan()
        elapsed_ms = (time.perf_counter() - t0) * 1000
        return n, elapsed_ms




"""harness.loader — L2/L3 懒加载层

L2: 读 SKILL.md 并截断到 <!-- REFERENCE_FOLLOWS --> 标记
L3: 按 resource_index 里的 id 加载 references/*.md、scripts/* 等

带文件级缓存（基于 mtime 失效）。
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

from .cache import FileCache
from .registry import SkillMeta


# 在 SKILL.md 里用于「执行清单/参考手册」分割的标记
REFERENCE_MARKER = "<!-- REFERENCE_FOLLOWS -->"


@dataclass
class LoadResult:
    """单次加载结果（含耗时和大小，便于 benchmark）"""
    content: str
    bytes_read: int
    duration_ms: float
    truncated: bool = False
    source_path: Path | None = None


class LazyLoader:
    """按需加载 Skill 资源。

    用法:
        loader = LazyLoader(cache=FileCache())
        instr = loader.get_instruction(skill)             # SKILL.md 截断版
        ref   = loader.get_reference(skill, "arch")        # references/architecture.md
        full  = loader.get_full_skill_md(skill)            # 不截断，调试用
    """

    def __init__(self, cache: FileCache | None = None) -> None:
        self.cache = cache or FileCache()

    # ───────────────────────── L2: SKILL.md 截断加载 ─────────────────────────

    def get_instruction(self, skill: SkillMeta) -> LoadResult:
        """读取 SKILL.md，遇到 REFERENCE_MARKER 即截断。

        没有标记的 skill（如短 SKILL.md）返回全文。
        """
        t0 = time.perf_counter()
        skill_md = skill.path / "SKILL.md"
        content = self._read_cached(skill_md)
        if content is None:
            content = ""
        truncated = REFERENCE_MARKER in content
        if truncated:
            content = content.split(REFERENCE_MARKER, 1)[0].rstrip() + "\n"
        elapsed = (time.perf_counter() - t0) * 1000
        return LoadResult(
            content=content,
            bytes_read=len(content.encode("utf-8")),
            duration_ms=elapsed,
            truncated=truncated,
            source_path=skill_md,
        )

    def get_full_skill_md(self, skill: SkillMeta) -> LoadResult:
        """读取 SKILL.md 全文（不截断，调试 / 对比用）。"""
        t0 = time.perf_counter()
        skill_md = skill.path / "SKILL.md"
        content = self._read_cached(skill_md) or ""
        elapsed = (time.perf_counter() - t0) * 1000
        return LoadResult(
            content=content,
            bytes_read=len(content.encode("utf-8")),
            duration_ms=elapsed,
            truncated=False,
            source_path=skill_md,
        )

    # ───────────────────────── L3: 资源懒加载 ─────────────────────────

    def get_reference(self, skill: SkillMeta, ref_id: str) -> LoadResult | None:
        """按 resource_index 的 id 加载 references 或 scripts。

        返回 None 表示未找到该 ref_id。
        """
        resource = self._find_resource(skill, ref_id)
        if resource is None:
            return None
        rel_path = resource.get("path", "")
        if not rel_path:
            return None
        target = skill.path / rel_path
        if not target.exists():
            return None
        t0 = time.perf_counter()
        content = self._read_cached(target) or ""
        elapsed = (time.perf_counter() - t0) * 1000
        return LoadResult(
            content=content,
            bytes_read=len(content.encode("utf-8")),
            duration_ms=elapsed,
            source_path=target,
        )

    def list_resources(self, skill: SkillMeta) -> list[dict]:
        """列出该 skill 所有可加载的资源（来自 manifest.json 的 resource_index）。"""
        return list(skill.resource_index)

    def _find_resource(self, skill: SkillMeta, ref_id: str) -> dict | None:
        for r in skill.resource_index:
            if r.get("id") == ref_id:
                return r
        return None

    # ───────────────────────── 内部 ─────────────────────────

    def _read_cached(self, path: Path) -> str | None:
        cached = self.cache.get(path)
        if cached is not None:
            return cached
        if not path.exists():
            return None
        content = path.read_text(encoding="utf-8")
        self.cache.put(path, content)
        return content



"""harness.router — 用户输入 → Skill 路由

MVP 实现：基于 manifest.json 的 triggers 字段做关键词子串匹配。
- 大小写不敏感
- 命中第一个即返回
- 无匹配时按 description 做一次宽松子串兜底
- 后续可升级为 embedding 检索

新增：返回 inferred_types，用于触发 L3 references 的懒加载。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from .registry import SkillMeta, SkillRegistry


# type 关键词 → 资源 id 的映射（驱动 L3 懒加载）
# baoyu-diagram 的 references/*.md 就用这 4 个 id
TYPE_KEYWORDS: dict[str, list[str]] = {
    "architecture": ["架构图", "architecture", "组件关系", "组件", "系统图", "微服务"],
    "flowchart":    ["流程图", "flowchart", "决策", "流程", "状态流转"],
    "sequence":     ["时序图", "sequence diagram", "时序", "交互图", "泳道"],
    "structural":   ["结构图", "structural diagram", "类图", "er 图", "组织架构"],
}

# 中文/英文停用词（路由匹配时去除，避免被连接词切断触发词）
# 注意：必须是 list 而非 set！且按长度倒序（长的先匹配，否则短 stopword
# 会先拆散长 stopword，比如「个」先匹配会把「一个」拆成「画一 流程图」）
STOPWORDS = [
    "帮我", "一个", "的", "加", "和", "与", "用", "做",
    "请", "我", "要", "是", "给", "下", "个",
]


def _strip_stopwords(text: str) -> str:
    """去掉停用词 + 多空格折叠。"""
    out = text
    for sw in STOPWORDS:
        out = out.replace(sw, " ")
    return " ".join(out.split())


def _normalize(text: str) -> str:
    """去停用词 + 去空格（用于 trigger 容错匹配）。"""
    return _strip_stopwords(text).replace(" ", "")


@dataclass
class RouteResult:
    skill: SkillMeta | None
    matched_trigger: str | None
    matched_via: str          # "trigger" | "description" | "exact" | "none"
    inferred_types: list[str] = field(default_factory=list)  # 新增：推断的图表类型

    @property
    def ok(self) -> bool:
        return self.skill is not None


class Router:
    """轻量路由器。

    用法:
        router = Router(registry)
        result = router.match("帮我画一个架构图")
        if result.ok:
            print(result.skill.name, result.inferred_types)
    """

    def __init__(self, registry: SkillRegistry) -> None:
        self.registry = registry

    def match(self, query: str) -> RouteResult:
        q = query.strip()
        if not q:
            return RouteResult(None, None, "none")

        # 优先级 1：精确命令前缀 /skill <name>
        if q.startswith("/skill "):
            name = q[len("/skill "):].strip().split()[0]
            skill = self.registry.get(name)
            if skill:
                return self._infer_types(skill, q, name, "exact")
            return RouteResult(None, None, "none")

        # 优先级 2：trigger 关键词命中（遍历所有 skill，按 skill 注册顺序）
        ql = q.lower()
        ql_norm = _normalize(ql)
        for skill in self.registry.list():
            for trig in skill.triggers:
                tl = trig.lower()
                # 先原样匹配；失败则标准化后再匹配（容错停用词+空格）
                if tl in ql or tl.replace(" ", "") in ql_norm:
                    return self._infer_types(skill, q, trig, "trigger")

        # 优先级 3：description 关键词兜底（中文/英文都试）
        for skill in self.registry.list():
            if skill.description and skill.description[:30].lower() in ql:
                return self._infer_types(skill, q, skill.description[:30], "description")

        return RouteResult(None, None, "none")

    @staticmethod
    def _infer_types(skill: SkillMeta, query: str, trigger: str, via: str) -> RouteResult:
        """从 query 中推断涉及的 type（驱动 L3 懒加载）。

        先在原始 query 中找，找不到再去掉停用词后找。
        """
        ql = query.lower()
        ql_norm = _normalize(ql)
        types: list[str] = []
        for type_name, keywords in TYPE_KEYWORDS.items():
            for kw in keywords:
                kwl = kw.lower()
                kwl_norm = kwl.replace(" ", "")
                if kwl in ql or kwl_norm in ql_norm:
                    types.append(type_name)
                    break
        return RouteResult(
            skill=skill,
            matched_trigger=trigger,
            matched_via=via,
            inferred_types=types,
        )


"""harness.executor — Skill 执行器（subprocess）

MVP 实现：
- 根据 manifest.entry 找到 scripts/ 下的脚本
- 用 subprocess.run 执行（不真正解析 args，由上游按 skill 协议传入）
- 捕获 stdout/stderr/returncode/duration
"""
from __future__ import annotations

import shlex
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from .registry import SkillMeta


@dataclass
class ExecResult:
    returncode: int
    stdout: str
    stderr: str
    duration_ms: float
    cmd: list[str]

    @property
    def ok(self) -> bool:
        return self.returncode == 0


class Executor:
    """执行 Skill 的 entry 脚本。

    用法:
        ex = Executor()
        r = ex.execute(skill, args=["--help"])
    """

    DEFAULT_TIMEOUT = 30  # 秒

    def execute(
        self,
        skill: SkillMeta,
        args: Optional[list[str]] = None,
        timeout: int = DEFAULT_TIMEOUT,
        cwd: Optional[Path] = None,
    ) -> ExecResult:
        script_path = skill.path / skill.entry if skill.entry else None
        if script_path is None or not script_path.exists():
            return ExecResult(
                returncode=-1,
                stdout="",
                stderr=f"entry script not found: {skill.entry}",
                duration_ms=0.0,
                cmd=[],
            )

        cmd = self._build_cmd(script_path, args or [])
        cwd = cwd or skill.path
        t0 = time.perf_counter()
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=str(cwd),
            )
            elapsed_ms = (time.perf_counter() - t0) * 1000
            return ExecResult(
                returncode=proc.returncode,
                stdout=proc.stdout,
                stderr=proc.stderr,
                duration_ms=elapsed_ms,
                cmd=cmd,
            )
        except subprocess.TimeoutExpired:
            elapsed_ms = (time.perf_counter() - t0) * 1000
            return ExecResult(
                returncode=-1,
                stdout="",
                stderr=f"timeout after {timeout}s",
                duration_ms=elapsed_ms,
                cmd=cmd,
            )
        except FileNotFoundError as e:
            elapsed_ms = (time.perf_counter() - t0) * 1000
            return ExecResult(
                returncode=-1,
                stdout="",
                stderr=f"runtime not found: {e}",
                duration_ms=elapsed_ms,
                cmd=cmd,
            )

    @staticmethod
    def _build_cmd(script_path: Path, args: list[str]) -> list[str]:
        ext = script_path.suffix.lower()
        if ext == ".py":
            # python script.py arg1 arg2
            return ["python", str(script_path), *args]
        if ext == ".ts":
            # bun script.ts arg1 arg2（兜底用 npx bun）
            return ["bun", str(script_path), *args]
        if ext in (".sh", ".bash"):
            return ["bash", str(script_path), *args]
        # 默认直接执行（依赖 shebang）
        return [str(script_path), *args]

    @staticmethod
    def quote_cmd(cmd: list[str]) -> str:
        return " ".join(shlex.quote(c) for c in cmd)





