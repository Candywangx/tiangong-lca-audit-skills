from __future__ import annotations

import json
import importlib
from copy import deepcopy
from pathlib import Path

import pytest

from tiangong_audit.case_store import CaseStore
from tiangong_audit.contracts.agent_review import required_rule_ids
from tiangong_audit.report.platform import build_platform_comment
from tiangong_audit.workflows import semantic_review
from tiangong_audit.workflows.semantic_review import (
    MAX_CONTEXT_TEXT_CHARS,
    _agent_review_findings,
    _normalize_precheck_finding,
    _platform_result,
    _reconcile_conclusion,
    _source_consistency_review,
    _source_findings,
    _source_quality_findings,
)


def test_semantic_markdown_passes_conclusion_to_platform_renderer(monkeypatch):
    captured: dict[str, object] = {}
    semantic_review_module = importlib.import_module(
        "tiangong_audit.workflows.semantic_review"
    )

    def capture_platform_input(payload):
        captured.update(payload)
        return "## 平台退回意见\n\n无\n"

    monkeypatch.setattr(
        semantic_review_module, "render_platform_return_opinion", capture_platform_input
    )
    semantic_review_module.render_semantic_review(
        {
            "dataset": {"name_zh": "测试数据", "name_en": ""},
            "audit_scope": "完整审核",
            "dataset_type": "process",
            "dataset_id": "dataset-1",
            "version": "01.01.000",
            "input_sufficiency": "充分",
            "conclusion": "不通过",
            "source_consistency": {"conclusion": "一致", "reason": "已核验"},
            "rule_compliance": {"conclusion": "不符合规则", "reason": "存在阻断问题"},
            "agent_review": {},
            "audit_completeness": {"complete": True},
            "source_summary": {},
            "findings": [],
            "source_limitations": [],
            "report_note": "存在阻断问题。",
        }
    )

    assert captured["conclusion"] == "不通过"


def test_semantic_review_merges_precheck_source_checks_and_agent_gaps(tmp_path):
    _write_skill_contract_files(tmp_path)
    store = CaseStore(tmp_path / "cases")
    manifest = store.create_case(
        review_id="review-1",
        batch_id="20260707-member",
        dataset_id="dataset-1",
        version="01.01.000",
        dataset_type="process",
        name_zh="叶片制造",
        name_en="Blades manufacture",
    )
    case_root = tmp_path / "cases" / manifest.case_dir
    _write_json(
        case_root / "snapshots/dataset.raw.json",
        {"processDataSet": {"processInformation": {"dataSetInformation": {}}}},
    )
    precheck = {
        "dataset": {
            "id": "dataset-1",
            "version": "01.01.000",
            "name": {"zh": "叶片制造", "en": "Blades manufacture"},
        },
        "dataset_type": "process",
        "findings": [
            {
                "rule_id": "process.flow.semantic_match",
                "severity": "blocking",
                "location": "输入/输出 / 风轮机叶片",
                "evidence": "缺少流类型、流分类。",
                "judgment": "缺失元数据会影响检索、连接或流角色判断。",
                "suggestion": "补充该流的流类型、流分类。",
            }
        ],
        "summary": {"blocking": 1, "advisory": 0, "manual_review": 0, "input_gap": 0},
    }
    _write_json(case_root / "precheck/precheck.json", precheck)
    _write_json(
        case_root / "source-checks/checks.json",
        [
            {
                "field": "process.name.zh",
                "dataset_value": "叶片制造",
                "source_ref_id": "source-1",
                "status": "not_found",
                "notes": "Dataset value was not found in extracted source text",
            },
            {
                "field": "process.route.en",
                "dataset_value": "Blade diameter 151 m",
                "source_ref_id": "source-1",
                "status": "conflict",
                "evidence": "rotor diameter of 151 meters",
                "notes": "Source value is 'rotor diameter of 151 meters'",
            },
            {
                "field": "process.dataset_type",
                "dataset_value": "Unit process, black box",
                "source_ref_id": "source-1",
                "status": "ambiguous",
                "evidence": "process-based life cycle inventory",
                "notes": "Source contains related evidence, but not all required semantic facts were supported",
            },
        ],
    )
    _write_json(
        case_root / "sources/source-001/manifest.json",
        {
            "ref": {"source_id": "source-1"},
            "status": "extracted",
            "extracted_text_path": "extracted.md",
        },
    )
    (case_root / "sources/source-001/extracted.md").write_text(
        "# Page 3\n\nrotor diameter of 151 meters",
        encoding="utf-8",
    )

    summary = semantic_review(
        "review-1",
        root=tmp_path,
        batch_id="20260707-member",
        case_store=store,
    )

    assert summary["conclusion"] == "不通过"
    assert summary["platform_conclusion"] == "rejected"
    assert summary["summary"]["blocking"] == 2
    assert summary["source_consistency"]["conclusion"] == "不一致"
    assert summary["rule_compliance"]["conclusion"] == "不符合规则"
    assert summary["source_summary"]["check_status_counts"] == {
        "ambiguous": 1,
        "conflict": 1,
        "not_found": 1,
    }
    assert summary["source_summary"]["source_document_count"] == 1
    assert summary["agent_review"]["present"] is False
    assert summary["audit_completeness"]["complete"] is False
    assert "agent_review_missing" in summary["audit_completeness"]["missing"]

    semantic = json.loads((case_root / "reports/semantic-review.json").read_text(encoding="utf-8"))
    assert "skill/tiangong-lca-audit/references/process-audit.md" in {
        item["path"] for item in semantic["references_used"]
    }
    assert semantic["source_limitations"][0]["status"] == "not_found"
    assert any(item["status"] == "ambiguous" for item in semantic["source_limitations"])
    assert semantic["source_consistency"]["layer"] == "pdf_source_consistency"
    assert semantic["rule_compliance"]["layer"] == "rule_compliance"
    assert semantic["semantic_context_summary"]["source_document_count"] == 1
    finding_rule_ids = {item["rule_id"] for item in semantic["findings"]}
    assert "semantic.agent_review.missing" in finding_rule_ids
    assert "source.field.ambiguous" in finding_rule_ids
    context = json.loads((case_root / "reports/semantic-context.json").read_text(encoding="utf-8"))
    assert context["references"][0]["content"]
    assert context["rules"][0]["rule_ids"]
    assert context["agent_review_present"] is False
    assert "rotor diameter" in context["source_documents"][0]["text"]

    platform = json.loads(
        (case_root / "reports/audit-result.platform.json").read_text(encoding="utf-8")
    )
    assert platform["conclusion"] == "rejected"
    assert platform["summary"]["source_consistency"]["conclusion"] == "不一致"
    assert platform["summary"]["rule_compliance"]["conclusion"] == "不符合规则"
    assert all("not_found" not in item["title"] for item in platform["findings"])

    updated = store.get_case("review-1", batch_id="20260707-member")
    # Audit inputs are incomplete (no agent review), so the case must not be
    # promoted to reported.
    assert updated.status != "reported"
    assert updated.steps["semantic_reviewed"] is True
    assert updated.steps["reported"] is False
    assert updated.steps["platform_written"] is False
    assert "semantic_context" in updated.artifacts


def test_semantic_review_does_not_downgrade_saved_draft_case(tmp_path):
    _write_skill_contract_files(tmp_path)
    store = CaseStore(tmp_path / "cases")
    manifest = store.create_case(
        review_id="review-1",
        batch_id="20260707-member",
        dataset_id="dataset-1",
        version="01.01.000",
        dataset_type="process",
        name_zh="叶片制造",
    )
    manifest.status = "draft_saved"
    manifest.platform_state = "draft_saved"
    manifest.set_step("platform_written", True)
    store.write_case(manifest)
    case_root = tmp_path / "cases" / manifest.case_dir
    _write_json(
        case_root / "precheck/precheck.json",
        {
            "dataset_type": "process",
            "findings": [],
            "summary": {"blocking": 0, "advisory": 0, "manual_review": 0, "input_gap": 0},
        },
    )
    _write_json(case_root / "source-checks/checks.json", [])

    semantic_review(
        "review-1",
        root=tmp_path,
        batch_id="20260707-member",
        case_store=store,
    )

    updated = store.get_case("review-1", batch_id="20260707-member")
    assert updated.status == "draft_saved"
    assert updated.steps["semantic_reviewed"] is True
    assert updated.steps["platform_written"] is True


def test_semantic_review_surfaces_related_artifact_requirements(tmp_path):
    _write_skill_contract_files(tmp_path)
    store = CaseStore(tmp_path / "cases")
    manifest = store.create_case(
        review_id="review-1",
        batch_id="20260708-admin",
        dataset_id="dataset-1",
        version="01.01.000",
        dataset_type="process",
        name_zh="叶片制造",
    )
    case_root = tmp_path / "cases" / manifest.case_dir
    _write_json(
        case_root / "snapshots/dataset.raw.json",
        {"processDataSet": {"processInformation": {"dataSetInformation": {}}}},
    )
    _write_json(
        case_root / "precheck/precheck.json",
        {
            "dataset_type": "process",
            "findings": [],
            "summary": {"blocking": 0, "advisory": 0, "manual_review": 0, "input_gap": 0},
        },
    )
    _write_json(case_root / "source-checks/checks.json", [])
    _write_json(
        case_root / "sources/source-001/manifest.json",
        {
            "ref": {"source_id": "source-1"},
            "status": "extracted",
            "extracted_text_path": "extracted.md",
            "related_artifact_requirements": [
                {
                    "kind": "supplementary_material",
                    "reference": "Supplementary Table S8",
                    "status": "requires_followup",
                    "action": "Download Supplementary Table S8 before source judgment.",
                }
            ],
        },
    )
    (case_root / "sources/source-001/extracted.md").write_text(
        "See Supplementary Table S8 for blade material details.",
        encoding="utf-8",
    )

    semantic_review(
        "review-1",
        root=tmp_path,
        batch_id="20260708-admin",
        case_store=store,
    )

    semantic = json.loads((case_root / "reports/semantic-review.json").read_text(encoding="utf-8"))
    assert any(
        item["rule_id"] == "source.related_artifact.requires_followup"
        and "Supplementary Table S8" in item["evidence"]
        for item in semantic["findings"]
    )


def test_complete_agent_review_and_matched_sources_allow_pass(tmp_path):
    _write_skill_contract_files(tmp_path)
    store, case_root = _create_clean_process_case(tmp_path)
    _write_json(
        case_root / "source-checks/claims.json",
        {"process.name.zh": "叶片制造", "process.time.referenceYear": "2024"},
    )
    _write_json(
        case_root / "source-checks/checks.json",
        [
            {
                "field": "process.name.zh",
                "dataset_value": "叶片制造",
                "source_ref_id": "source-1",
                "status": "matched",
                "evidence": "blade manufacture",
                "page": 3,
            },
            {
                "field": "process.time.referenceYear",
                "dataset_value": "2024",
                "source_ref_id": "source-1",
                "status": "matched",
                "evidence": "data collected in 2024",
                "page": 4,
            },
        ],
    )
    _write_agent_findings(case_root, verdict="pass")

    summary = semantic_review("review-1", root=tmp_path, batch_id="b-1", case_store=store)

    assert summary["agent_review"]["present"] is True
    assert summary["agent_review"]["valid"] is True
    assert summary["audit_completeness"]["complete"] is True
    assert summary["source_consistency"]["conclusion"] == "一致"
    assert summary["conclusion"] == "通过"
    assert summary["platform_conclusion"] == "approved"

    updated = store.get_case("review-1", batch_id="b-1")
    assert updated.status == "reported"
    assert updated.steps["reported"] is True
    assert updated.steps["agent_reviewed"] is True


def test_agent_fail_verdict_becomes_blocking_finding(tmp_path):
    _write_skill_contract_files(tmp_path)
    store, case_root = _create_clean_process_case(tmp_path)
    _write_json(case_root / "source-checks/checks.json", [
        {
            "field": "process.name.zh",
            "dataset_value": "叶片制造",
            "source_ref_id": "source-1",
            "status": "matched",
            "evidence": "blade manufacture",
        }
    ])
    overrides = {
        "process.type.boundary_match": {
            "verdict": "fail",
            "severity": "blocking",
            "location": "建模信息 / 数据集类型",
            "evidence": "数据集类型为 LCI result，但清单为单一未聚合过程。",
            "judgment": "数据集类型与边界证据不匹配。",
            "suggestion": "改为 Unit process 或补充聚合层级证据。",
            "evidence_refs": ["snapshots/dataset.raw.json"],
        }
    }
    _write_agent_findings(case_root, verdict="pass", overrides=overrides)

    summary = semantic_review("review-1", root=tmp_path, batch_id="b-1", case_store=store)

    assert summary["conclusion"] == "不通过"
    semantic = json.loads((case_root / "reports/semantic-review.json").read_text(encoding="utf-8"))
    finding = next(
        item for item in semantic["findings"]
        if item["rule_id"] == "process.type.boundary_match"
    )
    assert finding["severity"] == "blocking"
    assert finding["source"].startswith("agent-review")
    platform = json.loads(
        (case_root / "reports/audit-result.platform.json").read_text(encoding="utf-8")
    )
    assert any(
        item["rule_id"] == "process.type.boundary_match" for item in platform["findings"]
    )


def test_ambiguous_and_unverified_core_claims_cap_conclusion(tmp_path):
    _write_skill_contract_files(tmp_path)
    store, case_root = _create_clean_process_case(tmp_path)
    _write_json(
        case_root / "source-checks/claims.json",
        {
            "process.name.zh": "叶片制造",
            "process.geography.location.zh": "江苏如东",
            "process.exchange.input.1.flow_type": "Product flow",
        },
    )
    _write_json(
        case_root / "source-checks/checks.json",
        [
            {
                "field": "process.name.zh",
                "dataset_value": "叶片制造",
                "source_ref_id": "source-1",
                "status": "ambiguous",
                "evidence": "wind turbine blade production",
            }
        ],
    )
    _write_agent_findings(case_root, verdict="pass")

    summary = semantic_review("review-1", root=tmp_path, batch_id="b-1", case_store=store)

    # Even with a complete agent review, ambiguous plus unverified core claims
    # must keep the overall conclusion away from 通过.
    assert summary["conclusion"] == "需人工确认"
    semantic = json.loads((case_root / "reports/semantic-review.json").read_text(encoding="utf-8"))
    rule_ids = {item["rule_id"] for item in semantic["findings"]}
    assert "source.field.ambiguous" in rule_ids
    assert "source.core_claim.unverified" in rule_ids
    core_finding = next(
        item for item in semantic["findings"] if item["rule_id"] == "source.core_claim.unverified"
    )
    # Exchange metadata fields never appear in papers; they must not be
    # counted as unverified core facts.
    assert "flow_type" not in core_finding["evidence"]
    assert "process.geography.location.zh" in core_finding["evidence"]


def test_overall_conclusion_never_beats_source_layer(tmp_path):
    _write_skill_contract_files(tmp_path)
    store, case_root = _create_clean_process_case(tmp_path)
    # No checks at all: source layer is 证据不足/未核验 territory.
    _write_agent_findings(case_root, verdict="pass")

    summary = semantic_review("review-1", root=tmp_path, batch_id="b-1", case_store=store)

    assert summary["conclusion"] != "通过"
    assert summary["platform_conclusion"] != "approved"


def test_truncated_source_document_requires_read_acknowledgment(tmp_path):
    _write_skill_contract_files(tmp_path)
    store, case_root = _create_clean_process_case(
        tmp_path,
        extracted_text="A" * (MAX_CONTEXT_TEXT_CHARS + 100),
    )
    _write_json(case_root / "source-checks/checks.json", [
        {
            "field": "process.name.zh",
            "dataset_value": "叶片制造",
            "source_ref_id": "source-1",
            "status": "matched",
            "evidence": "blade manufacture",
        }
    ])
    _write_agent_findings(case_root, verdict="pass")

    summary = semantic_review("review-1", root=tmp_path, batch_id="b-1", case_store=store)
    semantic = json.loads((case_root / "reports/semantic-review.json").read_text(encoding="utf-8"))
    assert any(
        item["rule_id"] == "source.document.truncated_context"
        for item in semantic["findings"]
    )
    assert summary["conclusion"] == "需人工确认"

    # Acknowledging the full read clears the finding.
    _write_agent_findings(
        case_root,
        verdict="pass",
        source_documents_read=["sources/source-001/extracted.md"],
    )
    semantic_review("review-1", root=tmp_path, batch_id="b-1", case_store=store)
    semantic = json.loads((case_root / "reports/semantic-review.json").read_text(encoding="utf-8"))
    assert not any(
        item["rule_id"] == "source.document.truncated_context"
        for item in semantic["findings"]
    )


def test_invalid_agent_findings_block_pass_with_input_gap(tmp_path):
    _write_skill_contract_files(tmp_path)
    store, case_root = _create_clean_process_case(tmp_path)
    _write_json(case_root / "source-checks/checks.json", [
        {
            "field": "process.name.zh",
            "dataset_value": "叶片制造",
            "source_ref_id": "source-1",
            "status": "matched",
            "evidence": "blade manufacture",
        }
    ])
    # fail verdict without severity/suggestion/evidence_refs → contract errors
    payload = {
        "schema_version": "tiangong-audit-agent-findings-v1",
        "review_id": "review-1",
        "dataset_type": "process",
        "reviewed_by": "agent",
        "rule_reviews": [
            {"rule_id": rule_id, "verdict": "fail"}
            for rule_id in required_rule_ids("process")
        ],
        "additional_findings": [],
    }
    _write_json(case_root / "agent-review/agent-findings.json", payload)

    summary = semantic_review("review-1", root=tmp_path, batch_id="b-1", case_store=store)

    assert summary["agent_review"]["valid"] is False
    assert summary["conclusion"] in {"信息不足", "不通过"}
    semantic = json.loads((case_root / "reports/semantic-review.json").read_text(encoding="utf-8"))
    assert any(
        item["rule_id"] == "semantic.agent_review.invalid" for item in semantic["findings"]
    )


def _create_clean_process_case(tmp_path: Path, *, extracted_text: str = "blade manufacture 2024"):
    store = CaseStore(tmp_path / "cases")
    manifest = store.create_case(
        review_id="review-1",
        batch_id="b-1",
        dataset_id="dataset-1",
        version="01.01.000",
        dataset_type="process",
        name_zh="叶片制造",
        name_en="Blades manufacture",
    )
    case_root = tmp_path / "cases" / manifest.case_dir
    _write_json(
        case_root / "snapshots/dataset.raw.json",
        {"processDataSet": {"processInformation": {"dataSetInformation": {}}}},
    )
    _write_json(
        case_root / "precheck/precheck.json",
        {
            "dataset_type": "process",
            "findings": [],
            "summary": {"blocking": 0, "advisory": 0, "manual_review": 0, "input_gap": 0},
        },
    )
    _write_json(
        case_root / "sources/source-001/manifest.json",
        {
            "ref": {"source_id": "source-1"},
            "status": "extracted",
            "extracted_text_path": "extracted.md",
        },
    )
    (case_root / "sources/source-001/extracted.md").write_text(
        extracted_text, encoding="utf-8"
    )
    return store, case_root


def _write_agent_findings(
    case_root: Path,
    *,
    verdict: str = "pass",
    overrides: dict | None = None,
    source_documents_read: list[str] | None = None,
) -> None:
    overrides = overrides or {}
    rule_reviews = []
    for rule_id in required_rule_ids("process"):
        if rule_id in overrides:
            review = {"rule_id": rule_id, **overrides[rule_id]}
        else:
            review = {
                "rule_id": rule_id,
                "verdict": verdict,
                "location": "过程信息",
                "evidence": "字段与 source 摘录一致。",
                "judgment": "该规则在现有证据下满足。",
                "suggestion": "",
                "severity": "",
                "evidence_refs": ["sources/source-001/extracted.md:p3"],
            }
        rule_reviews.append(review)
    payload = {
        "schema_version": "tiangong-audit-agent-findings-v1",
        "review_id": "review-1",
        "dataset_id": "dataset-1",
        "dataset_type": "process",
        "reviewed_by": "agent",
        "source_documents_read": source_documents_read or [],
        "rule_reviews": rule_reviews,
        "additional_findings": [],
    }
    _write_json(case_root / "agent-review/agent-findings.json", payload)


def _write_skill_contract_files(root: Path) -> None:
    files = {
        "skill/tiangong-lca-audit/SKILL.md": "# Skill\n",
        "skill/tiangong-lca-audit/references/input-contract.md": "# Input\n",
        "skill/tiangong-lca-audit/references/audit-policy.md": "# Policy\n",
        "skill/tiangong-lca-audit/references/output-contract.md": "# Output\n",
        "skill/tiangong-lca-audit/references/process-audit.md": "# Process\n",
        "skill/tiangong-lca-audit/rules/common.json": {
            "schema_version": "rules-v1",
            "rules": [{"id": "common.language.semantic_consistency"}],
        },
        "skill/tiangong-lca-audit/rules/process.json": {
            "schema_version": "rules-v1",
            "dataset_type": "process",
            "rules": [{"id": "process.flow.semantic_match"}],
        },
    }
    for relative_path, value in files.items():
        path = root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(value, str):
            path.write_text(value, encoding="utf-8")
        else:
            path.write_text(json.dumps(value, ensure_ascii=False) + "\n", encoding="utf-8")


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _valid_v2_agent_payload(*, additional_findings=None, platform_overrides=None):
    return {
        "schema_version": "tiangong-audit-agent-findings-v2",
        "review_id": "review-1",
        "dataset_id": "dataset-1",
        "dataset_type": "process",
        "reviewed_by": "agent",
        "source_documents_read": [],
        "rule_reviews": [
            {
                "rule_id": rule_id,
                "verdict": "pass",
                "location": "过程信息",
                "evidence": "字段与 source 摘录一致。",
                "judgment": "该规则满足。",
                "suggestion": "",
                "severity": "",
                "evidence_refs": ["sources/source-001/extracted.md:p3"],
                "platform": {"disposition": "internal_only"},
            }
            for rule_id in required_rule_ids("process")
        ],
        "additional_findings": additional_findings or [],
        "platform_overrides": platform_overrides or [],
    }


def _minimal_semantic_result(findings, *, conclusion="不通过"):
    return {
        "review_task_id": "review-1",
        "dataset_id": "dataset-1",
        "dataset_type": "process",
        "version": "01.01.000",
        "conclusion": conclusion,
        "platform_conclusion": "rejected" if conclusion == "不通过" else "approved",
        "summary": {"blocking": 1, "advisory": 0, "manual_review": 0, "input_gap": 0},
        "source_consistency": {"conclusion": "一致"},
        "rule_compliance": {"conclusion": "不符合规则"},
        "agent_review": {"valid": True},
        "audit_completeness": {"complete": True},
        "source_summary": {},
        "report_note": "内部说明",
        "findings": findings,
    }


def test_generator_platform_opinion_has_one_required_and_two_suggestions(tmp_path):
    fixture = json.loads(
        (Path(__file__).parent / "fixtures/regressions/generator-platform-opinion.json")
        .read_text(encoding="utf-8")
    )
    _write_skill_contract_files(tmp_path)
    store, case_root = _create_clean_process_case(tmp_path)
    _write_json(case_root / "precheck/precheck.json", {
        "dataset_type": "process",
        "findings": [fixture["precheck_finding"]],
        "summary": {"blocking": 1, "advisory": 0, "manual_review": 0, "input_gap": 0},
    })
    _write_json(case_root / "source-checks/checks.json", fixture["source_checks"])
    payload = _valid_v2_agent_payload(additional_findings=fixture["additional_findings"])
    _write_json(case_root / "agent-review/agent-findings.json", payload)

    semantic_review("review-1", root=tmp_path, batch_id="b-1", case_store=store)
    semantic = json.loads(
        (case_root / "reports/semantic-review.json").read_text(encoding="utf-8")
    )
    platform = json.loads(
        (case_root / "reports/audit-result.platform.json").read_text(encoding="utf-8")
    )
    markdown = (case_root / "reports/semantic-review.md").read_text(encoding="utf-8")
    comment = platform["platform_comment"]

    assert semantic["agent_review"]["valid"] is True
    assert comment["valid"] is True
    assert [item["disposition"] for item in comment["findings"]] == [
        "required",
        "suggested",
        "suggested",
    ]
    for expected in fixture["expected_messages"]:
        assert expected in comment["opinion"]
        assert expected in markdown
    for excluded in ("钢材分类", "截断覆盖率", "DQR", "存疑字段"):
        assert excluded not in comment["opinion"]
        assert excluded not in markdown.split("## 平台退回意见", 1)[1]
    assert {
        "process.flow.steel_shape",
        "process.boundary.cutoff_coverage",
        "process.metadata.dqr_guidance",
    } <= {item["rule_id"] for item in semantic["findings"]}


def test_advisory_only_source_uncertainty_does_not_cap_result():
    checks = [{
        "field": "process.time.referenceYear", "dataset_value": "2014",
        "source_ref_id": "source-1", "status": "ambiguous", "severity": "advisory",
    }]
    source_review = _source_consistency_review(checks, [], [])
    assert source_review["conclusion"] == "基本一致，有建议补充"
    assert _reconcile_conclusion(
        "通过",
        source_consistency=source_review,
        rule_compliance={"conclusion": "符合规则"},
        audit_completeness={"complete": True},
    ) == "通过"


def test_mixed_source_statuses_follow_impact_priority():
    base = {"field": "a", "dataset_value": "v", "source_ref_id": "s"}
    cases = [
        ([{**base, "status": "matched"}], "一致"),
        ([{**base, "status": "ambiguous", "severity": "advisory"}], "基本一致，有建议补充"),
        ([{**base, "status": "ambiguous", "severity": "manual_review"}, {**base, "field": "b", "status": "ambiguous", "severity": "advisory"}], "需人工确认"),
        ([{**base, "status": "source_unavailable", "severity": "input_gap"}, {**base, "field": "b", "status": "ambiguous", "severity": "manual_review"}], "证据不足"),
        ([{**base, "status": "conflict", "severity": "blocking"}, {**base, "field": "b", "status": "source_unavailable", "severity": "input_gap"}], "不一致"),
    ]
    for checks, expected in cases:
        assert _source_consistency_review(checks, [], [])["conclusion"] == expected


def test_field_level_source_findings_are_not_duplicated_by_aggregate():
    checks = [{
        "field": "process.time.referenceYear", "dataset_value": "2014",
        "source_ref_id": "source-1", "status": "ambiguous", "severity": "manual_review",
    }]
    findings = _source_findings(checks, [], []) + _source_quality_findings(
        claims={}, source_checks=checks, source_documents=[], agent_review={}
    )
    assert len(findings) == 1
    assert findings[0]["location"] == "Source 核验 / process.time.referenceYear"


def test_same_source_field_gap_and_failed_artifact_are_counted_once():
    checks = [{
        "field": "process.time.referenceYear",
        "dataset_value": "2014",
        "source_ref_id": "source-1",
        "status": "extraction_failed",
        "severity": "input_gap",
    }]
    artifacts = [{
        "status": "extraction_failed",
        "ref": {"source_id": "source-1"},
        "error": "PDF extraction failed",
    }]
    findings = _source_findings(checks, artifacts, [])
    review = _source_consistency_review(checks, artifacts, [])

    assert len(findings) == 1
    assert findings[0]["origin"] == "source_check"
    assert review["conclusion"] == "证据不足"
    assert review["check_severity_counts"] == {"input_gap": 1}
    assert "1 个字段" in review["reason"]
    assert "0 个文档" in review["reason"]


def test_same_uri_source_gap_and_artifact_without_source_id_are_counted_once():
    uri = "https://example.invalid/source.pdf"
    checks = [{
        "field": "process.time.referenceYear",
        "dataset_value": "2014",
        "source_ref_id": uri,
        "status": "source_unavailable",
        "severity": "input_gap",
    }]
    artifacts = [{
        "status": "source_unavailable",
        "ref": {"uri": uri, "label": "论文附件"},
        "error": "source unavailable",
    }]

    findings = _source_findings(checks, artifacts, [])
    review = _source_consistency_review(checks, artifacts, [])

    assert len(findings) == 1
    assert review["conclusion"] == "证据不足"
    assert "1 个字段" in review["reason"]
    assert "0 个文档" in review["reason"]


def test_deterministic_advisory_override_merges_once():
    deterministic = _normalize_precheck_finding({
        "rule_id": "process.description.detail", "severity": "advisory",
        "location": "过程描述 / 技术说明", "evidence": "说明较短。",
        "judgment": "可读性可改善。", "suggestion": "补充一句关键工艺。",
    })
    payload = _valid_v2_agent_payload(platform_overrides=[{
        "rule_id": deterministic["rule_id"], "location": deterministic["location"],
        "platform": {"disposition": "suggested", "message": "建议补充一句关键工艺说明。"},
    }])
    findings, summary, merged = _agent_review_findings(
        payload, agent_review_present=True, dataset_type="process",
        deterministic_findings=[deterministic],
    )
    assert summary["valid"] is True
    assert findings == []
    assert "platform" not in deterministic
    assert merged[0]["platform"]["disposition"] == "suggested"
    required = _normalize_precheck_finding({
        "rule_id": "required", "severity": "blocking", "location": "类型",
        "evidence": "类型错误", "judgment": "需修改", "suggestion": "修改类型",
    })
    comment = build_platform_comment({"conclusion": "不通过", "findings": [required, *merged]})
    assert comment["opinion"].count("建议补充一句关键工艺说明") == 1


def test_platform_overrides_require_one_exact_target():
    finding = _normalize_precheck_finding({
        "rule_id": "rule.a", "severity": "advisory", "location": "位置 A",
        "evidence": "e", "judgment": "j", "suggestion": "s",
    })
    override = {
        "rule_id": "rule.a", "location": "位置 A",
        "platform": {"disposition": "suggested", "message": "建议处理。"},
    }
    scenarios = (
        ([finding], [{**override, "location": "不存在"}]),
        ([finding, deepcopy(finding)], [override]),
        ([finding], [override, deepcopy(override)]),
    )
    for deterministic, overrides in scenarios:
        _, summary, merged = _agent_review_findings(
            _valid_v2_agent_payload(platform_overrides=overrides),
            agent_review_present=True,
            dataset_type="process",
            deterministic_findings=deterministic,
        )
        assert summary["valid"] is False
        assert all("platform" not in item for item in merged)


def test_platform_result_keeps_evidence_and_adds_platform_comment():
    finding = _normalize_precheck_finding({
        "rule_id": "process.type", "severity": "blocking", "location": "数据集类型",
        "evidence": "类型和边界不一致", "judgment": "必须修改", "suggestion": "修改类型",
    })
    platform = _platform_result(_minimal_semantic_result([finding]))
    assert platform["platform_comment"]["valid"] is True
    assert platform["platform_comment"]["findings"][0]["disposition"] == "required"
    assert platform["findings"][0]["evidence"] == "类型和边界不一致"


def test_platform_result_rejects_inconsistent_platform_conclusion():
    finding = _normalize_precheck_finding({
        "rule_id": "process.type", "severity": "blocking", "location": "数据集类型",
        "evidence": "类型错误", "judgment": "必须修改", "suggestion": "修改类型",
    })
    result = _minimal_semantic_result([finding])
    result["platform_conclusion"] = "approved"
    with pytest.raises(ValueError, match="platform_conclusion"):
        _platform_result(result)


def test_invalid_source_checks_create_validation_origin_and_invalid_comment(tmp_path):
    _write_skill_contract_files(tmp_path)
    store, case_root = _create_clean_process_case(tmp_path)
    _write_json(case_root / "precheck/precheck.json", {
        "dataset_type": "process",
        "findings": [{"rule_id": "process.type", "severity": "blocking", "location": "类型", "evidence": "类型错误", "judgment": "必须修改", "suggestion": "修改类型"}],
        "summary": {"blocking": 1, "advisory": 0, "manual_review": 0, "input_gap": 0},
    })
    _write_json(case_root / "source-checks/checks.json", [
        {
            "field": "process.name.zh", "dataset_value": "叶片制造", "source_ref_id": "source-1",
            "status": "conflict", "evidence": "另一个过程名称",
        },
        {
            "field": "process.time.referenceYear", "dataset_value": "2024", "source_ref_id": "source-1",
            "status": "matched", "severity": "blocking",
        },
    ])
    _write_agent_findings(case_root)
    semantic_review("review-1", root=tmp_path, batch_id="b-1", case_store=store)
    semantic = json.loads((case_root / "reports/semantic-review.json").read_text(encoding="utf-8"))
    invalid = next(item for item in semantic["findings"] if item["origin"] == "validation")
    assert invalid["rule_id"] == "source.checks.invalid"
    assert any(item["rule_id"] == "source.field.conflict" for item in semantic["findings"])
    assert semantic["source_summary"]["check_count"] == 1
    assert semantic["source_consistency"]["conclusion"] == "不一致"
    platform = json.loads((case_root / "reports/audit-result.platform.json").read_text(encoding="utf-8"))
    assert platform["platform_comment"]["valid"] is False


def test_every_finding_construction_path_assigns_controlled_origin():
    deterministic = _normalize_precheck_finding({"rule_id": "d", "severity": "advisory"})
    agent, _, _ = _agent_review_findings(
        _valid_v2_agent_payload(additional_findings=[{
            "rule_id": "a", "severity": "advisory", "location": "a", "evidence": "e",
            "judgment": "j", "suggestion": "s", "source": "agent-review",
            "evidence_refs": ["x"], "platform": {"disposition": "internal_only"},
        }]), agent_review_present=True, dataset_type="process",
    )
    source = _source_findings([
        {"field": "x", "dataset_value": "x", "source_ref_id": "s", "status": "conflict"}
    ], [], [])
    context = _source_quality_findings(
        claims={}, source_checks=[],
        source_documents=[{"truncated": True, "path": "x", "source_ref_id": "s"}],
        agent_review={},
    )
    semantic_context = _source_quality_findings(
        claims={"process.geography.location.zh": "江苏"},
        source_checks=[],
        source_documents=[{"truncated": False, "path": "x", "source_ref_id": "s"}],
        agent_review={},
    )
    extraction = _source_findings([], [{
        "status": "extraction_failed", "ref": {"source_id": "s"}, "error": "bad pdf"
    }], [])
    workflow, _, _ = _agent_review_findings(
        {}, agent_review_present=False, dataset_type="process"
    )
    validation, _, _ = _agent_review_findings(
        {}, agent_review_present=True, dataset_type="process"
    )
    assert deterministic["origin"] == "deterministic"
    assert agent[0]["origin"] == "agent"
    assert source[0]["origin"] == "source_check"
    assert context[0]["origin"] == "extraction"
    assert semantic_context[0]["origin"] == "semantic_context"
    assert extraction[0]["origin"] == "extraction"
    assert workflow[0]["origin"] == "workflow"
    assert validation[0]["origin"] == "validation"
