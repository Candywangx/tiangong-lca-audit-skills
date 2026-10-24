"""Sanitized evidence-boundary regressions for raw and projected inputs."""

from copy import deepcopy
import json
from pathlib import Path

import pytest

from tiangong_audit.normalizer import normalize_dataset
from tiangong_audit.rule_engine import load_skill_guardrails, run_deterministic_checks, run_guardrails
from tiangong_audit.sources import generate_source_claims


def raw_payload():
    def exchange(internal_id, direction):
        return {
            "@dataSetInternalID": internal_id,
            "exchangeDirection": direction,
            "resultingAmount": "1",
            "meanAmount": "2",
            "referenceToFlowDataSet": {
                "@refObjectId": f"flow-{internal_id}",
                "@version": "01.00.000",
                "shortDescription": {"zh": "已引用交换", "en": "Referenced exchange"},
            },
            "flowDataSet": {
                "flowInformation": {
                    "dataSetInformation": {
                        "UUID": f"flow-{internal_id}",
                        "name": {"baseName": {"zh": "验证流", "en": "Verified flow"}},
                        "classificationInformation": {
                            "classification": {"class": {"#text": "Products"}}
                        },
                    },
                    "quantitativeReference": {"referenceToReferenceFlowProperty": "mass"},
                },
                "administrativeInformation": {
                    "publicationAndOwnership": {"dataSetVersion": "01.00.000"}
                },
                "modellingAndValidation": {"LCIMethod": {"typeOfDataSet": "Product flow"}},
                "flowProperties": {"flowProperty": [{
                    "@dataSetInternalID": "mass",
                    "referenceToFlowPropertyDataSet": {"shortDescription": "Mass"},
                    "unit": "kg",
                }]},
            },
        }

    return {"processDataSet": {
        "processInformation": {"dataSetInformation": {
            "UUID": "sanitized-process",
            "name": {"baseName": {"zh": "验证过程", "en": "Verified process"}},
            "referenceToReferenceFlow": "0",
        }},
        "modellingAndValidation": {"LCIMethodAndAllocation": {"typeOfDataSet": "Unit process, black box"}},
        "administrativeInformation": {"publicationAndOwnership": {"dataSetVersion": "01.00.000"}},
        "exchanges": {"exchange": [exchange("0", "Output"), exchange("1", "Input")]},
    }}


def first_raw(payload):
    return payload["processDataSet"]["exchanges"]["exchange"][0]


def first_output(payload):
    return normalize_dataset(payload)["exchanges"]["outputs"][0]


@pytest.mark.parametrize("amount", [0, "0", -3, "-3", "1.25"])
def test_explicit_resulting_amount_survives_normalization(amount):
    payload = raw_payload()
    first_raw(payload)["resultingAmount"] = amount
    assert first_output(payload)["amount"] == float(amount)


@pytest.mark.parametrize("field, fallback", [("resultingAmount", "meanAmount"), ("meanAmount", "resultingAmount")])
def test_missing_quantity_uses_existing_fallback(field, fallback):
    payload = raw_payload()
    del first_raw(payload)[field]
    output = first_output(payload)
    target = "amount" if field == "resultingAmount" else "mean_amount"
    assert output[target] == float(first_raw(payload)[fallback])


@pytest.mark.parametrize("invalid", ["not-a-number", "NaN", "Infinity", "-Infinity", "1e999", False])
@pytest.mark.parametrize("field, target", [("resultingAmount", "amount"), ("meanAmount", "mean_amount")])
def test_invalid_explicit_quantity_is_not_silently_replaced(invalid, field, target):
    payload = raw_payload()
    row = first_raw(payload)
    row[field] = invalid
    output = first_output(payload)
    assert output[target] is None
    assert output["raw"] == row


def test_zero_mean_amount_is_not_replaced_by_resulting_amount():
    payload = raw_payload()
    first_raw(payload)["meanAmount"] = 0
    assert first_output(payload)["mean_amount"] == 0


@pytest.mark.parametrize("amount", [None, "invalid", "NaN", "Infinity"])
def test_missing_or_invalid_reference_amount_requires_input_gap(amount):
    payload = raw_payload()
    row = first_raw(payload)
    row["resultingAmount"] = amount
    if amount is None:
        del row["meanAmount"]
    result = run_deterministic_checks(normalize_dataset(payload))
    assert result["conclusion"] == "预检信息不足"
    quantity_findings = [item for item in result["findings"] if item["rule_id"] == "process.reference_flow.quantity_unit"]
    assert len(quantity_findings) == 1
    assert quantity_findings[0]["severity"] == "input_gap"
    assert result["summary"]["blocking"] == 0


@pytest.mark.parametrize("amount", [0, -1])
def test_reference_quantity_precheck_preserves_zero_and_negative_without_suitability_judgment(amount):
    payload = raw_payload()
    first_raw(payload)["resultingAmount"] = amount
    result = run_deterministic_checks(normalize_dataset(payload))
    assert result["conclusion"] == "预检通过"
    assert not any(item["rule_id"] == "process.reference_flow.quantity_unit" for item in result["findings"])


def test_exact_flow_property_link_supplies_unit_without_exchange_unit():
    payload = raw_payload()
    output = first_output(payload)
    assert "unit" not in first_raw(payload)
    assert output["unit"]["raw"] == "kg"
    assert run_deterministic_checks(normalize_dataset(payload))["summary"]["input_gap"] == 0


def test_linked_property_without_unit_reports_one_metadata_gap():
    payload = raw_payload()
    del first_raw(payload)["flowDataSet"]["flowProperties"]["flowProperty"][0]["unit"]
    result = run_deterministic_checks(normalize_dataset(payload))
    assert result["conclusion"] == "预检信息不足"
    assert result["summary"]["input_gap"] == 1
    assert result["findings"][0]["rule_id"] == "process.flow.semantic_match"


def test_unresolved_property_reports_one_gap_for_property_and_unit():
    payload = raw_payload()
    first_raw(payload)["flowDataSet"]["flowInformation"]["quantitativeReference"]["referenceToReferenceFlowProperty"] = "unknown"
    result = run_deterministic_checks(normalize_dataset(payload))
    assert result["summary"]["input_gap"] == 1


def test_namespaced_embedded_identity_can_bind_exact_referenced_flow():
    payload = raw_payload()
    flow = first_raw(payload)["flowDataSet"]
    information = flow["flowInformation"]["dataSetInformation"]
    information["common:UUID"] = information.pop("UUID")
    publication = flow["administrativeInformation"]["publicationAndOwnership"]
    publication["common:dataSetVersion"] = publication.pop("dataSetVersion")
    output = first_output(payload)
    assert output["flow_type"] == "Product flow"
    assert output["unit"]["raw"] == "kg"
    assert output["flow_binding"]["status"] == "matched"


@pytest.mark.parametrize("pointer", ["not-present", None])
def test_unresolved_reference_property_never_guesses_first_unit(pointer):
    payload = raw_payload()
    flow = first_raw(payload)["flowDataSet"]
    flow["flowInformation"]["quantitativeReference"]["referenceToReferenceFlowProperty"] = pointer
    assert not any(first_output(payload)["unit"].values())
    findings = run_deterministic_checks(normalize_dataset(payload))["findings"]
    assert any(item["severity"] == "input_gap" for item in findings)


def test_duplicate_matching_property_ids_do_not_select_arbitrary_unit():
    payload = raw_payload()
    properties = first_raw(payload)["flowDataSet"]["flowProperties"]["flowProperty"]
    properties.append({**deepcopy(properties[0]), "unit": "m3"})
    assert not any(first_output(payload)["unit"].values())


@pytest.mark.parametrize("conflict", ["uuid", "version"])
def test_explicit_embedded_flow_identity_conflict_cannot_supply_metadata(conflict):
    payload = raw_payload()
    row = first_raw(payload)
    flow = row["flowDataSet"]
    if conflict == "uuid":
        flow["flowInformation"]["dataSetInformation"]["UUID"] = "different-flow"
    else:
        flow["administrativeInformation"]["publicationAndOwnership"]["dataSetVersion"] = "02.00.000"
    output = first_output(payload)
    assert output["flow_dataset_name"] == {"zh": "", "en": "", "raw": ""}
    assert output["name"] == output["exchange_description"]
    assert output["flow_type"] == ""
    assert output["classification"] == []
    assert not any(output["unit"].values())
    assert output["raw"] == row
    result = run_deterministic_checks(normalize_dataset(payload))
    assert result["conclusion"] == "预检信息不足"
    assert any(item["rule_id"] == "process.flow.version_identity" and item["severity"] == "input_gap" for item in result["findings"])


@pytest.mark.parametrize("missing", ["reference_version", "embedded_version", "embedded_uuid"])
def test_partial_explicit_flow_binding_restricts_linked_metadata(missing):
    payload = raw_payload()
    row = first_raw(payload)
    if missing == "reference_version":
        del row["referenceToFlowDataSet"]["@version"]
    elif missing == "embedded_version":
        del row["flowDataSet"]["administrativeInformation"]
    else:
        del row["flowDataSet"]["flowInformation"]["dataSetInformation"]["UUID"]
    output = first_output(payload)
    assert output["flow_type"] == ""
    assert not any(output["unit"].values())
    result = run_deterministic_checks(normalize_dataset(payload))
    assert result["conclusion"] == "预检信息不足"


def test_legacy_embedded_metadata_is_preserved_with_binding_gap():
    payload = raw_payload()
    row = first_raw(payload)
    del row["flowDataSet"]["administrativeInformation"]
    del row["flowDataSet"]["flowInformation"]["dataSetInformation"]["UUID"]
    output = first_output(payload)
    assert output["flow_type"] == "Product flow"
    assert output["unit"]["raw"] == "kg"
    result = run_deterministic_checks(normalize_dataset(payload))
    assert result["conclusion"] == "预检信息不足"
    assert any(item["rule_id"] == "process.flow.version_identity" for item in result["findings"])


def make_legacy(row):
    del row["flowDataSet"]["administrativeInformation"]
    del row["flowDataSet"]["flowInformation"]["dataSetInformation"]["UUID"]


@pytest.mark.parametrize("binding, reference_name, blocking", [
    ("legacy", "工业水", False),
    ("legacy", "电力", True),
    ("matched", "工业水", True),
])
def test_electricity_blocking_requires_reference_or_bound_flow_name(binding, reference_name, blocking):
    payload = raw_payload()
    information = payload["processDataSet"]["processInformation"]["dataSetInformation"]
    information["generalComment"] = {"zh": "本数据集不包含电力。"}
    row = payload["processDataSet"]["exchanges"]["exchange"][1]
    row["referenceToFlowDataSet"]["shortDescription"] = {"zh": reference_name}
    row["flowDataSet"]["flowInformation"]["dataSetInformation"]["name"]["baseName"] = {"zh": "电力", "en": "Electricity"}
    if binding == "legacy":
        make_legacy(row)
    dataset = normalize_dataset(payload)
    original = deepcopy(dataset)
    result = run_deterministic_checks(dataset)
    assert (result["summary"]["blocking"] > 0) is blocking
    assert dataset == original
    assert dataset["exchanges"]["inputs"][0]["flow_dataset_name"]["zh"] == "电力"


def test_legacy_classification_cannot_support_upstream_boundary_blocking():
    payload = raw_payload()
    information = payload["processDataSet"]["processInformation"]["dataSetInformation"]
    information["generalComment"] = {"zh": "本数据集不包含上游材料生产的环境影响。"}
    row = payload["processDataSet"]["exchanges"]["exchange"][1]
    row["flowDataSet"]["flowInformation"]["dataSetInformation"]["classificationInformation"]["classification"]["class"] = {"#text": "production mix"}
    make_legacy(row)
    result = run_deterministic_checks(normalize_dataset(payload))
    assert result["summary"]["blocking"] == 0


@pytest.mark.parametrize("entrypoint", ["engine", "guardrails"])
def test_legacy_flow_type_cannot_support_purchased_elementary_blocking(entrypoint):
    payload = raw_payload()
    information = payload["processDataSet"]["processInformation"]["dataSetInformation"]
    information["generalComment"] = {"zh": "本数据集使用外购工业氧气作为投入品。"}
    row = payload["processDataSet"]["exchanges"]["exchange"][1]
    row["referenceToFlowDataSet"]["shortDescription"] = {"zh": "工业氧气", "en": "Industrial oxygen"}
    row["flowDataSet"]["modellingAndValidation"]["LCIMethod"]["typeOfDataSet"] = "Elementary flow"
    make_legacy(row)
    dataset = normalize_dataset(payload)
    guardrails = load_skill_guardrails(Path(__file__).resolve().parents[1])
    findings = run_guardrails(dataset, guardrails) if entrypoint == "guardrails" else run_deterministic_checks(dataset, guardrails=guardrails)["findings"]
    assert not any(item["severity"] == "blocking" for item in findings)


@pytest.mark.parametrize("binding, own_unit, blocking", [
    ("legacy", None, False),
    ("legacy", "m3", True),
    ("matched", None, True),
])
def test_form_unit_check_uses_only_exchange_unit_or_bound_property_unit(binding, own_unit, blocking):
    payload = raw_payload()
    row = payload["processDataSet"]["exchanges"]["exchange"][1]
    row["referenceToFlowDataSet"]["shortDescription"] = {"zh": "液态氧气", "en": "Liquid oxygen"}
    row["flowDataSet"]["flowInformation"]["dataSetInformation"]["name"]["baseName"] = {"zh": "液态氧气", "en": "Liquid oxygen"}
    row["flowDataSet"]["flowProperties"]["flowProperty"][0]["unit"] = "m3"
    if own_unit:
        row["unit"] = own_unit
    if binding == "legacy":
        make_legacy(row)
    result = run_deterministic_checks(normalize_dataset(payload))
    unit_findings = [item for item in result["findings"] if item["rule_id"] == "process.flow.form_unit_consistency"]
    assert any(item["severity"] == "blocking" for item in unit_findings) is blocking


def test_normalized_claims_do_not_promote_legacy_flow_metadata_to_evidence():
    payload = raw_payload()
    make_legacy(first_raw(payload))
    row = payload["processDataSet"]["exchanges"]["exchange"][1]
    row["referenceToFlowDataSet"]["shortDescription"] = {"zh": "工业水", "en": "Industrial water"}
    make_legacy(row)
    claims = generate_source_claims(normalize_dataset(payload))
    assert claims["process.exchange.input.1.name.zh"] == "工业水"
    assert "process.exchange.input.1.flow_type" not in claims
    assert "process.exchange.input.1.classification" not in claims
    assert "process.exchange.input.1.unit.zh" not in claims
    assert "process.exchange.input.1.unit.en" not in claims
    assert "reference_flow.1.unit" not in claims


def test_missing_flow_metadata_is_input_gap_not_blocking():
    payload = raw_payload()
    del first_raw(payload)["flowDataSet"]
    result = run_deterministic_checks(normalize_dataset(payload))
    metadata_findings = [item for item in result["findings"] if item["rule_id"] == "process.flow.semantic_match"]
    assert metadata_findings
    assert {item["severity"] for item in metadata_findings} == {"input_gap"}
    assert result["conclusion"] == "预检信息不足"


def test_metadata_gap_does_not_mask_independent_blocking_conflict():
    payload = raw_payload()
    del first_raw(payload)["flowDataSet"]
    process_info = payload["processDataSet"]["processInformation"]["dataSetInformation"]
    process_info["generalComment"] = {"zh": "本数据集不包含电力。"}
    input_row = payload["processDataSet"]["exchanges"]["exchange"][1]
    input_row["flowDataSet"]["flowInformation"]["dataSetInformation"]["name"]["baseName"] = {"zh": "电力", "en": "Electricity"}
    result = run_deterministic_checks(normalize_dataset(payload))
    assert result["summary"]["input_gap"] > 0
    assert result["summary"]["blocking"] > 0
    assert result["conclusion"] == "预检不通过"


def test_raw_exchange_and_caller_input_are_preserved_completely():
    payload = raw_payload()
    first_raw(payload)["extraEvidence"] = {"nested": [0, False, "unparsed"]}
    original = deepcopy(payload)
    output = first_output(payload)
    assert payload == original
    assert output["raw"] == first_raw(original)
    output["raw"]["extraEvidence"]["nested"].append("isolated")
    assert payload == original


def test_projected_metadata_only_gap_has_insufficient_precheck():
    path = Path(__file__).parent / "fixtures/projected-api/process-audit-input-noapproved-projected.json"
    result = run_deterministic_checks(normalize_dataset(json.loads(path.read_text())))
    assert result["summary"]["blocking"] == 0
    assert result["summary"]["input_gap"] > 0
    assert result["conclusion"] == "预检信息不足"
