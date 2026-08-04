"""
Demo Skill: 报告生成（演示依赖注入）

演示：
  1. 依赖关系声明
  2. 自动依赖注入
  3. 结果聚合和格式化
"""

from typing import Any, Dict
from datetime import datetime


class SkillImpl:
    """Skill 实现"""
    
    def __init__(self, context):
        self.context = context
    
    async def execute(self, **kwargs) -> Dict[str, Any]:
        """
        生成综合报告
        
        Args:
            **kwargs: title (str), demo_data_process (dict)
        
        Returns:
            报告对象
        """
        title = kwargs.get("title", "数据分析报告")
        data_process_result = kwargs.get("demo_data_process")
        
        # 基础报告结构
        report = {
            "title": title,
            "generated_at": datetime.now().isoformat(),
            "version": "1.0",
            "status": "success",
            "sections": [],
        }
        
        # 如果没有前置数据，返回空报告
        if not data_process_result:
            report["status"] = "warning"
            report["message"] = "未收到前置数据处理结果"
            return report
        
        # 检查是否有错误
        if not data_process_result.get("success", False):
            report["status"] = "error"
            report["message"] = data_process_result.get("error", "未知错误")
            return report
        
        operation = data_process_result.get("operation", "unknown")
        
        # 根据不同的操作生成对应的报告部分
        if operation == "summary":
            report["sections"].append(self._section_summary(data_process_result))
        elif operation == "filtering":
            report["sections"].append(self._section_filtering(data_process_result))
        elif operation == "sorting":
            report["sections"].append(self._section_sorting(data_process_result))
        
        # 添加结论
        report["sections"].append({
            "type": "conclusion",
            "title": "结论",
            "content": f"数据处理完成，应用了 {operation} 操作。",
            "recommendations": [
                "定期更新数据集",
                "验证数据质量",
                "考虑多维度分析",
            ],
        })
        
        return report
    
    def _section_summary(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """统计摘要部分"""
        return {
            "type": "statistics",
            "title": "数据统计",
            "key_metrics": {
                "样本数": data.get("count"),
                "总和": data.get("sum"),
                "平均值": f"{data.get('avg', 0):.2f}",
                "最小值": data.get("min"),
                "最大值": data.get("max"),
                "中位数": data.get("median"),
                "标准差": f"{data.get('stdev', 0):.2f}",
            },
            "interpretation": "以上数据展示了数据集的基本统计特征。",
        }
    
    def _section_filtering(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """过滤部分"""
        median = data.get("median")
        count = len(data.get("filtered", []))
        ratio = data.get("filter_ratio", 0)
        
        return {
            "type": "filtering",
            "title": "数据过滤",
            "filter_threshold": median,
            "filtered_count": count,
            "filter_ratio": f"{ratio * 100:.1f}%",
            "interpretation": f"共 {count} 个数据点超过中位数 {median}。",
        }
    
    def _section_sorting(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """排序部分"""
        is_ascending = data.get("is_ascending", False)
        sorted_data = data.get("sorted", [])[:5]  # 只显示前5个
        
        return {
            "type": "sorting",
            "title": "数据排序",
            "order": "升序" if is_ascending else "非升序",
            "preview": sorted_data,
            "interpretation": "数据已按升序排列。",
        }
