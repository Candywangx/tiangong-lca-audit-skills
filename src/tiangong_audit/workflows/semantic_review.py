from __future__ import annotations

from collections import Counter
from copy import deepcopy
import hashlib
import json
from pathlib import Path
from typing import Any

from tiangong_audit.case_store import CaseStore
from tiangong_audit.contracts.agent_review import (
    required_rule_ids,
    uncovered_required_rule_ids,
    validate_agent_findings,
)
from tiangong_audit.contracts.platform import (
    PlatformProjection,
    validate_platform_projection,
)
from tiangong_audit.contracts.source import (
    SOURCE_CHECK_STATUS_POLICY,
    SourceCheck,
    SourceRef,
    validate_source_checks,
)
from tiangong_audit.report.markdown import render_platform_return_opinion
from tiangong_audit.report.platform import build_platform_comment


SEMANTIC_REVIEW_SCHEMA_VERSION = "tiangong-audit-semantic-review-v1"
SEMANTIC_CONTEXT_SCHEMA_VERSION = "tiangong-audit-semantic-context-v1"
PLATFORM_RESULT_SCHEMA_VERSION = "tiangong-audit-platform-result-v1"
MAX_CONTEXT_TEXT_CHARS = 50_000
AGENT_FINDINGS_RELATIVE_PATH = "agent-review/agent-findings.json"
# Claims whose semantic facts must be source-verified before the source layer
# can support an approval; anything else may legitimately stay unmatched.
CORE_CLAIM_PREFIXES = (
    "process.name",
    "dataset.name",
    "process.reference_flow",
    "reference_flow.",
    "process.time",
    "process.geography",
    "process.route",
    "process.technology",
    "process.production_volume",
)
_CONCLUSION_RANK = {"通过": 0, "需人工确认": 1, "信息不足": 2, "不通过": 3}
_SOURCE_LAYER_FLOOR = {
    "不一致": "不通过",
    "证据不足": "信息不足",
    "需人工确认": "需人工确认",
    "未完全证实": "需人工确认",
    "未核验": "需人工确认",
    "基本一致，有建议补充": "通过",
    "一致": "通过",
}
_RULE_LAYER_FLOOR = {
    "不符合规则": "不通过",
    "规则证据不足": "信息不足",
    "需人工确认": "需人工确认",
    "基本符合规则，有建议修改": "通过",
    "符合规则": "通过",
}

COMMON_REFERENCE_FILES = (
    "skill/tiangong-lca-audit/SKILL.md",
    "skill/tiangong-lca-audit/references/input-contract.md",
    "skill/tiangong-lca-audit/references/audit-policy.md",
    "skill/tiangong-lca-audit/references/output-contract.md",
)
DATASET_REFERENCE_FILES = {
    "process": ("skill/tiangong-lca-audit/references/process-audit.md",),
    "model": ("skill/tiangong-lca-audit/references/model-audit.md",),
}
COMMON_RULE_FILES = ("skill/tiangong-lca-audit/rules/common.json",)
DATASET_RULE_FILES = {
    "process": ("skill/tiangong-lca-audit/rules/process.json",),
    "model": ("skill/tiangong-lca-audit/rules/model.json",),
}
SEVERITIES = ("blocking", "advisory", "manual_review", "input_gap")
LABELS = {
    "blocking": "阻断问题",
    "advisory": "建议修改",
    "manual_review": "需人工确认",
    "input_gap": "信息缺口",
}


def semantic_review(
    review_id: str,
    *,
    root: Path,
    batch_id: str | None = None,
    case_store: CaseStore | None = None,
) -> dict[str, Any]:
    """Synthesize a full audit report from Skill references, precheck, and source checks."""

    root = Path(root)
    store = case_store or CaseStore(root / "cases")
    manifest = store.get_case(review_id, batch_id=batch_id)
    case_root = root / "cases" / manifest.case_dir
    reports_dir = case_root / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)

    first_precheck = _read_optional_json(case_root / "precheck" / "precheck.json", default={})
    dataset_type = manifest.dataset_type or str(first_precheck.get("dataset_type") or "")
    context = build_semantic_context(
        root=root,
        case_root=case_root,
        manifest=manifest,
        dataset_type=dataset_type,
    )
    precheck = context["precheck"]
    source_checks = context["source_checks"]
    source_artifacts = context["source_artifacts"]
    source_documents = context["source_documents"]
    claims = context["claims"] if isinstance(context["claims"], dict) else {}
    agent_review = context["agent_review"]
    references_used = _reference_manifest_from_bundle(context["references"])
    rules_used = _rule_manifest_from_bundle(context["rules"])
    deterministic_findings = [
        _normalize_precheck_finding(item)
        for item in precheck.get("findings", [])
        if isinstance(item, dict)
    ]
    agent_findings, agent_review_summary, deterministic_findings = _agent_review_findings(
        agent_review,
        agent_review_present=context["agent_review_present"],
        dataset_type=dataset_type,
        deterministic_findings=deterministic_findings,
        case_root=case_root,
    )
    findings = deterministic_findings
    findings.extend(agent_findings)
    findings.extend(_source_findings(source_checks, source_artifacts, source_documents))
    findings.extend(
        _source_quality_findings(
            claims=claims,
            source_checks=source_checks,
            source_documents=source_documents,
            agent_review=agent_review,
        )
    )
    findings.extend(
        _input_gap_findings(
            case_root,
            precheck,
            source_checks,
            dataset_type,
            source_check_validation_errors=context["source_check_validation_errors"],
        )
    )
    findings.extend(_semantic_context_findings(context))

    summary = _summary(findings)
    source_summary = _source_summary(source_checks, source_artifacts, source_documents)
    source_consistency = _source_consistency_review(
        source_checks,
        source_artifacts,
        source_documents,
    )
    rule_compliance = _rule_compliance_review(findings)
    audit_completeness = _audit_completeness(
        agent_review_summary=agent_review_summary,
        source_checks=source_checks,
        source_check_validation_errors=context["source_check_validation_errors"],
    )
    conclusion = _reconcile_conclusion(
        _conclusion(summary),
        source_consistency=source_consistency,
        rule_compliance=rule_compliance,
        audit_completeness=audit_completeness,
    )
    platform_conclusion = _platform_conclusion(conclusion)
    dataset = _dataset_identity(manifest, precheck)
    limitations = _source_limitations(source_checks, source_artifacts)
    context_summary = _semantic_context_summary(context)

    result = {
        "schema_version": SEMANTIC_REVIEW_SCHEMA_VERSION,
        "review_task_id": manifest.review_id,
        "dataset_id": manifest.dataset_id,
        "version": manifest.version,
        "dataset_type": dataset_type or "unknown",
        "dataset": dataset,
        "audit_scope": "full-lca-semantic-review",
        "input_sufficiency": _input_sufficiency(summary),
        "conclusion": conclusion,
        "platform_conclusion": platform_conclusion,
        "summary": summary,
        "source_consistency": source_consistency,
        "rule_compliance": rule_compliance,
        "agent_review": agent_review_summary,
        "audit_completeness": audit_completeness,
        "source_summary": source_summary,
        "source_limitations": limitations,
        "semantic_context_summary": context_summary,
        "references_used": references_used,
        "rules_used": rules_used,
        "findings": findings,
        "report_note": (
            "本报告由 semantic-review 阶段根据 Skill references、rules、程序预检、"
            "Agent 规则复核（agent-review/agent-findings.json）、source 文档抽取文本、"
            "source-checks 和本地 case 证据生成；平台写回草稿前仍需审核员确认。"
        ),
    }
    platform_result = _platform_result(result)
    markdown = render_semantic_review(result)

    context_json = reports_dir / "semantic-context.json"
    semantic_json = reports_dir / "semantic-review.json"
    semantic_md = reports_dir / "semantic-review.md"
    platform_json = reports_dir / "audit-result.platform.json"
    _write_json(context_json, context)
    _write_json(semantic_json, result)
    semantic_md.write_text(markdown, encoding="utf-8")
    _write_json(platform_json, platform_result)

    audit_inputs_complete = bool(audit_completeness.get("complete"))
    if not _has_platform_write(manifest) and audit_inputs_complete:
        manifest.status = "reported"
    manifest.conclusion = platform_conclusion
    manifest.report = _case_path_label(platform_json, root)
    manifest.set_step("semantic_reviewed", True)
    manifest.set_step("agent_reviewed", bool(agent_review_summary.get("valid")))
    manifest.set_step("reported", audit_inputs_complete)
    manifest.artifacts["semantic_context"] = _case_path_label(context_json, root)
    manifest.artifacts["semantic_review"] = _case_path_label(semantic_json, root)
    manifest.artifacts["semantic_review_markdown"] = _case_path_label(semantic_md, root)
    manifest.artifacts["audit_result_platform"] = _case_path_label(platform_json, root)
    store.write_case(manifest)

    return {
        "review_id": manifest.review_id,
        "batch_id": manifest.batch_id,
        "case_dir": manifest.case_dir,
        "dataset_id": manifest.dataset_id,
        "dataset_type": dataset_type or "unknown",
        "conclusion": conclusion,
        "platform_conclusion": platform_conclusion,
        "summary": summary,
        "source_consistency": source_consistency,
        "rule_compliance": rule_compliance,
        "agent_review": agent_review_summary,
        "audit_completeness": audit_completeness,
        "source_summary": source_summary,
        "outputs": {
            "semantic_context": _case_path_label(context_json, root),
            "semantic_review": _case_path_label(semantic_json, root),
            "semantic_review_markdown": _case_path_label(semantic_md, root),
            "audit_result_platform": _case_path_label(platform_json, root),
        },
    }


def render_semantic_review(result: dict[str, Any]) -> str:
    dataset = result["dataset"]
    context_summary = result.get("semantic_context_summary") or {}
    lines = [
        "# LCA 语义审核报告",
        "",
        "## 证据型报告",
        "",
        f"- 审核范围：{result['audit_scope']}",
        f"- 数据集类型：{result['dataset_type']}",
        f"- 数据集名称：{dataset.get('name_zh') or dataset.get('name_en') or '-'}",
        f"- 数据集 ID / 版本：{result['dataset_id'] or '-'} / {result['version'] or '-'}",
        f"- 输入充分性：{result['input_sufficiency']}",
        f"- 审核结论：{result['conclusion']}",
        f"- Skill references：{context_summary.get('reference_count', 0)} 份",
        f"- 机器规则：{context_summary.get('rule_count', 0)} 条",
        f"- Source 抽取文本：{context_summary.get('source_document_count', 0)} 份",
        "",
        "## 两层结论",
        "",
        f"- 第一层 PDF/source 一致性：{result['source_consistency']['conclusion']}",
        f"  - {result['source_consistency']['reason']}",
        f"- 第二层规则符合性：{result['rule_compliance']['conclusion']}",
        f"  - {result['rule_compliance']['reason']}",
        f"- 综合结论：{result['conclusion']}",
        "",
        "### Agent 规则复核",
        "",
        f"- 复核文件：{result['agent_review'].get('path') or AGENT_FINDINGS_RELATIVE_PATH}",
        f"- 是否存在 / 是否通过契约校验：{result['agent_review'].get('present')} / {result['agent_review'].get('valid')}",
        f"- 必审规则覆盖：{result['agent_review'].get('required_covered', 0)} / {result['agent_review'].get('required_total', 0)}",
        f"- 结论分布：{json.dumps(result['agent_review'].get('verdict_counts', {}), ensure_ascii=False, sort_keys=True)}",
        f"- 审核输入完整性：{'完整' if result['audit_completeness'].get('complete') else '不完整：' + '、'.join(result['audit_completeness'].get('missing', []))}",
        "",
        "### Source 核验范围",
        "",
        f"- Source 文件数：{result['source_summary'].get('artifact_count', 0)}",
        f"- 字段核验数：{result['source_summary'].get('check_count', 0)}",
        f"- 已读取抽取文本数：{result['source_summary'].get('source_document_count', 0)}",
        f"- 状态统计：{json.dumps(result['source_summary'].get('check_status_counts', {}), ensure_ascii=False, sort_keys=True)}",
        "",
    ]
    for severity in SEVERITIES:
        severity_findings = [item for item in result["findings"] if item["severity"] == severity]
        if not severity_findings:
            continue
        lines.extend([f"## {LABELS[severity]}", ""])
        for index, item in enumerate(severity_findings, 1):
            lines.extend(
                [
                    f"{index}. **位置**：{item['location']}",
                    f"   **证据**：{item['evidence']}",
                    f"   **判断与影响**：{item['judgment']}",
                    f"   **修改建议**：{item['suggestion']}",
                    f"   **来源**：{item.get('source') or '-'}",
                    "",
                ]
            )
    if result["source_limitations"]:
        lines.extend(["## Source 核验限制", ""])
        for index, item in enumerate(result["source_limitations"], 1):
            lines.append(
                f"{index}. {item['field']}：{item['status']}；{item.get('notes') or '未提供更多说明'}"
            )
        lines.append("")
    lines.extend(
        [
            "## 结论说明",
            "",
            result["report_note"],
            "",
        ]
    )
    platform_render_input = {
        "conclusion": result["conclusion"],
        "findings": result["findings"],
    }
    lines.append(render_platform_return_opinion(platform_render_input).rstrip())
    return "\n".join(lines).rstrip() + "\n"


def build_semantic_context(
    *,
    root: Path,
    case_root: Path,
    manifest: Any,
    dataset_type: str,
) -> dict[str, Any]:
    """Materialize the evidence bundle that semantic-review actually uses."""

    precheck = _read_optional_json(case_root / "precheck" / "precheck.json", default={})
    raw_source_checks = _read_optional_json(
        case_root / "source-checks" / "checks.json", default=[]
    )
    source_checks: list[dict[str, Any]] = []
    source_check_validation_errors: list[str] = []
    if isinstance(raw_source_checks, list):
        for index, raw_check in enumerate(raw_source_checks):
            row_errors = validate_source_checks([raw_check])
            if row_errors:
                source_check_validation_errors.extend(
                    error.replace("source_checks[0]", f"source_checks[{index}]", 1)
                    for error in row_errors
                )
            else:
                source_checks.append(raw_check)
    else:
        source_check_validation_errors.extend(validate_source_checks(raw_source_checks))
    source_artifacts = _read_source_artifacts(case_root)
    source_documents = _read_source_documents(case_root, source_artifacts)
    agent_review_path = case_root / AGENT_FINDINGS_RELATIVE_PATH
    agent_review = _read_optional_json(agent_review_path, default=None)
    return {
        "schema_version": SEMANTIC_CONTEXT_SCHEMA_VERSION,
        "review_id": manifest.review_id,
        "dataset_id": manifest.dataset_id,
        "version": manifest.version,
        "dataset_type": dataset_type or "unknown",
        "case_dir": manifest.case_dir,
        "dataset_raw": _read_optional_json(case_root / "snapshots" / "dataset.raw.json", default={}),
        "dataset_normalized": _read_optional_json(
            case_root / "snapshots" / "dataset.normalized.json",
            default={},
        ),
        "precheck": precheck if isinstance(precheck, dict) else {},
        "claims": _read_optional_json(case_root / "source-checks" / "claims.json", default={}),
        "source_checks": source_checks,
        "source_checks_raw": raw_source_checks,
        "source_check_validation_errors": source_check_validation_errors,
        "source_artifacts": source_artifacts,
        "source_documents": source_documents,
        "agent_review": agent_review if isinstance(agent_review, dict) else {},
        "agent_review_present": isinstance(agent_review, dict),
        "model_evidence": _read_model_evidence(case_root),
        "references": _read_reference_bundle(root, dataset_type),
        "rules": _read_rule_bundle(root, dataset_type),
    }


def _read_reference_bundle(root: Path, dataset_type: str) -> list[dict[str, Any]]:
    paths = [
        *COMMON_REFERENCE_FILES,
        *DATASET_REFERENCE_FILES.get(dataset_type, ()),
    ]
    return [_file_bundle(root, path, content_key="content") for path in paths]


def _read_rule_bundle(root: Path, dataset_type: str) -> list[dict[str, Any]]:
    paths = [
        *COMMON_RULE_FILES,
        *DATASET_RULE_FILES.get(dataset_type, ()),
    ]
    bundles = []
    for path in paths:
        bundle = _file_bundle(root, path, content_key="content")
        payload = json.loads(bundle["content"])
        rules = payload.get("rules") if isinstance(payload, dict) else []
        bundle["rule_count"] = len(rules) if isinstance(rules, list) else 0
        bundle["rule_ids"] = [
            str(rule.get("id") or "")
            for rule in rules
            if isinstance(rule, dict) and rule.get("id")
        ]
        bundles.append(bundle)
    return bundles


def _reference_manifest_from_bundle(bundles: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {key: value for key, value in bundle.items() if key != "content"}
        for bundle in bundles
    ]


def _rule_manifest_from_bundle(bundles: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {key: value for key, value in bundle.items() if key != "content"}
        for bundle in bundles
    ]


def _file_bundle(root: Path, relative_path: str, *, content_key: str) -> dict[str, Any]:
    path = root / relative_path
    content = path.read_text(encoding="utf-8")
    return {
        "path": relative_path,
        "sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
        "bytes": len(content.encode("utf-8")),
        content_key: content,
    }


def _normalize_precheck_finding(item: dict[str, Any]) -> dict[str, Any]:
    finding = {
        "rule_id": str(item.get("rule_id") or ""),
        "severity": _severity(item.get("severity")),
        "location": str(item.get("location") or ""),
        "evidence": str(item.get("evidence") or ""),
        "judgment": str(item.get("judgment") or ""),
        "impact": _impact(_severity(item.get("severity"))),
        "suggestion": str(item.get("suggestion") or ""),
        "source": "precheck",
        "origin": "deterministic",
    }
    if isinstance(item.get("platform"), dict):
        finding["platform"] = dict(item["platform"])
    return finding


def _agent_review_findings(
    agent_review: dict[str, Any],
    *,
    agent_review_present: bool,
    dataset_type: str,
    deterministic_findings: list[dict[str, Any]] | None = None,
    case_root: Path | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any], list[dict[str, Any]]]:
    """Turn the Agent's rule reviews into first-class findings plus a summary."""

    required = list(required_rule_ids(dataset_type))
    merged_deterministic_findings = deepcopy(deterministic_findings or [])
    applied_precheck_resolutions: list[dict[str, Any]] = []
    if not agent_review_present:
        summary = {
            "present": False,
            "valid": False,
            "path": AGENT_FINDINGS_RELATIVE_PATH,
            "verdict_counts": {},
            "required_total": len(required),
            "required_covered": 0,
            "validation_error_count": 0,
            "precheck_resolution_count": 0,
            "precheck_resolutions": [],
        }
        finding = {
            "rule_id": "semantic.agent_review.missing",
            "severity": "manual_review",
            "location": AGENT_FINDINGS_RELATIVE_PATH,
            "evidence": "未找到 Agent 规则复核结果。",
            "judgment": (
                "判断型规则（对象一致性、边界匹配、清单完整性等）未经 Agent 显式复核，"
                "不能仅凭程序预检形成通过结论。"
            ),
            "impact": _impact("manual_review"),
            "suggestion": (
                "先运行 `agent-findings template` 生成待复核清单，由 Agent 按 Skill 完成"
                "逐条复核并写入 agent-review/agent-findings.json。"
            ),
            "source": "semantic-review",
            "origin": "workflow",
        }
        return [finding], summary, merged_deterministic_findings

    errors = validate_agent_findings(agent_review, dataset_type=dataset_type)
    if not errors:
        for index, override in enumerate(agent_review.get("platform_overrides") or []):
            rule_id = str(override.get("rule_id") or "")
            location = str(override.get("location") or "")
            matches = [
                item
                for item in merged_deterministic_findings
                if item.get("rule_id") == rule_id and item.get("location") == location
            ]
            if len(matches) != 1:
                errors.append(
                    f"platform_overrides[{index}]: expected exactly one deterministic "
                    f"finding for rule_id={rule_id!r}, location={location!r}; "
                    f"found {len(matches)}"
                )
                continue
            projection_errors = validate_platform_projection(
                str(matches[0].get("severity") or ""), override.get("platform")
            )
            errors.extend(
                f"platform_overrides[{index}]: {error}" for error in projection_errors
            )
        for index, resolution in enumerate(agent_review.get("precheck_resolutions") or []):
            rule_id = str(resolution.get("rule_id") or "")
            location = str(resolution.get("location") or "")
            for ref_index, evidence_ref in enumerate(
                resolution.get("evidence_refs") or []
            ):
                evidence_error = _precheck_resolution_evidence_error(
                    evidence_ref, case_root=case_root
                )
                if evidence_error:
                    errors.append(
                        f"precheck_resolutions[{index}].evidence_refs[{ref_index}]: "
                        f"{evidence_error}"
                    )
            matches = [
                item
                for item in merged_deterministic_findings
                if item.get("rule_id") == rule_id and item.get("location") == location
            ]
            if len(matches) != 1:
                errors.append(
                    f"precheck_resolutions[{index}]: expected exactly one deterministic "
                    f"finding for rule_id={rule_id!r}, location={location!r}; "
                    f"found {len(matches)}"
                )
        if not errors:
            for override in agent_review.get("platform_overrides") or []:
                target = next(
                    item
                    for item in merged_deterministic_findings
                    if item.get("rule_id") == override.get("rule_id")
                    and item.get("location") == override.get("location")
                )
                target["platform"] = PlatformProjection.from_dict(
                    override["platform"]
                ).to_dict()
            resolved_targets = {
                (str(item.get("rule_id") or ""), str(item.get("location") or ""))
                for item in agent_review.get("precheck_resolutions") or []
            }
            if resolved_targets:
                merged_deterministic_findings = [
                    item
                    for item in merged_deterministic_findings
                    if (str(item.get("rule_id") or ""), str(item.get("location") or ""))
                    not in resolved_targets
                ]
                applied_precheck_resolutions = deepcopy(
                    agent_review.get("precheck_resolutions") or []
                )
    missing = uncovered_required_rule_ids(agent_review, dataset_type=dataset_type)
    rule_reviews = [
        item for item in agent_review.get("rule_reviews") or [] if isinstance(item, dict)
    ]
    verdict_counts = dict(
        Counter(str(item.get("verdict") or "") for item in rule_reviews)
    )
    summary = {
        "present": True,
        "valid": not errors,
        "path": AGENT_FINDINGS_RELATIVE_PATH,
        "reviewed_by": str(agent_review.get("reviewed_by") or ""),
        "verdict_counts": verdict_counts,
        "required_total": len(required),
        "required_covered": len(required) - len(missing),
        "validation_error_count": len(errors),
        "precheck_resolution_count": len(applied_precheck_resolutions),
        "precheck_resolutions": applied_precheck_resolutions,
    }

    findings: list[dict[str, Any]] = []
    if errors:
        shown = "；".join(errors[:5])
        if len(errors) > 5:
            shown += f"；另有 {len(errors) - 5} 条校验错误"
        findings.append(
            {
                "rule_id": "semantic.agent_review.invalid",
                "severity": "input_gap",
                "location": AGENT_FINDINGS_RELATIVE_PATH,
                "evidence": f"Agent 复核文件未通过契约校验：{shown}",
                "judgment": "复核记录不满足证据契约时，其判断不能纳入正式审核结论。",
                "impact": _impact("input_gap"),
                "suggestion": "运行 `agent-findings validate` 修复列出的契约错误后重新执行 semantic-review。",
                "source": "semantic-review",
                "origin": "validation",
            }
        )
    elif missing:
        findings.append(
            {
                "rule_id": "semantic.agent_review.incomplete",
                "severity": "manual_review",
                "location": AGENT_FINDINGS_RELATIVE_PATH,
                "evidence": f"以下必审规则缺少显式复核结论：{'、'.join(missing)}。",
                "judgment": "必审规则未逐条给出 pass/fail/cannot_judge 结论前，不能形成完整通过结论。",
                "impact": _impact("manual_review"),
                "suggestion": "补齐缺失规则的复核结论和证据引用。",
                "source": "semantic-review",
                "origin": "workflow",
            }
        )

    for item in rule_reviews:
        verdict = str(item.get("verdict") or "")
        rule_id = str(item.get("rule_id") or "")
        refs = "; ".join(str(ref) for ref in item.get("evidence_refs") or [])
        source_label = "agent-review" + (f": {refs}" if refs else "")
        if verdict == "fail":
            finding = {
                    "rule_id": rule_id,
                    "severity": _severity(item.get("severity")),
                    "location": str(item.get("location") or rule_id),
                    "evidence": str(item.get("evidence") or ""),
                    "judgment": str(item.get("judgment") or ""),
                    "impact": _impact(_severity(item.get("severity"))),
                    "suggestion": str(item.get("suggestion") or ""),
                    "source": source_label,
                    "origin": "agent",
                }
            if isinstance(item.get("platform"), dict):
                finding["platform"] = dict(item["platform"])
            findings.append(finding)
        elif verdict == "cannot_judge":
            finding = {
                    "rule_id": rule_id,
                    "severity": "manual_review",
                    "location": str(item.get("location") or rule_id),
                    "evidence": str(item.get("evidence") or "Agent 无法基于现有证据判断该规则。"),
                    "judgment": str(item.get("judgment") or ""),
                    "impact": _impact("manual_review"),
                    "suggestion": str(item.get("suggestion") or "由审核员补充证据后人工确认。"),
                    "source": source_label,
                    "origin": "agent",
                }
            if isinstance(item.get("platform"), dict):
                finding["platform"] = dict(item["platform"])
            findings.append(finding)

    for item in agent_review.get("additional_findings") or []:
        if not isinstance(item, dict):
            continue
        severity = _severity(item.get("severity"))
        finding = {
                "rule_id": str(item.get("rule_id") or "agent.additional_finding"),
                "severity": severity,
                "location": str(item.get("location") or ""),
                "evidence": str(item.get("evidence") or ""),
                "judgment": str(item.get("judgment") or ""),
                "impact": _impact(severity),
                "suggestion": str(item.get("suggestion") or ""),
                "source": "agent-review",
                "origin": "agent",
            }
        if isinstance(item.get("platform"), dict):
            finding["platform"] = dict(item["platform"])
        findings.append(finding)
    return findings, summary, merged_deterministic_findings


def _precheck_resolution_evidence_error(
    evidence_ref: Any, *, case_root: Path | None
) -> str:
    if case_root is None:
        return "cannot validate evidence without a case root"
    if not isinstance(evidence_ref, str) or not evidence_ref.strip():
        return "must be a non-empty case-relative path"
    ref_path = Path(evidence_ref.strip())
    if ref_path.is_absolute():
        return "must be a case-relative path"
    resolved_case_root = case_root.resolve()
    resolved_evidence = (resolved_case_root / ref_path).resolve()
    try:
        resolved_evidence.relative_to(resolved_case_root)
    except ValueError:
        return "must stay inside the current case directory"
    if not resolved_evidence.is_file():
        return "does not point to an existing evidence file"
    return ""


def _source_quality_findings(
    *,
    claims: dict[str, Any],
    source_checks: list[dict[str, Any]],
    source_documents: list[dict[str, Any]],
    agent_review: dict[str, Any],
) -> list[dict[str, Any]]:
    """Findings that keep unresolved source verification out of a silent pass."""

    findings: list[dict[str, Any]] = []
    if source_documents and claims:
        checked_status: dict[str, set[str]] = {}
        for check in source_checks:
            field = str(check.get("field") or "")
            checked_status.setdefault(field, set()).add(str(check.get("status") or ""))
        unverified = []
        for field in claims:
            if not str(field).startswith(CORE_CLAIM_PREFIXES):
                continue
            statuses = checked_status.get(str(field), set())
            if statuses & SOURCE_CHECK_STATUS_POLICY.keys():
                continue
            unverified.append(str(field))
        if unverified:
            shown = "、".join(unverified[:8])
            if len(unverified) > 8:
                shown += f" 等 {len(unverified)} 项"
            findings.append(
                {
                    "rule_id": "source.core_claim.unverified",
                    "severity": "manual_review",
                    "location": "Source 核验 / 核心字段",
                    "evidence": f"以下核心字段未得到 source 语义核验支持：{shown}。",
                    "judgment": (
                        "参考流、年份、地区、技术路线等核心字段未被 source 证实时，"
                        "不能把来源代表性视为已通过。"
                    ),
                    "impact": _impact("manual_review"),
                    "suggestion": "读取 source 原文核验这些字段并写入 checks.json；确无来源支持时按信息缺口处理。",
                    "source": "source-checks/claims.json",
                    "origin": "semantic_context",
                }
            )

    read_paths = [
        str(item) for item in (agent_review.get("source_documents_read") or []) if str(item)
    ]
    for document in source_documents:
        if not document.get("truncated"):
            continue
        doc_path = str(document.get("path") or "")
        if _path_acknowledged(doc_path, read_paths):
            continue
        findings.append(
            {
                "rule_id": "source.document.truncated_context",
                "severity": "manual_review",
                "location": f"Source 文档 / {document.get('source_ref_id') or doc_path}",
                "evidence": (
                    f"抽取文本 {doc_path} 超过 {MAX_CONTEXT_TEXT_CHARS} 字符，"
                    "semantic-context 仅包含截断后的前段内容。"
                ),
                "judgment": (
                    "补充材料和附表通常位于文档后半部分；未确认完整读取前，"
                    "不能认为 source 核验已覆盖全文。"
                ),
                "impact": _impact("manual_review"),
                "suggestion": (
                    "由 Agent 直接完整读取该抽取文件，并在 agent-findings.json 的 "
                    "source_documents_read 中记录该路径。"
                ),
                "source": "semantic-context",
                "origin": "extraction",
            }
        )
    return findings


def _path_acknowledged(doc_path: str, read_paths: list[str]) -> bool:
    normalized = doc_path.strip("/")
    for read_path in read_paths:
        candidate = read_path.strip("/")
        if not candidate:
            continue
        if normalized == candidate or normalized.endswith(candidate) or candidate.endswith(normalized):
            return True
    return False


def _audit_completeness(
    *,
    agent_review_summary: dict[str, Any],
    source_checks: list[dict[str, Any]],
    source_check_validation_errors: list[str] | None = None,
) -> dict[str, Any]:
    agent_ok = bool(agent_review_summary.get("valid"))
    source_checks_valid = not source_check_validation_errors
    source_checks_present = bool(source_checks) and source_checks_valid
    missing: list[str] = []
    if not agent_review_summary.get("present"):
        missing.append("agent_review_missing")
    elif not agent_ok:
        missing.append("agent_review_invalid_or_incomplete")
    if not source_checks_present:
        missing.append(
            "source_checks_invalid" if source_check_validation_errors else "source_checks_missing"
        )
    return {
        "complete": agent_ok and source_checks_present,
        "agent_review_valid": agent_ok,
        "source_checks_present": source_checks_present,
        "source_checks_valid": source_checks_valid,
        "missing": missing,
    }


def _reconcile_conclusion(
    conclusion: str,
    *,
    source_consistency: dict[str, Any],
    rule_compliance: dict[str, Any],
    audit_completeness: dict[str, Any],
) -> str:
    """Guarantee the overall conclusion is never better than any layer implies."""

    candidates = [conclusion]
    candidates.append(
        _SOURCE_LAYER_FLOOR.get(str(source_consistency.get("conclusion")), "需人工确认")
    )
    candidates.append(
        _RULE_LAYER_FLOOR.get(str(rule_compliance.get("conclusion")), "需人工确认")
    )
    if not audit_completeness.get("complete"):
        candidates.append("需人工确认")
    return max(candidates, key=lambda item: _CONCLUSION_RANK.get(item, 1))


def _artifact_source_id(artifact: dict[str, Any]) -> str:
    """Resolve one artifact identity with the shared SourceRef precedence."""

    return SourceRef.from_dict(dict(artifact.get("ref") or {})).stable_id()


def _source_findings(
    source_checks: list[dict[str, Any]],
    source_artifacts: list[dict[str, Any]],
    source_documents: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    field_gap_source_ids: set[str] = set()
    documents_by_source = {
        str(item.get("source_ref_id") or ""): item
        for item in source_documents
        if item.get("source_ref_id")
    }
    for check in source_checks:
        parsed = SourceCheck.from_dict(check)
        severity = parsed.resolved_severity()
        if severity is None:
            continue
        field = parsed.field
        source_ref_id = parsed.checked_source_id or parsed.source_ref_id
        source_doc = documents_by_source.get(source_ref_id, {})
        page_label = f"第 {parsed.page} 页，" if parsed.page else ""
        excerpt = parsed.matched_excerpt or parsed.evidence or parsed.notes or "未记录摘录"
        status_text = {
            "conflict": "与数据集字段存在直接冲突",
            "ambiguous": "存在相关证据，但不足以确认全部语义事实",
            "not_found": "未找到支持当前字段值的直接证据",
            "source_unavailable": "对应 source 当前不可用",
            "download_failed": "对应 source 下载失败",
            "extraction_failed": "对应 source 抽取失败",
        }.get(parsed.status, parsed.status)
        finding = {
            "rule_id": f"source.field.{parsed.status}",
            "severity": severity,
            "location": f"Source 核验 / {field}",
            "evidence": (
                f"数据集字段值为“{parsed.dataset_value}”；source {source_ref_id or '-'} "
                f"{page_label}核验结果为“{status_text}”，证据为“{excerpt}”。"
            ),
            "judgment": {
                "blocking": "source 与数据集字段直接冲突，当前字段不能按原样通过。",
                "advisory": "现有 source 不确定性不单独阻断审核，但值得补充说明。",
                "manual_review": "现有 source 证据不足以确认该字段，需要补充事实或人工判断。",
                "input_gap": "当前无法完成该字段的 source 核验，限制完整审核结论。",
            }[severity],
            "impact": _impact(severity),
            "suggestion": parsed.notes or "核对 source 原文，并按核验结果修改字段或补充说明。",
            "source": (
                f"source-checks/checks.json:{field}; "
                f"{source_doc.get('path') or 'sources/*/extracted.md'}"
            ),
            "origin": "source_check",
        }
        if parsed.platform is not None:
            finding["platform"] = parsed.platform.to_dict()
        findings.append(finding)
        if severity == "input_gap" and source_ref_id:
            field_gap_source_ids.add(source_ref_id)
    for artifact in source_artifacts:
        status = str(artifact.get("status") or "")
        if status not in {"source_unavailable", "download_failed", "extraction_failed"}:
            continue
        artifact_source_id = _artifact_source_id(artifact)
        if artifact_source_id and artifact_source_id in field_gap_source_ids:
            continue
        source_id = artifact_source_id or "-"
        findings.append(
            {
                "rule_id": "source.artifact.unavailable",
                "severity": "input_gap",
                "location": f"Source 文档 / {source_id}",
                "evidence": str(artifact.get("error") or f"source artifact status={status}"),
                "judgment": "无法完成 source 语义核验，来源代表性和字段支持关系受到限制。",
                "impact": _impact("input_gap"),
                "suggestion": "补充可下载的 source 文件，或提供可复核的页码、表格和数据处理说明。",
                "source": "sources/*/manifest.json",
                "origin": "extraction",
            }
        )
    for artifact in source_artifacts:
        source_id = _artifact_source_id(artifact) or "-"
        for requirement in artifact.get("related_artifact_requirements") or []:
            reference = str(requirement.get("reference") or "supplementary material")
            action = str(requirement.get("action") or "")
            findings.append(
                {
                    "rule_id": "source.related_artifact.requires_followup",
                    "severity": "manual_review",
                    "location": f"Source 补充材料 / {source_id}",
                    "evidence": f"已下载 source 文本引用了“{reference}”，当前 case 需确认该补充材料是否已取得并纳入核验。",
                    "judgment": "若字段事实依赖该补充表、附录或 source table，不能仅凭主文 PDF 判定 source 已支持。",
                    "impact": _impact("manual_review"),
                    "suggestion": action
                    or "补充下载相关材料；无法取得时，将受影响字段标为 ambiguous 或 source_unavailable。",
                    "source": "sources/*/manifest.json",
                    "origin": "semantic_context",
                }
            )
    for artifact in source_artifacts:
        status = str(artifact.get("status") or "")
        if status != "extracted":
            continue
        source_id = _artifact_source_id(artifact)
        if source_id and source_id not in documents_by_source:
            findings.append(
                {
                    "rule_id": "source.artifact.extraction_unreadable",
                    "severity": "input_gap",
                    "location": f"Source 文档 / {source_id}",
                    "evidence": "source manifest 标记为 extracted，但 semantic-review 未能读取 extracted.md。",
                    "judgment": "无法把 source 抽取文本纳入正式语义审核上下文。",
                    "impact": _impact("input_gap"),
                    "suggestion": "重新抽取 source 文本，或补充可读取的 source 摘录和页码证据。",
                    "source": "sources/*/manifest.json",
                    "origin": "extraction",
                }
            )
    return findings


def _input_gap_findings(
    case_root: Path,
    precheck: dict[str, Any],
    source_checks: list[dict[str, Any]],
    dataset_type: str,
    source_check_validation_errors: list[str] | None = None,
) -> list[dict[str, Any]]:
    findings = []
    if not (case_root / "precheck" / "precheck.json").exists() and dataset_type == "process":
        findings.append(
            {
                "rule_id": "semantic.precheck.missing",
                "severity": "input_gap",
                "location": "precheck/precheck.json",
                "evidence": "未找到程序预检结果。",
                "judgment": "缺少确定性预检结果，无法完成完整审核的程序化复核部分。",
                "impact": _impact("input_gap"),
                "suggestion": "先运行 intake-review 或 check-rules 生成 precheck.json。",
                "source": "semantic-review",
                "origin": "workflow",
            }
        )
    if not source_checks and not source_check_validation_errors:
        checks_path = case_root / "source-checks" / "checks.json"
        evidence = (
            "source-checks/checks.json 存在但没有任何字段核验结果。"
            if checks_path.exists()
            else "未找到 source 字段核验结果。"
        )
        findings.append(
            {
                "rule_id": "semantic.source_checks.missing",
                "severity": "manual_review",
                "location": "source-checks/checks.json",
                "evidence": evidence,
                "judgment": "来源支持关系未完成核验，不能把来源代表性视为已通过。",
                "impact": _impact("manual_review"),
                "suggestion": "先读取 source 原文和 claims，由 Agent 完成语义核验并写入 source-checks/checks.json。",
                "source": "semantic-review",
                "origin": "workflow",
            }
        )
    return findings


def _semantic_context_findings(context: dict[str, Any]) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    dataset_type = str(context.get("dataset_type") or "")
    validation_errors = context.get("source_check_validation_errors") or []
    if validation_errors:
        shown = "；".join(str(error) for error in validation_errors[:5])
        if len(validation_errors) > 5:
            shown += f"；另有 {len(validation_errors) - 5} 条校验错误"
        findings.append(
            {
                "rule_id": "source.checks.invalid",
                "severity": "input_gap",
                "location": "source-checks/checks.json",
                "evidence": f"Source 核验文件未通过契约校验：{shown}",
                "judgment": "无效的来源核验记录不能参与严重程度汇总或审核结论。",
                "impact": _impact("input_gap"),
                "suggestion": "修复列出的 source-check 契约错误后重新执行 semantic-review。",
                "source": "semantic-context",
                "origin": "validation",
            }
        )
    if not context.get("dataset_raw"):
        findings.append(
            {
                "rule_id": "semantic.dataset_raw.missing",
                "severity": "input_gap",
                "location": "snapshots/dataset.raw.json",
                "evidence": "未找到被审核数据集原始 JSON。",
                "judgment": "缺少原始数据会阻止复核标准化、source 引用和字段级判断。",
                "impact": _impact("input_gap"),
                "suggestion": "先运行 intake-review 下载并保存 dataset.raw.json。",
                "source": "semantic-context",
                "origin": "semantic_context",
            }
        )
    if dataset_type == "process":
        findings.extend(_process_context_findings(context))
    elif dataset_type == "model":
        findings.extend(_model_context_findings(context))
    else:
        findings.append(
            {
                "rule_id": "semantic.dataset_type.unknown",
                "severity": "input_gap",
                "location": "输入类型",
                "evidence": f"dataset_type={dataset_type or 'unknown'}。",
                "judgment": "无法确认输入是过程数据集还是模型数据集，不能形成完整审核结论。",
                "impact": _impact("input_gap"),
                "suggestion": "补充过程或模型数据集 JSON，或显式说明审核对象类型。",
                "source": "semantic-context",
                "origin": "semantic_context",
            }
        )
    return findings


def _process_context_findings(context: dict[str, Any]) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    source_artifacts = context.get("source_artifacts") or []
    source_documents = context.get("source_documents") or []
    if source_artifacts and not source_documents:
        findings.append(
            {
                "rule_id": "process.source.document_availability",
                "severity": "input_gap",
                "location": "sources/*/extracted.md",
                "evidence": f"识别到 {len(source_artifacts)} 个 source artifact，但没有可读取的抽取文本。",
                "judgment": "无法核查 source 是否支持边界、年份、地区、技术路线或关键清单字段。",
                "impact": _impact("input_gap"),
                "suggestion": "补充可下载和可抽取的 source 文档，或提供页码、表格和数据处理说明。",
                "source": "semantic-context",
                "origin": "extraction",
            }
        )
    return findings


def _model_context_findings(context: dict[str, Any]) -> list[dict[str, Any]]:
    evidence = dict(context.get("model_evidence") or {})
    linked_refs = evidence.get("linked_process_refs") or []
    linked_processes = evidence.get("linked_processes") or []
    linked_prechecks = evidence.get("linked_prechecks") or []
    findings: list[dict[str, Any]] = []
    if not linked_refs:
        findings.append(
            {
                "rule_id": "model.linked_process.audit",
                "severity": "input_gap",
                "location": "模型结构 / 关联过程",
                "evidence": "未识别到模型关联过程引用。",
                "judgment": "模型完整审核至少需要关联过程列表和关键关联过程的可审数据。",
                "impact": _impact("input_gap"),
                "suggestion": "补充模型节点、连接关系和关联过程引用后重新运行 intake-review。",
                "source": "semantic-context",
                "origin": "semantic_context",
            }
        )
    elif not linked_processes:
        findings.append(
            {
                "rule_id": "model.linked_process.audit",
                "severity": "input_gap",
                "location": "模型结构 / 关联过程",
                "evidence": f"识别到 {len(linked_refs)} 个关联过程引用，但没有成功下载关联过程 JSON。",
                "judgment": "无法复用过程审核结果确认关键关联过程是否支撑模型目标和连接关系。",
                "impact": _impact("input_gap"),
                "suggestion": "下载关键关联过程 JSON，并对其运行过程预检和 source 核验。",
                "source": "semantic-context",
                "origin": "semantic_context",
            }
        )
    for precheck in linked_prechecks:
        summary = dict(precheck.get("summary") or {})
        if summary.get("blocking"):
            findings.append(
                {
                    "rule_id": "model.linked_process.audit",
                    "severity": "blocking",
                    "location": f"模型关联过程 / {precheck.get('dataset_id') or '-'}",
                    "evidence": f"关联过程预检存在 {summary.get('blocking')} 个阻断问题。",
                    "judgment": "关键关联过程存在阻断问题时，模型不能直接作为完整通过结论使用。",
                    "impact": _impact("blocking"),
                    "suggestion": "先修正关联过程阻断问题，再复核模型目标量和连接关系。",
                    "source": str(precheck.get("path") or "precheck/linked-processes/*.json"),
                    "origin": "semantic_context",
                }
            )
    return findings


def _has_platform_write(manifest: Any) -> bool:
    return bool(manifest.steps.get("platform_written")) or manifest.status in {
        "draft_saved",
        "submitted",
        "completed",
    }


def _source_summary(
    source_checks: list[dict[str, Any]],
    source_artifacts: list[dict[str, Any]],
    source_documents: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "artifact_count": len(source_artifacts),
        "artifact_status_counts": dict(Counter(str(item.get("status") or "") for item in source_artifacts)),
        "source_document_count": len(source_documents),
        "source_document_bytes": sum(int(item.get("bytes") or 0) for item in source_documents),
        "check_count": len(source_checks),
        "check_status_counts": dict(Counter(str(item.get("status") or "") for item in source_checks)),
    }


def _source_consistency_review(
    source_checks: list[dict[str, Any]],
    source_artifacts: list[dict[str, Any]],
    source_documents: list[dict[str, Any]],
) -> dict[str, Any]:
    check_counts = Counter(str(item.get("status") or "") for item in source_checks)
    parsed_checks = [SourceCheck.from_dict(item) for item in source_checks]
    resolved_severities = [check.resolved_severity() for check in parsed_checks]
    severity_counts = Counter(
        severity for severity in resolved_severities if severity is not None
    )
    artifact_counts = Counter(str(item.get("status") or "") for item in source_artifacts)
    matched_count = check_counts.get("matched", 0)
    failed_artifact_count = sum(
        artifact_counts.get(status, 0)
        for status in ("source_unavailable", "download_failed", "extraction_failed")
    )
    field_gap_source_ids = {
        check.checked_source_id or check.source_ref_id
        for check in parsed_checks
        if check.resolved_severity() == "input_gap"
    }
    failed_artifact_ids: set[str] = set()
    anonymous_failed_artifacts = 0
    for artifact in source_artifacts:
        if str(artifact.get("status") or "") not in {
            "source_unavailable",
            "download_failed",
            "extraction_failed",
        }:
            continue
        artifact_id = _artifact_source_id(artifact)
        if artifact_id:
            failed_artifact_ids.add(artifact_id)
        else:
            anonymous_failed_artifacts += 1
    independent_failed_artifact_count = (
        len(failed_artifact_ids - field_gap_source_ids) + anonymous_failed_artifacts
    )
    if severity_counts.get("blocking"):
        conclusion = "不一致"
        reason = f"发现 {severity_counts['blocking']} 个会阻断审核的 source 字段冲突。"
    elif severity_counts.get("input_gap") or failed_artifact_count:
        field_count = severity_counts.get("input_gap", 0)
        conclusion = "证据不足"
        reason = (
            f"{field_count} 个字段、{independent_failed_artifact_count} 个文档"
            "存在 source 核验信息缺口。"
        )
    elif severity_counts.get("manual_review"):
        conclusion = "需人工确认"
        reason = f"{severity_counts['manual_review']} 个字段需要补充事实或人工确认。"
    elif severity_counts.get("advisory"):
        conclusion = "基本一致，有建议补充"
        reason = f"未发现阻断冲突，但有 {severity_counts['advisory']} 个非阻断 source 建议。"
    elif not source_checks and not source_artifacts:
        conclusion = "未核验"
        reason = "没有可用的 source 文档或字段核验结果。"
    elif source_checks:
        conclusion = "一致"
        reason = f"{matched_count} 个字段的语义事实得到 source 支持，未发现直接冲突。"
    else:
        conclusion = "证据不足"
        reason = "已识别 source 文档，但没有字段级核验结果。"
    return {
        "layer": "pdf_source_consistency",
        "conclusion": conclusion,
        "reason": reason,
        "check_status_counts": dict(check_counts),
        "check_severity_counts": dict(severity_counts),
        "artifact_status_counts": dict(artifact_counts),
        "source_document_count": len(source_documents),
    }


def _rule_compliance_review(findings: list[dict[str, Any]]) -> dict[str, Any]:
    rule_findings = [
        item for item in findings if not _is_source_layer_finding(str(item.get("rule_id") or ""))
    ]
    summary = _summary(rule_findings)
    if summary["blocking"]:
        conclusion = "不符合规则"
        reason = f"规则审核发现 {summary['blocking']} 个阻断问题。"
    elif summary["input_gap"]:
        conclusion = "规则证据不足"
        reason = f"规则审核存在 {summary['input_gap']} 个信息缺口。"
    elif summary["manual_review"]:
        conclusion = "需人工确认"
        reason = f"规则审核存在 {summary['manual_review']} 个需要人工确认的问题。"
    elif summary["advisory"]:
        conclusion = "基本符合规则，有建议修改"
        reason = f"未发现阻断问题，但有 {summary['advisory']} 个建议修改。"
    else:
        conclusion = "符合规则"
        reason = "未发现阻断、建议、人工确认或信息缺口类规则问题。"
    return {
        "layer": "rule_compliance",
        "conclusion": conclusion,
        "reason": reason,
        "summary": summary,
    }


def _is_source_layer_finding(rule_id: str) -> bool:
    return rule_id.startswith(("source.", "semantic.source_checks", "process.source."))


def _source_limitations(
    source_checks: list[dict[str, Any]],
    source_artifacts: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    limitations = [
        {
            "field": str(check.get("field") or ""),
            "status": str(check.get("status") or ""),
            "notes": str(check.get("notes") or ""),
            "source_ref_id": str(check.get("source_ref_id") or ""),
        }
        for check in source_checks
        if str(check.get("status") or "") in {"ambiguous", "not_found", "not_applicable"}
    ]
    limitations.extend(
        {
            "field": str(dict(item.get("ref") or {}).get("source_id") or "source artifact"),
            "status": str(item.get("status") or ""),
            "notes": str(item.get("error") or ""),
            "source_ref_id": str(dict(item.get("ref") or {}).get("source_id") or ""),
        }
        for item in source_artifacts
        if str(item.get("status") or "") in {"source_unavailable", "download_failed", "extraction_failed"}
    )
    return limitations


def _summary(findings: list[dict[str, Any]]) -> dict[str, int]:
    return {severity: sum(1 for item in findings if item["severity"] == severity) for severity in SEVERITIES}


def _conclusion(summary: dict[str, int]) -> str:
    if summary["blocking"]:
        return "不通过"
    if summary["input_gap"]:
        return "信息不足"
    if summary["manual_review"]:
        return "需人工确认"
    return "通过"


def _platform_conclusion(conclusion: str) -> str:
    return {
        "通过": "approved",
        "不通过": "rejected",
        "信息不足": "manual_review",
        "需人工确认": "manual_review",
    }[conclusion]


def _input_sufficiency(summary: dict[str, int]) -> str:
    return "不充分" if summary["input_gap"] else "充分"


def _impact(severity: str) -> str:
    return {
        "blocking": "影响通过；该问题需要修改后复核。",
        "advisory": "不单独影响通过，但影响表达清晰度或复用质量。",
        "manual_review": "可能影响结论，需要审核员或提交者补充确认。",
        "input_gap": "限制完整审核结论，需要补充证据。",
    }.get(severity, "需要复核。")


def _severity(value: Any) -> str:
    severity = str(value or "manual_review")
    return severity if severity in SEVERITIES else "manual_review"


def _dataset_identity(manifest: Any, precheck: dict[str, Any]) -> dict[str, Any]:
    identity = dict(precheck.get("dataset") or {})
    name = dict(identity.get("name") or {})
    return {
        "id": manifest.dataset_id or identity.get("id") or "",
        "version": manifest.version or identity.get("version") or "",
        "name_zh": manifest.name_zh or name.get("zh") or "",
        "name_en": manifest.name_en or name.get("en") or "",
    }


def _platform_result(result: dict[str, Any]) -> dict[str, Any]:
    expected_platform_conclusion = _platform_conclusion(str(result["conclusion"]))
    supplied_platform_conclusion = str(result.get("platform_conclusion") or "")
    if supplied_platform_conclusion != expected_platform_conclusion:
        raise ValueError(
            "platform_conclusion does not match conclusion: "
            f"expected {expected_platform_conclusion!r}, got {supplied_platform_conclusion!r}"
        )
    platform_comment = build_platform_comment(
        {"conclusion": result["conclusion"], "findings": result["findings"]}
    )
    return {
        "schema_version": PLATFORM_RESULT_SCHEMA_VERSION,
        "review_task_id": result["review_task_id"],
        "dataset_id": result["dataset_id"],
        "dataset_type": result["dataset_type"],
        "version": result["version"],
        "conclusion": expected_platform_conclusion,
        "platform_comment": platform_comment,
        "summary": {
            "conclusion_zh": result["conclusion"],
            **result["summary"],
            "source_consistency": result["source_consistency"],
            "rule_compliance": result["rule_compliance"],
            "agent_review": result["agent_review"],
            "audit_completeness": result["audit_completeness"],
            "source_summary": result["source_summary"],
            "note": result["report_note"],
        },
        "findings": [
            {
                "id": f"{item.get('rule_id') or 'finding'}_{index}",
                "rule_id": item.get("rule_id") or "",
                "severity": item["severity"],
                "title": item["evidence"],
                "description": item["judgment"],
                "evidence": item["evidence"],
                "suggested_fix": item["suggestion"],
                "related_field": item["location"],
                "tags": [str(item.get("source") or "")] if item.get("source") else [],
                "origin": item.get("origin") or "",
                **(
                    {"platform": dict(item["platform"])}
                    if isinstance(item.get("platform"), dict)
                    else {}
                ),
            }
            for index, item in enumerate(result["findings"], 1)
        ],
        "auditor_notes": result["report_note"],
    }


def _semantic_context_summary(context: dict[str, Any]) -> dict[str, Any]:
    rule_count = sum(
        int(bundle.get("rule_count") or 0)
        for bundle in context.get("rules", [])
        if isinstance(bundle, dict)
    )
    model_evidence = dict(context.get("model_evidence") or {})
    return {
        "reference_count": len(context.get("references") or []),
        "rule_count": rule_count,
        "source_document_count": len(context.get("source_documents") or []),
        "source_check_count": len(context.get("source_checks") or []),
        "has_dataset_raw": bool(context.get("dataset_raw")),
        "has_dataset_normalized": bool(context.get("dataset_normalized")),
        "linked_process_ref_count": len(model_evidence.get("linked_process_refs") or []),
        "linked_process_count": len(model_evidence.get("linked_processes") or []),
        "linked_process_precheck_count": len(model_evidence.get("linked_prechecks") or []),
    }


def _read_source_artifacts(case_root: Path) -> list[dict[str, Any]]:
    artifacts = []
    for path in sorted((case_root / "sources").glob("source-*/manifest.json")):
        payload = _read_optional_json(path, default={})
        if isinstance(payload, dict):
            payload["_manifest_path"] = str(path)
            artifacts.append(payload)
    return artifacts


def _read_source_documents(
    case_root: Path,
    source_artifacts: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    documents = []
    for artifact in source_artifacts:
        manifest_path = Path(str(artifact.get("_manifest_path") or ""))
        extracted_path_text = str(artifact.get("extracted_text_path") or "")
        if not extracted_path_text:
            continue
        extracted_path = Path(extracted_path_text)
        if not extracted_path.is_absolute() and manifest_path:
            extracted_path = manifest_path.parent / extracted_path
        if not extracted_path.exists() and manifest_path:
            extracted_path = manifest_path.parent / Path(extracted_path_text).name
        if not extracted_path.exists():
            continue
        try:
            text = extracted_path.read_text(encoding="utf-8")
        except OSError:
            continue
        ref = dict(artifact.get("ref") or {})
        source_ref_id = str(
            ref.get("source_id")
            or ref.get("uri")
            or ref.get("url")
            or ref.get("path")
            or ref.get("label")
            or extracted_path.parent.name
        )
        text_bytes = len(text.encode("utf-8"))
        truncated = text_bytes > MAX_CONTEXT_TEXT_CHARS
        context_text = text[:MAX_CONTEXT_TEXT_CHARS]
        documents.append(
            {
                "source_ref_id": source_ref_id,
                "path": _case_relative_path(extracted_path, case_root),
                "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
                "bytes": text_bytes,
                "truncated": truncated,
                "text": context_text,
            }
        )
    return documents


def _read_model_evidence(case_root: Path) -> dict[str, Any]:
    linked_refs = _read_optional_json(
        case_root / "snapshots" / "model-linked-process-refs.json",
        default=[],
    )
    if not isinstance(linked_refs, list):
        linked_refs = []
    linked_processes = []
    for path in sorted((case_root / "snapshots" / "linked-processes").glob("*.json")):
        payload = _read_optional_json(path, default={})
        if isinstance(payload, dict):
            linked_processes.append(
                {
                    "path": str(path.relative_to(case_root)),
                    "id": str(payload.get("id") or ""),
                    "version": str(payload.get("version") or ""),
                }
            )
    linked_prechecks = []
    for path in sorted((case_root / "precheck" / "linked-processes").glob("*.precheck.json")):
        payload = _read_optional_json(path, default={})
        if isinstance(payload, dict):
            identity = dict(payload.get("dataset") or {})
            linked_prechecks.append(
                {
                    "path": str(path.relative_to(case_root)),
                    "dataset_id": identity.get("id") or "",
                    "summary": dict(payload.get("summary") or {}),
                    "conclusion": str(payload.get("conclusion") or ""),
                }
            )
    return {
        "linked_process_refs": linked_refs,
        "linked_processes": linked_processes,
        "linked_prechecks": linked_prechecks,
    }


def _read_optional_json(path: Path, *, default: Any) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _case_path_label(path: Path, root: Path) -> str:
    try:
        return str(Path(path).relative_to(root / "cases"))
    except ValueError:
        return str(path)


def _case_relative_path(path: Path, case_root: Path) -> str:
    try:
        return str(Path(path).relative_to(case_root))
    except ValueError:
        return str(path)
