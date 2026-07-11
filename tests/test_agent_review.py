from __future__ import annotations

import json
import tomllib
from pathlib import Path

import jsonschema

from tiangong_audit.contracts.agent_review import (
    AGENT_FINDINGS_SCHEMA_VERSION,
    AGENT_FINDINGS_SCHEMA_VERSION_V1,
    REQUIRED_AGENT_REVIEW_RULE_IDS,
    new_agent_findings_template,
    required_rule_ids,
    uncovered_required_rule_ids,
    validate_agent_findings,
)
from tiangong_audit.contracts.platform import (
    PLATFORM_ORIGINS,
    PlatformProjection,
    is_internal_blocking_origin,
    validate_platform_projection,
)

ROOT = Path(__file__).resolve().parents[1]


def _valid_payload(dataset_type: str = "process") -> dict:
    return {
        "schema_version": AGENT_FINDINGS_SCHEMA_VERSION,
        "review_id": "review-1",
        "dataset_id": "dataset-1",
        "dataset_type": dataset_type,
        "reviewed_by": "agent",
        "source_documents_read": ["sources/source-001/extracted.md"],
        "rule_reviews": [
            {
                "rule_id": rule_id,
                "verdict": "pass",
                "location": "过程信息",
                "evidence": "字段与 source 摘录一致。",
                "judgment": "满足规则。",
                "suggestion": "",
                "severity": "",
                "evidence_refs": ["sources/source-001/extracted.md:p3"],
            }
            for rule_id in required_rule_ids(dataset_type)
        ],
        "additional_findings": [],
    }


def test_valid_payload_passes_contract():
    assert validate_agent_findings(_valid_payload(), dataset_type="process") == []


def test_required_rule_ids_registered_in_rule_catalog():
    catalog_ids: set[str] = set()
    for name in ("common.json", "process.json", "model.json"):
        payload = json.loads(
            (ROOT / "skill/tiangong-lca-audit/rules" / name).read_text(encoding="utf-8")
        )
        catalog_ids.update(rule["id"] for rule in payload["rules"])
    for rule_ids in REQUIRED_AGENT_REVIEW_RULE_IDS.values():
        assert set(rule_ids) <= catalog_ids


def test_fail_verdict_requires_severity_suggestion_and_refs():
    payload = _valid_payload()
    payload["rule_reviews"][0].update(
        {"verdict": "fail", "severity": "", "suggestion": "", "evidence_refs": []}
    )
    errors = validate_agent_findings(payload, dataset_type="process")
    joined = "\n".join(errors)
    assert "requires severity" in joined
    assert "requires suggestion" in joined
    assert "requires evidence_refs" in joined


def test_pass_verdict_requires_evidence():
    payload = _valid_payload()
    payload["rule_reviews"][0]["evidence"] = ""
    errors = validate_agent_findings(payload, dataset_type="process")
    assert any("requires evidence" in error for error in errors)


def test_cannot_judge_requires_judgment():
    payload = _valid_payload()
    payload["rule_reviews"][0].update({"verdict": "cannot_judge", "judgment": ""})
    errors = validate_agent_findings(payload, dataset_type="process")
    assert any("requires judgment" in error for error in errors)


def test_missing_required_rule_is_reported():
    payload = _valid_payload()
    removed = payload["rule_reviews"].pop()
    errors = validate_agent_findings(payload, dataset_type="process")
    assert any(removed["rule_id"] in error for error in errors)
    assert removed["rule_id"] in uncovered_required_rule_ids(
        payload, dataset_type="process"
    )


def test_reviewed_by_is_required():
    payload = _valid_payload()
    payload["reviewed_by"] = ""
    errors = validate_agent_findings(payload, dataset_type="process")
    assert any("reviewed_by" in error for error in errors)


def test_additional_findings_must_be_complete():
    payload = _valid_payload()
    payload["additional_findings"] = [{"severity": "blocking", "location": "x"}]
    errors = validate_agent_findings(payload, dataset_type="process")
    assert any("evidence is required" in error for error in errors)


def test_template_covers_required_rules_and_fails_until_filled():
    template = new_agent_findings_template(
        review_id="review-1", dataset_id="dataset-1", dataset_type="process"
    )
    assert {item["rule_id"] for item in template["rule_reviews"]} == set(
        required_rule_ids("process")
    )
    assert validate_agent_findings(template, dataset_type="process")


def test_model_dataset_requires_linked_process_audit():
    payload = _valid_payload(dataset_type="model")
    assert validate_agent_findings(payload, dataset_type="model") == []
    payload["rule_reviews"] = []
    errors = validate_agent_findings(payload, dataset_type="model")
    assert any("model.linked_process.audit" in error for error in errors)


def test_agent_findings_schema_asset_matches_contract():
    schema = json.loads(
        (
            ROOT / "src/tiangong_audit/contracts/schemas/agent-findings.schema.json"
        ).read_text(encoding="utf-8")
    )
    assert schema["properties"]["schema_version"]["const"] == AGENT_FINDINGS_SCHEMA_VERSION
    verdicts = set(schema["$defs"]["rule_review"]["properties"]["verdict"]["enum"])
    assert verdicts == {"pass", "fail", "cannot_judge", "not_applicable"}


def test_v2_template_contains_internal_platform_and_empty_overrides():
    template = new_agent_findings_template(
        review_id="review-1", dataset_id="dataset-1", dataset_type="process"
    )
    assert template["schema_version"] == "tiangong-audit-agent-findings-v2"
    assert template["platform_overrides"] == []
    assert all(
        item["platform"] == {"disposition": "internal_only"}
        for item in template["rule_reviews"]
    )


def test_v1_agent_findings_remain_readable():
    payload = _valid_payload()
    payload["schema_version"] = AGENT_FINDINGS_SCHEMA_VERSION_V1
    for review in payload["rule_reviews"]:
        review.pop("platform", None)
    payload.pop("platform_overrides", None)
    assert validate_agent_findings(payload, dataset_type="process") == []


def test_platform_projection_requires_message_for_submitter_dispositions():
    for disposition in ("required", "clarification", "suggested"):
        errors = validate_platform_projection(
            "blocking" if disposition == "required" else "advisory",
            {"disposition": disposition, "message": "   "},
        )
        assert any("message" in error for error in errors)


def test_internal_only_projection_forbids_message():
    errors = validate_platform_projection(
        "advisory",
        {"disposition": "internal_only", "message": "do not send"},
    )
    assert any("forbids message" in error for error in errors)


def test_platform_projection_severity_disposition_matrix():
    valid = {
        "blocking": ("required",),
        "advisory": ("suggested", "internal_only"),
        "manual_review": ("clarification", "internal_only"),
        "input_gap": ("clarification", "internal_only"),
    }
    all_dispositions = {"required", "clarification", "suggested", "internal_only"}
    for severity, allowed in valid.items():
        for disposition in all_dispositions:
            payload = {"disposition": disposition}
            if disposition != "internal_only":
                payload["message"] = "请处理这一项。"
            errors = validate_platform_projection(severity, payload)
            assert (errors == []) is (disposition in allowed), (severity, disposition, errors)


def test_platform_projection_parser_and_controlled_origins():
    projection = PlatformProjection.from_dict(
        {"disposition": "suggested", "message": "  建议补充依据。  "}
    )
    assert projection.disposition == "suggested"
    assert projection.message == "建议补充依据。"
    assert PLATFORM_ORIGINS == {
        "agent",
        "deterministic",
        "source_check",
        "semantic_context",
        "validation",
        "extraction",
        "workflow",
    }
    assert is_internal_blocking_origin("validation")
    assert not is_internal_blocking_origin("agent")


def test_non_internal_projection_forbidden_on_pass_and_not_applicable_reviews():
    for verdict in ("pass", "not_applicable"):
        payload = _valid_payload()
        payload["rule_reviews"][0].update(
            {
                "verdict": verdict,
                "judgment": "不形成发现。",
                "platform": {"disposition": "suggested", "message": "建议改进。"},
            }
        )
        errors = validate_agent_findings(payload, dataset_type="process")
        assert any("non-internal" in error and verdict in error for error in errors)


def test_platform_override_requires_exact_target_shape_and_rejects_duplicates():
    payload = _valid_payload()
    payload["platform_overrides"] = [
        {
            "rule_id": "process.reference_year.preferred",
            "location": "时间代表性.referenceYear",
            "platform": {"disposition": "suggested", "message": "请核实参考年。"},
        },
        {
            "rule_id": "process.reference_year.preferred",
            "location": "时间代表性.referenceYear",
            "platform": {"disposition": "suggested", "message": "重复。"},
        },
    ]
    errors = validate_agent_findings(payload, dataset_type="process")
    assert any("duplicate override target" in error for error in errors)

    payload["platform_overrides"] = [
        {
            "rule_id": "process.reference_year.preferred",
            "platform": {"disposition": "suggested", "message": "请核实参考年。"},
        }
    ]
    errors = validate_agent_findings(payload, dataset_type="process")
    assert any("location is required" in error for error in errors)


def test_python_and_json_schema_accept_same_valid_v2_payload():
    payload = _valid_payload()
    payload["rule_reviews"][0].update(
        {
            "verdict": "fail",
            "severity": "advisory",
            "suggestion": "补充说明。",
            "platform": {"disposition": "suggested", "message": "建议补充说明。"},
        }
    )
    payload["platform_overrides"] = []
    schema = json.loads(
        (ROOT / "src/tiangong_audit/contracts/schemas/agent-findings.schema.json").read_text(
            encoding="utf-8"
        )
    )
    assert validate_agent_findings(payload, dataset_type="process") == []
    jsonschema.Draft202012Validator(schema).validate(payload)


def test_python_and_json_schema_reject_same_invalid_v2_payload():
    payload = _valid_payload()
    payload["rule_reviews"][0].update(
        {
            "verdict": "fail",
            "severity": "advisory",
            "suggestion": "补充说明。",
            "platform": {"disposition": "required", "message": "必须补充说明。"},
        }
    )
    payload["platform_overrides"] = []
    schema = json.loads(
        (ROOT / "src/tiangong_audit/contracts/schemas/agent-findings.schema.json").read_text(
            encoding="utf-8"
        )
    )
    assert any("required" in error for error in validate_agent_findings(payload))
    errors = list(jsonschema.Draft202012Validator(schema).iter_errors(payload))
    assert errors


def test_cannot_judge_uses_fixed_manual_review_projection_semantics():
    payload = _valid_payload()
    payload["rule_reviews"][0].update(
        {
            "verdict": "cannot_judge",
            "severity": "advisory",
            "judgment": "现有证据不足。",
            "platform": {"disposition": "internal_only"},
        }
    )
    schema = json.loads(
        (ROOT / "src/tiangong_audit/contracts/schemas/agent-findings.schema.json").read_text(
            encoding="utf-8"
        )
    )
    assert any(
        "cannot_judge" in error and "manual_review" in error
        for error in validate_agent_findings(payload)
    )
    assert list(jsonschema.Draft202012Validator(schema).iter_errors(payload))

    payload["rule_reviews"][0].update(
        {
            "severity": "",
            "platform": {
                "disposition": "clarification",
                "message": "请补充用于判断的事实依据。",
            },
        }
    )
    assert validate_agent_findings(payload) == []
    jsonschema.Draft202012Validator(schema).validate(payload)


def test_python_and_json_schema_reject_whitespace_only_platform_message():
    payload = _valid_payload()
    payload["rule_reviews"][0].update(
        {
            "verdict": "fail",
            "severity": "advisory",
            "suggestion": "补充说明。",
            "platform": {"disposition": "suggested", "message": " \t\n "},
        }
    )
    schema = json.loads(
        (ROOT / "src/tiangong_audit/contracts/schemas/agent-findings.schema.json").read_text(
            encoding="utf-8"
        )
    )
    assert any("message" in error for error in validate_agent_findings(payload))
    assert list(jsonschema.Draft202012Validator(schema).iter_errors(payload))


def test_python_and_json_schema_reject_severity_on_non_finding_verdicts():
    schema = json.loads(
        (ROOT / "src/tiangong_audit/contracts/schemas/agent-findings.schema.json").read_text(
            encoding="utf-8"
        )
    )
    for verdict in ("pass", "not_applicable"):
        payload = _valid_payload()
        payload["rule_reviews"][0].update(
            {
                "verdict": verdict,
                "severity": "advisory",
                "judgment": "不形成审核发现。",
                "platform": {"disposition": "internal_only"},
            }
        )
        assert any(
            verdict in error and "severity" in error
            for error in validate_agent_findings(payload)
        )
        assert list(jsonschema.Draft202012Validator(schema).iter_errors(payload))


def test_python_and_json_schema_reject_coerced_platform_field_types():
    schema = json.loads(
        (ROOT / "src/tiangong_audit/contracts/schemas/agent-findings.schema.json").read_text(
            encoding="utf-8"
        )
    )

    message_payload = _valid_payload()
    message_payload["rule_reviews"][0].update(
        {
            "verdict": "fail",
            "severity": "advisory",
            "suggestion": "补充说明。",
            "platform": {"disposition": "suggested", "message": 123},
        }
    )

    numeric_rule_id_payload = _valid_payload()
    numeric_rule_id_payload["platform_overrides"] = [
        {
            "rule_id": 123,
            "location": "时间代表性.referenceYear",
            "platform": {"disposition": "suggested", "message": "请核实参考年。"},
        }
    ]

    numeric_location_payload = _valid_payload()
    numeric_location_payload["platform_overrides"] = [
        {
            "rule_id": "process.reference_year.preferred",
            "location": 456,
            "platform": {"disposition": "suggested", "message": "请核实参考年。"},
        }
    ]

    for payload in (
        message_payload,
        numeric_rule_id_payload,
        numeric_location_payload,
    ):
        assert validate_agent_findings(payload)
        assert list(jsonschema.Draft202012Validator(schema).iter_errors(payload))


def test_python_and_json_schema_reject_platform_whitespace_mismatches():
    schema = json.loads(
        (ROOT / "src/tiangong_audit/contracts/schemas/agent-findings.schema.json").read_text(
            encoding="utf-8"
        )
    )

    padded_disposition = _valid_payload()
    padded_disposition["rule_reviews"][0].update(
        {
            "verdict": "fail",
            "severity": "advisory",
            "suggestion": "补充说明。",
            "platform": {"disposition": " suggested ", "message": "建议补充说明。"},
        }
    )

    blank_rule_id = _valid_payload()
    blank_rule_id["platform_overrides"] = [
        {
            "rule_id": "   ",
            "location": "时间代表性.referenceYear",
            "platform": {"disposition": "suggested", "message": "请核实参考年。"},
        }
    ]

    blank_location = _valid_payload()
    blank_location["platform_overrides"] = [
        {
            "rule_id": "process.reference_year.preferred",
            "location": "\t\n ",
            "platform": {"disposition": "suggested", "message": "请核实参考年。"},
        }
    ]

    for payload in (padded_disposition, blank_rule_id, blank_location):
        assert validate_agent_findings(payload)
        assert list(jsonschema.Draft202012Validator(schema).iter_errors(payload))


def test_jsonschema_is_declared_as_a_dev_dependency():
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert any(
        dependency.startswith("jsonschema")
        for dependency in project["project"]["optional-dependencies"]["dev"]
    )


def test_validator_returns_errors_for_invalid_evidence_refs_types():
    payload = _valid_payload()
    payload["rule_reviews"][0]["evidence_refs"] = 123
    errors = validate_agent_findings(payload)
    assert any("evidence_refs must be a list" in error for error in errors)

    payload = _valid_payload()
    payload["additional_findings"] = [
        {
            "rule_id": "custom.check",
            "severity": "advisory",
            "location": "字段",
            "evidence": "可见证据。",
            "judgment": "建议完善。",
            "suggestion": "补充说明。",
            "evidence_refs": [123],
        }
    ]
    errors = validate_agent_findings(payload)
    assert any("evidence_refs[1] must be a string" in error for error in errors)


def test_python_and_json_schema_reject_unknown_v2_fields():
    schema = json.loads(
        (ROOT / "src/tiangong_audit/contracts/schemas/agent-findings.schema.json").read_text(
            encoding="utf-8"
        )
    )
    payloads = []

    top_level = _valid_payload()
    top_level["unexpected"] = True
    payloads.append(top_level)

    rule_review = _valid_payload()
    rule_review["rule_reviews"][0]["unexpected"] = True
    payloads.append(rule_review)

    additional = _valid_payload()
    additional["additional_findings"] = [
        {
            "rule_id": "custom.check",
            "severity": "advisory",
            "location": "字段",
            "evidence": "可见证据。",
            "judgment": "建议完善。",
            "suggestion": "补充说明。",
            "unexpected": True,
        }
    ]
    payloads.append(additional)

    for payload in payloads:
        assert any("unknown properties" in error for error in validate_agent_findings(payload))
        assert list(jsonschema.Draft202012Validator(schema).iter_errors(payload))


def test_v1_rejects_v2_only_platform_fields():
    payload = _valid_payload()
    payload["schema_version"] = AGENT_FINDINGS_SCHEMA_VERSION_V1
    payload["platform_overrides"] = []
    payload["rule_reviews"][0]["platform"] = {"disposition": "internal_only"}
    payload["additional_findings"] = [
        {
            "rule_id": "custom.check",
            "severity": "advisory",
            "location": "字段",
            "evidence": "可见证据。",
            "judgment": "建议完善。",
            "suggestion": "补充说明。",
            "platform": {"disposition": "internal_only"},
        }
    ]
    errors = validate_agent_findings(payload)
    joined = "\n".join(errors)
    assert "platform_overrides" in joined and "v1" in joined
    assert "rule_reviews[1]" in joined and "platform" in joined and "v1" in joined
    assert "additional_findings[1]" in joined and "platform" in joined and "v1" in joined
