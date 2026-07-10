from __future__ import annotations

import re
from typing import Any

from tiangong_audit.normalizer import normalize_dataset


MAX_CLAIM_LENGTH = 180


def generate_source_claims(payload: Any) -> dict[str, str]:
    """Extract dataset fields that Codex should semantically verify against source text.

    These claims are review targets, not machine-verification rules. The final
    source status must be written by Codex or a human after reading the dataset
    field and source context together.
    """

    dataset = _dataset_payload(payload)
    if not isinstance(dataset, dict):
        return {}
    if isinstance(dataset.get("processDataSet"), dict):
        return _raw_process_claims(dataset["processDataSet"])
    if isinstance(dataset.get("lifeCycleModelDataSet"), dict):
        return _raw_model_claims(dataset["lifeCycleModelDataSet"])
    try:
        normalized = normalize_dataset(dataset)
    except ValueError:
        return {}
    return _normalized_claims(normalized)


def _dataset_payload(payload: Any) -> Any:
    if not isinstance(payload, dict):
        return payload
    if isinstance(payload.get("data"), dict):
        return _dataset_payload(payload["data"])
    for key in ("json_ordered", "json_tg", "json"):
        if isinstance(payload.get(key), dict):
            return payload[key]
    return payload


def _raw_process_claims(process: dict[str, Any]) -> dict[str, str]:
    claims: dict[str, str] = {}
    process_information = process.get("processInformation") or {}
    data_set_information = process_information.get("dataSetInformation") or {}
    name = data_set_information.get("name") or {}
    modelling = process.get("modellingAndValidation") or {}
    lci_method = modelling.get("LCIMethodAndAllocation") or {}
    treatment = modelling.get("dataSourcesTreatmentAndRepresentativeness") or {}

    _add_localized(claims, "process.name", name.get("baseName"))
    _add_localized(claims, "process.route", name.get("treatmentStandardsRoutes"))
    _add_localized(claims, "process.location_type", name.get("mixAndLocationTypes"))
    _add_claim(claims, "process.dataset_type", lci_method.get("typeOfDataSet"))

    time = process_information.get("time") or {}
    for key in ("referenceYear", "dataSetValidUntil"):
        _add_claim(claims, f"process.time.{key}", time.get(key))
    _add_years(claims, "process.time.years", time)

    geography = process_information.get("geography") or {}
    _add_localized(
        claims,
        "process.geography.location",
        geography.get("locationOfOperationSupplyOrProduction"),
    )

    technology = process_information.get("technology") or {}
    _add_localized(
        claims,
        "process.technology.included_processes",
        technology.get("technologyDescriptionAndIncludedProcesses"),
    )

    _add_localized(
        claims,
        "process.cutoff",
        treatment.get("dataCutOffAndCompletenessPrinciples")
        or lci_method.get("dataCutOffAndCompletenessPrinciples"),
    )
    _add_localized(
        claims,
        "process.production_volume",
        treatment.get("annualSupplyOrProductionVolume"),
    )
    _add_years(claims, "process.representativeness.years", treatment)

    reference_pointer = str(
        data_set_information.get("referenceToReferenceFlow")
        or _get_path(process_information, "quantitativeReference", "referenceToReferenceFlow")
        or _get_path(data_set_information, "quantitativeReference", "referenceToReferenceFlow")
        or ""
    )
    for exchange in _items(_get_path(process, "exchanges", "exchange")):
        if not isinstance(exchange, dict):
            continue
        internal_id = str(
            exchange.get("@dataSetInternalID")
            or exchange.get("dataSetInternalID")
            or exchange.get("internalId")
            or ""
        )
        if not exchange.get("referenceToReferenceFlow") and internal_id != reference_pointer:
            continue
        reference = exchange.get("referenceToFlowDataSet") or {}
        _add_localized(
            claims,
            "process.reference_flow.name",
            reference.get("common:shortDescription") or reference.get("shortDescription"),
        )
        _add_claim(
            claims,
            "process.reference_flow.amount",
            exchange.get("resultingAmount") or exchange.get("meanAmount"),
        )
        break
    _add_raw_exchange_claims(claims, process)
    return claims


def _raw_model_claims(model: dict[str, Any]) -> dict[str, str]:
    claims: dict[str, str] = {}
    data_set_information = _get_path(
        model,
        "lifeCycleModelInformation",
        "dataSetInformation",
    ) or {}
    name = data_set_information.get("name") or {}
    _add_localized(claims, "model.name", name.get("baseName"))
    _add_localized(claims, "model.route", name.get("treatmentStandardsRoutes"))
    _add_localized(claims, "model.location_type", name.get("mixAndLocationTypes"))
    return claims


def _normalized_claims(dataset: dict[str, Any]) -> dict[str, str]:
    claims: dict[str, str] = {}
    identity = dataset.get("identity") or {}
    name = identity.get("name") or {}
    _add_claim(claims, "dataset.name.zh", name.get("zh"))
    _add_claim(claims, "dataset.name.en", name.get("en"))

    for section_name, section in (dataset.get("sections") or {}).items():
        fields = section.get("fields") if isinstance(section, dict) else {}
        if not isinstance(fields, dict):
            continue
        for field_name in (
            "处理、标准、路线",
            "位置类型",
            "数据集类型",
            "技术描述及背景系统",
            "年产量或参考产量",
        ):
            value = fields.get(field_name)
            field_id = f"section.{_slug(section_name)}.{_slug(field_name)}"
            if isinstance(value, dict):
                _add_claim(claims, f"{field_id}.zh", value.get("zh"))
                _add_claim(claims, f"{field_id}.en", value.get("en"))
            else:
                _add_claim(claims, field_id, value)

    for index, exchange in enumerate((dataset.get("reference_flow") or {}).get("exchanges") or [], 1):
        if not isinstance(exchange, dict):
            continue
        name = exchange.get("name") or {}
        _add_claim(claims, f"reference_flow.{index}.name.zh", name.get("zh"))
        _add_claim(claims, f"reference_flow.{index}.name.en", name.get("en"))
        _add_claim(claims, f"reference_flow.{index}.amount", exchange.get("amount"))
        _add_claim(claims, f"reference_flow.{index}.unit", exchange.get("unit"))
    _add_normalized_exchange_claims(claims, dataset)
    return claims


def _add_raw_exchange_claims(claims: dict[str, str], process: dict[str, Any]) -> None:
    direction_counts = {"input": 0, "output": 0, "unknown": 0}
    for exchange in _items(_get_path(process, "exchanges", "exchange")):
        if not isinstance(exchange, dict):
            continue
        direction = _exchange_direction(exchange.get("exchangeDirection") or exchange.get("direction"))
        direction_counts[direction] = direction_counts.get(direction, 0) + 1
        prefix = f"process.exchange.{direction}.{direction_counts[direction]}"
        reference = exchange.get("referenceToFlowDataSet") or {}
        _add_localized(
            claims,
            f"{prefix}.name",
            reference.get("common:shortDescription")
            or reference.get("shortDescription")
            or exchange.get("name"),
        )
        _add_claim(claims, f"{prefix}.amount", exchange.get("resultingAmount") or exchange.get("meanAmount"))
        _add_claim(claims, f"{prefix}.unit", _exchange_unit(exchange))
        _add_localized(claims, f"{prefix}.comment", exchange.get("generalComment"))


def _add_normalized_exchange_claims(claims: dict[str, str], dataset: dict[str, Any]) -> None:
    exchanges = dataset.get("exchanges") or {}
    for direction, items in (("input", exchanges.get("inputs")), ("output", exchanges.get("outputs"))):
        for index, exchange in enumerate(_items(items), 1):
            if not isinstance(exchange, dict):
                continue
            prefix = f"process.exchange.{direction}.{index}"
            name = exchange.get("name") or {}
            _add_claim(claims, f"{prefix}.name.zh", name.get("zh"))
            _add_claim(claims, f"{prefix}.name.en", name.get("en"))
            _add_claim(claims, f"{prefix}.amount", exchange.get("amount") or exchange.get("mean_amount"))
            unit = exchange.get("unit") or {}
            _add_claim(claims, f"{prefix}.unit.zh", unit.get("zh") if isinstance(unit, dict) else unit)
            _add_claim(claims, f"{prefix}.unit.en", unit.get("en") if isinstance(unit, dict) else unit)
            _add_claim(claims, f"{prefix}.flow_type", exchange.get("flow_type"))
            classification = exchange.get("classification")
            if isinstance(classification, list):
                _add_claim(claims, f"{prefix}.classification", " > ".join(str(item) for item in classification))
            else:
                _add_claim(claims, f"{prefix}.classification", classification)


def _exchange_direction(value: Any) -> str:
    text = _text(value).lower()
    if text in {"input", "inputs", "in"} or "input" in text:
        return "input"
    if text in {"output", "outputs", "out"} or "output" in text:
        return "output"
    return "unknown"


def _exchange_unit(exchange: dict[str, Any]) -> Any:
    return (
        exchange.get("unit")
        or exchange.get("referenceUnit")
        or exchange.get("common:referenceUnit")
        or exchange.get("@unit")
    )


def _add_localized(claims: dict[str, str], field: str, value: Any) -> None:
    localized = _localized_values(value)
    for language in ("zh", "en"):
        _add_claim(claims, f"{field}.{language}", localized.get(language))
    if not localized.get("zh") and not localized.get("en"):
        _add_claim(claims, field, localized.get("raw"))


def _add_claim(claims: dict[str, str], field: str, value: Any) -> None:
    text = _text(value)
    if not text or len(text) > MAX_CLAIM_LENGTH:
        return
    if text in {"-", "N/A", "n/a", "not applicable", "Not applicable"}:
        return
    claims.setdefault(field, text)


def _add_years(claims: dict[str, str], field: str, value: Any) -> None:
    text = _flatten_text(value)
    years = []
    for match in re.finditer(r"\b(19\d{2}|20\d{2}|21\d{2})\b", text):
        year = match.group(1)
        if year not in years:
            years.append(year)
    for index, year in enumerate(years[:5], 1):
        claims.setdefault(f"{field}.{index}", year)


def _localized_values(value: Any) -> dict[str, str]:
    result = {"zh": "", "en": "", "raw": ""}
    if isinstance(value, list):
        raw_parts: list[str] = []
        for item in value:
            item_values = _localized_values(item)
            for language in ("zh", "en"):
                if item_values[language] and not result[language]:
                    result[language] = item_values[language]
            if item_values["raw"]:
                raw_parts.append(item_values["raw"])
        result["raw"] = " / ".join(raw_parts)
        return result
    if isinstance(value, dict):
        if "zh" in value or "en" in value:
            return {
                "zh": _text(value.get("zh")),
                "en": _text(value.get("en")),
                "raw": _text(value.get("raw")),
            }
        text = _text(
            value.get("#text")
            or value.get("text")
            or value.get("value")
            or value.get("name")
        )
        language = _text(
            value.get("@xml:lang")
            or value.get("xml:lang")
            or value.get("lang")
            or value.get("language")
        ).lower()
        if language.startswith("zh"):
            result["zh"] = text
        elif language.startswith("en"):
            result["en"] = text
        result["raw"] = text
        return result
    result["raw"] = _text(value)
    return result


def _items(value: Any) -> list[Any]:
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def _get_path(value: Any, *path: str) -> Any:
    current = value
    for key in path:
        if isinstance(current, list):
            current = current[0] if current else None
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def _flatten_text(value: Any) -> str:
    if isinstance(value, dict):
        return " ".join(_flatten_text(item) for item in value.values())
    if isinstance(value, list):
        return " ".join(_flatten_text(item) for item in value)
    return _text(value)


def _text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _slug(value: str) -> str:
    text = re.sub(r"\W+", "_", value, flags=re.UNICODE).strip("_")
    return text or "field"
