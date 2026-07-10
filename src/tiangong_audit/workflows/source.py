from __future__ import annotations

import json
from pathlib import Path
import re
from typing import Any

from tiangong_audit.case_store import CaseStore
from tiangong_audit.contracts import SourceArtifact, SourceRef
from tiangong_audit.integrations import tiangong_api
from tiangong_audit.sources import (
    download_platform_external_doc,
    download_source_artifact,
    extract_source_text,
    generate_source_claims,
    resolve_source_refs,
    with_external_doc_base,
)

RELATED_ARTIFACT_PATTERN = re.compile(
    r"\b(?:Supplementary|Supporting)\s+"
    r"(?:Table|Tables|Data|Information|Material|Materials|Figure|Figures|Fig\.?|Appendix)"
    r"\s*[A-Z]?\d*[A-Za-z]?\b"
    r"|\b(?:Table|Figure|Fig\.?)\s+S\d+[A-Za-z]?\b"
    r"|\bAppendix\s+[A-Z0-9][A-Za-z0-9.-]*\b"
    r"|附表\s*[A-Za-z]?\s*\d*(?:[-–]\d+)?"
    r"|附录\s*[A-Za-z0-9一二三四五六七八九十]*"
    r"|补充\s*(?:材料|资料|信息|数据|表格?|图)\s*[A-Za-z]?\s*\d*"
    r"|支持信息|支撑材料",
    re.IGNORECASE,
)
MAX_RELATED_ARTIFACT_REQUIREMENTS = 20


def resolve_sources(
    payload: Any,
    *,
    case_store: CaseStore | None = None,
    review_id: str | None = None,
    batch_id: str | None = None,
    external_doc_base_url: str | None = None,
) -> list[SourceRef]:
    refs = with_external_doc_base(resolve_source_refs(payload), external_doc_base_url)
    if case_store and review_id:
        manifest = case_store.get_case(review_id, batch_id=batch_id)
        manifest.set_step("sources_resolved", True)
        case_store.write_case(manifest)
    return refs


def fetch_sources(
    payload: Any,
    *,
    root: Path,
    case_store: CaseStore | None = None,
    review_id: str | None = None,
    batch_id: str | None = None,
    output_dir: Path | None = None,
    external_doc_base_url: str | None = None,
    account_role: str | None = None,
    platform_client: Any | None = None,
    claims: dict[str, Any] | None = None,
) -> dict[str, Any]:
    refs = with_external_doc_base(resolve_source_refs(payload), external_doc_base_url)
    manifest = case_store.get_case(review_id, batch_id=batch_id) if case_store and review_id else None
    target_dir = output_dir or (
        root / "cases" / manifest.case_dir / "sources" if manifest else None
    )
    if target_dir is None:
        raise ValueError("--output-dir is required unless --review-id is provided")
    target_dir.mkdir(parents=True, exist_ok=True)

    platform_client = platform_client or (
        tiangong_api.TiangongAPIClient(account_role=account_role)
        if account_role
        else None
    )
    dataset_api = tiangong_api.DatasetAPI(platform_client) if platform_client else None
    generated_claims = {str(key): value for key, value in (claims or {}).items()}
    if generated_claims:
        checks_dir = (
            root / "cases" / manifest.case_dir / "source-checks"
            if manifest
            else target_dir.parent / "source-checks"
        )
        checks_dir.mkdir(parents=True, exist_ok=True)
        (checks_dir / "claims.json").write_text(
            json.dumps(generated_claims, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    artifacts = []
    for index, ref in enumerate(refs, 1):
        source_dir = target_dir / f"source-{index:03d}"
        source_dir.mkdir(parents=True, exist_ok=True)
        source_dir_ref = _resolve_platform_source_dataset(
            ref,
            source_dir,
            dataset_api=dataset_api,
        )
        if platform_client and _external_doc_name(source_dir_ref.uri or source_dir_ref.locator()) and not source_dir_ref.url:
            artifact = download_platform_external_doc(source_dir_ref, source_dir, client=platform_client)
        else:
            artifact = download_source_artifact(source_dir_ref, source_dir)
        artifact = extract_source_text(artifact, source_dir)
        manifest_payload = _artifact_manifest_payload(artifact, source_dir)
        (source_dir / "manifest.json").write_text(
            json.dumps(manifest_payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        artifacts.append(manifest_payload)

    if case_store and manifest:
        manifest.set_step("sources_resolved", True)
        manifest.set_step(
            "sources_downloaded",
            bool(artifacts)
            and all(
                artifact.get("status") in {"downloaded", "extracted", "extraction_failed"}
                for artifact in artifacts
            ),
        )
        manifest.artifacts["sources"] = _case_path_label(target_dir, root)
        if generated_claims:
            manifest.artifacts["source_claims"] = _case_path_label(
                root / "cases" / manifest.case_dir / "source-checks" / "claims.json",
                root,
            )
        case_store.write_case(manifest)

    return {
        "source_count": len(refs),
        "claim_count": len(generated_claims),
        "check_count": 0,
        "artifacts": artifacts,
        "checks": [],
    }


def _case_path_label(path: Path, root: Path) -> str:
    try:
        return str(Path(path).relative_to(root / "cases"))
    except ValueError:
        return str(path)


def _artifact_manifest_payload(artifact: SourceArtifact, source_dir: Path) -> dict[str, Any]:
    artifact.related_artifact_requirements = _related_artifact_requirements(artifact)
    payload = artifact.to_dict()
    for key in ("file_path", "extracted_text_path"):
        value = str(payload.get(key) or "")
        if not value:
            continue
        path = Path(value)
        try:
            payload[key] = str(path.relative_to(source_dir))
        except ValueError:
            payload[key] = str(path)
    return payload


def _related_artifact_requirements(artifact: SourceArtifact) -> list[dict[str, str]]:
    extracted_path = Path(artifact.extracted_text_path) if artifact.extracted_text_path else None
    if not extracted_path or not extracted_path.exists():
        return []
    try:
        text = extracted_path.read_text(encoding="utf-8")
    except OSError:
        return []
    requirements = []
    seen = set()
    truncated = False
    for match in RELATED_ARTIFACT_PATTERN.finditer(text):
        reference = " ".join(match.group(0).strip(" .,:;()[]、，。").split())
        key = reference.lower()
        if not reference or key in seen:
            continue
        seen.add(key)
        if len(requirements) >= MAX_RELATED_ARTIFACT_REQUIREMENTS:
            truncated = True
            break
        requirements.append(
            {
                "kind": "supplementary_material",
                "reference": reference,
                "status": "requires_followup",
                "action": (
                    "Locate and download the referenced supplement, appendix, or source table "
                    "from the platform source dataset, publisher/DOI page, or cited URL before "
                    "judging claims that depend on it; if unavailable, record the affected claims "
                    "as ambiguous or source_unavailable."
                ),
            }
        )
    if truncated:
        requirements.append(
            {
                "kind": "scan_truncated",
                "reference": f"more than {MAX_RELATED_ARTIFACT_REQUIREMENTS} supplementary references",
                "status": "requires_followup",
                "action": (
                    "The supplementary-reference scan hit its cap; read the extracted text "
                    "directly and list any further supplements it cites."
                ),
            }
        )
    return requirements


def generate_claims_for_payload(payload: Any) -> dict[str, str]:
    return generate_source_claims(payload)


def attach_extraction(
    review_id: str,
    *,
    root: Path,
    source_dir_name: str,
    extracted_text: Path,
    method: str = "document-granular-decompose",
    case_store: CaseStore | None = None,
    batch_id: str | None = None,
) -> dict[str, Any]:
    """Backfill a high-fidelity extraction (e.g. image-aware fulltext) into a case source.

    This closes the loop the Agent opens when it runs
    ``skill/document-granular-decompose`` manually: the result becomes the
    canonical ``extracted.md``, the source manifest is updated, and the
    supplementary-material scan is re-run on the richer text.
    """

    store = case_store or CaseStore(root / "cases")
    manifest = store.get_case(review_id, batch_id=batch_id)
    source_dir = root / "cases" / manifest.case_dir / "sources" / source_dir_name
    manifest_path = source_dir / "manifest.json"
    if not manifest_path.exists():
        raise ValueError(f"Source manifest not found: {manifest_path}")
    extracted_text = Path(extracted_text)
    if not extracted_text.exists():
        raise ValueError(f"Extracted text file not found: {extracted_text}")

    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    artifact = SourceArtifact.from_dict(payload)

    target = source_dir / "extracted.md"
    if target.exists():
        previous_method = str(payload.get("extraction_method") or "basic")
        backup = source_dir / f"extracted.{previous_method}.md"
        if target.resolve() != extracted_text.resolve():
            backup.write_text(target.read_text(encoding="utf-8"), encoding="utf-8")
    text = extracted_text.read_text(encoding="utf-8")
    target.write_text(text, encoding="utf-8")

    artifact.extracted_text_path = str(target)
    artifact.status = "extracted"
    artifact.error = ""
    updated_payload = _artifact_manifest_payload(artifact, source_dir)
    updated_payload["extraction_method"] = method
    manifest_path.write_text(
        json.dumps(updated_payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    manifest.artifacts[f"source_extraction:{source_dir_name}"] = _case_path_label(
        target, root
    )
    store.write_case(manifest)
    return {
        "review_id": review_id,
        "source_dir": source_dir_name,
        "extracted_text_path": _case_path_label(target, root),
        "extraction_method": method,
        "bytes": len(text.encode("utf-8")),
        "related_artifact_requirements": updated_payload.get(
            "related_artifact_requirements", []
        ),
    }


def _resolve_platform_source_dataset(
    ref: SourceRef,
    source_dir: Path,
    *,
    dataset_api: Any | None,
) -> SourceRef:
    if dataset_api is None or not _is_platform_source_dataset_ref(ref):
        return ref
    try:
        row = dataset_api.get_source(ref.source_id, ref.version)
    except Exception as error:  # noqa: BLE001 - preserve platform errors as source evidence.
        return SourceRef(
            source_id=ref.source_id,
            version=ref.version,
            uri=ref.uri,
            url=ref.url,
            path=ref.path,
            label=ref.label,
            source_type=ref.source_type,
            location=f"{ref.location}; source dataset lookup failed: {error}",
        )

    (source_dir / "source-dataset-row.json").write_text(
        json.dumps(row, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    source_payload = (
        row.get("json_ordered")
        if isinstance(row, dict) and isinstance(row.get("json_ordered"), dict)
        else row.get("json")
        if isinstance(row, dict) and isinstance(row.get("json"), dict)
        else {}
    )
    if not source_payload:
        return ref
    (source_dir / "source-dataset.json").write_text(
        json.dumps(source_payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    digital_refs = resolve_source_refs(source_payload)
    for digital_ref in digital_refs:
        if _external_doc_name(digital_ref.uri or digital_ref.locator()) or digital_ref.url or digital_ref.path:
            return SourceRef(
                source_id=digital_ref.source_id or ref.source_id,
                version=digital_ref.version or ref.version,
                uri=digital_ref.uri,
                url=digital_ref.url,
                path=digital_ref.path,
                label=digital_ref.label or ref.label,
                source_type=digital_ref.source_type or "source data set digital file",
                location=digital_ref.location,
            )
    return ref


def _is_platform_source_dataset_ref(ref: SourceRef) -> bool:
    locator = ref.uri or ref.locator()
    return bool(ref.source_id) and (
        "../sources/" in locator
        or locator.startswith("sources/")
        or "source data set" in ref.source_type.lower()
    ) and not _external_doc_name(locator)


def _external_doc_name(uri: str) -> str:
    text = str(uri or "").strip()
    marker = "external_docs/"
    if marker in text:
        return text.split(marker, 1)[1].lstrip("/")
    if text.startswith("../external_docs/"):
        return text.removeprefix("../external_docs/").lstrip("/")
    if text.startswith("external_docs/"):
        return text.removeprefix("external_docs/").lstrip("/")
    return ""
