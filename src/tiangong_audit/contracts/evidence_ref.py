"""Resolve evidence locations without claiming semantic support for a verdict."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re


class EvidenceReferenceError(ValueError):
    """A reference cannot be verified inside the current case."""


@dataclass(frozen=True, slots=True)
class EvidenceReference:
    path: Path
    pointer: str | None = None
    page: int | None = None
    block: int | None = None


def _pointer_exists(value: object, pointer: str) -> None:
    if pointer == "":
        return
    if not pointer.startswith("/"):
        raise EvidenceReferenceError("JSON pointer must begin with /")
    for token in pointer[1:].split("/"):
        if re.search(r"~(?![01])", token):
            raise EvidenceReferenceError("invalid JSON pointer escape")
        token = token.replace("~1", "/").replace("~0", "~")
        if isinstance(value, dict) and token in value:
            value = value[token]
        elif isinstance(value, list) and re.fullmatch(r"0|[1-9][0-9]*", token) and int(token) < len(value):
            value = value[int(token)]
        else:
            raise EvidenceReferenceError("JSON pointer does not exist")


def _page_blocks(path: Path) -> tuple[set[int], dict[int, int | None]]:
    if path.suffix.lower() == ".pdf":
        from pypdf import PdfReader

        try:
            return set(range(1, len(PdfReader(path).pages) + 1)), {}
        except Exception as error:
            raise EvidenceReferenceError("PDF page count cannot be verified") from error
    text = path.read_text(encoding="utf-8")
    pages: set[int] = set()
    blocks: dict[int, int | None] = {}
    if path.suffix.lower() == ".json":
        payload = json.loads(text)
        entries = payload.get("result") if isinstance(payload, dict) else None
        if isinstance(entries, list):
            for index, entry in enumerate(entries, 1):
                page = entry.get("page_number") if isinstance(entry, dict) else None
                if type(page) is int and page > 0:
                    pages.add(page)
                    blocks[index] = page
        return pages, blocks
    page = None
    for line in text.splitlines():
        page_match = re.fullmatch(r"#{1,6}\s+Page\s+([1-9][0-9]*)\s*", line)
        block_match = re.fullmatch(r"#{1,6}\s+Block\s+([1-9][0-9]*)(?:\s+\([^\n]*\))?\s*", line)
        if page_match:
            page = int(page_match[1])
            pages.add(page)
        elif block_match:
            index = int(block_match[1])
            if index in blocks:
                raise EvidenceReferenceError("block locator is ambiguous")
            blocks[index] = page
    return pages, blocks


def resolve_evidence_ref(ref: str, *, case_root: Path) -> EvidenceReference:
    """Accept relative files, ``file#/pointer``, ``file:p3[:b2]`` or ``file:b2``.

    JSON values may be false/null/empty; presence, not truthiness, is checked.
    Page numbers require actual page markers, parser metadata or a readable PDF.
    """
    if not isinstance(ref, str) or not ref.strip():
        raise EvidenceReferenceError("evidence reference must be a nonempty string")
    if any(ord(char) < 32 for char in ref):
        raise EvidenceReferenceError("evidence reference contains control characters")
    ref = ref.strip()
    pointer = None
    page = block = None
    if "#" in ref:
        name, pointer = ref.split("#", 1)
    else:
        match = re.fullmatch(r"(.+?)(?::p([1-9][0-9]*))?(?::b([1-9][0-9]*))?", ref)
        if match is None:
            raise EvidenceReferenceError("unsupported evidence locator")
        name = match[1]
        page = int(match[2]) if match[2] else None
        block = int(match[3]) if match[3] else None
    relative = Path(name)
    if not name or relative.is_absolute() or ".." in relative.parts or ":" in name:
        raise EvidenceReferenceError("use a case-relative file and a supported locator")
    try:
        root = Path(case_root).resolve()
        path = (root / relative).resolve()
    except (OSError, RuntimeError) as error:
        raise EvidenceReferenceError("evidence path cannot be resolved") from error
    if not path.is_relative_to(root):
        raise EvidenceReferenceError("evidence reference escapes the current case")
    if not path.is_file():
        raise EvidenceReferenceError("evidence file does not exist or is not a regular file")
    try:
        with path.open("rb") as stream:
            stream.read(1)
        if pointer is not None:
            _pointer_exists(json.loads(path.read_text(encoding="utf-8")), pointer)
        if page is not None or block is not None:
            pages, blocks = _page_blocks(path)
            if page is not None and page not in pages:
                raise EvidenceReferenceError("page locator cannot be verified")
            if block is not None and block not in blocks:
                raise EvidenceReferenceError("block locator cannot be verified")
            if block is not None and page is not None and blocks[block] != page:
                raise EvidenceReferenceError("block does not belong to the referenced page")
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise EvidenceReferenceError(f"evidence location cannot be read: {type(error).__name__}") from error
    return EvidenceReference(path=path, pointer=pointer, page=page, block=block)
