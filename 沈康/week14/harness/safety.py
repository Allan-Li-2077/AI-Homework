"""路径沙箱校验。

所有文件类工具（list_dir / read_file / write_file / open_in_browser）都通过
``safe_join`` 把 LLM 给出的相对路径拼到项目根下，并校验结果仍在项目根内，
防止 ``..`` 或绝对路径越界写出到沙箱之外。
"""
from __future__ import annotations

from pathlib import Path

__all__ = ["safe_join"]


def safe_join(root: Path, user_path: str) -> Path | None:
    """把 ``user_path`` 拼到 ``root`` 下并校验未越界。

    Args:
        root: 项目根目录（沙箱边界）。
        user_path: LLM 给出的相对路径，例如 ``.skill/flash-card/data/crazy.json``。

    Returns:
        解析后的绝对路径；若越界（含 ``..`` 逃逸、绝对路径指向沙箱外）则返回 ``None``。
    """
    if user_path is None:
        return None
    root = root.resolve()
    # 空路径视为项目根本身
    candidate = (root / (user_path or ".")).resolve()
    try:
        candidate.relative_to(root)
    except ValueError:
        return None
    return candidate
