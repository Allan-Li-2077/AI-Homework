"""
Demo Skill: 个性化问候生成

演示：
  1. SkillImpl 接口实现
  2. Context 使用
  3. 参数验证与处理
  4. 同步执行
"""

from typing import Any, Dict
import asyncio


class SkillImpl:
    """Skill 实现基类"""
    
    def __init__(self, context):
        """
        Args:
            context: SkillContext 实例（包含元数据、参数、依赖结果）
        """
        self.context = context
    
    async def execute(self, **kwargs) -> str:
        """
        执行 skill 的主逻辑
        
        Args:
            **kwargs: 从 context 中提取的输入参数
        
        Returns:
            生成的问候文本
        """
        name = kwargs.get("name", "Friend")
        tone = kwargs.get("tone", "friendly")
        language = kwargs.get("language", "zh")
        
        # 模拟一些计算（演示异步）
        await asyncio.sleep(0.1)
        
        # 根据语言和风格选择模板
        greetings = {
            ("friendly", "zh"): f"你好 {name}！😊 祝你今天过得愉快！",
            ("friendly", "en"): f"Hello {name}! 😊 Have a wonderful day!",
            ("formal", "zh"): f"尊敬的 {name}，祝您安好。",
            ("formal", "en"): f"Dear {name}, I hope you are doing well.",
            ("casual", "zh"): f"嘿 {name}！👋 怎么样？",
            ("casual", "en"): f"Hey {name}! 👋 What's up?",
            ("enthusiastic", "zh"): f"太棒了 {name}！🎉 见到你真开心！",
            ("enthusiastic", "en"): f"Awesome {name}! 🎉 Excited to see you!",
        }
        
        greeting = greetings.get(
            (tone, language),
            f"Hello {name}!",
        )
        
        return greeting
