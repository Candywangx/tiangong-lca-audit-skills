from __future__ import annotations

from copy import deepcopy
from datetime import date
import json
from pathlib import Path
import re
from typing import Any

from tiangong_audit.case_store import CaseStore, CaseStoreError
from tiangong_audit.contracts.agent_review import new_agent_findings_template
from tiangong_audit.integrations import tiangong_api
from tiangong_audit.normalizer import normalize_dataset
from tiangong_audit.report.markdown import render_findings
from tiangong_audit.rule_engine import load_skill_guardrails, run_deterministic_checks
from tiangong_audit.sources import generate_source_claims

from .source import fetch_sources


def intake_review(
    review_id: str,
    *,
    root: Path,
    account_role: str = "admin",
    batch_id: str | None = None,
    case_store: CaseStore | None = None,
    client: Any | None = None,
) -> dict[str, Any]:
    """Fetch a platform review task and build the local evidence case."""

    root = Path(root)
    store = case_store or CaseStore(root / "cases")
    platform_client = client or tiangong_api.TiangongAPIClient(account_role=account_role)
    review_api = tiangong_api.ReviewAPI(platform_client)
    dataset_api = tiangong_api.DatasetAPI(platform_client)

    task = review_api.get_task(review_id)
    dataset_id = str(task.get("data_id") or task.get("dataset_id") or "")
    version = str(task.get("data_version") or task.get("version") or "")
    if not dataset_id or not version:
        raise tiangong_api.TiangongAPIError(
            f"Review task {review_id} is missing data_id or data_version"
        )

    dataset_result = dataset_api.resolve_dataset(dataset_id, version)
    dataset_type = str(dataset_result.get("dataset_type") or "")
    dataset_row = dict(dataset_result.get("data") or {})
    dataset_payload = _dataset_payload(dataset_row)
    name = _dataset_name(dataset_payload)
    manifest = _get_or_create_case(
        store,
        review_id=review_id,
        batch_id=batch_id or _default_batch_id(account_role),
        dataset_id=dataset_id,
        version=version,
        dataset_type=dataset_type,
        name_zh=name.get("zh", ""),
        name_en=name.get("en", ""),
    )

    case_root = root / "cases" / manifest.case_dir
    snapshots = case_root / "snapshots"
    snapshots.mkdir(parents=True, exist_ok=True)
    _write_json(snapshots / "review-task.json", task)
    _write_json(snapshots / "dataset-row.json", dataset_row)
    _write_json(snapshots / "dataset.raw.json", dataset_payload)

    manifest.dataset_id = dataset_id
    manifest.version = version
    manifest.dataset_type = dataset_type
    manifest.name_zh = name.get("zh", "")
    manifest.name_en = name.get("en", "")
    manifest.status = "intake_fetched"
    manifest.set_step("fetched", True)
    manifest.artifacts["review_task"] = _case_path_label(snapshots / "review-task.json", root)
    manifest.artifacts["dataset_raw"] = _case_path_label(snapshots / "dataset.raw.json", root)

    normalization_payload = dataset_payload
    flow_evidence_summary: dict[str, Any] | None = None
    if dataset_type == "process":
        normalization_payload, flow_evidence_summary = _materialize_process_flows(
            dataset_payload,
            dataset_api=dataset_api,
            snapshots=snapshots,
            root=root,
        )
        enriched_path = snapshots / "dataset.enriched.json"
        _write_json(enriched_path, normalization_payload)
        manifest.artifacts["dataset_enriched"] = _case_path_label(enriched_path, root)
        manifest.artifacts["flow_metadata"] = _case_path_label(
            snapshots / "flow-metadata.json", root
        )

    guardrails = load_skill_guardrails(root)
    precheck_summary: dict[str, Any] | None = None
    model_evidence_summary: dict[str, Any] | None = None
    try:
        normalized = normalize_dataset(normalization_payload)
    except ValueError:
        normalized = None
    if normalized:
        normalized_path = snapshots / "dataset.normalized.json"
        _write_json(normalized_path, normalized)
        manifest.set_step("normalized", True)
        manifest.artifacts["dataset_normalized"] = _case_path_label(normalized_path, root)
        if normalized.get("dataset_type") == "process":
            precheck = run_deterministic_checks(normalized, guardrails=guardrails)
            precheck_dir = case_root / "precheck"
            precheck_dir.mkdir(parents=True, exist_ok=True)
            precheck_json = precheck_dir / "precheck.json"
            precheck_md = precheck_dir / "precheck.md"
            _write_json(precheck_json, precheck)
            precheck_md.write_text(render_findings(precheck), encoding="utf-8")
            manifest.set_step("prechecked", True)
            manifest.artifacts["precheck"] = _case_path_label(precheck_json, root)
            precheck_summary = precheck.get("summary")

    if dataset_type == "model":
        model_evidence_summary = _materialize_model_linked_processes(
            dataset_payload,
            dataset_api=dataset_api,
            case_root=case_root,
            root=root,
            guardrails=guardrails,
        )
        manifest.artifacts["model_linked_process_refs"] = _case_path_label(
            case_root / "snapshots" / "model-linked-process-refs.json",
            root,
        )

    agent_review_dir = case_root / "agent-review"
    agent_review_dir.mkdir(parents=True, exist_ok=True)
    template_path = agent_review_dir / "agent-findings.template.json"
    _write_json(
        template_path,
        new_agent_findings_template(
            review_id=review_id,
            dataset_id=dataset_id,
            dataset_type=dataset_type,
        ),
    )
    manifest.artifacts["agent_findings_template"] = _case_path_label(template_path, root)

    store.write_case(manifest)

    claims = generate_source_claims(dataset_payload)
    source_summary = fetch_sources(
        dataset_payload,
        root=root,
        case_store=store,
        review_id=review_id,
        batch_id=manifest.batch_id,
        account_role=account_role,
        platform_client=platform_client,
        claims=claims,
    )
    manifest = store.get_case(review_id, batch_id=manifest.batch_id)
    manifest.status = "intake_completed"
    store.write_case(manifest)

    return {
        "review_id": review_id,
        "batch_id": manifest.batch_id,
        "case_dir": manifest.case_dir,
        "dataset_id": dataset_id,
        "version": version,
        "dataset_type": dataset_type,
        "claim_count": len(claims),
        "source_count": source_summary.get("source_count", 0),
        "check_count": source_summary.get("check_count", 0),
        "precheck_summary": precheck_summary,
        "model_evidence_summary": model_evidence_summary,
        "flow_evidence_summary": flow_evidence_summary,
        "artifacts": dict(manifest.artifacts),
    }


def _materialize_process_flows(
    payload: dict[str, Any],
    *,
    dataset_api: Any,
    snapshots: Path,
    root: Path,
) -> tuple[dict[str, Any], dict[str, Any]]:
    enriched = deepcopy(payload)
    exchanges = _process_exchange_rows(enriched)
    related_dir = snapshots / "related-flows"
    cache: dict[tuple[str, str], dict[str, Any]] = {}
    reference_counts: dict[tuple[str, str], int] = {}

    for exchange in exchanges:
        reference = exchange.get("referenceToFlowDataSet") or {}
        flow_id = str(
            reference.get("@refObjectId")
            or reference.get("refObjectId")
            or reference.get("uuid")
            or reference.get("@uuid")
            or ""
        )
        version = str(reference.get("@version") or reference.get("version") or "")
        key = (flow_id, version)
        reference_counts[key] = reference_counts.get(key, 0) + 1
        if key not in cache:
            cache[key] = _fetch_flow_evidence(
                flow_id,
                version,
                dataset_api=dataset_api,
                related_dir=related_dir,
                root=root,
            )
        evidence = cache[key]
        exchange["flowMetadataStatus"] = evidence["status"]
        if evidence.get("error"):
            exchange["flowMetadataError"] = evidence["error"]
        if evidence["status"] == "resolved":
            exchange["flowDataSet"] = deepcopy(evidence["flow_dataset"])

    records = []
    for key, evidence in cache.items():
        record = {
            "flow_id": key[0],
            "version": key[1],
            "status": evidence["status"],
            "reference_count": reference_counts[key],
        }
        for field in ("path", "error"):
            if evidence.get(field):
                record[field] = evidence[field]
        records.append(record)
    _write_json(snapshots / "flow-metadata.json", {"flows": records})
    summary = {
        "reference_count": len(exchanges),
        "unique_flow_count": len(cache),
        "resolved_count": sum(item["status"] == "resolved" for item in cache.values()),
        "unresolved_count": sum(item["status"] != "resolved" for item in cache.values()),
    }
    return enriched, summary


def _process_exchange_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    process = payload.get("processDataSet")
    if not isinstance(process, dict):
        return []
    exchange_value = (process.get("exchanges") or {}).get("exchange")
    if isinstance(exchange_value, dict):
        return [exchange_value]
    if isinstance(exchange_value, list):
        return [item for item in exchange_value if isinstance(item, dict)]
    return []


def _fetch_flow_evidence(
    flow_id: str,
    version: str,
    *,
    dataset_api: Any,
    related_dir: Path,
    root: Path,
) -> dict[str, Any]:
    if not flow_id:
        return {"status": "not_fetched", "error": "exchange flow reference has no UUID"}
    if not version:
        return {"status": "not_fetched", "error": "exchange flow reference has no version"}
    try:
        row = dataset_api.get_flow(flow_id, version)
    except tiangong_api.TiangongAPIError as error:
        message = str(error)
        status = "not_found" if "not found" in message.lower() else "fetch_failed"
        return {"status": status, "error": message}

    flow_payload = _dataset_payload(row)
    flow_dataset = flow_payload.get("flowDataSet") if isinstance(flow_payload, dict) else None
    related_dir.mkdir(parents=True, exist_ok=True)
    target = related_dir / f"{_safe_filename(flow_id)}_{_safe_filename(version or 'latest')}.json"
    _write_json(target, row)
    path = _case_path_label(target, root)
    if not isinstance(flow_dataset, dict):
        return {
            "status": "parse_failed",
            "error": "flow payload does not contain flowDataSet",
            "path": path,
        }
    return {"status": "resolved", "flow_dataset": flow_dataset, "path": path}


def _get_or_create_case(
    store: CaseStore,
    *,
    review_id: str,
    batch_id: str,
    dataset_id: str,
    version: str,
    dataset_type: str,
    name_zh: str,
    name_en: str,
):
    try:
        return store.get_case(review_id, batch_id=batch_id)
    except CaseStoreError:
        try:
            return store.get_case(review_id)
        except CaseStoreError:
            return store.create_case(
                review_id=review_id,
                batch_id=batch_id,
                dataset_id=dataset_id,
                version=version,
                dataset_type=dataset_type,
                name_zh=name_zh,
                name_en=name_en,
            )


def _default_batch_id(account_role: str) -> str:
    return f"{date.today().strftime('%Y%m%d')}-{account_role}"


def _dataset_payload(row: dict[str, Any]) -> dict[str, Any]:
    for key in ("json_ordered", "json_tg", "json"):
        value = row.get(key)
        if isinstance(value, dict):
            return value
    return row


def _dataset_name(payload: dict[str, Any]) -> dict[str, str]:
    if isinstance(payload.get("processDataSet"), dict):
        name = (
            payload["processDataSet"]
            .get("processInformation", {})
            .get("dataSetInformation", {})
            .get("name", {})
        )
    elif isinstance(payload.get("lifeCycleModelDataSet"), dict):
        name = (
            payload["lifeCycleModelDataSet"]
            .get("lifeCycleModelInformation", {})
            .get("dataSetInformation", {})
            .get("name", {})
        )
    else:
        return {"zh": "", "en": ""}
    return {
        "zh": _localized_text(name.get("baseName"), "zh"),
        "en": _localized_text(name.get("baseName"), "en"),
    }


def _localized_text(value: Any, language: str) -> str:
    if isinstance(value, list):
        for item in value:
            text = _localized_text(item, language)
            if text:
                return text
        return ""
    if isinstance(value, dict):
        if value.get("@xml:lang") == language:
            return str(value.get("#text") or "")
        return str(value.get(language) or "")
    return ""


def _materialize_model_linked_processes(
    payload: dict[str, Any],
    *,
    dataset_api: Any,
    case_root: Path,
    root: Path,
    guardrails: dict[str, Any] | None = None,
) -> dict[str, Any]:
    refs = _resolve_model_process_refs(payload)
    snapshots = case_root / "snapshots"
    linked_dir = snapshots / "linked-processes"
    linked_precheck_dir = case_root / "precheck" / "linked-processes"
    _write_json(snapshots / "model-linked-process-refs.json", refs)
    linked_dir.mkdir(parents=True, exist_ok=True)
    linked_precheck_dir.mkdir(parents=True, exist_ok=True)

    fetched = []
    errors = []
    for ref in refs:
        process_id = ref.get("process_id") or ""
        version = ref.get("version") or ""
        if not process_id or not version:
            errors.append({"ref": ref, "error": "missing process_id or version"})
            continue
        try:
            row = dataset_api.get_process(process_id, version)
        except Exception as error:  # noqa: BLE001 - keep per-process lookup failures as evidence.
            errors.append({"ref": ref, "error": str(error)})
            continue
        target = linked_dir / f"{_safe_filename(process_id)}_{_safe_filename(version)}.json"
        _write_json(target, row)
        process_payload = _dataset_payload(row)
        flow_evidence_dir = linked_dir / (
            f"{_safe_filename(process_id)}_{_safe_filename(version)}.evidence"
        )
        enriched_process, flow_evidence_summary = _materialize_process_flows(
            process_payload,
            dataset_api=dataset_api,
            snapshots=flow_evidence_dir,
            root=root,
        )
        _write_json(flow_evidence_dir / "dataset.enriched.json", enriched_process)
        fetched.append(
            {
                "process_id": process_id,
                "version": version,
                "path": _case_path_label(target, root),
                "flow_evidence_summary": flow_evidence_summary,
            }
        )
        try:
            normalized = normalize_dataset(enriched_process)
            if normalized.get("dataset_type") == "process":
                precheck = run_deterministic_checks(normalized, guardrails=guardrails)
                precheck["linked_process_ref"] = ref
                precheck_path = linked_precheck_dir / (
                    f"{_safe_filename(process_id)}_{_safe_filename(version)}.precheck.json"
                )
                _write_json(precheck_path, precheck)
        except ValueError as error:
            errors.append({"ref": ref, "error": f"linked process precheck skipped: {error}"})

    if errors:
        _write_json(snapshots / "model-linked-process-errors.json", errors)
    return {
        "linked_process_ref_count": len(refs),
        "linked_process_fetched_count": len(fetched),
        "linked_process_error_count": len(errors),
    }


def _resolve_model_process_refs(payload: Any) -> list[dict[str, str]]:
    refs: list[dict[str, str]] = []
    _walk_model_process_refs(payload, "$", refs)
    deduped: dict[tuple[str, str], dict[str, str]] = {}
    for ref in refs:
        key = (ref.get("process_id", ""), ref.get("version", ""))
        if key[0]:
            deduped.setdefault(key, ref)
    return list(deduped.values())


def _walk_model_process_refs(value: Any, location: str, refs: list[dict[str, str]]) -> None:
    if isinstance(value, dict):
        ref = _dict_to_model_process_ref(value, location)
        if ref:
            refs.append(ref)
        for key, child in value.items():
            _walk_model_process_refs(child, f"{location}.{key}", refs)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _walk_model_process_refs(child, f"{location}[{index}]", refs)


def _dict_to_model_process_ref(value: dict[str, Any], location: str) -> dict[str, str] | None:
    ref_type = str(value.get("@type") or value.get("type") or "").lower()
    uri = str(value.get("@uri") or value.get("uri") or "")
    looks_like_process = (
        "process data set" in ref_type
        or "../processes/" in uri
        or "/processes/" in uri
        or "datasetdetail/process.xhtml" in uri
    )
    if not looks_like_process:
        return None
    process_id = str(
        value.get("@refObjectId")
        or value.get("refObjectId")
        or value.get("uuid")
        or value.get("@uuid")
        or _query_value(uri, "uuid")
        or _process_id_from_uri(uri)
        or ""
    )
    if not process_id:
        return None
    return {
        "process_id": process_id,
        "version": str(value.get("@version") or value.get("version") or _query_value(uri, "version") or ""),
        "uri": uri,
        "label": _localized_text(
            value.get("common:shortDescription")
            or value.get("shortDescription")
            or value.get("name"),
            "zh",
        )
        or _localized_text(
            value.get("common:shortDescription")
            or value.get("shortDescription")
            or value.get("name"),
            "en",
        ),
        "location": location,
    }


def _query_value(uri: str, key: str) -> str:
    match = re.search(rf"[?&]{re.escape(key)}=([^&#]+)", uri)
    return match.group(1) if match else ""


def _process_id_from_uri(uri: str) -> str:
    match = re.search(r"/processes/([^/?#]+?)(?:\.xml)?(?:[?#]|$)", uri)
    return match.group(1) if match else ""


def _safe_filename(value: str) -> str:
    return "".join(char if char.isalnum() or char in "._-" else "_" for char in str(value))[:120]


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _case_path_label(path: Path, root: Path) -> str:
    try:
        return str(Path(path).relative_to(root / "cases"))
    except ValueError:
        return str(path)
