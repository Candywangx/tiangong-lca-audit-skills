"""Read-only CSV projection; source files remain the immutable evidence artifact."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import re
from collections import Counter
from pathlib import Path


HEADERS = ('姓名', '单位名称', '是否入库', '电子邮箱', '评审领域', 'LCA/碳足迹领域主要经验')
LOCAL = re.compile(r"[A-Za-z0-9!#$%&'*+/=?^_`{|}~.-]+\Z")
DOMAIN_LABEL = re.compile(r'[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\Z')


def normalize_email(value: object) -> str | None:
    """Accept one ASCII mailbox, trim outer whitespace, lowercase domain only.

    Local-part case, dots and plus tags stay exact. Display names, address lists,
    quoted/Unicode mailboxes and invalid syntax require manual correction; no
    guessed corrections or provider-specific mailbox equivalence are applied.
    """
    if not isinstance(value, str):
        return None
    email = value.strip()
    if len(email) > 254 or email.count('@') != 1:
        return None
    local, domain = email.split('@')
    if not 1 <= len(local) <= 64 or not LOCAL.fullmatch(local):
        return None
    if local.startswith('.') or local.endswith('.') or '..' in local:
        return None
    labels = domain.split('.')
    if len(labels) < 2 or len(domain) > 253 or not all(DOMAIN_LABEL.fullmatch(label) for label in labels):
        return None
    if len(labels[-1]) < 2 or not labels[-1].isalpha():
        return None
    return f'{local}@{domain.lower()}'


def import_roster(path: str | Path) -> dict:
    """Project approved CSV fields into versioned JSON without changing source."""
    source = Path(path).read_bytes()
    reader = csv.reader(io.StringIO(source.decode('utf-8-sig'), newline=''), strict=True)
    try:
        headers = next(reader)
    except StopIteration as error:
        raise ValueError('Missing CSV header') from error
    if len(headers) != len(set(headers)):
        raise ValueError('Duplicate CSV header')
    missing = set(HEADERS) - set(headers)
    if missing:
        raise ValueError('Missing required CSV header: ' + ', '.join(sorted(missing)))
    indices = {name: headers.index(name) for name in HEADERS}
    records = []
    for source_row, cells in enumerate(reader, start=2):
        row = {key: cells[index] if index < len(cells) else '' for key, index in indices.items()}
        email = normalize_email(row['电子邮箱'])
        admission = {'是': 'included', '否': 'excluded'}.get(row['是否入库'].strip(), 'unknown')
        identity = email or json.dumps(row, ensure_ascii=False, sort_keys=True)
        record = {
            'expert_id': 'expert_' + hashlib.sha256(identity.encode()).hexdigest(),
            'source_row': source_row,
            'name': row['姓名'],
            'organization': row['单位名称'],
            'admission': admission,
            'email_raw': row['电子邮箱'],
            'email_normalized': email,
            'fields_text': row['评审领域'],
            'experience_text': row['LCA/碳足迹领域主要经验'],
            'issues': [],
        }
        if email is None:
            record['issues'].append('invalid_email')
        if admission == 'unknown':
            record['issues'].append('admission_unknown')
        if len(cells) != len(headers):
            record['issues'].append('column_count_mismatch')
        records.append(record)
    counts = Counter(record['email_normalized'] for record in records if record['email_normalized'])
    for record in records:
        if counts[record['email_normalized']] > 1:
            record['issues'].append('duplicate_email')
    return {'schema_version': 1, 'source_sha256': hashlib.sha256(source).hexdigest(), 'records': records}
