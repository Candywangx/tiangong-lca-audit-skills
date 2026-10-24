from __future__ import annotations

import json
from pathlib import Path

from tiangong_audit.contracts.agent_review import (
    AGENT_FINDINGS_SCHEMA_VERSION,
    REQUIRED_AGENT_REVIEW_RULE_IDS,
    new_agent_findings_template,
    required_rule_ids,
    uncovered_required_rule_ids,
    validate_agent_findings,
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


def test_admission_separates_file_and_record_errors_and_effective_coverage():
    from tiangong_audit.contracts.agent_review import admit_agent_findings
    payload = _valid_payload()
    payload["rule_reviews"][0]["evidence"] = ""
    result = admit_agent_findings(payload, dataset_type="process")
    assert result.file_errors == []
    assert set(result.rule_review_errors) == {0}
    assert 0 not in result.accepted_rule_review_indexes
    assert result.missing_required_rule_ids == [required_rule_ids("process")[0]]
    assert validate_agent_findings(payload, dataset_type="process") == result.errors
    payload["dataset_type"] = "model"
    fatal = admit_agent_findings(payload, dataset_type="process")
    assert fatal.file_errors
    assert fatal.accepted_rule_review_indexes == []
    assert fatal.missing_required_rule_ids == list(required_rule_ids("process"))


def test_admission_handles_malformed_containers_and_records():
    from tiangong_audit.contracts.agent_review import admit_agent_findings
    for malformed in (42, "bad", {}):
        payload = _valid_payload()
        payload["rule_reviews"] = malformed
        assert admit_agent_findings(payload, dataset_type="process").file_errors
    payload = _valid_payload()
    payload["rule_reviews"][0] = 42
    payload["additional_findings"] = [None]
    result = admit_agent_findings(payload, dataset_type="process")
    assert 0 in result.rule_review_errors
    assert 0 in result.additional_finding_errors
    assert result.accepted_additional_finding_indexes == []


def test_duplicate_reviews_do_not_count_as_coverage():
    from tiangong_audit.contracts.agent_review import admit_agent_findings
    payload = _valid_payload()
    payload["rule_reviews"].append(dict(payload["rule_reviews"][0]))
    result = admit_agent_findings(payload, dataset_type="process")
    assert 0 not in result.accepted_rule_review_indexes
    assert len(payload["rule_reviews"]) - 1 not in result.accepted_rule_review_indexes
    assert required_rule_ids("process")[0] in result.missing_required_rule_ids


def test_required_reviews_cannot_all_be_waived():
    payload = _valid_payload()
    for review in payload['rule_reviews']:
        review.update(verdict='not_applicable', judgment='已核查本项不适用。')
    assert validate_agent_findings(payload, dataset_type='process')
    assert 'process.object.consistency' in uncovered_required_rule_ids(payload, dataset_type='process')


def test_core_review_cannot_be_waived_even_with_evidence():
    payload = _valid_payload()
    review = payload['rule_reviews'][0]
    review.update(verdict='not_applicable', judgment='本案件对象有明确说明，因此请求豁免。')
    assert any('does not allow not_applicable' in error for error in validate_agent_findings(payload, dataset_type='process'))


def test_annual_supply_na_requires_evidence_and_reason_but_not_text_length():
    payload = _valid_payload()
    annual = next(item for item in payload['rule_reviews'] if item['rule_id'] == 'process.reference_flow.annual_supply_unit')
    annual.update(verdict='not_applicable', evidence='年产量与参考产量字段为空，技术说明未声明年供应量。基准输出为1 kg。', judgment='无产量声明；基准量已审。', evidence_refs=['snapshots/dataset.normalized.json#/reference_flow'])
    assert validate_agent_findings(payload, dataset_type='process') == []
    annual['evidence_refs'] = []
    assert any('requires evidence_refs' in error for error in validate_agent_findings(payload, dataset_type='process'))
    annual.update(verdict='cannot_judge', evidence='', judgment='未提供可读产量说明，无法确定适用性。')
    assert validate_agent_findings(payload, dataset_type='process') == []


def test_custom_catalog_drives_template_precheck_and_semantic_coverage_dynamically(tmp_path):
    import shutil
    from tiangong_audit.rule_engine import run_deterministic_checks
    from tiangong_audit.workflows.semantic_review import _agent_review_findings
    rules_dir = tmp_path / 'rules'
    shutil.copytree(ROOT / 'skill/tiangong-lca-audit/rules', rules_dir)
    path = rules_dir / 'process.json'
    catalog = json.loads(path.read_text())
    for rule in catalog['rules']:
        rule['agent_review_required'] = rule['id'] == 'process.object.consistency'
    path.write_text(json.dumps(catalog))
    assert required_rule_ids('process', rules_dir=rules_dir) == ('process.object.consistency',)
    template = new_agent_findings_template(review_id='review-1', dataset_type='process', rules_dir=rules_dir)
    assert [item['rule_id'] for item in template['rule_reviews']] == ['process.object.consistency']
    from tiangong_audit.normalizer import normalize_dataset
    dataset = normalize_dataset(json.loads((ROOT / 'tests/fixtures/projected-api/process-audit-input-projected.json').read_text()))
    assert run_deterministic_checks(dataset, rules_dir=rules_dir)['semantic_review']['required_rule_ids'] == ['process.object.consistency']
    payload = _valid_payload()
    payload['rule_reviews'] = payload['rule_reviews'][:1]
    assert _agent_review_findings(payload, agent_review_present=True, dataset_type='process', rules_dir=rules_dir)[1]['valid']
    catalog['rules'][0]['agent_review_required'] = True
    path.write_text(json.dumps(catalog))
    changed = required_rule_ids('process', rules_dir=rules_dir)
    assert len(changed) == 2
    assert len(new_agent_findings_template(review_id='review-1', dataset_type='process', rules_dir=rules_dir)['rule_reviews']) == 2
    assert run_deterministic_checks(dataset, rules_dir=rules_dir)['semantic_review']['required_rule_ids'] == list(changed)
    assert not _agent_review_findings(payload, agent_review_present=True, dataset_type='process', rules_dir=rules_dir)[1]['valid']


def test_malformed_rule_identity_is_rejected_without_crashing_na_admission():
    payload = _valid_payload()
    payload['rule_reviews'][0].update(rule_id=['process.object.consistency'], verdict='not_applicable')
    assert validate_agent_findings(payload, dataset_type='process')


def test_unknown_or_missing_dataset_type_cannot_silently_have_empty_coverage():
    from tiangong_audit.contracts.agent_review import admit_agent_findings
    for dataset_type in ('unknown', '', None):
        payload = _valid_payload()
        payload['dataset_type'] = dataset_type
        payload['rule_reviews'] = []
        result = admit_agent_findings(payload)
        assert any('dataset_type' in error for error in result.file_errors)
        assert not result.accepted_rule_review_indexes


def test_context_evidence_and_case_identity_admission(tmp_path):
    from tiangong_audit.contracts.agent_review import admit_agent_findings
    payload = _valid_payload()
    source = tmp_path / 'sources/source-001/extracted.md'
    source.parent.mkdir(parents=True)
    source.write_text('# Page 3\nevidence')
    assert not admit_agent_findings(payload, dataset_type='process', case_root=tmp_path, expected_review_id='review-1', expected_dataset_id='dataset-1').errors
    payload['rule_reviews'][0]['evidence_refs'] = ['sources/source-001/extracted.md:p999']
    admission = admit_agent_findings(payload, dataset_type='process', case_root=tmp_path)
    assert 0 in admission.rule_review_errors
    assert 1 in admission.accepted_rule_review_indexes
    assert validate_agent_findings(payload, dataset_type='process') == []  # structure only
    payload['review_id'] = 'another-case'
    admission = admit_agent_findings(payload, dataset_type='process', case_root=tmp_path, expected_review_id='review-1')
    assert admission.file_errors and not admission.accepted_rule_review_indexes


def test_additional_finding_requires_locatable_refs(tmp_path):
    from tiangong_audit.contracts.agent_review import admit_agent_findings
    payload = _valid_payload()
    payload['additional_findings'] = [{'severity': 'blocking', 'location': 'x', 'evidence': 'x', 'judgment': 'x', 'suggestion': 'x'}]
    assert 0 in admit_agent_findings(payload, dataset_type='process').additional_finding_errors
    payload['additional_findings'][0]['evidence_refs'] = ['missing.json#/x']
    assert 0 in admit_agent_findings(payload, dataset_type='process', case_root=tmp_path).additional_finding_errors
