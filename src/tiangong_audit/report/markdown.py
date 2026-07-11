from __future__ import annotations

from typing import Any

from .platform import build_platform_comment

LABELS = {
    "blocking": "阻断问题",
    "advisory": "建议修改",
    "manual_review": "需人工确认",
    "input_gap": "信息缺口",
}

def render_platform_return_opinion(result: dict[str, Any]) -> str:
    platform_comment = build_platform_comment(result)
    lines = ["## 平台退回意见", ""]
    lines.extend(platform_comment["opinion"].splitlines())
    return "\n".join(lines).rstrip() + "\n"


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
