"""Route evidence findings into a submitter-facing platform comment."""

from __future__ import annotations

from typing import Any

from tiangong_audit.contracts.platform import (
    PLATFORM_ORIGINS,
    PlatformProjection,
    is_internal_blocking_origin,
    validate_platform_projection,
)

_DISPOSITION_PRIORITY = {"required": 0, "clarification": 1, "suggested": 2}
_DISPOSITION_LABEL = {
    "required": "【需修改】",
    "clarification": "【请补充】",
    "suggested": "【建议】",
}
_CIRCLED_NUMBERS = "①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳"
_TERMINAL_PUNCTUATION = "。！？!?；;."


def normalize_platform_conclusion(value: object) -> str:
    """Normalize every supported audit/platform conclusion into one shared kind."""

    if not isinstance(value, str):
        raise ValueError("conclusion must be a string")
    conclusion = value.strip().lower().replace("-", "_").replace(" ", "_")
    aliases = {
        "approved": "approved",
        "pass": "approved",
        "passed": "approved",
        "通过": "approved",
        "预检通过": "approved",
        "rejected": "rejected",
        "reject": "rejected",
        "fail": "rejected",
        "failed": "rejected",
        "不通过": "rejected",
        "预检不通过": "rejected",
        "manual_review": "manual_review",
        "needs_manual_review": "manual_review",
        "需人工确认": "manual_review",
        "需人工审核": "manual_review",
        "预检需人工确认": "manual_review",
        "information_insufficient": "information_insufficient",
        "insufficient_information": "information_insufficient",
        "信息不足": "information_insufficient",
        "预检信息不足": "information_insufficient",
    }
    try:
        return aliases[conclusion]
    except KeyError as exc:
        raise ValueError(f"unknown platform conclusion {value!r}") from exc


def _legacy_message(item: dict[str, Any]) -> str:
    location = str(item.get("location") or item.get("related_field") or "相关字段")
    evidence = str(item.get("evidence") or item.get("title") or "存在需要修改的问题。")
    judgment = str(item.get("judgment") or item.get("description") or "")
    suggestion = str(item.get("suggestion") or item.get("suggested_fix") or "请补充或修正。")
    evidence = _ensure_terminal(evidence, "；")
    judgment = _ensure_terminal(judgment, "。") if judgment else ""
    suggestion = _ensure_terminal(suggestion, "。")
    return f"{location} 中，{evidence}{judgment}建议：{suggestion}"


def _ensure_terminal(text: str, default: str) -> str:
    text = text.strip()
    return text if text.endswith(tuple(_TERMINAL_PUNCTUATION)) else text + default


def _safe_routed_finding(
    item: dict[str, Any], projection: PlatformProjection
) -> dict[str, Any]:
    rule_id = str(item.get("rule_id") or "")
    label = _DISPOSITION_LABEL[projection.disposition]
    return {
        "id": str(item.get("id") or rule_id or "finding"),
        "severity": item["severity"],
        "disposition": projection.disposition,
        "title": f"{label}{projection.message}",
        "description": projection.message,
        "evidence": "",
        "suggested_fix": projection.message,
        "related_field": "",
        "tags": [projection.disposition],
    }


def _number(index: int) -> str:
    if 1 <= index <= len(_CIRCLED_NUMBERS):
        return _CIRCLED_NUMBERS[index - 1]
    return f"{index}."


def _render_opinion(findings: list[dict[str, Any]]) -> str:
    if not findings:
        return "无"
    lines = [
        f"{_number(index)}{_DISPOSITION_LABEL[item['disposition']]}{item['description']}"
        for index, item in enumerate(findings, 1)
    ]
    if any(item["disposition"] == "suggested" for item in findings):
        lines.append("以上【建议】项用于改善数据说明，不作为本轮审核通过的前置条件。")
    return "\n".join(lines)


def build_platform_comment(result: dict[str, Any]) -> dict[str, Any]:
    """Build and validate the safe platform projection for one audit result."""

    errors: list[str] = []
    routed: list[tuple[int, dict[str, Any]]] = []
    findings = result.get("findings")
    if not isinstance(findings, list):
        findings = []
        errors.append("findings must be a list")

    raw_conclusion = result.get("conclusion")
    try:
        conclusion = normalize_platform_conclusion(raw_conclusion)
    except ValueError as exc:
        errors.append(str(exc))
        conclusion = "invalid"

    for index, raw_item in enumerate(findings):
        if not isinstance(raw_item, dict):
            errors.append(f"findings[{index}] must be an object")
            continue
        item = raw_item
        row_invalid = False
        raw_origin = item.get("origin")
        origin_provided = raw_origin is not None
        if raw_origin is None:
            origin = ""
        elif not isinstance(raw_origin, str):
            errors.append(f"findings[{index}] origin must be a string")
            origin = ""
            row_invalid = True
        else:
            origin = raw_origin
        if origin_provided and isinstance(raw_origin, str) and origin not in PLATFORM_ORIGINS:
            errors.append(f"findings[{index}] has unknown controlled origin {origin!r}")
            row_invalid = True
        elif origin and is_internal_blocking_origin(origin):
            errors.append(
                f"findings[{index}] from internal origin {origin!r} blocks platform drafting"
            )
            row_invalid = True

        raw_severity = item.get("severity")
        if not isinstance(raw_severity, str):
            errors.append(f"findings[{index}] severity must be a string")
            severity = ""
            row_invalid = True
        else:
            severity = raw_severity
        raw_projection = item.get("platform")
        if raw_projection is None:
            projection = PlatformProjection(
                disposition="required" if severity == "blocking" else "internal_only",
                message=_legacy_message(item) if severity == "blocking" else "",
            )
        else:
            try:
                projection = (
                    raw_projection
                    if isinstance(raw_projection, PlatformProjection)
                    else PlatformProjection.from_dict(raw_projection)
                )
            except ValueError as exc:
                errors.append(f"findings[{index}] platform: {exc}")
                projection = None
                row_invalid = True

        if projection is not None and severity:
            projection_errors = validate_platform_projection(severity, projection)
            if projection_errors:
                errors.extend(f"findings[{index}] {error}" for error in projection_errors)
                row_invalid = True
        if row_invalid or projection is None:
            continue
        if projection.disposition == "internal_only":
            continue
        routed.append((index, _safe_routed_finding(item, projection)))

    routed.sort(key=lambda pair: (_DISPOSITION_PRIORITY[pair[1]["disposition"]], pair[0]))
    routed_findings = [item for _, item in routed]
    if conclusion == "approved":
        if any(item["disposition"] in {"required", "clarification"} for item in routed_findings):
            errors.append("approved result cannot contain required or clarification items")
        routed_findings = []
    elif conclusion == "rejected":
        if not any(item["disposition"] == "required" for item in routed_findings):
            errors.append("rejected result requires at least one required platform item")
    elif conclusion in {"manual_review", "information_insufficient"}:
        if not any(item["disposition"] == "clarification" for item in routed_findings):
            errors.append(
                f"{conclusion} result requires at least one clarification platform item"
            )

    return {
        "valid": not errors,
        "validation_errors": errors,
        "opinion": _render_opinion(routed_findings),
        "findings": routed_findings,
    }
