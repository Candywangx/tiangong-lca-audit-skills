import csv
import hashlib

import pytest

from tiangong_audit.experts.importer import import_roster, normalize_email


HEADERS = ['姓名', '单位名称', '是否入库', '电子邮箱', '评审领域', 'LCA/碳足迹领域主要经验']


def write_roster(tmp_path, rows, headers=HEADERS):
    path = tmp_path / 'synthetic.csv'
    with path.open('w', encoding='utf-8-sig', newline='') as handle:
        writer = csv.writer(handle)
        writer.writerow(headers)
        writer.writerows(rows)
    return path


def test_import_preserves_rows_multiline_and_source_bytes(tmp_path):
    path = write_roster(tmp_path, [
        ['专家甲', '合成机构', '是', ' a@EXAMPLE.org ', '钢铁\n电力', 'LCA\r\nexperience'],
        ['专家乙', '合成机构', '否', 'b@example.org', '', ''],
        ['专家丙', '合成机构', '', '', '', ''],
    ])
    before = path.read_bytes()
    result = import_roster(path)
    assert result == import_roster(path)
    assert result['schema_version'] == 1
    assert result['source_sha256'] == hashlib.sha256(before).hexdigest()
    assert [r['source_row'] for r in result['records']] == [2, 3, 4]
    assert [r['admission'] for r in result['records']] == ['included', 'excluded', 'unknown']
    assert result['records'][0]['fields_text'] == '钢铁\n电力'
    assert result['records'][0]['experience_text'] == 'LCA\r\nexperience'
    assert result['records'][0]['email_raw'] == ' a@EXAMPLE.org '
    assert result['records'][0]['email_normalized'] == 'a@example.org'
    assert path.read_bytes() == before


@pytest.mark.parametrize('email', ['a@example.org;b@example.org', 'A <a@example.org>',
    'a@example.org b@example.org', 'a@@example.org', 'a@localhost', 'a..b@example.org',
    '.a@example.org', 'a@example..org', 'a@example.org\nBcc:x@example.org', ''])
def test_ambiguous_or_invalid_email_is_preserved_and_flagged(tmp_path, email):
    record = import_roster(write_roster(tmp_path, [['甲', '机构', '是', email, '', '']]))['records'][0]
    assert record['email_raw'] == email
    assert record['email_normalized'] is None
    assert 'invalid_email' in record['issues']


def test_email_normalization_does_not_guess_mailbox_equivalence():
    assert normalize_email(' A.Tag+review@EXAMPLE.ORG ') == 'A.Tag+review@example.org'
    assert normalize_email('a.tag+review@example.org') != normalize_email('A.Tag+review@example.org')


def test_duplicate_email_flags_every_occurrence_with_stable_identity(tmp_path):
    records = import_roster(write_roster(tmp_path, [
        ['甲', '机构', '是', 'a@EXAMPLE.org', '', ''],
        ['乙', '机构', '否', ' a@example.org ', '', ''],
    ]))['records']
    assert records[0]['expert_id'] == records[1]['expert_id']
    assert all('duplicate_email' in row['issues'] for row in records)


def test_import_drops_unapproved_private_columns(tmp_path):
    path = write_roster(tmp_path, [['甲', '机构', '是', 'a@example.org', '电力', '', 'private-phone', 'private-cv']], HEADERS + ['电话', '简历'])
    assert 'private' not in str(import_roster(path))


def test_missing_and_duplicate_headers_rejected(tmp_path):
    with pytest.raises(ValueError, match='header'):
        import_roster(write_roster(tmp_path, [], HEADERS[:-1]))
    with pytest.raises(ValueError, match='header'):
        import_roster(write_roster(tmp_path, [], HEADERS + ['姓名']))
