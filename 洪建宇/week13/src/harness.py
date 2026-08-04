"""harness - FileSkill Harness 主调度器。

职责：
    1. 发现：通过 skill_discovery 获取所有 skill 的元信息（轻量，无导入）
    2. 加载：按需 import 某个 skill 模块（渐进式，仅在执行时触发）
    3. 执行：依赖检查 -> 参数类型转换 -> 调用 skill.run()
    4. 卸载：从 sys.modules 移除已加载 skill，释放其依赖占用的内存

渐进式加载的核心收益：
    - 启动时只读元信息，不加载任何重依赖
    - 同一时刻只加载当前用到的 skill
    - 执行完毕可卸载，避免长期占用内存
"""
import importlib
import importlib.metadata as importlib_metadata
import sys
from typing import Any, Dict, Optional, Tuple

from skill_discovery import discover_skills


# pip 包名 -> Python import 名 的映射（仅收录本项目用到的）
# 大多数包两者一致，只有 Pillow（pip 名）实际 import 为 PIL。
_PACKAGE_IMPORT_ALIASES = {
    "Pillow": "PIL",
    "PyPDF2": "PyPDF2",
    "openpyxl": "openpyxl",
    "moviepy": "moviepy",
    "qrcode": "qrcode",
    "pandas": "pandas",
    "pdfplumber": "pdfplumber",
}


class FileSkillHarness:
    """渐进式 skill 调度器。"""

    def __init__(self, skills_dir: str = "skills"):
        self.skills_dir = skills_dir
        # 元信息注册表：仅含字典字面量，不含任何模块导入
        self._registry: Dict[str, Dict[str, Any]] = discover_skills(skills_dir)
        # 已加载的 skill 模块实例（懒加载缓存）
        self._loaded: Dict[str, Any] = {}

    # ------------------------------------------------------------------
    # 元信息查询（零导入）
    # ------------------------------------------------------------------
    def list_skills(self) -> Dict[str, Dict[str, Any]]:
        """返回所有已发现的 skill 元信息（不触发任何 import）。"""
        return self._registry

    def get_skill_info(self, name: str) -> Optional[Dict[str, Any]]:
        """获取单个 skill 的元信息。"""
        return self._registry.get(name)

    def is_loaded(self, name: str) -> bool:
        """该 skill 模块是否已被加载（import）。"""
        return name in self._loaded

    # ------------------------------------------------------------------
    # 依赖检查（不触发 skill 模块本身的导入）
    # ------------------------------------------------------------------
    @staticmethod
    def _is_package_installed(package: str) -> bool:
        """检查某个 pip 包是否已安装。

        处理 'qrcode[pil]' 这类带 extras 的写法：取 [ 之前的部分作为包名。
        优先尝试 import，失败再查 importlib.metadata（应对导入名与包名不一致）。
        """
        base = package.split("[", 1)[0].strip()
        import_name = _PACKAGE_IMPORT_ALIASES.get(base, base)
        # 1) 直接尝试 import（最可靠）
        try:
            importlib.import_module(import_name)
            return True
        except ImportError:
            pass
        # 2) 查 distribution 元数据（包已装但 import 名不同 / 延迟加载场景）
        try:
            importlib_metadata.distribution(base)
            return True
        except importlib_metadata.PackageNotFoundError:
            return False

    def check_dependencies(self, name: str) -> Tuple[bool, list]:
        """返回 (是否全部就绪, 缺失包列表)。"""
        meta = self._registry.get(name)
        if not meta:
            return False, []
        missing = [p for p in meta.get("dependencies", []) if not self._is_package_installed(p)]
        return (len(missing) == 0), missing

    # ------------------------------------------------------------------
    # 加载 / 卸载（渐进式核心）
    # ------------------------------------------------------------------
    def load_skill(self, name: str):
        """按需导入 skill 模块。已加载则直接返回缓存。

        - 不存在 -> KeyError
        - 依赖缺失 -> ImportError（提示安装命令）
        - 模块缺 run() -> AttributeError
        """
        if name in self._loaded:
            return self._loaded[name]

        meta = self._registry.get(name)
        if not meta:
            raise KeyError(f"未找到 skill: {name}（请检查 skills/ 目录）")

        ok, missing = self.check_dependencies(name)
        if not ok:
            raise ImportError(
                f"skill '{name}' 缺少依赖: {missing}\n"
                f"请运行: pip install {' '.join(missing)}"
            )

        # 动态导入 skill 模块（此时该 skill 内部的重依赖才会被真正加载）
        module = importlib.import_module(f"skills.{name}")
        if not hasattr(module, "run"):
            raise AttributeError(f"skill '{name}' 缺少 run() 入口函数")
        self._loaded[name] = module
        return module

    def unload_skill(self, name: str) -> bool:
        """卸载已加载的 skill，从 sys.modules 移除以释放内存。

        注意：仅移除该 skill 自身模块，其引入的第三方依赖（如 PIL）
        仍可能留在 sys.modules 中——这是 Python 的限制。如需彻底释放，
        进程退出是最干净的方式。返回是否发生了卸载。
        """
        unloaded = False
        if name in self._loaded:
            del self._loaded[name]
            unloaded = True
        module_path = f"skills.{name}"
        if module_path in sys.modules:
            del sys.modules[module_path]
            unloaded = True
        return unloaded

    # ------------------------------------------------------------------
    # 执行
    # ------------------------------------------------------------------
    def execute(self, name: str, **kwargs) -> Dict[str, Any]:
        """加载并执行 skill，返回 run() 的结构化结果。"""
        module = self.load_skill(name)
        meta = self._registry[name]
        # 根据 SKILL_META 做参数类型转换与校验
        coerced = self._coerce_params(kwargs, meta.get("params", {}))
        result = module.run(**coerced)
        return result if isinstance(result, dict) else {"result": result}

    @staticmethod
    def _coerce_params(raw: Dict[str, Any], spec: Dict[str, Any]) -> Dict[str, Any]:
        """根据 SKILL_META.params 中的 type 声明转换 CLI 传入的字符串参数。

        - 填充 default
        - 校验 required
        - int / float / bool / str 类型转换
        """
        coerced: Dict[str, Any] = {}
        for k, v in raw.items():
            t = spec.get(k, {}).get("type", "str")
            if v is None:
                coerced[k] = None
                continue
            try:
                if t == "int":
                    coerced[k] = int(v)
                elif t == "float":
                    coerced[k] = float(v)
                elif t == "bool":
                    coerced[k] = str(v).strip().lower() in ("1", "true", "yes", "on")
                else:
                    coerced[k] = str(v)
            except (ValueError, TypeError):
                coerced[k] = v  # 转换失败保留原值，交给 skill 自行处理

        # 填充默认值
        for k, s in spec.items():
            if k not in coerced and "default" in s:
                coerced[k] = s["default"]

        # 必填校验
        for k, s in spec.items():
            if s.get("required") and coerced.get(k) is None and k not in raw:
                raise ValueError(f"缺少必填参数: {k}")

        return coerced
