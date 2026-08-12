"""翻译结果统一对外文案。"""

from __future__ import annotations

from src.sub_agents.translate.parse import LANGS, UNSUPPORTED_MSG


def _mode_line(result: dict) -> str:
    mode = result.get("mode") or (result.get("metrics") or {}).get("mode") or ""
    if mode == "serial":
        return "串行模式"
    if mode == "parallel":
        return "并行模式"
    if result.get("parallel") is True:
        return "并行模式"
    if result.get("parallel") is False:
        return "串行模式"
    return ""


def _metrics_line(result: dict) -> str:
    metrics = result.get("metrics") or {}
    parts: list[str] = []
    if metrics.get("elapsed_s") is not None:
        parts.append(f"用时 {metrics['elapsed_s']}s")
    if metrics.get("total_tokens") is not None:
        parts.append(f"Token {metrics['total_tokens']}")
    return "，".join(parts)


def format_translation_reply(result: dict) -> str:
    """
    统一返回格式：

    并行模式

    英文：
    Hello

    日文：
    こんにちは

    用时 12.212s，Token 3319

    不支持语种（且无成功译文）：
      抱歉，不支持翻译该种语言
    """
    if result.get("error") == UNSUPPORTED_MSG and not result.get("translations"):
        return UNSUPPORTED_MSG

    targets = result.get("targets") or []
    translations = result.get("translations") or {}
    if not targets and result.get("unsupported"):
        return UNSUPPORTED_MSG

    blocks: list[str] = []
    for code in targets:
        item = translations.get(code)
        label = LANGS.get(code, (code, ""))[0]
        text = ""
        if isinstance(item, dict):
            label = item.get("label") or label
            text = (item.get("text") or item.get("error") or "").strip()
        elif item is not None:
            text = str(item).strip()
        if not text and isinstance(item, dict) and item.get("error"):
            text = str(item["error"]).strip()
        blocks.append(f"{label}：\n{text}")

    if blocks:
        parts: list[str] = []
        mode = _mode_line(result)
        if mode:
            parts.append(mode)
        parts.append("\n\n".join(blocks))
        if result.get("unsupported") or result.get("unsupported_message"):
            parts.append(UNSUPPORTED_MSG)
        metrics = _metrics_line(result)
        if metrics:
            parts.append(metrics)
        return "\n\n".join(parts)

    if result.get("error") == UNSUPPORTED_MSG or result.get("unsupported"):
        return UNSUPPORTED_MSG

    err = (result.get("error") or "").strip()
    return err or UNSUPPORTED_MSG
