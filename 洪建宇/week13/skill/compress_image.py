"""compress_image - 压缩图片，可指定质量与最大宽度。

依赖: Pillow (pip install Pillow)
渐进式约定: Pillow 在 run() 内部局部 import，避免被发现阶段加载。
"""
import os
from typing import Any, Dict

SKILL_META: Dict[str, Any] = {
    "name": "compress_image",
    "description": "压缩图片，可指定质量与最大宽度",
    "category": "image",
    "params": {
        "input_path": {
            "type": "str",
            "required": True,
            "description": "输入图片路径（jpg/png/webp 等）",
        },
        "output_path": {
            "type": "str",
            "required": False,
            "default": None,
            "description": "输出路径，不填则在原文件名后加 _compressed",
        },
        "quality": {
            "type": "int",
            "required": False,
            "default": 85,
            "description": "压缩质量 (1-100)，数值越小压缩率越高",
        },
        "max_width": {
            "type": "int",
            "required": False,
            "default": 1920,
            "description": "最大宽度（像素），超过则等比缩小",
        },
    },
    "dependencies": ["Pillow"],
}


def run(**kwargs) -> Dict[str, Any]:
    """压缩图片。返回输出路径、原始大小、压缩后大小。"""
    # 局部 import：仅在真正执行时加载 Pillow
    from PIL import Image

    input_path = kwargs["input_path"]
    output_path = kwargs.get("output_path")
    quality = int(kwargs.get("quality", 85))
    max_width = int(kwargs.get("max_width", 1920))

    if not os.path.isfile(input_path):
        raise FileNotFoundError(f"输入图片不存在: {input_path}")

    # 默认输出路径：原名_compressed.原扩展名
    if not output_path:
        base, ext = os.path.splitext(input_path)
        output_path = f"{base}_compressed{ext}"

    original_size = os.path.getsize(input_path)

    with Image.open(input_path) as img:
        # 转为 RGB（避免 PNG 带 alpha 通道时 JPEG 保存报错）
        save_kwargs = {"quality": quality, "optimize": True}

        # 等比缩小到 max_width 以内
        if img.width > max_width:
            ratio = max_width / float(img.width)
            new_size = (max_width, int(img.height * ratio))
            img = img.resize(new_size, Image.LANCZOS)

        # 若目标为 jpg 而图像带 alpha，先转 RGB
        out_ext = os.path.splitext(output_path)[1].lower()
        if out_ext in (".jpg", ".jpeg") and img.mode in ("RGBA", "P"):
            img = img.convert("RGB")

        img.save(output_path, **save_kwargs)

    compressed_size = os.path.getsize(output_path)
    saved_pct = (1 - compressed_size / original_size) * 100 if original_size else 0

    return {
        "output_path": output_path,
        "original_size": original_size,
        "compressed_size": compressed_size,
        "saved_percent": round(saved_pct, 2),
    }
