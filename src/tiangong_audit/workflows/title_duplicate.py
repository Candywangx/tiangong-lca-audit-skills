"""Title-based duplicate check before a dataset audit begins."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime
import hashlib
import json
from pathlib import Path
from typing import Any


CHECK_RELATIVE_PATH = "snapshots/title-duplicate-check.json"
CONFIRMATION_RELATIVE_PATH = "agent-review/title-duplicate-confirmation.json"


def dataset_payload(row: dict[str, Any]) -> dict[str, Any]:
    for key in ("json_ordered", "json_tg", "json"):
        if isinstance(row.get(key), dict):
            return row[key]
    return row


def dataset_titles(payload: dict[str, Any]) -> dict[str, str]:
    if isinstance(payload.get("processDataSet"), dict):
        information = payload["processDataSet"].get("processInformation")
    elif isinstance(payload.get("lifeCycleModelDataSet"), dict):
        information = payload["lifeCycleModelDataSet"].get("lifeCycleModelInformation")
    else:
        return {"zh": "", "en": ""}
    data_set_information = information.get("dataSetInformation") if isinstance(information, dict) else None
    if not isinstance(data_set_information, dict):
        return {"zh": "", "en": ""}
    name = data_set_information.get("name", {})
    base_name = name.get("baseName") if isinstance(name, dict) else None
    return {language: _localized_text(base_name, language) for language in ("zh", "en")}


def _localized_text(value: Any, language: str) -> str:
    if isinstance(value, list):
        return next((text for item in value if (text := _localized_text(item, language))), "")
    if isinstance(value, dict):
        if value.get("@xml:lang") == language:
            return str(value.get("#text") or "")
        return str(value.get(language) or "")
    return ""


def _content_digest(row: dict[str, Any], dataset_type: str) -> str:
    version = str(row.get("version") or "")
    if not version:
        raise ValueError("题目查重缺少数据集版本，无法比较完整内容")
    root_key = "processDataSet" if dataset_type == "process" else "lifeCycleModelDataSet"
    info_key = "processInformation" if dataset_type == "process" else "lifeCycleModelInformation"

    payload = deepcopy(dataset_payload(row))
    body = payload.get(root_key)
    if not isinstance(body, dict):
        raise ValueError("题目查重无法读取完整数据集内容")

    def without_own_uuid(value: dict[str, Any]) -> dict[str, Any]:
        copied = deepcopy(value)
        data_body = copied.get(root_key)
        if isinstance(data_body, dict):
            information = data_body.get(info_key)
            data_set_information = (
                information.get("dataSetInformation") if isinstance(information, dict) else None
            )
            if not isinstance(data_set_information, dict):
                raise ValueError("题目查重无法读取数据集身份信息")
            for key in ("common:UUID", "UUID", "@UUID"):
                data_set_information.pop(key, None)
        return copied

    json_fields = {
        key: without_own_uuid(value)
        for key in ("json", "json_tg", "json_ordered")
        if isinstance((value := row.get(key)), dict)
    }
    if not json_fields:
        json_fields = {"json": without_own_uuid(payload)}
    serialized = json.dumps(
        [version, json_fields], ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _search_fingerprint(
    dataset_type: str,
    dataset_id: str,
    version: str,
    titles: dict[str, str],
    current_digest: str,
    fingerprint_items: list[tuple[str, str, str]],
) -> str:
    evidence = [dataset_type, dataset_id, version, titles, current_digest, fingerprint_items]
    return hashlib.sha256(
        json.dumps(evidence, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()


def check_title_duplicates(
    current_row: dict[str, Any], dataset_type: str, dataset_api: Any
) -> dict[str, Any]:
    dataset_id = str(current_row.get("id") or "")
    version = str(current_row.get("version") or "")
    if dataset_type not in {"process", "model"} or not dataset_id or not version:
        raise ValueError("题目查重需要数据集类型、UUID 和版本")
    titles = dataset_titles(dataset_payload(current_row))
    if not any(titles.values()):
        raise ValueError("题目查重缺少可搜索的中文或英文题目")
    current_digest = _content_digest(current_row, dataset_type)
    candidates: dict[tuple[str, str], dict[str, Any]] = {}
    for language, title in titles.items():
        if not title:
            continue
        rows = dataset_api.search_title(dataset_type, language, title)
        if not isinstance(rows, list) or len(rows) >= 1000:
            raise ValueError("题目查重搜索结果不完整，不能继续审核")
        current_matches = [
            row for row in rows if isinstance(row, dict)
            and str(row.get("id") or "") == dataset_id
            and str(row.get("version") or "") == version
        ]
        if not current_matches or any(
            _content_digest(row, dataset_type) != current_digest for row in current_matches
        ):
            raise ValueError("题目查重搜索结果无法验证当前数据集，不能继续审核")
        for row in rows:
            if not isinstance(row, dict):
                raise ValueError("题目查重搜索结果格式无效")
            row_id, row_version = str(row.get("id") or ""), str(row.get("version") or "")
            if not row_id or not row_version:
                raise ValueError("题目查重搜索结果缺少 UUID 或版本")
            if row_id == dataset_id:
                continue
            if dataset_titles(dataset_payload(row)).get(language) == title:
                candidates[(row_id, row_version)] = row

    matches = []
    fingerprint_items = []
    for (row_id, row_version), row in sorted(candidates.items()):
        candidate_digest = _content_digest(row, dataset_type)
        matches.append({
            "id": row_id,
            "version": row_version,
            "content_identical": candidate_digest == current_digest,
        })
        fingerprint_items.append((row_id, row_version, candidate_digest))
    identical = [
        {"id": item["id"], "version": item["version"]}
        for item in matches if item["content_identical"]
    ]
    fingerprint = _search_fingerprint(
        dataset_type, dataset_id, version, titles, current_digest, fingerprint_items
    )
    return {
        "schema_version": "tiangong-title-duplicate-check-v1",
        "dataset_type": dataset_type,
        "dataset_id": dataset_id,
        "version": version,
        "titles": titles,
        "status": "awaiting_human_confirmation" if identical else "clear",
        "matches": matches,
        "candidate_rows": [row for _, row in sorted(candidates.items())],
        "identical_candidates": identical,
        "current_content_digest": current_digest,
        "search_fingerprint": fingerprint,
    }


def require_title_duplicate_clearance(
    case_root: Path, dataset_id: str, version: str, dataset_type: str
) -> None:
    check_path = case_root / CHECK_RELATIVE_PATH
    if not check_path.exists():
        raise ValueError("缺少题目查重记录，暂停审核")
    check = json.loads(check_path.read_text(encoding="utf-8"))
    if not isinstance(check, dict) or any(
        check.get(key) != value
        for key, value in (
            ("schema_version", "tiangong-title-duplicate-check-v1"),
            ("dataset_id", dataset_id), ("version", version), ("dataset_type", dataset_type),
        )
    ):
        raise ValueError("题目查重记录与当前数据集不符，暂停审核")
    matches = check.get("matches")
    identical = check.get("identical_candidates")
    candidate_rows = check.get("candidate_rows")
    titles = check.get("titles")
    if (not isinstance(matches, list) or not isinstance(identical, list)
        or not isinstance(candidate_rows, list) or not isinstance(titles, dict)
        or len(matches) != len(candidate_rows)):
        raise ValueError("题目查重记录不完整，暂停审核")
    raw_path = case_root / "snapshots/dataset.raw.json"
    if not raw_path.exists():
        raise ValueError("缺少当前数据集原始内容，无法验证题目查重记录")
    current_payload = json.loads(raw_path.read_text(encoding="utf-8"))
    row_path = case_root / "snapshots/dataset-row.json"
    if row_path.exists():
        current_row = json.loads(row_path.read_text(encoding="utf-8"))
        if dataset_payload(current_row) != current_payload:
            raise ValueError("题目查重记录已过期：当前数据集原始内容发生变化")
    elif dataset_type == "model":
        raise ValueError("缺少模型数据集完整原始记录，无法验证题目查重")
    else:
        current_row = {"version": version, "json": current_payload}
    current_digest = _content_digest(current_row, dataset_type)
    if current_digest != check.get("current_content_digest"):
        raise ValueError("题目查重记录已过期：当前数据集内容发生变化，须重新搜索")
    fingerprint_items = []
    for match, row in zip(matches, candidate_rows):
        if not isinstance(match, dict) or not isinstance(row, dict) or any((
            str(row.get("id") or "") != match.get("id"),
            str(row.get("version") or "") != match.get("version"),
        )):
            raise ValueError("题目查重候选记录与比较结果不一致")
        candidate_digest = _content_digest(row, dataset_type)
        if match.get("content_identical") is not (candidate_digest == current_digest):
            raise ValueError("题目查重候选内容比较结果不一致")
        fingerprint_items.append((match["id"], match["version"], candidate_digest))
    if check.get("search_fingerprint") != _search_fingerprint(
        dataset_type, dataset_id, version, titles, current_digest, fingerprint_items
    ):
        raise ValueError("题目查重记录已过期，须重新搜索")
    expected_identical = [
        {"id": item.get("id"), "version": item.get("version")}
        for item in matches if isinstance(item, dict) and item.get("content_identical") is True
    ]
    if identical != expected_identical or check.get("status") != (
        "awaiting_human_confirmation" if identical else "clear"
    ):
        raise ValueError("题目查重记录状态不一致，暂停审核")
    if not identical:
        return
    confirmation_path = case_root / CONFIRMATION_RELATIVE_PATH
    if not confirmation_path.exists():
        raise ValueError("发现同题目、不同 UUID 且内容相同的数据集，须人工确认后继续审核")
    confirmation = json.loads(confirmation_path.read_text(encoding="utf-8"))
    if not isinstance(confirmation, dict):
        raise ValueError("同题目相同内容数据集的人工确认无效，暂停审核")
    expected_ids = {f"{item['id']}@{item['version']}" for item in identical}
    candidate_ids = confirmation.get("candidate_ids")
    if confirmation.get("decision") != "continue":
        raise ValueError("同题目相同内容数据集的人工确认无效，暂停审核")
    if (
        not str(confirmation.get("reviewer") or "").strip()
        or confirmation.get("search_fingerprint") != check.get("search_fingerprint")
        or not isinstance(candidate_ids, list)
        or not all(isinstance(item, str) for item in candidate_ids)
        or set(candidate_ids) != expected_ids
    ):
        raise ValueError("同题目相同内容数据集的人工确认无效，暂停审核")
    try:
        confirmed_at = datetime.fromisoformat(str(confirmation.get("confirmed_at") or ""))
    except ValueError as error:
        raise ValueError("人工确认时间无效，暂停审核") from error
    if confirmed_at.tzinfo is None:
        raise ValueError("人工确认时间须包含时区，暂停审核")
