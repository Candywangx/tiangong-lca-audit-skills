from __future__ import annotations

import re
from typing import Any

LABELS = {
    "blocking": "阻断问题",
    "advisory": "建议修改",
    "manual_review": "需人工确认",
    "input_gap": "信息缺口",
}

CIRCLED_NUMBERS = "①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳"
PLATFORM_LABELS = {
    "blocking": "【需修改】",
    "input_gap": "【需补充】",
    "manual_review": "【需确认】",
    "advisory": "【建议优化】",
}
MAX_PLATFORM_OPINION_LENGTH = 1000


def _finding_ref_key(ref: Any) -> tuple[str, str]:
    if not isinstance(ref, dict) or not all(
        isinstance(ref.get(key), str) and ref[key].strip() for key in ("path", "pointer")
    ):
        raise ValueError("finding_refs require nonblank path and pointer")
    return ref["path"], ref["pointer"]


def _platform_severity(item: dict[str, Any]) -> str:
    severity = item.get("severity")
    if not isinstance(severity, str) or severity not in PLATFORM_LABELS:
        raise ValueError(f"Invalid platform opinion severity: {severity!r}")
    return severity


def _has_actionable_content(item: dict[str, Any]) -> bool:
    return item.get("platform_actionable") is not False and all(
        isinstance(item.get(key), str) and item[key].strip()
        for key in ("location", "evidence", "judgment", "suggestion")
    )


def _fallback_opinion(item: dict[str, Any]) -> str:
    sentences = []
    for key in ("evidence", "judgment", "suggestion"):
        value = str(item.get(key) or "").strip()
        if value:
            sentences.append(value if value[-1] in "。！？.!?" else value + "。")
    return str(item.get("location") or "审核发现").strip() + "：" + " ".join(sentences)


def _platform_items(result: dict[str, Any]) -> list[tuple[str, str]]:
    findings = result["findings"]
    indexed = {}
    for finding in findings:
        _platform_severity(finding)
        if finding.get("finding_ref") is not None:
            key = _finding_ref_key(finding["finding_ref"])
            if key in indexed and indexed[key] != finding:
                raise ValueError(f"Conflicting findings share a finding_ref: {key!r}")
            indexed[key] = finding

    authored = result.get("platform_opinions", [])
    if not isinstance(authored, list):
        raise ValueError("platform_opinions must be a list")
    covered = set()
    items = []
    for opinion in authored:
        if not isinstance(opinion, dict):
            raise ValueError("platform opinion must be an object")
        severity = _platform_severity(opinion)
        text = opinion.get("text")
        if not isinstance(text, str) or not text.strip():
            raise ValueError("platform opinion text must be nonblank")
        text = text.strip()
        if text[0] in CIRCLED_NUMBERS or re.match(r"^[0-9]+\.(?![0-9])", text):
            raise ValueError("platform opinion text must not include a leading number")
        if any(tag in text for tag in PLATFORM_LABELS.values()):
            raise ValueError("platform opinion text must not include a public severity tag")
        refs = opinion.get("finding_refs")
        if not isinstance(refs, list) or not refs:
            raise ValueError("platform opinion requires finding_refs")
        for ref in refs:
            key = _finding_ref_key(ref)
            finding = indexed.get(key)
            if finding is None:
                raise ValueError(f"Unknown platform opinion finding_ref: {key!r}")
            if finding["severity"] != severity:
                raise ValueError(f"Platform opinion severity differs from finding_ref: {key!r}")
            if not _has_actionable_content(finding):
                raise ValueError(f"Finding is not actionable for the submitter: {key!r}")
            covered.add(key)
        items.append((severity, text.strip()))

    for finding in findings:
        ref = finding.get("finding_ref")
        if ref is not None and _finding_ref_key(ref) in covered:
            continue
        severity = finding["severity"]
        if severity != "blocking":
            if not _has_actionable_content(finding):
                continue
            if severity != "advisory" and finding.get("platform_actionable") is not True:
                continue
        # An authored subset can never silently remove an uncovered blocker.
        items.append((severity, _fallback_opinion(finding)))

    rank = {severity: index for index, severity in enumerate(PLATFORM_LABELS)}
    return sorted(dict.fromkeys(items), key=lambda item: rank[item[0]])


def _platform_number(index: int) -> str:
    if 1 <= index <= len(CIRCLED_NUMBERS):
        return CIRCLED_NUMBERS[index - 1]
    return f"{index}."


def render_platform_return_opinion(result: dict[str, Any]) -> str:
    actionable = _platform_items(result)
    lines = ["## 平台退回意见", ""]
    if not actionable:
        lines.append("无")
    else:
        for index, (severity, text) in enumerate(actionable, 1):
            lines.append(f"{_platform_number(index)}{PLATFORM_LABELS[severity]}{text}")
            lines.append("")
    rendered = "\n".join(lines).rstrip() + "\n"
    if len(rendered) > MAX_PLATFORM_OPINION_LENGTH:
        raise ValueError(
            f"平台退回意见不得超过 {MAX_PLATFORM_OPINION_LENGTH} 字（含标题、编号、标识和换行）；"
            "请合并同根问题并精简文字，保留全部已验证阻断问题。"
        )
    return rendered


def render_findings(result: dict[str, Any]) -> str:
    identity = result["dataset"]
    name = identity["name"].get("zh") or identity["name"].get("en") or identity["name"].get("raw")
    lines = [
        "# 自动规则预检结果",
        "",
        f"- 数据集类型：{result['dataset_type']}",
        f"- 数据集名称：{name or '未识别'}",
        f"- 数据集 ID / 版本：{identity.get('id') or '-'} / {identity.get('version') or '-'}",
        f"- 预检结论：{result['conclusion']}",
        f"- 引擎范围：{result['engine_scope']}",
        "",
        "> 本结果仅包含可程序化执行的保守预检；分类合理性、过程边界和关键流完整性仍需 Agent 或人工审核。",
        "",
    ]
    for severity in ("blocking", "advisory", "manual_review", "input_gap"):
        findings = [item for item in result["findings"] if item["severity"] == severity]
        if not findings:
            continue
        lines.extend([f"## {LABELS[severity]}", ""])
        for index, item in enumerate(findings, 1):
            lines.extend(
                [
                    f"{index}. **位置**：{item['location']}",
                    f"   **证据**：{item['evidence']}",
                    f"   **判断**：{item['judgment']}",
                    f"   **建议**：{item['suggestion']}",
                    f"   **规则**：`{item['rule_id']}`",
                    "",
                ]
            )
    lines.extend(["", render_platform_return_opinion(result).rstrip()])
    return "\n".join(lines).rstrip() + "\n"
