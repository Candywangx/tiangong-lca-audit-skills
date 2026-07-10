"""Data-driven, case-derived deterministic guardrails.

These checks originated from concrete correction cases (see ``origin_case`` on
each entry). They are intentionally kept out of the universal deterministic
engine: their patterns are narrow, so they live in
``skill/tiangong-lca-audit/rules/guardrails.json`` where a new correction can
be added as data plus an eval case, without touching engine code.
"""

from __future__ import annotations

import json
from pathlib import Path
import re
from typing import Any

from .engine import (
    _all_exchanges,
    _combined_language_text,
    _combined_section_text,
    _exchange_label,
    _exchange_text,
    _finding,
)

GUARDRAILS_SCHEMA_VERSION = "1.0"
VALID_GUARDRAIL_TYPES = (
    "context_expected_inventory",
    "bilingual_term_mismatch",
    "purchased_elementary_input_role",
)


class GuardrailError(ValueError):
    """Raised when the guardrail catalog is structurally invalid."""


def load_skill_guardrails(root: Path) -> dict[str, Any] | None:
    """Load the skill guardrail catalog under a project root, if it exists."""

    path = Path(root) / "skill/tiangong-lca-audit/rules/guardrails.json"
    if not path.exists():
        return None
    return load_guardrails(path)


def load_guardrails(path: Path) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    errors = validate_guardrails(payload)
    if errors:
        raise GuardrailError("; ".join(errors))
    return payload


def validate_guardrails(payload: Any) -> list[str]:
    errors: list[str] = []
    if not isinstance(payload, dict):
        return ["guardrail catalog must be a JSON object"]
    if payload.get("schema_version") != GUARDRAILS_SCHEMA_VERSION:
        errors.append(f"schema_version must be {GUARDRAILS_SCHEMA_VERSION}")
    entries = payload.get("guardrails")
    if not isinstance(entries, list):
        return errors + ["guardrails must be a list"]
    seen_ids: set[str] = set()
    for index, entry in enumerate(entries, 1):
        label = f"guardrails[{index}]"
        if not isinstance(entry, dict):
            errors.append(f"{label} must be an object")
            continue
        entry_id = str(entry.get("id") or "")
        if not entry_id:
            errors.append(f"{label}: id is required")
        if entry_id in seen_ids:
            errors.append(f"{label}: duplicate id {entry_id}")
        seen_ids.add(entry_id)
        for key in ("rule_id", "origin_case"):
            if not str(entry.get(key) or ""):
                errors.append(f"{label}: {key} is required")
        guardrail_type = str(entry.get("type") or "")
        if guardrail_type not in VALID_GUARDRAIL_TYPES:
            errors.append(
                f"{label}: type must be one of {', '.join(VALID_GUARDRAIL_TYPES)}"
            )
            continue
        if guardrail_type == "context_expected_inventory":
            groups = entry.get("groups")
            if not isinstance(groups, list) or not groups:
                errors.append(f"{label}: groups must be a non-empty list")
                continue
            for group in groups:
                if not isinstance(group, dict) or not all(
                    str(group.get(key) or "")
                    for key in ("label", "context_pattern", "inventory_pattern")
                ):
                    errors.append(
                        f"{label}: each group requires label, context_pattern, inventory_pattern"
                    )
        elif guardrail_type == "bilingual_term_mismatch":
            pairs = entry.get("pairs")
            if not isinstance(pairs, list) or not pairs:
                errors.append(f"{label}: pairs must be a non-empty list")
                continue
            for pair in pairs:
                if not isinstance(pair, dict) or not all(
                    str(pair.get(key) or "")
                    for key in ("zh_pattern", "en_pattern", "zh_label", "en_label")
                ):
                    errors.append(
                        f"{label}: each pair requires zh_pattern, en_pattern, zh_label, en_label"
                    )
        elif guardrail_type == "purchased_elementary_input_role":
            patterns = entry.get("material_patterns")
            if not isinstance(patterns, list) or not patterns:
                errors.append(f"{label}: material_patterns must be a non-empty list")
    return errors


def guardrail_rule_ids(payload: dict[str, Any]) -> set[str]:
    return {
        str(entry.get("rule_id") or "")
        for entry in payload.get("guardrails", [])
        if isinstance(entry, dict) and entry.get("rule_id")
    }


def run_guardrails(dataset: dict[str, Any], payload: dict[str, Any]) -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []
    for entry in payload.get("guardrails", []):
        if not isinstance(entry, dict):
            continue
        guardrail_type = str(entry.get("type") or "")
        if guardrail_type == "context_expected_inventory":
            findings.extend(_run_context_expected_inventory(dataset, entry))
        elif guardrail_type == "bilingual_term_mismatch":
            findings.extend(_run_bilingual_term_mismatch(dataset, entry))
        elif guardrail_type == "purchased_elementary_input_role":
            findings.extend(_run_purchased_elementary_input_role(dataset, entry))
    return findings


def _run_context_expected_inventory(
    dataset: dict[str, Any], entry: dict[str, Any]
) -> list[dict[str, str]]:
    context = _combined_section_text(dataset, "过程信息", "建模信息")
    inventory_text = "\n".join(_exchange_text(exchange) for exchange in _all_exchanges(dataset))
    missing = []
    for group in entry.get("groups", []):
        if re.search(str(group["context_pattern"]), context, re.IGNORECASE) and not re.search(
            str(group["inventory_pattern"]), inventory_text, re.IGNORECASE
        ):
            missing.append(str(group["label"]))
    if not missing:
        return []
    return [
        _finding(
            str(entry["rule_id"]),
            str(entry.get("severity") or "manual_review"),
            "过程信息 / 技术描述及背景系统 ↔ 输入/输出",
            f"技术或边界描述提到 {'、'.join(missing)}，但清单中未识别到对应交换或处理说明。",
            "关键投入、设施、处理过程或损失未在清单中对应时，审核员无法判断边界和清单是否一致。",
            f"补充 {'、'.join(missing)} 对应的交换，或说明其低于截断、已聚合表示或不属于本数据集边界。",
        )
    ]


def _run_bilingual_term_mismatch(
    dataset: dict[str, Any], entry: dict[str, Any]
) -> list[dict[str, str]]:
    zh_text = _combined_language_text(dataset, "zh")
    en_text = _combined_language_text(dataset, "en")
    for pair in entry.get("pairs", []):
        if re.search(str(pair["zh_pattern"]), zh_text) and re.search(
            str(pair["en_pattern"]), en_text, re.IGNORECASE
        ):
            zh_label = str(pair["zh_label"])
            en_label = str(pair["en_label"])
            return [
                _finding(
                    str(entry["rule_id"]),
                    str(entry.get("severity") or "blocking"),
                    "中英文名称、一般性说明或输出流",
                    f"中文对象或输出包含“{zh_label}”，英文说明出现 {en_label}。",
                    "中英文表达指向不同产品形态或对象，会影响复用和检索。",
                    str(
                        pair.get("suggestion")
                        or "统一中英文产品形态表述，使其与实际产品一致。"
                    ),
                )
            ]
    return []


def _run_purchased_elementary_input_role(
    dataset: dict[str, Any], entry: dict[str, Any]
) -> list[dict[str, str]]:
    context = _combined_section_text(dataset, "过程信息", "建模信息")
    if re.search(
        r"不代表外购|不是外购|非外购|not\s+purchased|does\s+not\s+represent\s+purchased",
        context,
        re.IGNORECASE,
    ):
        return []
    if not re.search(
        r"外购|采购|购买|投入品|原料|辅料|消耗品|purchased|procured|input material|auxiliary",
        context,
        re.IGNORECASE,
    ):
        return []

    material_patterns = [str(pattern) for pattern in entry.get("material_patterns", [])]
    findings = []
    for exchange in dataset["exchanges"]["inputs"]:
        flow_type = str(exchange.get("flow_type") or "")
        if not re.search(r"Elementary flow|基本流|elementary", flow_type, re.IGNORECASE):
            continue
        label_text = _exchange_text(exchange)
        matched_pattern = next(
            (
                pattern
                for pattern in material_patterns
                if re.search(pattern, label_text, re.IGNORECASE)
            ),
            None,
        )
        if not matched_pattern or not re.search(matched_pattern, context, re.IGNORECASE):
            continue
        severity = (
            "blocking"
            if re.search(r"外购|采购|购买|purchased|procured", context, re.IGNORECASE)
            else "manual_review"
        )
        findings.append(
            _finding(
                str(entry["rule_id"]),
                severity,
                f"输入/输出 / {_exchange_label(exchange)}",
                f"该输入流类型为 {flow_type}；过程说明将其描述为外购或工艺投入品。",
                "外购投入品通常应作为产品流连接背景过程；若作为基本流，会把技术圈输入误作环境资源交换。",
                "改选或新增匹配的产品流；若确为环境交换，补充说明其来自空气、水体或地质环境而非外购物料。",
            )
        )
    return findings
