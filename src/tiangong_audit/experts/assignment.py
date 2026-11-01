"""Private, read-only assignment planning and whole-package verification.

These artifacts describe platform evidence; they never confer write authority.
Professional recommendations and live identity checks remain separate steps.
"""
from __future__ import annotations

import hashlib
import json
from copy import deepcopy


def _index(rows: list, key: str) -> dict:
    if not isinstance(rows, list):
        raise ValueError('Expected complete list evidence')
    indexed = {}
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get(key), str) or not row[key] or row[key] in indexed:
            raise ValueError('Missing or duplicate evidence identity')
        indexed[row[key]] = row
    return indexed


def _scope(package: dict) -> str:
    tasks = _index(package['tasks'], 'id')
    refs = _index(package['references'], 'reference_review_id')
    root_id = package['root_review_id']
    if root_id in refs or set(tasks) != {root_id, *refs} or not package.get('root_content_sha256'):
        raise ValueError('Incomplete package scope')
    scope = {'root_review_id': root_id, 'root_content_sha256': package['root_content_sha256'],
             'tasks': sorted((uid, row['json']['data']['table'], row['data_id'], row['data_version'])
                             for uid, row in tasks.items()),
             'references': sorted((uid, row['target_table'], row['data_id'], row['data_version'],
                                   row['submitted_revision_checksum']) for uid, row in refs.items())}
    return hashlib.sha256(json.dumps(scope, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def plan_assignment(package: dict, reviewer_ids: list[str]) -> dict:
    """Classify every task, retaining conflicts instead of replacing reviewers."""
    if (not isinstance(reviewer_ids, list) or len(reviewer_ids) != 3
            or any(not isinstance(uid, str) or not uid for uid in reviewer_ids)
            or len(set(reviewer_ids)) != 3):
        raise ValueError('Exactly three distinct confirmed reviewer IDs are required')
    scope_sha256 = _scope(package)
    tasks = _index(package['tasks'], 'id')
    eligibility = _index(package['eligibility'], 'review_id')
    if set(eligibility) != set(tasks) or any(type(row.get('eligible')) is not bool for row in eligibility.values()):
        raise ValueError('Complete batch eligibility evidence is required')
    result = {'schema_version': 'tiangong-assignment-plan-v1', 'package': deepcopy(package),
              'scope_sha256': scope_sha256, 'reviewer_ids': list(reviewer_ids),
              'to_assign': [], 'already_assigned': [], 'completed': [], 'blocked': [],
              'assignment_authorized': False}
    for uid, row in tasks.items():
        state, current = row['state_code'], row['reviewer_id']
        if (type(state) is not int or not isinstance(current, list)
                or any(not isinstance(value, str) or not value for value in current)
                or len(set(current)) != len(current)):
            raise ValueError('Invalid assignment state')
        if state == 2 and uid != package['root_review_id']:
            result['completed'].append(uid)
        elif state not in (0, 1):
            result['blocked'].append({'review_id': uid, 'reason': 'invalid_state'})
        elif current and set(current) != set(reviewer_ids):
            result['blocked'].append({'review_id': uid, 'reason': 'reviewer_conflict'})
        elif state == 1 and set(current) == set(reviewer_ids):
            result['already_assigned'].append(uid)
        elif not eligibility[uid]['eligible']:
            result['blocked'].append({'review_id': uid, 'reason': 'not_eligible'})
        else:
            # State 0 may contain an assignment draft for these exact reviewers.
            result['to_assign'].append(uid)
    return result


def verify_assignment(plan: dict, current_package: dict) -> dict:
    """Root-only success, partial batches and changed closures never pass."""
    if (plan.get('schema_version') != 'tiangong-assignment-plan-v1'
            or _scope(plan['package']) != plan.get('scope_sha256')):
        raise ValueError('Invalid frozen assignment plan')
    expected = plan_assignment(plan['package'], plan['reviewer_ids'])
    same_scope = _scope(current_package) == plan['scope_sha256']
    assigned, completed, pending = [], [], []
    for row in current_package['tasks']:
        uid = row['id']
        if uid in expected['completed']:
            (completed if row['state_code'] == 2 else pending).append(uid)
        elif (row['state_code'] in (1, 2) and len(row['reviewer_id']) == 3
              and set(row['reviewer_id']) == set(plan['reviewer_ids'])):
            assigned.append(uid)
        else:
            pending.append(uid)
    return {'complete': same_scope and not pending and not expected['blocked'],
            'same_scope': same_scope, 'assigned_review_ids': sorted(assigned),
            'completed_review_ids': sorted(completed), 'pending_review_ids': sorted(pending),
            'assignment_authorized': False}


def check_shared_assignments(plans: list[dict]) -> list[str]:
    """Shared tasks are executed once; differing requested teams block the batch."""
    teams, conflicts = {}, set()
    for plan in plans:
        requested = frozenset(plan['reviewer_ids'])
        for task in plan['package']['tasks']:
            uid = task['id']
            if uid in teams and teams[uid] != requested:
                conflicts.add(uid)
            teams[uid] = requested
    return sorted(conflicts)
