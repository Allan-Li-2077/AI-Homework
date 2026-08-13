"""客服工具集（mock 数据，演示并行 subagent 各自处理不同子任务）

每个 subagent 实例化时挑 1~2 个工具，主 agent 用 dispatch_subagents 把
不同类的客户问题并行交给对应专长的子客服处理。

工具返回结构化文本，喂回 LLM 作为 Observation。
"""
import json, time, hashlib, logging
from typing import Optional

logger = logging.getLogger(__name__)

# ── 模拟数据库 ──────────────────────────────────────────────────────
_MOCK_ORDERS = {
    "A100001": {"user": "张三", "product": "无线蓝牙耳机", "qty": 1, "amount": 299.0,
                "status": "已签收", "logistics": "SF1234567", "paid_at": "2024-11-20 10:23"},
    "A100002": {"user": "李四", "product": "机械键盘", "qty": 2, "amount": 598.0,
                "status": "运输中", "logistics": "YT7654321", "paid_at": "2024-11-25 14:08"},
    "A100003": {"user": "王五", "product": "4K 显示器", "qty": 1, "amount": 1899.0,
                "status": "已发货", "logistics": "ZD9876543", "paid_at": "2024-11-28 09:15"},
    "A100004": {"user": "赵六", "product": "充电宝", "qty": 3, "amount": 237.0,
                "status": "待发货", "logistics": None, "paid_at": "2024-12-01 17:42"},
    "A100005": {"user": "孙七", "product": "智能手表", "qty": 1, "amount": 1299.0,
                "status": "已退款", "logistics": None, "paid_at": "2024-12-03 11:30"},
}

_MOCK_LOGISTICS = {
    "SF1234567": [{"t": "11-21 09:00", "loc": "深圳转运中心", "evt": "已揽收"},
                  {"t": "11-21 22:10", "loc": "广州分拨中心", "evt": "运输中"},
                  {"t": "11-22 14:35", "loc": "上海中转站", "evt": "运输中"},
                  {"t": "11-23 10:12", "loc": "上海浦东派送点", "evt": "派送中"},
                  {"t": "11-23 16:48", "loc": "用户签收", "evt": "已签收"}],
    "YT7654321": [{"t": "11-26 08:20", "loc": "杭州仓库", "evt": "已出库"},
                  {"t": "11-26 19:45", "loc": "杭州转运中心", "evt": "运输中"},
                  {"t": "11-27 10:30", "loc": "南京分拨中心", "evt": "运输中"}],
    "ZD9876543": [{"t": "11-29 07:15", "loc": "成都仓库", "evt": "已出库"},
                  {"t": "11-29 18:00", "loc": "成都转运中心", "evt": "运输中"}],
}

_MOCK_FAQ = {
    "退货政策": "7 天无理由退货（商品完好、附件齐全），15 天内质量问题可换货。"
               "内衣、食品、定制类商品不支持无理由退货。",
    "发票申请": "订单完成 7 天后可在「我的订单-发票」申请电子发票，"
               "支持企业抬头，1~3 个工作日开具到邮箱。",
    "会员等级": "V1 普通会员 / V2 银卡（年消费满 500）/ V3 金卡（满 3000）/ V4 钻石（满 10000），"
               "等级越高享越多折扣与优先客服。",
    "发票抬头修改": "发票开具前可修改抬头，开具后需红冲重开，请联系在线客服。",
    "保修期": "电子产品保修 1 年（凭订单号），配件 3 个月，软件服务不保修。",
    "配送范围": "中国大陆全境可送，港澳台需单独下单走跨境物流，部分偏远地区加 1~2 天。",
}


def query_order(order_id: str, **_) -> str:
    """查询订单详情：商品、金额、状态、物流单号、下单时间"""
    order = _MOCK_ORDERS.get(order_id)
    if not order:
        return f"未找到订单 {order_id}，请确认订单号是否正确（示例可用 A100001~A100005）"
    logistics = f"物流单号 {order['logistics']}" if order['logistics'] else "暂无物流单号"
    return (f"订单 {order_id}\n用户: {order['user']}\n商品: {order['product']} x{order['qty']}\n"
            f"金额: ¥{order['amount']}\n状态: {order['status']}\n{logistics}\n"
            f"下单时间: {order['paid_at']}")


def query_logistics(logistics_no: str, **_) -> str:
    """查询物流轨迹：返回最新 5 条物流轨迹"""
    track = _MOCK_LOGISTICS.get(logistics_no)
    if not track:
        return (f"未找到物流 {logistics_no}。提示：可从订单详情里拿到物流单号，"
                f"如 SF1234567 / YT7654321 / ZD9876543")
    lines = [f"[{t['t']}] {t['loc']} - {t['evt']}" for t in track[-5:]]
    return f"物流 {logistics_no} 轨迹（共 {len(track)} 条，显示最近 {len(lines)} 条）:\n" + "\n".join(lines)


def apply_refund(order_id: str, reason: str = "用户申请退款", **_) -> str:
    """发起退款申请，返回受理结果。校验订单存在与可退状态。"""
    order = _MOCK_ORDERS.get(order_id)
    if not order:
        return f"退款失败：订单 {order_id} 不存在"
    if order["status"] in ("已退款",):
        return f"订单 {order_id} 已退款，请勿重复申请"
    if order["status"] == "已签收":
        return (f"订单 {order_id} 已签收，需走 7 天无理由退货流程，"
                f"已生成退货工单 RFD-{order_id}，原因：{reason}，"
                f"请保持商品完好，快递员 24h 内上门取件。")
    # 其余状态直接受理
    ticket = "RFD-" + hashlib.md5((order_id + str(time.time())).encode()).hexdigest()[:6].upper()
    order["status"] = "退款审核中"
    return (f"订单 {order_id} 退款已受理，工单号 {ticket}，原因：{reason}。\n"
            f"退款金额 ¥{order['amount']}，1~3 个工作日原路退回。\n当前状态：退款审核中")


def query_faq(keyword: str, **_) -> str:
    """查询 FAQ 知识库，返回政策/规则说明。"""
    keyword = keyword.strip()
    # 直接匹配
    if keyword in _MOCK_FAQ:
        return f"【{keyword}】{_MOCK_FAQ[keyword]}"
    # 模糊匹配
    hits = [k for k in _MOCK_FAQ if keyword in k or k in keyword]
    if hits:
        return "\n".join(f"【{k}】{_MOCK_FAQ[k]}" for k in hits)
    return (f"未匹配到关键词「{keyword}」。可查: {list(_MOCK_FAQ.keys())}。"
            f"建议客户描述更具体，或升级人工。")


def escalate_human(summary: str, **_) -> str:
    """升级到人工客服（复杂/情绪/超权限问题）。返回工单号。"""
    ticket = "ES-" + hashlib.md5((summary + str(time.time())).encode()).hexdigest()[:6].upper()
    return (f"已升级人工客服，工单号 {ticket}。\n"
            f"问题摘要已记录：{summary[:120]}\n"
            f"预计 5 分钟内人工坐席接入，请客户保持会话。")


# ── subagent 工具集打包：每类专长一个工具集 ────────────────────────
# 主 agent dispatch_subagents 时按需实例化对应专长的 subagent
SUBAGENT_TOOLSETS = {
    "order": {
        "query_order": (query_order, "查询订单详情，参数=订单号（如 A100001）"),
        "query_logistics": (query_logistics, "查询物流轨迹，参数=物流单号"),
    },
    "after_sale": {
        "apply_refund": (apply_refund, "发起退款，参数格式：订单号|退款原因"),
        "query_order": (query_order, "查询订单详情，参数=订单号"),
    },
    "faq": {
        "query_faq": (query_faq, "查询政策/规则，参数=关键词（如 退货政策）"),
    },
    "escalation": {
        "escalate_human": (escalate_human, "升级人工，参数=问题摘要"),
    },
}


def get_toolset(name: str) -> dict:
    """按专长名取 subagent 工具集。未知时返回 faq 集作兜底。"""
    return SUBAGENT_TOOLSETS.get(name, SUBAGENT_TOOLSETS["faq"])


if __name__ == "__main__":
    print(query_order("A100002"))
    print("---")
    print(query_logistics("YT7654321"))
    print("---")
    print(apply_refund("A100003", "商品质量问题"))
    print("---")
    print(query_faq("退货政策"))
    print("---")
    print(escalate_human("客户投诉退款未到账"))
