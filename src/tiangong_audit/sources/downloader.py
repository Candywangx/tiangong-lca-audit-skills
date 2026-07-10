from __future__ import annotations

import hashlib
import shutil
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

import requests

from tiangong_audit.contracts import SourceArtifact, SourceRef
from tiangong_audit.contracts.operation import utc_now_iso


def download_source_artifact(
    ref: SourceRef,
    output_dir: Path,
    *,
    session: requests.Session | None = None,
    timeout: float = 30,
) -> SourceArtifact:
    """Download or copy one source reference into a case-local source folder."""

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    locator = ref.locator()
    if not locator:
        return SourceArtifact(ref=ref, status="source_unavailable", error="Source has no locator")

    parsed = urlparse(locator)
    try:
        if parsed.scheme in {"http", "https"}:
            return _download_http(ref, output_dir, session=session, timeout=timeout)
        return _copy_local(ref, output_dir)
    except OSError as error:
        return SourceArtifact(ref=ref, status="download_failed", error=str(error))
    except requests.RequestException as error:
        return SourceArtifact(ref=ref, status="download_failed", error=str(error))


def download_platform_external_doc(
    ref: SourceRef,
    output_dir: Path,
    *,
    client: Any,
) -> SourceArtifact:
    """Download a Tiangong external_docs reference through an authenticated client."""

    object_name = _external_doc_name(ref.uri or ref.locator())
    if not object_name:
        return SourceArtifact(ref=ref, status="source_unavailable", error="Not an external_docs URI")
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    target = output_dir / (_safe_name(ref) + Path(object_name).suffix)
    try:
        result = client.download_external_doc(object_name, target)
    except Exception as error:  # noqa: BLE001 - preserve platform error in source state.
        return SourceArtifact(ref=ref, status="download_failed", error=str(error))
    return SourceArtifact(
        ref=ref,
        status="downloaded",
        file_path=str(target),
        content_type=str(result.get("content_type") or _content_type_from_suffix(target.suffix)),
        sha256=_sha256_file(target),
        downloaded_at=utc_now_iso(),
    )


def _download_http(
    ref: SourceRef,
    output_dir: Path,
    *,
    session: requests.Session | None,
    timeout: float,
) -> SourceArtifact:
    client = session or requests.Session()
    response = client.get(ref.locator(), timeout=timeout)
    response.raise_for_status()
    content_type = response.headers.get("content-type", "").split(";", 1)[0]
    suffix = _suffix_from_locator(ref.locator(), content_type)
    target = output_dir / (_safe_name(ref) + suffix)
    target.write_bytes(response.content)
    return SourceArtifact(
        ref=ref,
        status="downloaded",
        file_path=str(target),
        content_type=content_type,
        sha256=_sha256_file(target),
        downloaded_at=utc_now_iso(),
    )


def _copy_local(ref: SourceRef, output_dir: Path) -> SourceArtifact:
    locator = ref.locator()
    parsed = urlparse(locator)
    source = Path(unquote(parsed.path)) if parsed.scheme == "file" else Path(locator)
    if not source.exists():
        return SourceArtifact(
            ref=ref,
            status="source_unavailable",
            error=f"Local source not found: {source}",
        )
    target = output_dir / (_safe_name(ref) + source.suffix)
    shutil.copyfile(source, target)
    return SourceArtifact(
        ref=ref,
        status="downloaded",
        file_path=str(target),
        content_type=_content_type_from_suffix(source.suffix),
        sha256=_sha256_file(target),
        downloaded_at=utc_now_iso(),
    )


def _safe_name(ref: SourceRef) -> str:
    raw = ref.source_id or Path(urlparse(ref.locator()).path).stem or "source"
    return "".join(char if char.isalnum() or char in "._-" else "_" for char in raw)[:120]


def _suffix_from_locator(locator: str, content_type: str) -> str:
    suffix = Path(urlparse(locator).path).suffix
    if suffix:
        return suffix
    if content_type == "application/pdf":
        return ".pdf"
    if content_type.startswith("text/"):
        return ".txt"
    return ".bin"


def _content_type_from_suffix(suffix: str) -> str:
    return {
        ".pdf": "application/pdf",
        ".txt": "text/plain",
        ".md": "text/markdown",
        ".json": "application/json",
    }.get(suffix.lower(), "application/octet-stream")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _external_doc_name(uri: str) -> str:
    text = str(uri or "").strip()
    marker = "external_docs/"
    if marker in text:
        return text.split(marker, 1)[1].lstrip("/")
    if text.startswith("../external_docs/"):
        return text.removeprefix("../external_docs/").lstrip("/")
    return ""
