"""Validate evidence-backed Agent proposals; never infer suitability or authorize writes."""
from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from .roles import ROLES, validate_role_profiles


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


def _contains_roles(value: Any) -> bool:
    """Prevent role-bearing contracts from bypassing v2 through version labels."""
    if isinstance(value, dict):
        role_keys = {'role_profiles', 'roles', 'role', 'primary_role', 'responsibility',
                     'suitability', 'team_rationale', 'composition_exception'}
        return bool(role_keys.intersection(value)) or any(_contains_roles(child) for child in value.values())
    if isinstance(value, list):
        return any(_contains_roles(child) for child in value)
    return False


def _validate_role_teams(context: dict, datasets: dict, proposals: dict,
                         errors: list[str]) -> list[dict]:
    checked = validate_role_profiles(context.get('experts'), context.get('role_profiles'))
    errors.extend(checked['errors'])
    # An invalid profile is never used to endorse an assigned role.
    role_index = {}
    if checked['valid']:
        role_index = {profile['expert_id']: {item['role']: item for item in profile['roles']}
                      for profile in context['role_profiles']['profiles']}
    diagnostics = []
    for case_id, proposal in proposals.items():
        label = f'case {case_id}'
        dataset_type = datasets.get(case_id, {}).get('dataset_type')
        if dataset_type not in ('process', 'model'):
            errors.append(f'{label}: role teams require process or model dataset_type')
        required = ['domain', 'method', 'data_model'] if dataset_type == 'model' else ['domain', 'method']
        composition = dict.fromkeys(('domain', 'method', 'data_model'), 0)
        if not _text(proposal.get('team_rationale')):
            errors.append(f'{label}: team_rationale is required')
        if 'composition_exception' in proposal and not _text(proposal['composition_exception']):
            errors.append(f'{label}: composition_exception must be nonempty when supplied')
        selected = proposal.get('selected')
        if not isinstance(selected, list):
            selected = []
        for n, candidate in enumerate(selected):
            where = f'{label} selected[{n}]'
            if not isinstance(candidate, dict):
                continue
            role, suitability = candidate.get('primary_role'), candidate.get('suitability')
            valid_role = isinstance(role, str) and role in ROLES
            if not valid_role:
                errors.append(f'{where}: primary_role must be one of domain, method or data_model')
            else:
                composition[role] += 1
            if not _text(candidate.get('responsibility')):
                errors.append(f'{where}: responsibility is required')
            if suitability not in ('supported', 'conditional'):
                errors.append(f'{where}: suitability must be supported or conditional')
            expert_id = candidate.get('expert_id')
            profile = (role_index.get(expert_id, {}).get(role)
                       if isinstance(expert_id, str) and valid_role else None)
            if profile is None or profile['support'] == 'insufficient':
                errors.append(f'{where}: assigned role lacks a supported or conditional profile')
            elif profile['support'] == 'conditional' and suitability != 'conditional':
                errors.append(f'{where}: conditional role requires conditional suitability')
            if proposal.get('status') == 'proposed':
                if suitability != 'supported' or profile is None or profile['support'] != 'supported':
                    errors.append(f'{where}: proposed requires supported suitability and role profile')
        present = [role for role in composition if composition[role]]
        missing = [role for role in required if not composition[role]]
        if proposal.get('status') == 'proposed':
            if missing:
                errors.append(f'{label}: proposed team is missing required roles: {", ".join(missing)}')
            if dataset_type == 'model' and any(composition[role] != 1 for role in ROLES):
                errors.append(f'{label}: model proposed requires one domain, method and data_model expert')
            if (dataset_type == 'process' and composition != {'domain': 2, 'method': 1, 'data_model': 0}
                    and not _text(proposal.get('composition_exception'))):
                errors.append(f'{label}: nondefault process composition requires composition_exception')
        diagnostics.append({'case_id': case_id, 'declared_composition': composition,
                            'declared_coverage': {'required': required, 'present': present, 'missing': missing},
                            'coverage_basis': 'declared_primary_roles'})
    return diagnostics


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
    context_version = context.get('schema_version')
    result_version = result.get('schema_version')
    v2 = context_version == 'tiangong-expert-context-v2' and result_version == 'tiangong-expert-recommendation-v2'
    v1 = context_version == 'tiangong-expert-context-v1' and result_version == 'tiangong-expert-recommendation-v1'
    if context_version not in ('tiangong-expert-context-v1', 'tiangong-expert-context-v2'):
        errors.append('context: unsupported schema_version')
    if not (v1 or v2):
        errors.append('context/result: schema versions must match')
    if context_version == 'tiangong-expert-context-v1' and _contains_roles(context):
        errors.append('context: role profiles or assignments require v2')
    if result_version == 'tiangong-expert-recommendation-v1' and _contains_roles(result):
        errors.append('result: role profiles or assignments require v2')
    if not isinstance(context.get('binding_sha256'), str) or not re.fullmatch('[0-9a-f]{64}', context['binding_sha256']):
        errors.append('context: binding snapshot SHA-256 is required')
    if result_version not in ('tiangong-expert-recommendation-v1', 'tiangong-expert-recommendation-v2'):
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
        if status not in ('proposed', 'insufficient_candidates', 'needs_context'):
            errors.append(f'{label}: unsupported proposal status')
        if status == 'proposed' and len(selected) != 3:
            errors.append(f'{label}: proposed requires three experts')
        if status in ('insufficient_candidates', 'needs_context') and not gaps:
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
    diagnostics = _validate_role_teams(context, datasets, proposals, errors) if v2 else None
    checked = {'valid': not errors, 'errors': errors,
               'assignment_authorized': False, 'semantic_accuracy_verified': False,
               'live_identity_rechecked': False, 'case_count': len(proposals)}
    if diagnostics is not None:
        checked['case_diagnostics'] = diagnostics
    return checked
