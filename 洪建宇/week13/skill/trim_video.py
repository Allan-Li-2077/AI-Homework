"""trim_video - 截取视频片段。

依赖: moviepy (pip install moviepy) —— 体积较大（约 50MB+），
       故本 skill 最能体现「渐进式加载」的价值：
       只有真正调用本 skill 时才会 import moviepy。
渐进式约定: moviepy 在 run() 内部局部 import。

注意: moviepy 依赖 ffmpeg。若系统未安装 ffmpeg，write_videofile 会失败。
"""
import os
from typing import Any, Dict

SKILL_META: Dict[str, Any] = {
    "name": "trim_video",
    "description": "截取视频片段",
    "category": "video",
    "params": {
        "input_path": {
            "type": "str",
            "required": True,
            "description": "输入视频路径",
        },
        "output_path": {
            "type": "str",
            "required": False,
            "default": None,
            "description": "输出视频路径；不填则原名加 _trimmed",
        },
        "start_time": {
            "type": "float",
            "required": True,
            "description": "开始时间（秒）",
        },
        "end_time": {
            "type": "float",
            "required": True,
            "description": "结束时间（秒）",
        },
    },
    "dependencies": ["moviepy"],
}


def run(**kwargs) -> Dict[str, Any]:
    """截取视频 [start_time, end_time] 片段。返回输出路径与时长。"""
    from moviepy.editor import VideoFileClip

    input_path = kwargs["input_path"]
    output_path = kwargs.get("output_path")
    start_time = float(kwargs["start_time"])
    end_time = float(kwargs["end_time"])

    if not os.path.isfile(input_path):
        raise FileNotFoundError(f"输入视频不存在: {input_path}")
    if end_time <= start_time:
        raise ValueError(f"end_time({end_time}) 必须大于 start_time({start_time})")

    if not output_path:
        base, ext = os.path.splitext(input_path)
        output_path = f"{base}_trimmed{ext}"

    # 用 with 上下文管理确保资源释放
    with VideoFileClip(input_path) as clip:
        if end_time > clip.duration:
            raise ValueError(
                f"end_time({end_time}) 超出视频时长({clip.duration:.2f}s)"
            )
        trimmed = clip.subclip(start_time, end_time)
        trimmed.write_videofile(
            output_path,
            codec="libx264",
            audio_codec="aac",
            verbose=False,
            logger=None,
        )

    duration = end_time - start_time
    return {
        "output_path": output_path,
        "duration": round(duration, 3),
    }
