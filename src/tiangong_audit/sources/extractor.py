from __future__ import annotations

import json
from pathlib import Path

from tiangong_audit.contracts import SourceArtifact


def extract_source_text(artifact: SourceArtifact, output_dir: Path) -> SourceArtifact:
    """Extract text from a downloaded source artifact into extracted.md."""

    if artifact.status != "downloaded" or not artifact.file_path:
        artifact.status = "extraction_skipped"
        artifact.error = artifact.error or "Source artifact was not downloaded"
        return artifact

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    source_path = Path(artifact.file_path)
    target = output_dir / "extracted.md"
    try:
        if source_path.suffix.lower() == ".pdf" or artifact.content_type == "application/pdf":
            text = _extract_pdf_text(source_path)
        elif source_path.suffix.lower() == ".json":
            text = "```json\n" + json.dumps(
                json.loads(source_path.read_text(encoding="utf-8")),
                ensure_ascii=False,
                indent=2,
            ) + "\n```\n"
        else:
            text = source_path.read_text(encoding="utf-8", errors="replace")
    except Exception as error:  # noqa: BLE001 - extraction failures are evidence state.
        artifact.status = "extraction_failed"
        artifact.error = str(error)
        return artifact

    target.write_text(text.rstrip() + "\n", encoding="utf-8")
    artifact.status = "extracted"
    artifact.extracted_text_path = str(target)
    artifact.error = ""
    return artifact


def _extract_pdf_text(path: Path) -> str:
    try:
        from pypdf import PdfReader
    except ImportError as error:
        raise RuntimeError("pypdf is required to extract PDF text") from error

    reader = PdfReader(str(path))
    pages = []
    for index, page in enumerate(reader.pages, 1):
        pages.append(f"# Page {index}\n\n{page.extract_text() or ''}".rstrip())
    return "\n\n".join(pages)
