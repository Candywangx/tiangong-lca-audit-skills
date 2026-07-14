from __future__ import annotations

from copy import deepcopy
from typing import Any

NORMALIZED_SCHEMA = "tiangong-audit-normalized-v1"
PROCESS_SECTIONS = ("过程信息", "建模信息", "管理信息", "输入/输出")


def _multilingual_name(value: Any) -> dict[str, str]:
    if isinstance(value, dict):
        return {
            "zh": str(value.get("zh", "") or ""),
            "en": str(value.get("en", "") or ""),
            "raw": "",
        }
    raw = str(value or "")
    languages = {"zh": "", "en": "", "raw": raw}
    for line in raw.splitlines():
        match = line.strip().partition(":")
        key = match[0].lower()
        if match[1] and key in {"zh", "en"}:
            languages[key] = match[2].strip()
    return languages


def _items(value: Any) -> list[Any]:
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def _first(value: Any) -> Any:
    return value[0] if isinstance(value, list) and value else value


def _get_path(value: dict[str, Any], *path: str) -> Any:
    current: Any = value
    for key in path:
        current = _first(current)
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def _localized_text(value: Any) -> dict[str, str]:
    if isinstance(value, dict) and ("zh" in value or "en" in value):
        return _multilingual_name(value)
    if isinstance(value, dict) and "baseName" in value:
        return _localized_text(value.get("baseName"))
    if isinstance(value, dict) and "shortDescription" in value:
        return _localized_text(value.get("shortDescription"))
    if isinstance(value, dict) and "common:shortDescription" in value:
        return _localized_text(value.get("common:shortDescription"))
    if isinstance(value, list):
        languages = {"zh": "", "en": "", "raw": ""}
        raw_parts: list[str] = []
        for item in value:
            localized = _localized_text(item)
            for key in ("zh", "en"):
                if localized[key] and not languages[key]:
                    languages[key] = localized[key]
            if localized["raw"]:
                raw_parts.append(localized["raw"])
        languages["raw"] = "\n".join(raw_parts)
        return languages
    if isinstance(value, dict):
        text = str(value.get("#text") or value.get("text") or value.get("value") or "")
        language = str(value.get("@xml:lang") or value.get("lang") or value.get("language") or "").lower()
        languages = {"zh": "", "en": "", "raw": text}
        if language.startswith("zh"):
            languages["zh"] = text
        elif language.startswith("en"):
            languages["en"] = text
        return languages
    return _multilingual_name(value)


def _number(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(str(value).replace(",", ""))
    except ValueError:
        return None


def _normalize_exchange(row: dict[str, Any], fallback_direction: str) -> dict[str, Any]:
    direction = str(row.get("方向") or fallback_direction).lower()
    return {
        "index": row.get("序号"),
        "internal_id": str(row.get("内部ID", "") or ""),
        "direction": "input" if direction.startswith("input") or fallback_direction == "input" else "output",
        "name": _multilingual_name(row.get("流")),
        "amount": _number(row.get("结果量")),
        "mean_amount": _number(row.get("平均量")),
        "unit": deepcopy(row.get("参考单位")),
        "derivation": str(row.get("数据推导类型/状态", "") or ""),
        "is_reference": str(row.get("是否基准流", "") or "") in {"是", "yes", "true", "True"},
        "flow_type": str(row.get("流类型", "") or ""),
        "classification": deepcopy(row.get("流分类") or []),
        "flow_metadata_status": str(
            row.get("流元数据状态") or row.get("flow_metadata_status") or "resolved"
        ),
        "flow_metadata_error": str(
            row.get("流元数据错误") or row.get("flow_metadata_error") or ""
        ),
        "flow_uuid": str(row.get("流UUID") or row.get("flow_uuid") or ""),
        "flow_version": str(row.get("流版本") or row.get("flow_version") or ""),
        "exchange_description": _multilingual_name(row.get("交换短描述") or {}),
        "flow_dataset_name": _multilingual_name(row.get("流数据集名称") or row.get("流")),
        "reference_property": _multilingual_name(row.get("参考属性") or {}),
        "reference_unit": _multilingual_name(row.get("参考单位")),
        "source": deepcopy(row.get("数据来源") or []),
        "raw": deepcopy(row),
    }


def _normalize_projected(payload: dict[str, Any]) -> dict[str, Any]:
    categories = {item.get("name"): item for item in payload.get("categories", [])}
    sections = {
        name: {
            "present": name in categories,
            "fields": deepcopy(categories.get(name, {}).get("fields", {})),
            "missing_fields": deepcopy(categories.get(name, {}).get("missingFields", [])),
        }
        for name in PROCESS_SECTIONS
    }

    io_category = categories.get("输入/输出", {})
    inputs: list[dict[str, Any]] = []
    outputs: list[dict[str, Any]] = []
    for table in io_category.get("tables", []):
        fallback = "input" if table.get("caption") == "输入" else "output"
        for row in table.get("rows", []):
            exchange = _normalize_exchange(row, fallback)
            (inputs if exchange["direction"] == "input" else outputs).append(exchange)

    process_fields = sections["过程信息"]["fields"]
    management_fields = sections["管理信息"]["fields"]
    reference_pointer = process_fields.get("功能单位或基准流", {})
    if not isinstance(reference_pointer, dict):
        reference_pointer = {}

    missing_sections = [name for name, section in sections.items() if not section["present"]]
    return {
        "schema_version": NORMALIZED_SCHEMA,
        "source": {
            "schema_version": payload.get("schemaVersion"),
            "projection_version": payload.get("projectionVersion"),
            "extraction_method": payload.get("extractionMethod"),
        },
        "dataset_type": "process",
        "identity": {
            "id": str(payload.get("processId", "") or ""),
            "version": str(payload.get("processVersion") or management_fields.get("数据集版本") or ""),
            "name": _multilingual_name(process_fields.get("基本名称")),
        },
        "sections": sections,
        "reference_flow": {
            "pointer": str(reference_pointer.get("referenceToReferenceFlow", "") or ""),
            "exchanges": [item for item in [*inputs, *outputs] if item["is_reference"]],
        },
        "exchanges": {"inputs": inputs, "outputs": outputs},
        "coverage": {
            "present_sections": [name for name, section in sections.items() if section["present"]],
            "missing_sections": missing_sections,
            "input_count": len(inputs),
            "output_count": len(outputs),
        },
        "precheck_findings": deepcopy(payload.get("precheckFindings", [])),
        "omitted_fields": deepcopy(payload.get("omittedFields", [])),
    }


def _classifications(value: Any) -> list[dict[str, str]]:
    classification_information = _first(
        _get_path(value, "classificationInformation")
    ) or {}
    if not isinstance(classification_information, dict):
        return []
    classification = _first(
        classification_information.get("classification")
        or classification_information.get("common:classification")
        or classification_information.get("elementaryFlowCategorization")
        or classification_information.get("common:elementaryFlowCategorization")
    ) or {}
    if not isinstance(classification, dict):
        return []
    classes = (
        classification.get("class")
        or classification.get("common:class")
        or classification.get("category")
        or classification.get("common:category")
    )
    result: list[dict[str, str]] = []
    for item in _items(classes):
        if isinstance(item, dict):
            name = str(item.get("#text") or item.get("name") or item.get("@name") or "")
            level = str(item.get("@level") or item.get("level") or "")
        else:
            name = str(item or "")
            level = ""
        if name:
            result.append({"level": level, "name": name})
    return result


def _flow_property(
    flow_dataset: dict[str, Any], reference_property_id: str
) -> tuple[dict[str, str], dict[str, str]]:
    properties = _get_path(flow_dataset, "flowProperties", "flowProperty")
    selected = None
    for item in _items(properties):
        if not isinstance(item, dict):
            continue
        item_id = str(
            item.get("@dataSetInternalID")
            or item.get("dataSetInternalID")
            or item.get("@id")
            or item.get("id")
            or ""
        )
        if reference_property_id and item_id == reference_property_id:
            selected = item
            break
        if selected is None:
            selected = item

    if not isinstance(selected, dict):
        return {"zh": "", "en": "", "raw": ""}, {"zh": "", "en": "", "raw": ""}

    reference_property = _localized_text(
        _get_path(selected, "referenceToFlowPropertyDataSet", "shortDescription")
        or selected.get("referenceToFlowPropertyDataSet")
    )
    reference_unit = _localized_text(
        _get_path(selected, "referenceToUnitGroupDataSet", "shortDescription")
        or selected.get("referenceToUnitGroupDataSet")
        or selected.get("unit")
    )
    return reference_property, reference_unit


def _normalize_raw_exchange(row: dict[str, Any], reference_pointer: str) -> dict[str, Any]:
    direction = str(row.get("exchangeDirection") or row.get("direction") or "").lower()
    reference = row.get("referenceToFlowDataSet") or {}
    raw_flow_dataset = row.get("flowDataSet")
    flow_dataset = raw_flow_dataset if isinstance(raw_flow_dataset, dict) else {}
    flow_information = _get_path(flow_dataset, "flowInformation") or {}
    data_set_information = _get_path(flow_information, "dataSetInformation") or {}
    exchange_description = _localized_text(
        reference.get("common:shortDescription") or reference.get("shortDescription")
    )
    flow_dataset_name = _localized_text(_get_path(data_set_information, "name", "baseName"))
    name = {
        "zh": flow_dataset_name["zh"] or exchange_description["zh"],
        "en": flow_dataset_name["en"] or exchange_description["en"],
        "raw": flow_dataset_name["raw"] or exchange_description["raw"],
    }
    reference_property_id = str(
        _get_path(flow_information, "quantitativeReference", "referenceToReferenceFlowProperty")
        or ""
    )
    reference_property, reference_unit = _flow_property(flow_dataset, reference_property_id)
    internal_id = str(
        row.get("@dataSetInternalID")
        or row.get("dataSetInternalID")
        or row.get("internalId")
        or row.get("id")
        or ""
    )
    flow_type = str(
        _get_path(flow_dataset, "modellingAndValidation", "LCIMethod", "typeOfDataSet")
        or _get_path(flow_dataset, "modellingAndValidation", "LCIMethodAndAllocation", "typeOfDataSet")
        or _get_path(flow_information, "dataSetInformation", "typeOfDataSet")
        or row.get("flowType")
        or ""
    )
    flow_uuid = str(
        reference.get("@refObjectId")
        or reference.get("refObjectId")
        or reference.get("uuid")
        or reference.get("@uuid")
        or ""
    )
    flow_metadata_status = str(
        row.get("flowMetadataStatus")
        or row.get("flow_metadata_status")
        or ("resolved" if isinstance(raw_flow_dataset, dict) else "not_fetched")
    )
    return {
        "index": row.get("exchangeNumber") or row.get("@index"),
        "internal_id": internal_id,
        "direction": "input" if direction.startswith("input") else "output",
        "name": name,
        "amount": _number(row.get("resultingAmount") or row.get("meanAmount")),
        "mean_amount": _number(row.get("meanAmount") or row.get("resultingAmount")),
        "unit": reference_unit,
        "derivation": str(row.get("dataDerivationTypeStatus") or ""),
        "is_reference": bool(row.get("referenceToReferenceFlow")) or internal_id == reference_pointer,
        "flow_type": flow_type,
        "classification": _classifications(data_set_information),
        "flow_metadata_status": flow_metadata_status,
        "flow_metadata_error": str(
            row.get("flowMetadataError") or row.get("flow_metadata_error") or ""
        ),
        "flow_uuid": flow_uuid,
        "flow_version": str(reference.get("@version") or reference.get("version") or ""),
        "exchange_description": exchange_description,
        "flow_dataset_name": flow_dataset_name,
        "reference_property": reference_property,
        "reference_unit": reference_unit,
        "source": deepcopy(row.get("dataSource") or []),
        "raw": deepcopy(row),
    }


def _normalize_raw_tidas(payload: dict[str, Any]) -> dict[str, Any]:
    process = payload.get("processDataSet") or payload
    process_information = process.get("processInformation", {})
    data_set_information = process_information.get("dataSetInformation", {})
    modelling = process.get("modellingAndValidation", {})
    lci_method = modelling.get("LCIMethodAndAllocation", {})
    data_treatment = modelling.get("dataSourcesTreatmentAndRepresentativeness", {})
    administrative = process.get("administrativeInformation", {})
    publication = administrative.get("publicationAndOwnership", {})

    reference_pointer = str(
        data_set_information.get("referenceToReferenceFlow")
        or _get_path(process_information, "quantitativeReference", "referenceToReferenceFlow")
        or _get_path(data_set_information, "quantitativeReference", "referenceToReferenceFlow")
        or ""
    )
    exchanges: list[dict[str, Any]] = []
    for row in _items(_get_path(process, "exchanges", "exchange")):
        if isinstance(row, dict):
            exchanges.append(_normalize_raw_exchange(row, reference_pointer))

    inputs = [item for item in exchanges if item["direction"] == "input"]
    outputs = [item for item in exchanges if item["direction"] == "output"]
    sections = {
        "过程信息": {
            "present": bool(process_information),
            "fields": {
                "基本名称": _localized_text(data_set_information.get("name")),
                "处理、标准、路线": _localized_text(
                    _get_path(data_set_information, "name", "treatmentStandardsRoutes")
                ),
                "位置类型": _localized_text(
                    _get_path(data_set_information, "name", "mixAndLocationTypes")
                ),
                "分类": deepcopy(_classifications(data_set_information)),
                "数据集一般性说明": _localized_text(
                    data_set_information.get("common:generalComment")
                    or data_set_information.get("generalComment")
                    or data_set_information.get("generalInformation")
                ),
                "技术描述及背景系统": _localized_text(
                    _get_path(process_information, "technology", "technologyDescriptionAndIncludedProcesses")
                    or _get_path(process_information, "technology", "technologicalApplicability")
                ),
            },
            "missing_fields": [],
        },
        "建模信息": {
            "present": bool(modelling),
            "fields": {
                "数据集类型": str(lci_method.get("typeOfDataSet") or ""),
                "数据切断和完整性原则": _localized_text(
                    data_treatment.get("dataCutOffAndCompletenessPrinciples")
                    or lci_method.get("dataCutOffAndCompletenessPrinciples")
                ),
                "年产量或参考产量": _localized_text(
                    data_treatment.get("annualSupplyOrProductionVolume")
                ),
                "数据来源、处理和代表性": _localized_text(
                    data_treatment.get("deviationsFromLCIMethodPrinciple")
                    or data_treatment.get("dataSelectionAndCombinationPrinciples")
                    or data_treatment.get("referenceToDataSource")
                    or lci_method.get("deviationsFromLCIMethodPrinciple")
                    or lci_method.get("dataSelectionAndCombinationPrinciples")
                ),
            },
            "missing_fields": [],
        },
        "管理信息": {
            "present": bool(administrative),
            "fields": {
                "数据集版本": str(publication.get("dataSetVersion") or ""),
            },
            "missing_fields": [],
        },
        "输入/输出": {"present": bool(exchanges), "fields": {}, "missing_fields": []},
    }
    missing_sections = [name for name, section in sections.items() if not section["present"]]
    return {
        "schema_version": NORMALIZED_SCHEMA,
        "source": {
            "schema_version": payload.get("schemaVersion"),
            "projection_version": None,
            "extraction_method": "raw-tidas",
        },
        "dataset_type": "process",
        "identity": {
            "id": str(data_set_information.get("UUID") or data_set_information.get("@UUID") or ""),
            "version": str(publication.get("dataSetVersion") or ""),
            "name": _localized_text(data_set_information.get("name")),
        },
        "sections": sections,
        "reference_flow": {
            "pointer": reference_pointer,
            "exchanges": [item for item in exchanges if item["is_reference"]],
        },
        "exchanges": {"inputs": inputs, "outputs": outputs},
        "coverage": {
            "present_sections": [name for name, section in sections.items() if section["present"]],
            "missing_sections": missing_sections,
            "input_count": len(inputs),
            "output_count": len(outputs),
        },
        "precheck_findings": deepcopy(payload.get("precheckFindings", [])),
        "omitted_fields": deepcopy(payload.get("omittedFields", [])),
    }


def normalize_dataset(payload: dict[str, Any]) -> dict[str, Any]:
    if payload.get("schema_version") == NORMALIZED_SCHEMA:
        return deepcopy(payload)
    if isinstance(payload.get("categories"), list):
        return _normalize_projected(payload)
    if isinstance(payload.get("processDataSet"), dict):
        return _normalize_raw_tidas(payload)
    raise ValueError(
        "Unsupported input JSON. Expected a projected Tiangong dataset with categories[] "
        f", raw processDataSet, or normalized schema {NORMALIZED_SCHEMA}."
    )
