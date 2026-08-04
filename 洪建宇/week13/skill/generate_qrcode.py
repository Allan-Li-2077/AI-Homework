"""generate_qrcode - 根据文本/链接生成二维码图片。

依赖: qrcode[pil] (pip install "qrcode[pil]")
渐进式约定: qrcode 在 run() 内部局部 import。
"""
from typing import Any, Dict

SKILL_META: Dict[str, Any] = {
    "name": "generate_qrcode",
    "description": "根据文本/链接生成二维码图片",
    "category": "generate",
    "params": {
        "text": {
            "type": "str",
            "required": True,
            "description": "要编码的文本或链接",
        },
        "output_path": {
            "type": "str",
            "required": False,
            "default": "qrcode.png",
            "description": "输出图片路径，默认 qrcode.png",
        },
        "size": {
            "type": "int",
            "required": False,
            "default": 300,
            "description": "最终输出图片的像素边长（正方形）",
        },
        "color": {
            "type": "str",
            "required": False,
            "default": "black",
            "description": "二维码前景色（如 black / #1a73e8）",
        },
    },
    "dependencies": ["qrcode[pil]"],
}


def run(**kwargs) -> Dict[str, Any]:
    """生成二维码图片。返回图片路径与尺寸。"""
    import qrcode
    from PIL import Image  # qrcode[pil] 的 [pil] extras 已带 Pillow

    text = kwargs["text"]
    output_path = kwargs.get("output_path", "qrcode.png")
    size = int(kwargs.get("size", 300))
    color = kwargs.get("color", "black")

    if not text:
        raise ValueError("text 不能为空")

    qr = qrcode.QRCode(
        version=1,  # 自动扩容（结合 make(fit=True)）
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=10,
        border=4,
    )
    qr.add_data(text)
    qr.make(fit=True)

    img = qr.make_image(fill_color=color, back_color="white").convert("RGB")
    # 缩放到目标像素尺寸
    img = img.resize((size, size), Image.LANCZOS)
    img.save(output_path)

    return {
        "output_path": output_path,
        "size": size,
        "text_length": len(text),
    }
