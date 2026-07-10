import json
from pathlib import Path

from tiangong_audit.normalizer import normalize_dataset
from tiangong_audit.report import markdown as report_markdown
from tiangong_audit.report.markdown import render_findings
from tiangong_audit.rule_engine import (
    guardrail_rule_ids,
    load_skill_guardrails,
    run_deterministic_checks,
    runtime_rule_ids,
)

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests/fixtures/projected-api"
GUARDRAILS = load_skill_guardrails(ROOT)


def synthetic_process_dataset(
    *,
    dataset_type: str = "Unit process, black box",
    general_zh: str,
    general_en: str,
    cutoff_zh: str,
    cutoff_en: str,
    technology_zh: str = "熔炼、连铸、轧制、清洗。",
    technology_en: str = "Melting, continuous casting, rolling, and cleaning.",
    oxygen_name: str = "en: Industrial oxygen\nzh: 工业氧气",
    oxygen_unit: object = "kg",
    waste_scope_zh: str = "采用 cut-off / recycled-content 口径，废料收集、分选、预处理和运输不纳入本过程。",
    water_scope_zh: str = "废水在厂内处理，处理后水体排放计入本过程；循环水、蒸发损失和污泥含水已在水量平衡中说明。",
):
    return {
        "schema_version": "tiangong-audit-normalized-v1",
        "dataset_type": "process",
        "identity": {
            "id": "synthetic-copper",
            "version": "01.01.000",
            "name": {"zh": "再生铜杆制造", "en": "Recycled copper rod manufacturing", "raw": ""},
        },
        "sections": {
            "过程信息": {
                "present": True,
                "fields": {
                    "基本名称": {"zh": "再生铜杆制造", "en": "Recycled copper rod manufacturing"},
                    "数据集一般性说明": {"zh": general_zh, "en": general_en},
                    "技术描述及背景系统": {"zh": technology_zh, "en": technology_en},
                },
                "missing_fields": [],
            },
            "建模信息": {
                "present": True,
                "fields": {
                    "数据集类型": dataset_type,
                    "数据切断和完整性原则": {"zh": cutoff_zh, "en": cutoff_en},
                    "数据来源、处理和代表性": {
                        "zh": "\n".join([waste_scope_zh, water_scope_zh]),
                        "en": "Documented source treatment and representativeness.",
                    },
                },
                "missing_fields": [],
            },
            "管理信息": {"present": True, "fields": {}, "missing_fields": []},
            "输入/输出": {"present": True, "fields": {}, "missing_fields": []},
        },
        "reference_flow": {"pointer": "4", "exchanges": [{"internal_id": "4"}]},
        "exchanges": {
            "inputs": [
                {
                    "index": 1,
                    "internal_id": "1",
                    "direction": "input",
                    "name": {"zh": "国内铜废料", "en": "Domestic copper scrap", "raw": ""},
                    "amount": 41600000.0,
                    "mean_amount": 41600000.0,
                    "unit": "kg",
                    "is_reference": False,
                    "flow_type": "Waste flow",
                    "classification": [{"name": "Wastes or scraps"}],
                    "raw": {},
                },
                {
                    "index": 2,
                    "internal_id": "2",
                    "direction": "input",
                    "name": {"zh": oxygen_name, "en": oxygen_name, "raw": oxygen_name},
                    "amount": 800.0,
                    "mean_amount": 800.0,
                    "unit": oxygen_unit,
                    "is_reference": False,
                    "flow_type": "Product flow",
                    "classification": [{"name": "Industrial gases"}],
                    "raw": {},
                },
                {
                    "index": 3,
                    "internal_id": "3",
                    "direction": "input",
                    "name": {"zh": "自来水", "en": "Tap water", "raw": ""},
                    "amount": 15500000.0,
                    "mean_amount": 15500000.0,
                    "unit": "kg",
                    "is_reference": False,
                    "flow_type": "Product flow",
                    "classification": [{"name": "Water"}],
                    "raw": {},
                },
            ],
            "outputs": [
                {
                    "index": 4,
                    "internal_id": "4",
                    "direction": "output",
                    "name": {"zh": "铜杆；牌号T2；在工厂", "en": "Copper rod; Grade T2; at plant", "raw": ""},
                    "amount": 40000000.0,
                    "mean_amount": 40000000.0,
                    "unit": "kg",
                    "is_reference": True,
                    "flow_type": "Product flow",
                    "classification": [{"name": "Copper products"}],
                    "raw": {},
                },
                {
                    "index": 5,
                    "internal_id": "5",
                    "direction": "output",
                    "name": {"zh": "COD，排放到水体", "en": "COD, emissions to water", "raw": ""},
                    "amount": 1160.0,
                    "mean_amount": 1160.0,
                    "unit": "kg",
                    "is_reference": False,
                    "flow_type": "Elementary flow",
                    "classification": [{"name": "Emissions to water"}],
                    "raw": {},
                },
            ],
        },
        "coverage": {
            "present_sections": ["过程信息", "建模信息", "管理信息", "输入/输出"],
            "missing_sections": [],
            "input_count": 3,
            "output_count": 2,
        },
    }


def rule_ids(result: dict) -> set[str]:
    return {item["rule_id"] for item in result["findings"]}


def rule_asset_ids() -> set[str]:
    ids: set[str] = set()
    for path in [
        ROOT / "skill/tiangong-lca-audit/rules/common.json",
        ROOT / "skill/tiangong-lca-audit/rules/process.json",
        ROOT / "skill/tiangong-lca-audit/rules/model.json",
    ]:
        payload = json.loads(path.read_text(encoding="utf-8"))
        ids.update(rule["id"] for rule in payload["rules"])
    return ids


def check(name: str):
    payload = json.loads((FIXTURES / name).read_text(encoding="utf-8"))
    return run_deterministic_checks(normalize_dataset(payload))


def test_approved_fixture_has_no_blocking_precheck():
    result = check("process-audit-input-approved-projected.json")
    assert result["summary"]["blocking"] == 0
    assert result["conclusion"] == "预检通过"


def test_problem_fixture_detects_missing_flow_metadata_and_duplicate_text():
    result = check("process-audit-input-noapproved-projected.json")
    rule_ids = [item["rule_id"] for item in result["findings"]]
    assert rule_ids.count("process.flow.semantic_match") >= 2
    assert "common.language.semantic_consistency" in rule_ids
    assert result["conclusion"] == "预检不通过"


def test_heavy_naphtha_fixture_is_left_for_semantic_audit():
    result = check("process-audit-input-projected.json")
    assert result["summary"]["blocking"] == 0
    assert result["engine_scope"] == "deterministic-and-conservative-precheck"


def test_markdown_report_explains_runtime_scope():
    markdown = render_findings(check("process-audit-input-noapproved-projected.json"))
    assert "# 自动规则预检结果" in markdown
    assert "仍需 Agent 或人工审核" in markdown


def test_program_findings_use_registered_rule_ids():
    dataset = synthetic_process_dataset(
        general_zh="本数据集使用外购氧气作为投入品。",
        general_en="The dataset uses purchased oxygen as an input.",
        cutoff_zh="本数据集采用 1% 单项和 5% 累计截断原则，覆盖率不低于 95%。",
        cutoff_en="The dataset applies 1% single-flow and 5% cumulative cut-off criteria.",
    )
    oxygen = dataset["exchanges"]["inputs"][1]
    oxygen["flow_type"] = "Elementary flow"
    oxygen["classification"] = [{"name": "Resources from air"}]

    assert rule_ids(run_deterministic_checks(dataset, guardrails=GUARDRAILS)) <= rule_asset_ids()


def test_program_findings_use_runtime_rule_bindings():
    result = check("process-audit-input-noapproved-projected.json")

    assert rule_ids(result) <= runtime_rule_ids()


def test_copper_recycling_fixture_triggers_semantic_guardrails():
    dataset = synthetic_process_dataset(
        dataset_type="Partly terminated system",
        general_zh="本数据集描述以废铜为原料生产再生铜杆的过程，不含运输过程。",
        general_en="This dataset describes production of recycled copper wire and excludes transportation.",
        cutoff_zh="从摇篮到大门。",
        cutoff_en="From cradle to gate.",
        oxygen_name="en: Oxygen (liquefied)\nzh: 氧气（液化）",
        oxygen_unit={"name": "m3", "property": "体积"},
        waste_scope_zh="数据来源为项目环评。",
        water_scope_zh="",
    )

    result = run_deterministic_checks(dataset, guardrails=GUARDRAILS)

    assert {
        "process.type.partly_terminated_evidence",
        "process.boundary.lifecycle_stage_contradiction",
        "process.recycling.secondary_material_burden",
        "process.flow.form_unit_consistency",
        "common.language.semantic_consistency",
        "process.inventory.water_balance_boundary",
    } <= rule_ids(result)
    assert result["conclusion"] == "预检不通过"


def test_documented_copper_recycling_fixture_avoids_new_guardrails():
    dataset = synthetic_process_dataset(
        general_zh=(
            "本数据集边界覆盖废铜入厂后的熔炼、连铸、轧制和清洗过程，"
            "不包括废铜收集、分选、预处理、运输、产品出厂运输、使用和报废阶段。"
        ),
        general_en=(
            "This dataset covers recycled copper rod production after copper scrap enters the plant. "
            "Scrap collection, sorting, preprocessing, transport, outbound transport, use, and end of life are excluded."
        ),
        cutoff_zh="本数据集采用 1% 单项和 5% 累计截断原则，覆盖率不低于 95%。",
        cutoff_en="The dataset applies 1% single-flow and 5% cumulative cut-off criteria with at least 95% coverage.",
    )

    result = run_deterministic_checks(dataset, guardrails=GUARDRAILS)

    assert not {
        "process.type.partly_terminated_evidence",
        "process.boundary.lifecycle_stage_contradiction",
        "process.recycling.secondary_material_burden",
        "process.flow.form_unit_consistency",
        "common.language.semantic_consistency",
        "process.inventory.water_balance_boundary",
    } & rule_ids(result)


def test_cutoff_placeholder_creates_auditable_finding():
    dataset = synthetic_process_dataset(
        general_zh="本数据集描述鲍鱼养殖过程，边界覆盖育苗、投喂和养殖管理。",
        general_en="This dataset describes abalone farming.",
        cutoff_zh="-",
        cutoff_en="-",
    )

    result = run_deterministic_checks(dataset)

    assert "process.boundary.cutoff_placeholder" in rule_ids(result)
    finding = next(
        item for item in result["findings"] if item["rule_id"] == "process.boundary.cutoff_placeholder"
    )
    assert finding["severity"] == "manual_review"
    assert "数据切断和完整性原则" in finding["location"]


def test_purchased_elementary_inputs_trigger_flow_role_finding():
    dataset = synthetic_process_dataset(
        general_zh="本数据集使用外购氧气和碳酸钙作为养殖投入品，用于增氧和调节水质。",
        general_en=(
            "The dataset uses purchased oxygen and calcium carbonate as farming inputs "
            "for aeration and water quality control."
        ),
        cutoff_zh="本数据集采用 1% 单项和 5% 累计截断原则，覆盖率不低于 95%。",
        cutoff_en="The dataset applies 1% single-flow and 5% cumulative cut-off criteria.",
    )
    oxygen = dataset["exchanges"]["inputs"][1]
    oxygen["flow_type"] = "Elementary flow"
    oxygen["classification"] = [{"name": "Resources from air"}]
    oxygen["flow_uuid"] = "flow-oxygen"
    oxygen["flow_version"] = "01.00.000"
    dataset["exchanges"]["inputs"].append(
        {
            "index": 6,
            "internal_id": "6",
            "direction": "input",
            "name": {
                "zh": "碳酸钙",
                "en": "Calcium carbonate",
                "raw": "en: Calcium carbonate\nzh: 碳酸钙",
            },
            "amount": 50.0,
            "mean_amount": 50.0,
            "unit": "kg",
            "is_reference": False,
            "flow_type": "Elementary flow",
            "classification": [{"name": "Resources from ground"}],
            "flow_uuid": "flow-calcium-carbonate",
            "flow_version": "01.00.000",
            "raw": {},
        }
    )

    result = run_deterministic_checks(dataset, guardrails=GUARDRAILS)
    findings = [
        item
        for item in result["findings"]
        if item["rule_id"] == "process.flow.purchased_elementary_input_role"
    ]

    assert len(findings) == 2
    assert {item["severity"] for item in findings} == {"blocking"}
    assert all("产品流" in item["suggestion"] for item in findings)


def test_exchange_with_flow_uuid_but_missing_version_creates_traceability_gap():
    dataset = synthetic_process_dataset(
        general_zh="本数据集描述鲍鱼养殖过程。",
        general_en="This dataset describes abalone farming.",
        cutoff_zh="本数据集采用 1% 单项和 5% 累计截断原则，覆盖率不低于 95%。",
        cutoff_en="The dataset applies 1% single-flow and 5% cumulative cut-off criteria.",
    )
    oxygen = dataset["exchanges"]["inputs"][1]
    oxygen["flow_uuid"] = "flow-oxygen"
    oxygen["flow_version"] = ""

    result = run_deterministic_checks(dataset)

    assert "process.flow.version_identity" in rule_ids(result)
    finding = next(
        item for item in result["findings"] if item["rule_id"] == "process.flow.version_identity"
    )
    assert finding["severity"] == "input_gap"
    assert "flow-oxygen" in finding["evidence"]


def test_environmental_elementary_input_is_not_rewritten_as_product_flow():
    dataset = synthetic_process_dataset(
        general_zh="本数据集记录养殖水体中的溶解氧环境交换，不代表外购增氧剂。",
        general_en="The dataset records dissolved oxygen as an environmental exchange.",
        cutoff_zh="本数据集采用 1% 单项和 5% 累计截断原则，覆盖率不低于 95%。",
        cutoff_en="The dataset applies 1% single-flow and 5% cumulative cut-off criteria.",
    )
    oxygen = dataset["exchanges"]["inputs"][1]
    oxygen["name"] = {"zh": "溶解氧，来自水体", "en": "Dissolved oxygen, from water", "raw": ""}
    oxygen["flow_type"] = "Elementary flow"
    oxygen["classification"] = [{"name": "Resources from water"}]

    result = run_deterministic_checks(dataset, guardrails=GUARDRAILS)

    assert "process.flow.purchased_elementary_input_role" not in rule_ids(result)


def test_explicit_aquaculture_requirements_missing_from_inventory_create_finding():
    dataset = synthetic_process_dataset(
        general_zh="本数据集描述鲍鱼养殖过程。",
        general_en="This dataset describes abalone farming.",
        technology_zh="养殖过程需要投喂饲料，使用网箱，定期消毒，并记录死亡率。",
        technology_en="The process uses feed, cages, disinfection, and records mortality.",
        cutoff_zh="本数据集采用 1% 单项和 5% 累计截断原则，覆盖率不低于 95%。",
        cutoff_en="The dataset applies 1% single-flow and 5% cumulative cut-off criteria.",
    )
    dataset["exchanges"]["inputs"] = [
        item for item in dataset["exchanges"]["inputs"] if "自来水" in item["name"]["zh"]
    ]

    result = run_deterministic_checks(dataset, guardrails=GUARDRAILS)

    assert "process.inventory.key_flow_completeness" in rule_ids(result)
    finding = next(
        item for item in result["findings"] if item["rule_id"] == "process.inventory.key_flow_completeness"
    )
    assert finding["severity"] == "manual_review"
    assert "饲料" in finding["evidence"]
    assert "补充" in finding["suggestion"]


def test_platform_return_opinion_uses_only_actionable_findings():
    dataset = synthetic_process_dataset(
        general_zh="本数据集使用外购氧气作为投入品。",
        general_en="The dataset uses purchased oxygen as an input.",
        cutoff_zh="-",
        cutoff_en="-",
    )
    dataset["exchanges"]["inputs"][1]["flow_type"] = "Elementary flow"
    dataset["exchanges"]["inputs"][1]["classification"] = [{"name": "Resources from air"}]
    result = run_deterministic_checks(dataset, guardrails=GUARDRAILS)

    opinion = report_markdown.render_platform_return_opinion(result)

    assert opinion.startswith("## 平台退回意见")
    assert "①" in opinion
    assert "规则" not in opinion
    assert "process.boundary.cutoff_placeholder" not in opinion


def test_engine_without_guardrails_keeps_only_structural_checks():
    dataset = synthetic_process_dataset(
        dataset_type="Unit process, black box",
        general_zh="本数据集使用外购氧气作为投入品。",
        general_en="The dataset uses purchased oxygen as an input.",
        technology_zh="养殖过程需要投喂饲料，使用网箱，定期消毒，并记录死亡率。",
        technology_en="The process uses feed, cages, disinfection, and records mortality.",
        cutoff_zh="本数据集采用 1% 单项和 5% 累计截断原则，覆盖率不低于 95%。",
        cutoff_en="The dataset applies 1% single-flow and 5% cumulative cut-off criteria.",
    )
    dataset["exchanges"]["inputs"][1]["flow_type"] = "Elementary flow"
    dataset["identity"]["name"]["en"] = "Recycled copper wire manufacturing"

    result = run_deterministic_checks(dataset)

    ids = rule_ids(result)
    assert "process.inventory.key_flow_completeness" not in ids
    assert "process.flow.purchased_elementary_input_role" not in ids
    # The copper rod/wire term pair now lives in guardrails, not in the engine.
    assert not any(
        "铜杆" in item["evidence"] and "copper wire" in item["evidence"]
        for item in result["findings"]
    )


def test_guardrail_rule_ids_are_registered_in_catalog():
    assert GUARDRAILS is not None
    assert guardrail_rule_ids(GUARDRAILS) <= rule_asset_ids()


def test_guardrail_entries_declare_origin_cases():
    assert GUARDRAILS is not None
    for entry in GUARDRAILS["guardrails"]:
        assert entry["origin_case"]
