from __future__ import annotations

from collections import Counter
import re
from typing import Any

from tiangong_audit.contracts.agent_review import REQUIRED_AGENT_REVIEW_RULE_IDS

CORE_PROCESS_SECTIONS = ("过程信息", "建模信息", "输入/输出")
# Judgment rules the Agent must explicitly review; the canonical definition
# lives in contracts.agent_review so precheck and semantic-review stay aligned.
REQUIRED_SEMANTIC_REVIEW_RULE_IDS = REQUIRED_AGENT_REVIEW_RULE_IDS["process"]
RUNTIME_RULE_BINDINGS = {
    "_check_coverage": ("process.core.input_coverage",),
    "_check_reference_flow": (
        "process.core.input_coverage",
        "process.reference_flow.quantity_unit",
    ),
    "_check_exchange_metadata": ("process.flow.semantic_match",),
    "_check_flow_version_identity": ("process.flow.version_identity",),
    "_check_explicit_electricity_conflict": ("process.inventory.boundary_consistency",),
    "_check_upstream_burden_boundary_conflict": ("process.inventory.boundary_consistency",),
    "_check_partly_terminated_evidence": ("process.type.partly_terminated_evidence",),
    "_check_cutoff_placeholder": ("process.boundary.cutoff_placeholder",),
    "_check_cutoff_quantitative_criteria": ("process.boundary.cutoff_and_exclusions",),
    "_check_lifecycle_stage_contradiction": ("process.boundary.lifecycle_stage_contradiction",),
    "_check_reference_output_mass_attribute": ("process.reference_flow.annual_supply_unit",),
    "_check_recycling_burden_scope": ("process.recycling.secondary_material_burden",),
    "_check_flow_form_unit_consistency": ("process.flow.form_unit_consistency",),
    "_check_water_boundary": ("process.inventory.water_balance_boundary",),
    "_check_duplicate_language": ("common.language.semantic_consistency",),
}


def runtime_rule_ids() -> set[str]:
    return {
        rule_id
        for rule_ids in RUNTIME_RULE_BINDINGS.values()
        for rule_id in rule_ids
    }


def _text(value: Any) -> str:
    if isinstance(value, dict):
        return "\n".join(str(item) for item in value.values() if item)
    return str(value or "")


def _flatten_text(value: Any) -> str:
    if isinstance(value, dict):
        return "\n".join(_flatten_text(item) for item in value.values() if item)
    if isinstance(value, list):
        return "\n".join(_flatten_text(item) for item in value if item)
    return str(value or "")


def _field_text(dataset: dict[str, Any], section: str, field: str) -> str:
    return _flatten_text(dataset["sections"].get(section, {}).get("fields", {}).get(field))


def _combined_section_text(dataset: dict[str, Any], *sections: str) -> str:
    return "\n".join(
        _flatten_text(dataset["sections"].get(section, {}).get("fields", {}))
        for section in sections
    )


def _combined_language_text(dataset: dict[str, Any], language: str) -> str:
    parts: list[str] = []
    for section in dataset["sections"].values():
        for value in section["fields"].values():
            if isinstance(value, dict) and value.get(language):
                parts.append(_flatten_text(value.get(language)))
    for exchange in [*dataset["exchanges"]["inputs"], *dataset["exchanges"]["outputs"]]:
        parts.append(str(exchange["name"].get(language) or ""))
    return "\n".join(parts)


def _all_exchanges(dataset: dict[str, Any]) -> list[dict[str, Any]]:
    return [*dataset["exchanges"]["inputs"], *dataset["exchanges"]["outputs"]]


def _exchange_label(exchange: dict[str, Any]) -> str:
    name = exchange["name"]
    return name.get("zh") or name.get("en") or name.get("raw") or f"exchange {exchange.get('index')}"


def _exchange_text(exchange: dict[str, Any]) -> str:
    return "\n".join(
        [
            _exchange_label(exchange),
            _flatten_text(exchange.get("flow_dataset_name")),
            _flatten_text(exchange.get("exchange_description")),
            str(exchange.get("flow_type") or ""),
            _flatten_text(exchange.get("classification")),
        ]
    )


def _finding(
    rule_id: str,
    severity: str,
    location: str,
    evidence: str,
    judgment: str,
    suggestion: str,
) -> dict[str, str]:
    return {
        "rule_id": rule_id,
        "severity": severity,
        "location": location,
        "evidence": evidence,
        "judgment": judgment,
        "suggestion": suggestion,
    }


def _check_coverage(dataset: dict[str, Any]) -> list[dict[str, str]]:
    findings = []
    missing = [name for name in CORE_PROCESS_SECTIONS if name in dataset["coverage"]["missing_sections"]]
    if missing:
        findings.append(
            _finding(
                "process.core.input_coverage",
                "input_gap",
                "输入范围",
                f"缺少核心窗口：{'、'.join(missing)}。",
                "缺失窗口会阻止完成过程数据集的核心审核。",
                "补充缺失窗口后再请求完整审核。",
            )
        )

    if not dataset["identity"]["name"].get("zh") and not dataset["identity"]["name"].get("en"):
        findings.append(
            _finding(
                "process.core.input_coverage",
                "input_gap",
                "过程信息 / 基本名称",
                "未识别到数据集基本名称。",
                "无法确认当前审核对象。",
                "补充数据集基本名称。",
            )
        )
    if not dataset["exchanges"]["inputs"] or not dataset["exchanges"]["outputs"]:
        findings.append(
            _finding(
                "process.core.input_coverage",
                "input_gap",
                "输入/输出",
                f"识别到输入 {len(dataset['exchanges']['inputs'])} 条、输出 {len(dataset['exchanges']['outputs'])} 条。",
                "缺少输入或输出时无法完成清单审核。",
                "补充完整输入/输出交换。",
            )
        )
    return findings


def _check_reference_flow(dataset: dict[str, Any]) -> list[dict[str, str]]:
    pointer = dataset["reference_flow"]["pointer"]
    references = dataset["reference_flow"]["exchanges"]
    findings = []
    if not pointer or not references:
        return [
            _finding(
                "process.core.input_coverage",
                "input_gap",
                "过程信息 / 功能单位或基准流",
                f"参考流指针为 {pointer or '空'}，识别到 {len(references)} 条基准交换。",
                "无法确认正式参考流。",
                "补充并标记唯一参考流。",
            )
        ]
    matched = [item for item in references if item["internal_id"] == pointer]
    if not matched:
        findings.append(
            _finding(
                "process.reference_flow.quantity_unit",
                "blocking",
                "过程信息 / 功能单位或基准流",
                f"参考流指针 {pointer} 未匹配任何标记为基准流的交换。",
                "参考流指针与交换不一致。",
                "将参考流指针修正为实际基准交换的内部 ID。",
            )
        )
    if len(references) > 1:
        findings.append(
            _finding(
                "process.reference_flow.quantity_unit",
                "manual_review",
                "输入/输出 / 基准流",
                f"识别到 {len(references)} 条标记为基准流的交换。",
                "需要确认是否允许多个参考流。",
                "确认并保留符合数据集目标的参考流标记。",
            )
        )
    return findings


def _check_exchange_metadata(dataset: dict[str, Any]) -> list[dict[str, str]]:
    findings = []
    for exchange in _all_exchanges(dataset):
        missing = []
        if not exchange["flow_type"]:
            missing.append("流类型")
        if not exchange["classification"]:
            missing.append("流分类")
        if missing:
            findings.append(
                _finding(
                    "process.flow.semantic_match",
                    "blocking",
                    f"输入/输出 / {_exchange_label(exchange)}",
                    f"缺少{'、'.join(missing)}。",
                    "缺失元数据会影响检索、连接或流角色判断。",
                    f"补充该流的{'、'.join(missing)}。",
                )
            )
    return findings


def _check_flow_version_identity(dataset: dict[str, Any]) -> list[dict[str, str]]:
    findings = []
    for exchange in _all_exchanges(dataset):
        flow_uuid = str(exchange.get("flow_uuid") or "")
        if not flow_uuid or exchange.get("flow_version"):
            continue
        findings.append(
            _finding(
                "process.flow.version_identity",
                "input_gap",
                f"输入/输出 / {_exchange_label(exchange)}",
                f"流 UUID 为 {flow_uuid}，但未识别到流数据集版本。",
                "缺少版本会导致同一流的不同版本无法区分，影响复核和重现。",
                "补充该交换引用的流数据集版本，或重新导出包含完整流身份信息的数据。",
            )
        )
    return findings


def _check_explicit_electricity_conflict(dataset: dict[str, Any]) -> list[dict[str, str]]:
    general = _text(dataset["sections"]["过程信息"]["fields"].get("数据集一般性说明"))
    excludes = re.search(
        r"(不包含|不包括|未包含|未纳入|排除).{0,12}(电力|用电)|"
        r"(exclude|without|does not include).{0,24}electricity",
        general,
        re.IGNORECASE,
    )
    electricity = [
        item
        for item in dataset["exchanges"]["inputs"]
        if re.search(r"电力|电能|electricity", _exchange_label(item), re.IGNORECASE)
    ]
    if excludes and electricity:
        names = "、".join(_exchange_label(item) for item in electricity[:3])
        return [
            _finding(
                "process.inventory.boundary_consistency",
                "blocking",
                "过程信息 / 数据集一般性说明 ↔ 输入/输出",
                f"一般性说明明确排除电力，但输入中存在：{names}。",
                "边界说明与清单直接冲突。",
                "统一一般性说明和输入清单，并说明实际电力边界。",
            )
        ]
    return []


def _check_upstream_burden_boundary_conflict(dataset: dict[str, Any]) -> list[dict[str, str]]:
    general = _field_text(dataset, "过程信息", "数据集一般性说明")
    context = _combined_section_text(dataset, "过程信息", "建模信息")
    input_text = "\n".join(_exchange_text(exchange) for exchange in dataset["exchanges"]["inputs"])
    excludes_upstream = re.search(
        r"(不包含|不包括|未包含|未纳入|排除|不含).{0,24}(上游材料生产|上游.{0,8}环境影响|上游.{0,8}生产)|"
        r"(does not include|exclude|excluding|without).{0,60}(upstream material production|upstream.{0,20}environmental impacts)",
        general,
        re.IGNORECASE,
    )
    linked_upstream = re.search(
        r"上游.{0,18}产品流|upstream.{0,40}product flow|生产混合|production mix",
        "\n".join([context, input_text]),
        re.IGNORECASE,
    )
    if not (excludes_upstream and linked_upstream):
        return []

    return [
        _finding(
            "process.inventory.boundary_consistency",
            "blocking",
            "过程信息 / 数据集一般性说明 ↔ 输入/输出",
            "一般性说明排除上游材料生产环境影响，但输入端使用生产混合产品流，或技术描述说明上游负荷通过输入产品流体现。",
            "若输入产品流链接背景过程，后续计算会引入上游生产负荷；边界说明不能简单写作不包含上游材料生产环境影响。",
            "改写系统边界，说明本数据集以前景过程表达制造阶段物料需求，复合材料生产负荷通过输入产品流的上游背景过程体现，并列明下游排除阶段。",
        )
    ]


def _check_partly_terminated_evidence(dataset: dict[str, Any]) -> list[dict[str, str]]:
    dataset_type = str(_field_text(dataset, "建模信息", "数据集类型")).strip()
    if dataset_type != "Partly terminated system":
        return []

    modelling_fields = dict(dataset["sections"]["建模信息"]["fields"])
    modelling_fields.pop("数据集类型", None)
    explanation = "\n".join(
        [
            _flatten_text(modelling_fields),
            _field_text(dataset, "过程信息", "数据集一般性说明"),
            _field_text(dataset, "过程信息", "技术描述及背景系统"),
        ]
    )
    has_termination_evidence = re.search(r"终止|terminated|termination", explanation, re.IGNORECASE)
    has_background_scope = re.search(
        r"上游|背景|background|linked process|仍调用|cut-?off|截断|终止.{0,12}(过程|系统)",
        explanation,
        re.IGNORECASE,
    )
    if has_termination_evidence and has_background_scope:
        return []

    return [
        _finding(
            "process.type.partly_terminated_evidence",
            "blocking",
            "建模信息 / 数据集类型",
            "数据集类型为 Partly terminated system，但未识别到已终止上游/背景过程及仍调用背景过程的说明。",
            "仅填写部分终止系统无法区分该数据集是黑箱单元过程、部分分解数据集还是聚合 LCI 结果。",
            "说明哪些上游或背景过程已终止、哪些输入仍调用背景数据；否则改为匹配的数据集类型。",
        )
    ]


def _is_placeholder_text(value: Any) -> bool:
    text = _flatten_text(value)
    if not text.strip():
        return False
    tokens = [part.strip().lower() for part in re.split(r"[\n,;；，]+", text) if part.strip()]
    placeholders = {"-", "—", "n/a", "na", "none", "不适用", "无"}
    return bool(tokens) and all(token in placeholders for token in tokens)


def _check_cutoff_placeholder(dataset: dict[str, Any]) -> list[dict[str, str]]:
    cutoff = dataset["sections"].get("建模信息", {}).get("fields", {}).get("数据切断和完整性原则")
    if not _is_placeholder_text(cutoff):
        return []
    return [
        _finding(
            "process.boundary.cutoff_placeholder",
            "manual_review",
            "建模信息 / 数据切断和完整性原则",
            f"该字段仅填写为占位符：{_flatten_text(cutoff).strip()}。",
            "占位符无法说明定量截断标准、覆盖率、排除活动或跨系统边界流。",
            "补充定量截断标准、覆盖率、排除活动和跨系统边界流；若确无截断，说明适用原因。",
        )
    ]


def _check_cutoff_quantitative_criteria(dataset: dict[str, Any]) -> list[dict[str, str]]:
    cutoff = _field_text(dataset, "建模信息", "数据切断和完整性原则")
    if not cutoff.strip() or _is_placeholder_text(cutoff):
        return []

    has_quantitative_criteria = re.search(
        r"1\s*%|5\s*%|95\s*%|单项|累计|覆盖率|cut-?off criteria|cumulative|coverage|less than",
        cutoff,
        re.IGNORECASE,
    )
    excludes_by_source_gap = re.search(
        r"未.{0,8}列出|未.{0,8}提供|未.{0,8}纳入|not separately reported|not included|not additionally estimated",
        cutoff,
        re.IGNORECASE,
    )
    if has_quantitative_criteria or not excludes_by_source_gap:
        return []

    return [
        _finding(
            "process.boundary.cutoff_and_exclusions",
            "manual_review",
            "建模信息 / 数据切断和完整性原则",
            "截断说明以文献未单独列出为主要理由，但未给出 1%/5%、95% 覆盖率或等效定量截断口径。",
            "仅因文献未列出不能证明制造能耗、辅助材料或其他排除项均可截断；缺少定量口径会限制正式工程核算适用性。",
            "补充单项贡献、累计贡献和覆盖率等截断标准，并说明未列出制造能耗和辅助材料时的数据适用范围。",
        )
    ]


def _check_lifecycle_stage_contradiction(dataset: dict[str, Any]) -> list[dict[str, str]]:
    boundary = "\n".join(
        [
            _field_text(dataset, "建模信息", "数据切断和完整性原则"),
            _field_text(dataset, "过程信息", "数据集一般性说明"),
        ]
    )
    all_scope_text = _combined_section_text(dataset, "过程信息", "建模信息")
    has_cradle_to_gate = re.search(
        r"cradle\s*[- ]?\s*to\s*[- ]?\s*gate|从摇篮到大门|摇篮到大门",
        boundary,
        re.IGNORECASE,
    )
    excludes_transport = re.search(
        r"(不包含|不包括|未包含|未纳入|排除|不含).{0,24}(运输|收集)|"
        r"(exclude|excluding|without|does not include).{0,40}(transport|collection)",
        all_scope_text,
        re.IGNORECASE,
    )
    if not (has_cradle_to_gate and excludes_transport):
        return []

    return [
        _finding(
            "process.boundary.lifecycle_stage_contradiction",
            "blocking",
            "建模信息 / 数据切断和完整性原则 ↔ 过程信息 / 数据集一般性说明",
            "边界使用 cradle-to-gate / 从摇篮到大门表述，同时又明确排除运输或收集过程。",
            "生命周期边界和排除活动之间存在未解释的口径冲突。",
            "将边界改写为实际包含的过程，并单独列出不含的收集、运输、使用和报废阶段。",
        )
    ]


def _check_reference_output_mass_attribute(dataset: dict[str, Any]) -> list[dict[str, str]]:
    reference_ids = {
        str(item.get("internal_id") or "")
        for item in dataset["reference_flow"].get("exchanges", [])
        if isinstance(item, dict)
    }
    reference_outputs = [
        item
        for item in dataset["exchanges"]["outputs"]
        if item.get("is_reference") or str(item.get("internal_id") or "") in reference_ids
    ]
    if not reference_outputs:
        return []

    technology = _field_text(dataset, "过程信息", "技术描述及背景系统")
    has_mass_in_technology = re.search(
        r"总质量|单件|每件|单个|约\s*\d+(?:\.\d+)?\s*t|total mass|per item|per unit|each|tons?",
        technology,
        re.IGNORECASE,
    )
    annual_reference = _field_text(dataset, "建模信息", "年产量或参考产量")
    annual_has_mass = re.search(
        r"质量|单件|每件|单个|\bkg\b|\d\s*t\b|吨|mass|tons?",
        annual_reference,
        re.IGNORECASE,
    )

    item_reference = False
    for item in reference_outputs:
        label_text = "\n".join([_flatten_text(item.get("unit")), _exchange_label(item)])
        amount = item.get("amount")
        try:
            small_count = amount is not None and float(amount) <= 10
        except (TypeError, ValueError):
            small_count = False
        if re.search(r"item|\bpcs?\b|片", label_text, re.IGNORECASE) or small_count:
            item_reference = True
            break

    if not (has_mass_in_technology and item_reference and not annual_has_mass):
        return []

    return [
        _finding(
            "process.reference_flow.annual_supply_unit",
            "advisory",
            "建模信息 / 年产量或参考产量 ↔ 输入/输出 / 基准流",
            f"技术描述包含质量信息，但参考产量仅写为：{annual_reference or '未填写'}。",
            "只写件数或片数会使后续用户难以判断参考输出与材料清单的质量闭合关系。",
            "在量值参考或定量产品属性中补充参考输出件数、总质量和单件质量。",
        )
    ]


def _check_recycling_burden_scope(dataset: dict[str, Any]) -> list[dict[str, str]]:
    secondary_inputs = [
        item
        for item in dataset["exchanges"]["inputs"]
        if re.search(
            r"废|再生|回收|scrap|waste|recycl|secondary",
            "\n".join([_exchange_label(item), str(item.get("flow_type") or "")]),
            re.IGNORECASE,
        )
    ]
    if not secondary_inputs:
        return []

    scope_text = _combined_section_text(dataset, "过程信息", "建模信息", "管理信息")
    has_burden_scope = re.search(
        r"cut-?off|recycled[- ]content|avoided burden|回收建模|废物流|上游负荷|原生.{0,8}负荷|"
        r"截断|零负担|负荷不计入|"
        r"(废料|废铜|废钢|废塑料|废纸|scrap|waste).{0,24}(收集|分选|预处理|前处理|纳入|不纳入|排除)",
        scope_text,
        re.IGNORECASE,
    )
    if has_burden_scope:
        return []

    names = "、".join(_exchange_label(item) for item in secondary_inputs[:3])
    return [
        _finding(
            "process.recycling.secondary_material_burden",
            "manual_review",
            "输入/输出 ↔ 建模信息 / 边界说明",
            f"输入中存在废料、再生料或回收料：{names}；未识别到回收建模口径或废料前处理负荷说明。",
            "用户无法判断这些二次原料是否包含收集、分选、预处理、运输或上游原生材料负荷。",
            "说明采用 cut-off、recycled-content、avoided burden 或其他口径，并列明废料前处理边界。",
        )
    ]


def _check_flow_form_unit_consistency(dataset: dict[str, Any]) -> list[dict[str, str]]:
    findings = []
    for exchange in _all_exchanges(dataset):
        label = _exchange_label(exchange)
        unit_text = _flatten_text(exchange.get("unit"))
        liquid = re.search(r"液化|液态|liquefied|liquid", label, re.IGNORECASE)
        volume = re.search(r"\bm3\b|m\^3|立方|体积|volume|cubic", unit_text, re.IGNORECASE)
        if liquid and volume:
            findings.append(
                _finding(
                    "process.flow.form_unit_consistency",
                    "blocking",
                    f"输入/输出 / {label}",
                    f"流名称表达为液态或液化形态，但参考单位/属性为体积：{unit_text or '未识别'}。",
                    "物理形态与单位口径不清会影响背景流选择和质量/体积换算。",
                    "若为液态体积则补充说明和换算；若为气态体积则改选气态氧气等匹配流。",
                )
            )
    return findings


def _check_water_boundary(dataset: dict[str, Any]) -> list[dict[str, str]]:
    water_inputs = [
        item
        for item in dataset["exchanges"]["inputs"]
        if re.search(r"水|water", _exchange_label(item), re.IGNORECASE)
    ]
    water_outputs = [
        item
        for item in dataset["exchanges"]["outputs"]
        if (
            re.search(
                r"COD|悬浮|水体|排放到水|emissions? to water|suspended solids|chemical oxygen demand",
                _exchange_label(item),
                re.IGNORECASE,
            )
            or (
                re.search(r"废水|污水|wastewater", _exchange_label(item), re.IGNORECASE)
                and re.search(r"Elementary flow|基本流", str(item.get("flow_type") or ""), re.IGNORECASE)
            )
        )
    ]
    if not (water_inputs and water_outputs):
        return []

    scope_text = _combined_section_text(dataset, "过程信息", "建模信息")
    has_water_boundary = re.search(
        r"废水处理|污水处理|循环水|回用|蒸发|损失|污泥含水|外部处理|水量平衡|"
        r"wastewater|recycled water|evaporation|water balance|sludge moisture|external treatment",
        scope_text,
        re.IGNORECASE,
    )
    if has_water_boundary:
        return []

    input_names = "、".join(_exchange_label(item) for item in water_inputs[:3])
    output_names = "、".join(_exchange_label(item) for item in water_outputs[:3])
    return [
        _finding(
            "process.inventory.water_balance_boundary",
            "manual_review",
            "输入/输出 ↔ 建模信息 / 水边界",
            f"存在水输入（{input_names}）和水体/废水相关输出（{output_names}），但未识别到水量去向或废水处理边界说明。",
            "水输入、废水处理和水体排放边界不清会影响清单完整性和外部处理是否重复计算。",
            "补充循环水、蒸发损失、污泥含水、废水内外部处理及处理后排放的边界说明。",
        )
    ]


def _repeated_paragraph(text: str) -> bool:
    paragraphs = [part.strip() for part in re.split(r"\n\s*\n", text) if len(part.strip()) >= 80]
    return any(count > 1 for count in Counter(paragraphs).values())


def _check_duplicate_language(dataset: dict[str, Any]) -> list[dict[str, str]]:
    findings = []
    for section_name in ("过程信息", "建模信息", "管理信息"):
        for field_name, value in dataset["sections"][section_name]["fields"].items():
            if isinstance(value, dict) and _repeated_paragraph(str(value.get("en", ""))):
                findings.append(
                    _finding(
                        "common.language.semantic_consistency",
                        "advisory",
                        f"{section_name} / {field_name} / English",
                        "英文内容存在完全重复的长段落。",
                        "重复内容影响可读性，但不单独构成阻断问题。",
                        "删除重复段落，保留一份完整表述。",
                    )
                )
    return findings


def _conclusion(findings: list[dict[str, str]]) -> str:
    severities = {item["severity"] for item in findings}
    if "blocking" in severities:
        return "预检不通过"
    if "input_gap" in severities:
        return "预检信息不足"
    if "manual_review" in severities:
        return "预检需人工确认"
    return "预检通过"


def run_deterministic_checks(
    dataset: dict[str, Any],
    *,
    guardrails: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if dataset.get("dataset_type") != "process":
        raise ValueError("The first runtime version only supports normalized process datasets.")
    findings = [
        *_check_coverage(dataset),
        *_check_reference_flow(dataset),
        *_check_exchange_metadata(dataset),
        *_check_flow_version_identity(dataset),
        *_check_explicit_electricity_conflict(dataset),
        *_check_upstream_burden_boundary_conflict(dataset),
        *_check_partly_terminated_evidence(dataset),
        *_check_cutoff_placeholder(dataset),
        *_check_cutoff_quantitative_criteria(dataset),
        *_check_lifecycle_stage_contradiction(dataset),
        *_check_reference_output_mass_attribute(dataset),
        *_check_recycling_burden_scope(dataset),
        *_check_flow_form_unit_consistency(dataset),
        *_check_water_boundary(dataset),
        *_check_duplicate_language(dataset),
    ]
    if guardrails:
        from .guardrails import run_guardrails

        findings.extend(run_guardrails(dataset, guardrails))
    return {
        "schema_version": "tiangong-audit-findings-v1",
        "dataset": dataset["identity"],
        "dataset_type": dataset["dataset_type"],
        "engine_scope": "deterministic-and-conservative-precheck",
        "conclusion": _conclusion(findings),
        "findings": findings,
        "semantic_review": {
            "required_rule_ids": list(REQUIRED_SEMANTIC_REVIEW_RULE_IDS),
            "note": "这些判断型或跨窗口规则必须由 Agent 结合标准化数据、程序预检和 Skill 参照文件复核；程序预检未命中不代表通过。",
        },
        "summary": {
            severity: sum(1 for item in findings if item["severity"] == severity)
            for severity in ("blocking", "advisory", "manual_review", "input_gap")
        },
    }
