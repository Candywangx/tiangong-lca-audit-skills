"""Validate evidence-backed Agent proposals; never infer suitability or authorize writes."""
from __future__ import annotations

import hashlib
import json
import re
from typing import Any


def context_digest(context: dict) -> str:
    return hashlib.sha256(json.dumps(context, ensure_ascii=False, sort_keys=True,
                                    separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def _text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _index(rows: Any, key: str, errors: list[str], label: str) -> dict:
    result = {}
    if not isinstance(rows, list):
        errors.append(f'{label}: expected a list')
        return result
    for i, row in enumerate(rows):
        if not isinstance(row, dict) or not _text(row.get(key)):
            errors.append(f'{label}[{i}]: missing {key}')
        elif row[key] in result:
            errors.append(f'{label}[{i}]: duplicate {key}')
        else:
            result[row[key]] = row
    return result


def _quotes(items: Any, source: dict, key: str, errors: list[str], label: str) -> None:
    if not isinstance(items, list) or not items:
        errors.append(f'{label}: evidence required')
        return
    for item in items:
        if not isinstance(item, dict):
            errors.append(f'{label}: malformed evidence')
            continue
        locator, quote = item.get(key), item.get('quote')
        original = source.get(locator) if isinstance(locator, str) else None
        if not _text(quote) or not isinstance(original, str) or quote not in original:
            errors.append(f'{label}: quote is not supported by the cited input')


def validate_recommendations(context: Any, result: Any) -> dict:
    """Check frozen inputs, eligibility, completeness and literal evidence locations.

    These checks do not establish semantic suitability. An independent reviewer
    must assess whether cited content actually supports the proposed expertise.
    This module has no platform client or assignment operation.
    """
    errors: list[str] = []
    if not isinstance(context, dict):
        context = {}; errors.append('context: expected an object')
    if not isinstance(result, dict):
        result = {}; errors.append('result: expected an object')
    if context.get('schema_version') != 'tiangong-expert-context-v1':
        errors.append('context: unsupported schema_version')
    if not isinstance(context.get('binding_sha256'), str) or not re.fullmatch('[0-9a-f]{64}', context['binding_sha256']):
        errors.append('context: binding snapshot SHA-256 is required')
    if result.get('schema_version') != 'tiangong-expert-recommendation-v1':
        errors.append('result: unsupported schema_version')
    if result.get('input_sha256') != context_digest(context):
        errors.append('input_sha256: context changed or was not bound')
    experts = _index(context.get('experts'), 'expert_id', errors, 'experts')
    datasets = _index(context.get('datasets'), 'case_id', errors, 'datasets')
    proposals = _index(result.get('cases'), 'case_id', errors, 'cases')
    if set(proposals) != set(datasets):
        errors.append('cases: must cover every dataset exactly once')
    for expert in experts.values():
        if type(expert.get('eligible')) is not bool:
            errors.append('experts: eligibility must be a boolean')
    for case_id, proposal in proposals.items():
        label = f'case {case_id}'
        selected, gaps, status = proposal.get('selected'), proposal.get('gaps'), proposal.get('status')
        if not isinstance(selected, list):
            errors.append(f'{label}: selected must be a list'); continue
        if len(selected) > 3:
            errors.append(f'{label}: at most three experts may be proposed')
        if not isinstance(gaps, list) or any(not _text(gap) for gap in gaps):
            errors.append(f'{label}: gaps must be a list of nonempty strings')
        if status not in {'proposed', 'insufficient_candidates', 'needs_context'}:
            errors.append(f'{label}: unsupported proposal status')
        if status == 'proposed' and len(selected) != 3:
            errors.append(f'{label}: proposed requires three experts')
        if status in {'insufficient_candidates', 'needs_context'} and not gaps:
            errors.append(f'{label}: a limited proposal requires an explanation')
        if status == 'insufficient_candidates' and len(selected) >= 3:
            errors.append(f'{label}: insufficient_candidates requires fewer than three experts')
        evidence_rows = datasets.get(case_id, {}).get('evidence', [])
        evidence_index = _index(evidence_rows, 'ref', errors, f'{label} input evidence')
        dataset_sources = {ref: row.get('text') for ref, row in evidence_index.items()}
        seen: set[str] = set()
        for n, candidate in enumerate(selected):
            where = f'{label} selected[{n}]'
            if not isinstance(candidate, dict):
                errors.append(f'{where}: expected an object'); continue
            expert_id = candidate.get('expert_id')
            if not isinstance(expert_id, str) or expert_id not in experts:
                errors.append(f'{where}: unknown expert'); continue
            if expert_id in seen:
                errors.append(f'{where}: duplicate expert')
            seen.add(expert_id)
            expert = experts[expert_id]
            if expert.get('eligible') is not True:
                errors.append(f'{where}: expert is not eligible')
            if not _text(candidate.get('reason')):
                errors.append(f'{where}: a suitability reason is required')
            _quotes(candidate.get('expert_evidence'),
                    {k: expert.get(k) for k in ('fields_text', 'experience_text')},
                    'field', errors, f'{where} expert evidence')
            _quotes(candidate.get('dataset_evidence'), dataset_sources,
                    'ref', errors, f'{where} dataset evidence')
    return {'valid': not errors, 'errors': errors,
            'assignment_authorized': False, 'semantic_accuracy_verified': False,
            'live_identity_rechecked': False,
            'case_count': len(proposals)}
