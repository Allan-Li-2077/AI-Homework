"""
Demo Skill: 数据处理

演示：
  1. 复杂参数处理（list）
  2. 返回字典结果（便于后续依赖使用）
  3. 同步执行（不使用 async/await）
"""

from typing import Any, Dict, List
import statistics


class SkillImpl:
    """Skill 实现"""
    
    def __init__(self, context):
        self.context = context
    
    async def execute(self, **kwargs) -> Dict[str, Any]:
        """
        执行数据处理
        
        Args:
            **kwargs: data (list), operation (str, default: 'summary')
        
        Returns:
            处理结果字典
        """
        data = kwargs.get("data", [])
        operation = kwargs.get("operation", "summary")
        
        if not isinstance(data, list) or len(data) == 0:
            return {
                "error": "data 必须是非空列表",
                "success": False,
            }
        
        # 确保数据是数字
        try:
            data = [float(x) for x in data]
        except (ValueError, TypeError):
            return {
                "error": "data 中存在非数字元素",
                "success": False,
            }
        
        if operation == "summary":
            return self._operation_summary(data)
        elif operation == "filtering":
            return self._operation_filtering(data)
        elif operation == "sorting":
            return self._operation_sorting(data)
        else:
            return {
                "error": f"未知操作: {operation}",
                "success": False,
            }
    
    def _operation_summary(self, data: List[float]) -> Dict[str, Any]:
        """统计摘要"""
        return {
            "success": True,
            "operation": "summary",
            "count": len(data),
            "sum": sum(data),
            "avg": sum(data) / len(data),
            "min": min(data),
            "max": max(data),
            "median": statistics.median(data),
            "stdev": statistics.stdev(data) if len(data) > 1 else 0,
        }
    
    def _operation_filtering(self, data: List[float]) -> Dict[str, Any]:
        """过滤操作（大于中位数）"""
        median = statistics.median(data)
        filtered = [x for x in data if x > median]
        return {
            "success": True,
            "operation": "filtering",
            "median": median,
            "filtered": filtered,
            "count": len(filtered),
            "filter_ratio": len(filtered) / len(data),
        }
    
    def _operation_sorting(self, data: List[float]) -> Dict[str, Any]:
        """排序操作"""
        sorted_data = sorted(data)
        return {
            "success": True,
            "operation": "sorting",
            "sorted": sorted_data,
            "original": data,
            "is_ascending": sorted_data == data,
        }
