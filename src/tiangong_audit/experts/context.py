"""Prepare professional evidence without deciding industry or expertise fit."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from tiangong_audit.workflows.title_duplicate import dataset_payload
from tiangong_audit.workflows.intake import _resolve_model_process_refs
from tiangong_audit.workflows.model_review import _snapshot_identity, dataset_snapshot_sha256
from .workspace import write_snapshot


def _leaves(value, pointer: str):
    if isinstance(value, dict):
        for key, child in value.items():
            if key in {'@xml:lang', '@lang'}:
                continue
            token = str(key).replace('~', '~0').replace('/', '~1')
            yield from _leaves(child, pointer + '/' + token)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from _leaves(child, pointer + '/' + str(index))
    elif isinstance(value, str) and value.strip():
        yield {'ref': pointer, 'text': value}
    elif isinstance(value, (int, float, bool)):
        yield {'ref': pointer, 'text': json.dumps(value, allow_nan=False)}


def dataset_evidence(payload: dict, *, snapshot_ref: str) -> list[dict]:
    """Retain reference pointers and exchanges even when the title is ambiguous.

    Payload is an unwrapped dataset snapshot. Locators refer to that exact
    snapshot; operational/administrative contact data is not projected.
    """
    result = []
    for key, info in [('processDataSet', 'processInformation'),
                      ('lifeCycleModelDataSet', 'lifeCycleModelInformation')]:
        body = payload.get(key)
        if not isinstance(body, dict):
            continue
        for section in (info, 'exchanges'):
            result.extend(_leaves(body.get(section, {}), f'{snapshot_ref}#/{key}/{section}'))
        modelling = body.get('modellingAndValidation') or {}
        if isinstance(modelling, dict):
            result.extend(_leaves(modelling.get('LCIMethodAndAllocation', {}),
                                  f'{snapshot_ref}#/{key}/modellingAndValidation/LCIMethodAndAllocation'))
    return result


def prepare_context(bindings_path: Path, case_dirs: list[Path], directory: Path) -> dict:
    raw_bindings = bindings_path.read_bytes()
    bindings = json.loads(raw_bindings)
    experts = []
    for record in bindings['records']:
        if record.get('eligible') is not True:
            continue
        if record.get('admission') != 'included' or record.get('binding', {}).get('status') != 'bound':
            raise ValueError('Eligible flag contradicts binding or admission')
        experts.append({key: record[key] for key in ('expert_id', 'eligible', 'fields_text', 'experience_text')})
    if len({r['expert_id'] for r in experts}) != len(experts):
        raise ValueError('Duplicate eligible expert identity')
    datasets = []
    for case_dir in case_dirs:
        manifest = json.loads((case_dir / 'case.json').read_text(encoding='utf-8'))
        source = case_dir / 'snapshots' / 'dataset.raw.json'
        source_bytes = source.read_bytes()
        payload = dataset_payload(json.loads(source_bytes))
        if 'processDataSet' in payload:
            dataset_type = 'process'
        elif 'lifeCycleModelDataSet' in payload:
            dataset_type = 'model'
        else:
            raise ValueError('Unsupported dataset snapshot')
        snapshot = write_snapshot(directory / 'snapshots', 'dataset', payload)
        snapshot_ref = snapshot.relative_to(directory).as_posix()
        evidence = dataset_evidence(payload, snapshot_ref=snapshot_ref)
        linked = []
        linked_gaps = []
        if dataset_type == 'model':
            references = _resolve_model_process_refs(payload)
            if not references:
                linked_gaps.append({'process_id': '', 'version': '', 'reason': 'no_verifiable_process_references'})
            rows = []
            for path in sorted((case_dir / 'snapshots' / 'linked-processes').glob('*.json')):
                row = json.loads(path.read_text(encoding='utf-8'))
                if isinstance(row, dict) and 'processDataSet' in dataset_payload(row):
                    rows.append(row)
            for reference in references:
                process_id, version = reference['process_id'], reference['version']
                matching = [row for row in rows if process_id and version and _snapshot_identity(row, process_id, version)]
                if not matching:
                    linked_gaps.append({'process_id': process_id, 'version': version, 'reason': 'missing_or_invalid_exact_snapshot'})
                    continue
                if len({dataset_snapshot_sha256(row) for row in matching}) != 1:
                    linked_gaps.append({'process_id': process_id, 'version': version, 'reason': 'conflicting_exact_snapshots'})
                    continue
                linked_payload = dataset_payload(matching[0])
                linked_path = write_snapshot(directory / 'snapshots', 'linked-process', linked_payload)
                linked_ref = linked_path.relative_to(directory).as_posix()
                linked.append(linked_ref)
                evidence.extend(dataset_evidence(linked_payload, snapshot_ref=linked_ref))
        # The same linked snapshot may appear through more than one reference.
        evidence = list({row['ref']: row for row in evidence}.values())
        datasets.append({'case_id': manifest['review_id'], 'dataset_type': dataset_type,
                         'name': manifest.get('name_zh') or manifest.get('name_en') or '',
                         'dataset_id': manifest.get('dataset_id'), 'version': manifest.get('version'),
                         'snapshot_ref': snapshot_ref,
                         'snapshot_sha256': hashlib.sha256(snapshot.read_bytes()).hexdigest(),
                         'source_sha256': hashlib.sha256(source_bytes).hexdigest(),
                         'linked_snapshots': sorted(set(linked)), 'linked_reference_gaps': linked_gaps,
                         'evidence': evidence})
    if not datasets or len({r['case_id'] for r in datasets}) != len(datasets):
        raise ValueError('Cases must be nonempty and unique')
    return {'schema_version': 'tiangong-expert-context-v1',
            'binding_sha256': hashlib.sha256(raw_bindings).hexdigest(),
            'experts': experts, 'datasets': datasets}
