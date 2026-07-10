"""Source reference resolution, download, extraction, and verification."""

from .claims import generate_source_claims
from .downloader import download_platform_external_doc, download_source_artifact
from .extractor import extract_source_text
from .resolver import resolve_source_refs, with_external_doc_base

__all__ = [
    "generate_source_claims",
    "download_source_artifact",
    "download_platform_external_doc",
    "extract_source_text",
    "resolve_source_refs",
    "with_external_doc_base",
]
