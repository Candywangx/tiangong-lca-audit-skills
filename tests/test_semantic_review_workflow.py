from __future__ import annotations

import json
from pathlib import Path

import pytest

from tiangong_audit.case_store import CaseStore
from tiangong_audit.contracts.agent_review import required_rule_ids
from tiangong_audit.workflows import semantic_review
from tiangong_audit.workflows.semantic_review import MAX_CONTEXT_TEXT_CHARS
from tiangong_audit.workflows.semantic_review import _source_conflict_severity
from tiangong_audit.workflows.title_duplicate import check_title_duplicates


def test_semantic_review_stops_without_title_duplicate_check(tmp_path):
    _write_skill_contract_files(tmp_path)
    store, case_root = _create_clean_process_case(tmp_path)
    (case_root / "snapshots/title-duplicate-check.json").unlink()

    with pytest.raises(ValueError, match="题目查重"):
        semantic_review("review-1", root=tmp_path, batch_id="b-1", case_store=store)

    assert not (case_root / "reports/semantic-review.json").exists()


def test_authored_platform_opinions_round_trip_without_changing_audit_findings(tmp_path):
    _write_skill_contract_files(tmp_path)
    store, case_root = _create_clean_process_case(tmp_path)
    issue = {
        "verdict": "fail", "severity": "blocking", "location": "参考流 / 单位",
        "evidence": "来源第 3 页为 kg，录入单位为 t。", "judgment": "单位不符。",
        "suggestion": "请修正单位。", "evidence_refs": ["sources/source-001/extracted.md:p3"],
    }
    rule_id = required_rule_ids("process")[0]
    _write_agent_findings(case_root, overrides={rule_id: issue})
    _write_json(case_root / "precheck/precheck.json", {
        "dataset_type": "process", "findings": [{"rule_id": "process.units", **issue}],
    })
    _write_json(case_root / "source-checks/checks.json", [{
        "field": "process.reference_flow.unit", "status": "conflict",
        "source_ref_id": "source-1", "dataset_value": "t", "evidence": "kg", "page": 3,
    }])
    baseline = semantic_review("review-1", root=tmp_path, batch_id="b-1", case_store=store)
    baseline_result = json.loads((case_root / "reports/semantic-review.json").read_text())
    authored = [{
        "severity": "blocking", "text": "参考流单位与来源第 3 页不一致。请按 kg 基准核对并修正清单。",
        "finding_refs": [
            {"path": "agent-review/agent-findings.json", "pointer": "/rule_reviews/0"},
            {"path": "precheck/precheck.json", "pointer": "/findings/0"},
            {"path": "source-checks/checks.json", "pointer": "/0"},
        ],
    }]
    _write_json(case_root / "agent-review/platform-opinions.json", {"items": authored})

    result = semantic_review("review-1", root=tmp_path, batch_id="b-1", case_store=store)
    semantic = json.loads((case_root / "reports/semantic-review.json").read_text())
    context = json.loads((case_root / "reports/semantic-context.json").read_text())
    platform = json.loads((case_root / "reports/audit-result.platform.json").read_text())
    markdown = (case_root / "reports/semantic-review.md").read_text()
    assert result["conclusion"] == baseline["conclusion"] == "不通过"
    assert semantic["findings"] == baseline_result["findings"]
    assert semantic["platform_opinions"] == context["platform_opinions"] == authored
    expected = "## 平台退回意见\n\n①【需修改】" + authored[0]["text"] + "\n"
    assert markdown.endswith(expected)
    assert platform["auditor_notes"] == expected
    assert "sources" not in expected


def test_explicit_input_gap_is_preserved_and_blank_cannot_judge_is_not_promoted(tmp_path):
    _write_skill_contract_files(tmp_path)
    store, case_root = _create_clean_process_case(tmp_path)
    ids = required_rule_ids("process")
    _write_agent_findings(case_root, overrides={
        ids[0]: {
            "verdict": "cannot_judge", "severity": "input_gap", "location": "参考流 / 折算依据",
            "evidence": "尚未提供产品质量与体积的折算依据。", "judgment": "目前无法核对清单基准。",
            "suggestion": "请提供密度及其来源。", "evidence_refs": ["snapshots/dataset.raw.json"],
        },
        ids[1]: {"verdict": "cannot_judge", "judgment": "原文待读取。", "severity": ""},
    })
    authored = [{
        "severity": "input_gap", "text": "产品清单缺少质量与体积的折算依据。请提供密度及其来源。",
        "finding_refs": [{"path": "agent-review/agent-findings.json", "pointer": "/rule_reviews/0"}],
    }]
    _write_json(case_root / "agent-review/platform-opinions.json", {"items": authored})

    semantic_review("review-1", root=tmp_path, batch_id="b-1", case_store=store)
    semantic = json.loads((case_root / "reports/semantic-review.json").read_text())
    findings = {item["rule_id"]: item for item in semantic["findings"]}
    assert findings[ids[0]]["severity"] == "input_gap"
    assert findings[ids[1]]["severity"] == "manual_review"
    opinion = (case_root / "reports/semantic-review.md").read_text().split("## 平台退回意见", 1)[1]
    assert "①【需补充】" in opinion
    assert "【需确认】" not in opinion


@pytest.mark.parametrize("payload", [None, [], {}, {"items": "invalid"}, {"items": [{
    "severity": "blocking", "text": "无法核验的意见。", "finding_refs": [
        {"path": "agent-review/agent-findings.json", "pointer": "/rule_reviews/0"},
    ],
}]}])
def test_invalid_authored_opinion_file_fails_before_replacing_reports(tmp_path, payload):
    _write_skill_contract_files(tmp_path)
    store, case_root = _create_clean_process_case(tmp_path)
    _write_agent_findings(case_root)
    semantic_review("review-1", root=tmp_path, batch_id="b-1", case_store=store)
    report = case_root / "reports/semantic-review.md"
    previous = report.read_bytes()
    _write_json(case_root / "agent-review/platform-opinions.json", payload)
    with pytest.raises(ValueError):
        semantic_review("review-1", root=tmp_path, batch_id="b-1", case_store=store)
    assert report.read_bytes() == previous


def test_source_tool_failures_remain_internal_with_authored_opinions(tmp_path):
    _write_skill_contract_files(tmp_path)
    store, case_root = _create_clean_process_case(tmp_path)
    _write_agent_findings(case_root)
    _write_json(case_root / "sources/source-001/manifest.json", {
        "ref": {"source_id": "source-1"}, "status": "extraction_failed", "error": "tool timeout",
    })
    _write_json(case_root / "agent-review/platform-opinions.json", {"items": []})
    semantic_review("review-1", root=tmp_path, batch_id="b-1", case_store=store)
    semantic = json.loads((case_root / "reports/semantic-review.json").read_text())
    tool_finding = next(item for item in semantic["findings"] if item["rule_id"] == "source.artifact.unavailable")
    assert tool_finding["platform_actionable"] is False
    platform = json.loads((case_root / "reports/audit-result.platform.json").read_text())
    assert platform["auditor_notes"] == "## 平台退回意见\n\n无\n"


@pytest.mark.parametrize("invalid", [False, "missing", "wrong_severity", "passed_rule"])
def test_source_conflict_severity_requires_matching_valid_agent_finding(tmp_path, invalid):
    _write_skill_contract_files(tmp_path)
    store, case_root = _create_clean_process_case(tmp_path)
    rule_id = required_rule_ids("process")[0]
    _write_agent_findings(case_root, overrides={rule_id: {
        "verdict": "fail", "severity": "advisory", "location": "描述 / 覆盖范围",
        "evidence": "来源仅说明费用比例。", "judgment": "该比例的描述需澄清。",
        "suggestion": "请改为费用比例。", "evidence_refs": ["sources/source-001/extracted.md:p3"],
    }})
    extra = {"reviewed_severity": "advisory", "reviewed_finding_ref": {
        "path": "agent-review/agent-findings.json", "pointer": "/rule_reviews/0",
    }}
    if invalid == "missing":
        extra["reviewed_finding_ref"]["pointer"] = "/rule_reviews/404"
    elif invalid == "wrong_severity":
        extra["reviewed_severity"] = "blocking"
    elif invalid == "passed_rule":
        extra["reviewed_finding_ref"]["pointer"] = "/rule_reviews/1"
    _write_json(case_root / "source-checks/checks.json", [{
        "field": "process.cutoff.zh", "status": "conflict", "source_ref_id": "source-1",
        "dataset_value": "覆盖比例", "evidence": "费用比例", "extra": extra,
    }])
    if invalid:
        with pytest.raises(ValueError, match="reviewed"):
            semantic_review("review-1", root=tmp_path, batch_id="b-1", case_store=store)
        return
    semantic_review("review-1", root=tmp_path, batch_id="b-1", case_store=store)
    semantic = json.loads((case_root / "reports/semantic-review.json").read_text())
    derived = next(item for item in semantic["findings"] if item["rule_id"] == "source.field.conflict")
    assert derived["severity"] == "advisory"
    assert derived["reviewed_finding_ref"] == extra["reviewed_finding_ref"]
    assert semantic["source_consistency"]["conclusion"] == "不一致"
    assert semantic["source_consistency"]["blocking_conflict_count"] == 0
    assert semantic["source_consistency"]["advisory_conflict_count"] == 1
    assert semantic["conclusion"] == "通过"


@pytest.mark.parametrize("status, conclusion", [("conflict", "不通过"), ("ambiguous", "需人工确认"), ("not_found", "需人工确认")])
def test_reviewed_advisory_does_not_remove_other_source_limits(tmp_path, status, conclusion):
    _write_skill_contract_files(tmp_path)
    store, case_root = _create_clean_process_case(tmp_path)
    _write_agent_findings(case_root, overrides={required_rule_ids("process")[0]: {
        "verdict": "fail", "severity": "advisory", "location": "描述 / 范围",
        "evidence": "来源使用不同描述。", "judgment": "需澄清描述。", "suggestion": "请澄清描述。",
        "evidence_refs": ["sources/source-001/extracted.md:p3"],
    }})
    _write_json(case_root / "source-checks/checks.json", [
        {"field": "process.cutoff.zh", "status": "conflict", "source_ref_id": "source-1",
         "evidence": "来源中的范围", "extra": {"reviewed_severity": "advisory", "reviewed_finding_ref": {
             "path": "agent-review/agent-findings.json", "pointer": "/rule_reviews/0",
         }}},
        {"field": "process.time.referenceYear", "status": status,
         "dataset_value": "2024", "source_ref_id": "source-1", "evidence": "2023"},
    ])
    summary = semantic_review("review-1", root=tmp_path, batch_id="b-1", case_store=store)
    assert summary["conclusion"] == conclusion


@pytest.mark.parametrize("origin", ["precheck", "agent", "additional"])
@pytest.mark.parametrize("severity", ["unknown", "", None])
def test_unknown_source_severity_cannot_be_laundered_into_a_manual_opinion(tmp_path, origin, severity):
    _write_skill_contract_files(tmp_path)
    store, case_root = _create_clean_process_case(tmp_path)
    issue = {"severity": severity, "location": "产品 / 单位", "evidence": "单位待核实。",
             "judgment": "单位不明确。", "suggestion": "请核对单位。"}
    if origin == "agent":
        _write_agent_findings(case_root, overrides={required_rule_ids("process")[0]: {
            **issue, "verdict": "cannot_judge",
        }})
        ref = {"path": "agent-review/agent-findings.json", "pointer": "/rule_reviews/0"}
    elif origin == "additional":
        _write_agent_findings(case_root)
        path = case_root / "agent-review/agent-findings.json"
        payload = json.loads(path.read_text())
        payload["additional_findings"] = [{"rule_id": "process.example", **issue}]
        _write_json(path, payload)
        ref = {"path": "agent-review/agent-findings.json", "pointer": "/additional_findings/0"}
    else:
        _write_agent_findings(case_root)
        _write_json(case_root / "precheck/precheck.json", {"dataset_type": "process", "findings": [issue]})
        ref = {"path": "precheck/precheck.json", "pointer": "/findings/0"}
    _write_json(case_root / "agent-review/platform-opinions.json", {"items": [{
        "severity": "manual_review", "text": "单位待核实。请核对单位。", "finding_refs": [ref],
    }]})
    with pytest.raises(ValueError, match="severity|actionable"):
        semantic_review("review-1", root=tmp_path, batch_id="b-1", case_store=store)


def test_agent_authored_source_issue_is_not_confused_with_a_tool_limitation(tmp_path):
    _write_skill_contract_files(tmp_path)
    store, case_root = _create_clean_process_case(tmp_path)
    _write_agent_findings(case_root)
    path = case_root / "agent-review/agent-findings.json"
    payload = json.loads(path.read_text())
    payload["additional_findings"] = [{
        "rule_id": "source.identity.clarify", "severity": "advisory", "location": "来源 / 署名",
        "evidence": "来源作者姓名缺少中间名。", "judgment": "补齐署名便于检索。", "suggestion": "请补齐姓名。",
    }]
    _write_json(path, payload)
    authored = [{"severity": "advisory", "text": "来源作者姓名缺少中间名。请补齐姓名，便于检索。", "finding_refs": [
        {"path": "agent-review/agent-findings.json", "pointer": "/additional_findings/0"},
    ]}]
    _write_json(case_root / "agent-review/platform-opinions.json", {"items": authored})
    semantic_review("review-1", root=tmp_path, batch_id="b-1", case_store=store)
    platform = json.loads((case_root / "reports/audit-result.platform.json").read_text())
    assert platform["auditor_notes"].endswith("①【建议优化】" + authored[0]["text"] + "\n")


@pytest.mark.parametrize("override_source", [False, True])
def test_cannot_judge_advisory_cannot_approve_or_downgrade_source_conflict(tmp_path, override_source):
    _write_skill_contract_files(tmp_path)
    store, case_root = _create_clean_process_case(tmp_path)
    _write_agent_findings(case_root, overrides={required_rule_ids("process")[0]: {
        "verdict": "cannot_judge", "severity": "advisory", "judgment": "尚未核实该规则。",
    }})
    check = {"field": "process.name.zh", "status": "matched", "source_ref_id": "source-1", "evidence": "产品"}
    if override_source:
        check.update({"status": "conflict", "extra": {
            "reviewed_severity": "advisory", "reviewed_finding_ref": {
                "path": "agent-review/agent-findings.json", "pointer": "/rule_reviews/0",
            },
        }})
    _write_json(case_root / "source-checks/checks.json", [check])
    with pytest.raises(ValueError, match="cannot_judge"):
        semantic_review("review-1", root=tmp_path, batch_id="b-1", case_store=store)


def test_source_override_requires_original_fail_verdict_not_just_normalized_severity():
    ref = {"path": "agent-review/agent-findings.json", "pointer": "/rule_reviews/0"}
    check = {"extra": {"reviewed_severity": "advisory", "reviewed_finding_ref": ref}}
    pending = {"finding_ref": ref, "severity": "advisory", "verdict": "cannot_judge"}
    with pytest.raises(ValueError, match="reviewed"):
        _source_conflict_severity(check, [pending])


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
    _write_clear_title_check(case_root)
    _write_json(
        case_root / "snapshots/dataset.raw.json",
        {"processDataSet": {"processInformation": {"dataSetInformation": {
            "name": {"baseName": [{"@xml:lang": "zh", "#text": "叶片制造"}]}
        }}}},
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
    _write_clear_title_check(case_root)
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
    _write_clear_title_check(case_root)
    _write_json(
        case_root / "snapshots/dataset.raw.json",
        {"processDataSet": {"processInformation": {"dataSetInformation": {
            "name": {"baseName": [{"@xml:lang": "zh", "#text": "叶片制造"}]}
        }}}},
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


def _write_clear_title_check(case_root: Path) -> None:
    row = {
        "id": "dataset-1", "version": "01.01.000",
        "json": {"processDataSet": {"processInformation": {"dataSetInformation": {
            "name": {"baseName": [{"@xml:lang": "zh", "#text": "叶片制造"}]}
        }}}},
    }

    class SearchAPI:
        def search_title(self, dataset_type, language, title):
            return [row]

    check = check_title_duplicates(row, "process", SearchAPI())
    _write_json(case_root / "snapshots/title-duplicate-check.json", check)
    _write_json(case_root / "snapshots/dataset.raw.json", row["json"])


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
    _write_clear_title_check(case_root)
    _write_json(
        case_root / "snapshots/dataset.raw.json",
        {"processDataSet": {"processInformation": {"dataSetInformation": {
            "name": {"baseName": [{"@xml:lang": "zh", "#text": "叶片制造"}]}
        }}}},
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
