"""Fail-closed exact mailbox binding to a complete read-only review directory."""

from __future__ import annotations

from collections import Counter, defaultdict
from copy import deepcopy

from .importer import normalize_email


def bind_roster(roster: dict, members: list[dict], visible_users: list[dict], *, platform_url: str, fetched_at: str, directory_complete: bool = True) -> dict:
    """Return a new roster with eligible status backed by member and ID readback.

    Exact mailbox comparison uses importer.normalize_email. Names never establish
    identity. Any invalid or repeated member ID makes the directory unusable.
    """
    result = deepcopy(roster)
    result['binding_provenance'] = {'platform_url': platform_url, 'fetched_at': fetched_at, 'directory_complete': directory_complete}
    by_email = defaultdict(list)
    by_identity = defaultdict(list)
    directory_errors = []
    ids = set()
    if not isinstance(members, list) or not isinstance(visible_users, list):
        raise ValueError('Member directory and visible identities must be lists')
    for member in members:
        if not isinstance(member, dict):
            directory_errors.append('invalid_member_record')
            continue
        member_id = member.get('user_id')
        email = normalize_email(member.get('email'))
        if not isinstance(member_id, str) or not member_id or member_id in ids or not email:
            directory_errors.append('invalid_or_duplicate_member_identity')
            continue
        roles = member.get('roles', member.get('role'))
        if not isinstance(roles, (str, list)) or isinstance(roles, list) and not all(isinstance(role, str) for role in roles):
            directory_errors.append('invalid_member_roles')
            continue
        ids.add(member_id)
        by_email[email].append(member)
    for identity in visible_users:
        if not isinstance(identity, dict) or not isinstance(identity.get('id'), str) or not identity['id']:
            directory_errors.append('invalid_identity_record')
            continue
        by_identity[identity['id']].append(identity)
    result['binding_provenance']['issues'] = directory_errors
    counts = Counter(record.get('email_normalized') for record in result['records'] if record.get('email_normalized'))
    for record in result['records']:
        binding = {'status': None, 'member_id': None, 'member_email': None, 'roles': [], 'identity_email': None, 'issues': []}
        record['binding'] = binding
        record['eligible'] = False
        email = normalize_email(record.get('email_raw'))
        status = None
        if record.get('admission') != 'included':
            binding['issues'].append('not_included')
        if not email or email != record.get('email_normalized'):
            status = 'invalid_email'
        elif 'column_count_mismatch' in record.get('issues', []):
            status = 'source_row_invalid'
        elif counts[email] > 1:
            status = 'duplicate_roster_email'
        elif not directory_complete:
            status = 'directory_incomplete'
        elif directory_errors:
            status = 'directory_invalid'
        elif len(by_email[email]) > 1:
            status = 'duplicate_member_email'
        elif not by_email[email]:
            status = 'email_case_mismatch' if any(candidate and rows and candidate.casefold() == email.casefold() for candidate, rows in by_email.items()) else 'member_missing'
        else:
            member = by_email[email][0]
            member_id = member['user_id']
            roles = member.get('roles', member.get('role', []))
            if isinstance(roles, str):
                roles = [roles]
            binding.update(member_id=member_id, member_email=member['email'], roles=deepcopy(roles))
            identities = by_identity[member_id]
            if 'review-member' not in roles:
                status = 'review_role_missing'
            elif not identities:
                status = 'identity_missing'
            elif len(identities) > 1:
                status = 'duplicate_identity'
            else:
                binding['identity_email'] = identities[0].get('email')
                status = 'bound' if normalize_email(binding['identity_email']) == email else 'identity_mismatch'
        binding['status'] = status
        if status != 'bound':
            binding['issues'].append(status)
        record['eligible'] = status == 'bound' and record.get('admission') == 'included'
    return result
