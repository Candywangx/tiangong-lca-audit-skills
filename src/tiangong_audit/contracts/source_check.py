"""Admission of source judgments; locating evidence never proves its meaning."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from .evidence_ref import EvidenceReferenceError, resolve_evidence_ref

SOURCE_CHECK_STATUSES = frozenset({'matched', 'conflict', 'not_applicable', 'ambiguous', 'not_found'})


def source_check_errors(check: Any, *, case_root: Path, claims: dict[str, Any], documents: list[dict[str, Any]]) -> list[str]:
    if not isinstance(check, dict):
        return ['check must be an object']
    errors = []
    status = check.get('status')
    if not isinstance(status, str) or status not in SOURCE_CHECK_STATUSES:
        errors.append('unknown source check status')
    claim = check.get('field')
    if not isinstance(claim, str) or claim not in claims:
        errors.append('field must identify a claim in claims.json')
    elif 'dataset_value' in check and check['dataset_value'] != claims[claim]:
        errors.append('dataset_value does not match the claimed field value')
    if not isinstance(status, str) or status not in {'matched', 'conflict', 'not_applicable'}:
        return errors
    ids = [check.get(key) for key in ('checked_source_id', 'source_ref_id') if check.get(key)]
    if not ids or not all(isinstance(value, str) for value in ids) or len(set(ids)) != 1:
        errors.append('checked_source_id/source_ref_id must identify the same known source')
        return errors
    source_documents = [doc for doc in documents if doc.get('source_ref_id') == ids[0]]
    if not source_documents:
        errors.append('source has no readable case document')
        return errors
    if not any(isinstance(check.get(key), str) and check[key].strip() for key in ('evidence', 'matched_excerpt')):
        errors.append(f'{status} requires evidence or matched_excerpt')
    if status == 'not_applicable' and not any(isinstance(check.get(key), str) and check[key].strip() for key in ('notes', 'confidence_reason')):
        errors.append('not_applicable requires an applicability reason')
    refs = check.get('evidence_refs', [])
    if not isinstance(refs, list) or not all(isinstance(ref, str) and ref.strip() for ref in refs):
        errors.append('evidence_refs must be a list of nonempty references')
        return errors
    page = check.get('page')
    if page is not None and (type(page) is not int or page < 1):
        errors.append('page must be a positive integer')
        return errors
    # Legacy checks refer to the identified source's extracted text. Explicit
    # refs also support parser JSON/table/block evidence in that source directory.
    locators = list(refs)
    if page is not None or not locators:
        path = source_documents[0]['path']
        locators.append(f'{path}:p{page}' if page is not None else path)
    source_dirs = [(case_root / doc['path']).resolve().parent for doc in source_documents]
    for ref in locators:
        try:
            resolved = resolve_evidence_ref(ref, case_root=case_root)
            if not any(resolved.path.is_relative_to(directory) for directory in source_dirs):
                errors.append(f'evidence_ref {ref!r} does not belong to the checked source')
        except EvidenceReferenceError as error:
            errors.append(f'invalid evidence_ref {ref!r}: {error}')
    return errors
