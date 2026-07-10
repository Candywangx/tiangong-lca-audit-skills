from __future__ import annotations

import json
from pathlib import Path

from tiangong_audit.case_store import CaseStore
from tiangong_audit.contracts.agent_review import required_rule_ids
from tiangong_audit.workflows import semantic_review
from tiangong_audit.workflows.semantic_review import MAX_CONTEXT_TEXT_CHARS


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
    assert "source.check.ambiguous" in finding_rule_ids
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
    assert "source.check.ambiguous" in rule_ids
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
