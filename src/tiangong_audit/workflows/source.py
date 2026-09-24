from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
from tempfile import TemporaryDirectory, mkdtemp
from typing import Any
from uuid import uuid4

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
EXTRACTION_BUNDLE_FILES = (
    "result.json", "extracted.md", "fulltext.txt", "request.json", "openapi.json",
)


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


def _safe_attachment_name(value: str, label: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", value):
        raise ValueError(f"Unsafe {label}: {value!r}")
    return value


def _no_symlinks(path: Path) -> Path:
    """Reject symlinks in any component, including dangling destination links."""
    path = path.absolute()
    if ".." in path.parts or any(part.is_symlink() for part in (path, *path.parents)):
        raise ValueError(f"Unsafe attachment path: {path}")
    return path


def _read_attachment_file(path: Path) -> bytes:
    path = _no_symlinks(path)
    if not path.is_file():
        raise ValueError(f"Attachment file not found or not a regular file: {path}")
    return path.read_bytes()


def _validated_extraction_bundle(
    directory: Path, text: bytes, source_sha256: str,
) -> dict[str, bytes]:
    """Validate the portable evidence contract without depending on Skill code.

    Rendering belongs to the standalone parser. Here we verify supplied Markdown
    identity and record its hash, rather than reimplementing that renderer.
    """
    directory = _no_symlinks(directory)
    files = {name: _read_attachment_file(directory / name) for name in EXTRACTION_BUNDLE_FILES}
    result = json.loads(files["result.json"])
    if not isinstance(result, dict) or not isinstance(result.get("result"), list):
        raise ValueError("result.json must contain a business object with a result list")
    blocks = result["result"]
    for block in blocks:
        if (
            not isinstance(block, dict)
            or not isinstance(block.get("text"), str)
            or type(block.get("page_number")) is not int
            or block["page_number"] <= 0
            or (block.get("type") is not None and not isinstance(block["type"], str))
        ):
            raise ValueError("Invalid result block: expected text, positive integer page_number, optional type")
    if not any(block["text"].strip() for block in blocks):
        raise ValueError("result.json must contain a nonempty text block")
    raw_text = result.get("txt")
    if raw_text is not None and not isinstance(raw_text, str):
        raise ValueError("result.json txt must be a string or null")
    # When service txt is absent/empty, the parser may derive a fallback from
    # blocks. Hash that artifact without duplicating the parser's rendering code.
    if raw_text and raw_text.strip() and files["fulltext.txt"] != raw_text.encode("utf-8"):
        raise ValueError("fulltext.txt does not match result.json txt")
    if text != files["extracted.md"]:
        raise ValueError("Supplied extracted text does not match bundle extracted.md")

    request = json.loads(files["request.json"])
    if not isinstance(request, dict) or request.get("state") != "SUCCESS":
        raise ValueError("request.json must record state SUCCESS")
    identity = request.get("identity")
    if (
        not isinstance(identity, dict)
        or not isinstance(identity.get("endpoint"), str)
        or not identity["endpoint"].strip()
        or not isinstance(identity.get("sha256"), str)
        or not re.fullmatch(r"[0-9a-fA-F]{64}", identity["sha256"])
        or not isinstance(identity.get("fields"), dict)
        or not isinstance(identity.get("query"), dict)
    ):
        raise ValueError("request.json must contain a valid request identity")
    if source_sha256 and identity["sha256"].lower() != source_sha256.lower():
        raise ValueError("Bundle input SHA256 does not match the source artifact")
    for name, key in (("result.json", "result_sha256"), ("openapi.json", "schema_sha256")):
        if request.get(key) != hashlib.sha256(files[name]).hexdigest():
            raise ValueError(f"{name} SHA256 does not match request.json {key}")
    schema = json.loads(files["openapi.json"])
    if not isinstance(schema, dict) or not isinstance(schema.get("openapi"), str) or not isinstance(schema.get("paths"), dict):
        raise ValueError("openapi.json must contain an OpenAPI schema")
    return files


def attach_extraction(
    review_id: str,
    *,
    root: Path,
    source_dir_name: str,
    extracted_text: Path,
    extraction_dir: Path | None = None,
    method: str = "document-granular-decompose",
    case_store: CaseStore | None = None,
    batch_id: str | None = None,
) -> dict[str, Any]:
    """Backfill a high-fidelity extraction (e.g. image-aware fulltext) into a case source.

    This closes the loop the Agent opens when it runs
    ``skill/document-granular-decompose`` manually: the result becomes the
    canonical ``extracted.md``, the source manifest is updated, and the
    supplementary-material scan is re-run on the richer text. An optional parser
    bundle is validated before any writes and retained locally with file hashes.
    """

    store = case_store or CaseStore(root / "cases")
    manifest = store.get_case(review_id, batch_id=batch_id)
    _safe_attachment_name(source_dir_name, "source directory")
    _safe_attachment_name(method, "extraction method")
    source_dir = _no_symlinks(root / "cases" / manifest.case_dir / "sources" / source_dir_name)
    if not source_dir.is_relative_to((root / "cases").absolute()):
        raise ValueError("Source directory escapes the cases directory")
    manifest_path = source_dir / "manifest.json"
    extracted_text = Path(extracted_text)
    original_manifest = _read_attachment_file(manifest_path)
    payload = json.loads(original_manifest)
    artifact = SourceArtifact.from_dict(payload)
    text = _read_attachment_file(extracted_text)
    text.decode("utf-8")  # Fail before backups or writes for invalid text encoding.
    bundle = (
        _validated_extraction_bundle(Path(extraction_dir), text, artifact.sha256)
        if extraction_dir is not None else None
    )

    target = _no_symlinks(source_dir / "extracted.md")
    parsing = _no_symlinks(source_dir / "parsing")
    history_root = _no_symlinks(source_dir / "parsing-history")
    if history_root.exists() and not history_root.is_dir():
        raise ValueError("Parsing history path must be a directory")
    if parsing.exists():
        if not parsing.is_dir():
            raise ValueError("Parsing path must be a directory")
        for path in parsing.rglob("*"):
            _no_symlinks(path)
    backup = None
    if target.exists():
        previous_method = _safe_attachment_name(str(payload.get("extraction_method") or "basic"), "previous extraction method")
        if target.resolve() != extracted_text.resolve():
            backup = source_dir / f"extracted.{previous_method}.md"
            while backup.exists() or backup.is_symlink():
                backup = source_dir / f"extracted.{previous_method}.{uuid4().hex}.md"
        previous_text = _read_attachment_file(target)

    # All external evidence and destination paths are checked before changing the
    # previous text or provenance. Stage exact bytes; never retain external paths.
    with TemporaryDirectory(prefix=".parsing-", dir=source_dir) as temporary:
        staged = Path(temporary) / "bundle"
        if bundle is not None:
            staged.mkdir()
            for name, data in bundle.items():
                (staged / name).write_bytes(data)
        if parsing.exists():
            history_root.mkdir(exist_ok=True)
            history_dir = Path(mkdtemp(prefix="extraction-", dir=history_root))
            archived = history_dir / "bundle"
            parsing.rename(archived)
            (history_dir / "source-manifest.json").write_bytes(original_manifest)
            history_entry = {
                "directory": str(archived.relative_to(source_dir)),
                "manifest_path": str((history_dir / "source-manifest.json").relative_to(source_dir)),
                "extraction_method": payload.get("extraction_method", ""),
            }
            payload.setdefault("extraction_history", []).append(history_entry)
            manifest.artifacts[f"source_parsing_history:{source_dir_name}:{history_dir.name}"] = _case_path_label(history_dir, root)
        payload.pop("extraction_bundle", None)
        for name in EXTRACTION_BUNDLE_FILES:
            manifest.artifacts.pop(f"source_parsing:{source_dir_name}:{name}", None)
        if bundle is not None:
            staged.rename(parsing)
            payload["extraction_bundle"] = {"files": {
                name: {"path": f"parsing/{name}", "sha256": hashlib.sha256(data).hexdigest()}
                for name, data in bundle.items()
            }}
            for name in bundle:
                manifest.artifacts[f"source_parsing:{source_dir_name}:{name}"] = _case_path_label(parsing / name, root)
        if backup is not None:
            with backup.open("xb") as output:
                output.write(previous_text)
        target.write_bytes(text)

    artifact.extracted_text_path = str(target)
    artifact.status = "extracted"
    artifact.error = ""
    changes = _artifact_manifest_payload(artifact, source_dir)
    updated_payload = payload
    # Preserve extension fields, including extensions nested in the source ref.
    for key in ("extracted_text_path", "status", "error", "related_artifact_requirements"):
        updated_payload[key] = changes[key]
    updated_payload.setdefault("schema_version", changes["schema_version"])
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
        "bytes": len(text),
        **({"extraction_bundle": updated_payload["extraction_bundle"]} if bundle is not None else {}),
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
