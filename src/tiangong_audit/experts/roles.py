"""Validate declared professional roles against literal source evidence.

Source text is data, never executable instructions. Validation establishes only
shape, complete coverage and quotation locations, not professional capability.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any


ROLES = frozenset({'domain', 'method', 'data_model'})
SUPPORT = frozenset({'supported', 'conditional', 'insufficient'})
SOURCE_FIELDS = frozenset({'fields_text', 'experience_text'})


def _text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def role_input_digest(experts: list[dict]) -> str:
    """Bind only original professional text and stable IDs, ignoring display data."""
    if not isinstance(experts, list):
        raise ValueError('experts: expected a list')
    projection = []
    seen = set()
    for expert in experts:
        if not isinstance(expert, dict) or not _text(expert.get('expert_id')):
            raise ValueError('experts: nonempty expert_id is required')
        expert_id = expert['expert_id']
        if expert_id in seen:
            raise ValueError('experts: duplicate expert_id')
        seen.add(expert_id)
        if any(not isinstance(expert.get(field), str) for field in SOURCE_FIELDS):
            raise ValueError('experts: professional source fields must be strings')
        projection.append({key: expert[key] for key in ('expert_id', 'fields_text', 'experience_text')})
    projection.sort(key=lambda expert: expert['expert_id'])
    canonical = json.dumps(projection, ensure_ascii=False, sort_keys=True,
                           separators=(',', ':'), allow_nan=False)
    return hashlib.sha256(canonical.encode()).hexdigest()


def _keys(value: dict, expected: set[str], errors: list[str], label: str) -> None:
    if set(value) != expected:
        errors.append(f'{label}: expected exactly {", ".join(sorted(expected))}')


def validate_role_profiles(experts: Any, payload: Any) -> dict:
    """Check complete role projections; never certify the meaning of evidence."""
    errors: list[str] = []
    try:
        digest = role_input_digest(experts)
    except ValueError as exc:
        return {'valid': False, 'errors': [str(exc)], 'semantic_accuracy_verified': False}
    sources = {expert['expert_id']: expert for expert in experts}
    if not isinstance(payload, dict):
        return {'valid': False, 'errors': ['role_profiles: expected an object'],
                'semantic_accuracy_verified': False}
    _keys(payload, {'schema_version', 'input_sha256', 'profiles'}, errors, 'role_profiles')
    if payload.get('schema_version') != 'tiangong-expert-roles-v1':
        errors.append('role_profiles: unsupported schema_version')
    if payload.get('input_sha256') != digest:
        errors.append('role_profiles input_sha256: professional input changed or was not bound')
    profiles = payload.get('profiles')
    if not isinstance(profiles, list):
        errors.append('role_profiles profiles: expected a list')
        profiles = []
    seen = set()
    for i, profile in enumerate(profiles):
        label = f'role_profiles profiles[{i}]'
        if not isinstance(profile, dict):
            errors.append(f'{label}: expected an object')
            continue
        _keys(profile, {'expert_id', 'roles'}, errors, label)
        expert_id = profile.get('expert_id')
        if not _text(expert_id) or expert_id not in sources:
            errors.append(f'{label}: unknown expert_id')
            source = {}
        else:
            source = sources[expert_id]
            if expert_id in seen:
                errors.append(f'{label}: duplicate expert_id')
            seen.add(expert_id)
        role_rows = profile.get('roles')
        if not isinstance(role_rows, list):
            errors.append(f'{label}: roles must be a list')
            role_rows = []
        seen_roles = set()
        for n, item in enumerate(role_rows):
            where = f'{label} roles[{n}]'
            if not isinstance(item, dict):
                errors.append(f'{where}: expected an object')
                continue
            _keys(item, {'role', 'support', 'scope', 'evidence', 'limits'}, errors, where)
            role, support = item.get('role'), item.get('support')
            if not isinstance(role, str) or role not in ROLES:
                errors.append(f'{where}: unsupported role')
            else:
                if role in seen_roles:
                    errors.append(f'{where}: duplicate role')
                seen_roles.add(role)
            if not isinstance(support, str) or support not in SUPPORT:
                errors.append(f'{where}: unsupported support')
            if not _text(item.get('scope')):
                errors.append(f'{where}: nonempty scope is required')
            limits = item.get('limits')
            if not isinstance(limits, list) or any(not _text(limit) for limit in limits):
                errors.append(f'{where}: limits must be a list of nonempty strings')
            if support in ('conditional', 'insufficient') and not limits:
                errors.append(f'{where}: conditional or insufficient support requires limits')
            evidence = item.get('evidence')
            if not isinstance(evidence, list):
                errors.append(f'{where}: evidence must be a list')
                evidence = []
            experience_quote = False
            for quote_item in evidence:
                if not isinstance(quote_item, dict):
                    errors.append(f'{where}: malformed evidence')
                    continue
                _keys(quote_item, {'field', 'quote'}, errors, f'{where} evidence')
                field, quote = quote_item.get('field'), quote_item.get('quote')
                original = source.get(field) if isinstance(field, str) else None
                if (not isinstance(field, str) or field not in SOURCE_FIELDS
                        or not _text(quote) or not isinstance(original, str) or quote not in original):
                    errors.append(f'{where}: quote is not supported by the cited input')
                elif field == 'experience_text':
                    experience_quote = True
            if support == 'supported' and not experience_quote:
                errors.append(f'{where}: supported requires experience_text evidence')
            if support == 'conditional' and not evidence:
                errors.append(f'{where}: conditional requires evidence')
        if seen_roles != ROLES or len(role_rows) != len(ROLES):
            errors.append(f'{label}: exactly one of each domain, method and data_model role is required')
    if seen != set(sources) or len(profiles) != len(sources):
        errors.append('role_profiles: must cover every expert exactly once')
    return {'valid': not errors, 'errors': errors, 'semantic_accuracy_verified': False}
