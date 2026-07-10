import json
from pathlib import Path

from tiangong_audit.rule_engine import (
    RUNTIME_RULE_BINDINGS,
    runtime_rule_ids,
    validate_guardrails,
)

ROOT = Path(__file__).resolve().parents[1]
RULES = ROOT / "skill/tiangong-lca-audit/rules"
REQUIRED_RULE_FIELDS = {
    "id",
    "dimension",
    "rule_type",
    "severity",
    "condition",
    "evidence_required",
    "decision",
    "suggestion",
    "exceptions",
}
VALID_RULE_TYPES = {"deterministic", "judgment"}
VALID_SEVERITIES = {"blocking", "advisory", "manual_review", "input_gap"}
CFIA_SOURCE = "CFIA-LCA-database-guideline"


def load_rules():
    rule_paths = [RULES / name for name in ("common.json", "process.json", "model.json")]
    return [json.loads(path.read_text(encoding="utf-8")) for path in rule_paths]


def test_rule_catalog_is_single_and_structured():
    payloads = load_rules()
    assert {payload["dataset_type"] for payload in payloads} == {"all", "process", "model"}

    ids = []
    for payload in payloads:
        assert payload["schema_version"] == "1.0"
        for rule in payload["rules"]:
            assert REQUIRED_RULE_FIELDS <= rule.keys()
            assert rule["rule_type"] in VALID_RULE_TYPES
            assert rule["severity"] in VALID_SEVERITIES
            assert rule["evidence_required"]
            for ref in rule.get("standard_refs", []):
                assert ref["source"] == CFIA_SOURCE
                assert ref["file"].endswith(".md")
                assert ref["sections"]
            ids.append(rule["id"])

    assert len(ids) == len(set(ids))


def test_rule_catalog_has_explicit_schema_asset():
    schema = json.loads((RULES / "schema.json").read_text(encoding="utf-8"))

    assert schema["title"] == "Tiangong LCA Audit Rule Catalog"
    assert "rule" in schema["$defs"]
    required_rule_fields = set(schema["$defs"]["rule"]["required"])
    assert REQUIRED_RULE_FIELDS <= required_rule_fields


def test_process_and_model_define_core_dimensions():
    payloads = {payload["dataset_type"]: payload for payload in load_rules()}
    assert len(payloads["process"]["core_dimensions"]) >= 5
    assert len(payloads["model"]["core_dimensions"]) >= 4


def test_process_rules_cover_source_content_attribution():
    payloads = {payload["dataset_type"]: payload for payload in load_rules()}
    rule_ids = {rule["id"] for rule in payloads["process"]["rules"]}
    assert "process.description.source_content_attribution" in rule_ids
    assert "process.source.document_availability" in rule_ids
    assert "process.source.field_conflict" in rule_ids
    assert "process.source.field_not_supported" in rule_ids


def test_classification_rules_require_candidate_paths_or_ranges():
    process_rules = {
        rule["id"]: rule
        for payload in load_rules()
        if payload["dataset_type"] == "process"
        for rule in payload["rules"]
    }
    for rule_id in ("process.flow.semantic_match", "process.classification.process_fit"):
        rule = process_rules[rule_id]
        evidence = " ".join(rule["evidence_required"])
        suggestion = rule["suggestion"]
        assert "searched classification candidates" in evidence
        assert "candidate classification paths or candidate ranges" in suggestion


def test_process_rules_cover_cfia_guideline_gaps():
    process_rules = {
        rule["id"]: rule
        for payload in load_rules()
        if payload["dataset_type"] == "process"
        for rule in payload["rules"]
    }
    expected = {
        "process.type.partly_terminated_evidence": "02-数据集组成.md",
        "process.boundary.lifecycle_stage_contradiction": "03-数据收集.md",
        "process.recycling.secondary_material_burden": "03-数据收集.md",
        "process.allocation.method_traceability": "03-数据收集.md",
        "process.boundary.cutoff_placeholder": "04-数据文档.md",
        "process.flow.purchased_elementary_input_role": "02-数据集组成.md",
        "process.flow.version_identity": "04-数据文档.md",
        "process.flow.form_unit_consistency": "04-数据文档.md",
        "process.inventory.water_balance_boundary": "05-数据质量评价方法.md",
        "process.metadata.dqr_completeness": "05-数据质量评价方法.md",
        "process.metadata.review_report_traceability": "04-数据文档.md",
    }
    for rule_id, source_file in expected.items():
        assert rule_id in process_rules
        files = {ref["file"] for ref in process_rules[rule_id].get("standard_refs", [])}
        assert source_file in files


def test_runtime_rule_bindings_point_to_registered_rules():
    rule_ids = {
        rule["id"]
        for payload in load_rules()
        for rule in payload["rules"]
    }

    assert RUNTIME_RULE_BINDINGS
    assert runtime_rule_ids() <= rule_ids


def test_guardrail_catalog_is_structurally_valid():
    payload = json.loads((RULES / "guardrails.json").read_text(encoding="utf-8"))
    assert validate_guardrails(payload) == []
    # Guardrails are case-derived: every entry must name its origin case so a
    # future maintainer can trace it back to the correction record.
    for entry in payload["guardrails"]:
        assert entry["origin_case"]
