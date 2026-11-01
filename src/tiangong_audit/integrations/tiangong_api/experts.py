"""Strict read-only RPC adapter for expert membership and identity evidence."""

from __future__ import annotations

from typing import Any

from ...experts.importer import normalize_email
from .client import TiangongAPIError


class ExpertDirectoryError(TiangongAPIError):
    """The directory/readback could not be established as complete and valid."""


class ExpertAPI:
    def __init__(self, client: Any):
        self.client = client

    def read_users(self, ids: list[str]) -> list[dict]:
        """Read visible identity records in batches of 40 without guessing omissions.

        Missing requested IDs remain absent so the binder can report individual
        identity_missing results. Malformed, duplicate or unrequested returned
        identities fail the call. RPC failures propagate unchanged.
        """
        if not isinstance(ids, list) or any(not isinstance(user_id, str) or not user_id for user_id in ids):
            raise ValueError('Identity IDs must be a list of nonempty strings')
        requested = list(dict.fromkeys(ids))
        results = []
        seen = set()
        for start in range(0, len(requested), 40):
            chunk = requested[start:start + 40]
            response = self.client.rpc('qry_identity_get_visible_users', {'p_user_ids': chunk})
            if not isinstance(response, list):
                raise ExpertDirectoryError('Identity readback must return a list')
            for row in response:
                if not isinstance(row, dict):
                    raise ExpertDirectoryError('Invalid identity readback record')
                user_id = row.get('id')
                if not isinstance(user_id, str) or user_id not in chunk or user_id in seen:
                    raise ExpertDirectoryError('Invalid, duplicate or unrequested identity ID')
                if normalize_email(row.get('email')) is None:
                    raise ExpertDirectoryError('Invalid identity readback email')
                seen.add(user_id)
                results.append(dict(row))
        return results

    def get_all_members(self, page_size: int = 50) -> list[dict]:
        """Read every review-member page; raise on unknown totals or anomalies.

        The platform returns a bare list with total_count repeated on each row.
        A bare empty list does not prove a zero total and fails closed.
        """
        if type(page_size) is not int or not 1 <= page_size <= 100:
            raise ValueError('page_size must be an integer between 1 and 100')
        records = []
        seen = set()
        total = None
        page_number = 1
        while True:
            response = self.client.rpc('qry_review_get_member_list', {
                'p_page': page_number, 'p_page_size': page_size,
                'p_sort_by': 'email', 'p_sort_order': 'asc', 'p_role': 'review-member',
            })
            if not isinstance(response, list) or not response:
                raise ExpertDirectoryError(f'Member page {page_number} missing list rows or known total_count')
            if len(response) > page_size:
                raise ExpertDirectoryError('Member page exceeds requested page size')
            for row in response:
                if not isinstance(row, dict):
                    raise ExpertDirectoryError('Invalid member row')
                count = row.get('total_count')
                if type(count) is not int or count < 0:
                    raise ExpertDirectoryError('Member total_count must be a known nonnegative integer')
                if total is None:
                    total = count
                if count != total:
                    raise ExpertDirectoryError('Member total_count changed during pagination')
                user_id = row.get('user_id')
                if not isinstance(user_id, str) or not user_id or user_id in seen:
                    raise ExpertDirectoryError('Invalid or duplicate member user_id')
                if normalize_email(row.get('email')) is None or row.get('role') != 'review-member':
                    raise ExpertDirectoryError('Invalid review-member identity or role')
                seen.add(user_id)
                records.append(dict(row))
            if len(records) > total:
                raise ExpertDirectoryError('Member count exceeds advertised total_count')
            if len(records) == total:
                return records
            if len(response) < page_size:
                raise ExpertDirectoryError('Member pagination ended before total_count')
            page_number += 1
