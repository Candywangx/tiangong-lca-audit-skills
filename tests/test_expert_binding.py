import copy

import pytest

from tiangong_audit.experts.binding import bind_roster
from tiangong_audit.experts.importer import import_roster
from tiangong_audit.integrations.tiangong_api.experts import ExpertAPI, ExpertDirectoryError
from test_expert_import import write_roster


def bind(roster, members, identities, **kwargs):
    return bind_roster(roster, members, identities, platform_url='https://synthetic.invalid', fetched_at='2026-10-28T00:00:00Z', **kwargs)


def roster(tmp_path, email='a@example.org', admission='是'):
    return import_roster(write_roster(tmp_path, [['甲', '合成机构', admission, email, '电力', 'LCA']]))


def member(email='a@example.org', id='u1'):
    return {'user_id': id, 'email': email, 'role': 'review-member', 'display_name': '甲'}


def identity(email='a@example.org', id='u1'):
    return {'id': id, 'email': email, 'display_name': '甲'}


def test_binding_requires_exact_member_and_identity_readback_without_mutation(tmp_path):
    source = roster(tmp_path)
    before = copy.deepcopy(source)
    result = bind(source, [member()], [identity()])
    record = result['records'][0]
    assert source == before
    assert record['eligible'] is True
    assert record['binding']['status'] == 'bound'
    assert record['binding']['member_id'] == 'u1'
    assert record['binding']['member_email'] == 'a@example.org'
    assert record['binding']['identity_email'] == 'a@example.org'
    assert record['binding']['roles'] == ['review-member']
    assert result['binding_provenance']['directory_complete'] is True


@pytest.mark.parametrize(('members', 'identities', 'status'), [
    ([], [], 'member_missing'),
    ([member()], [], 'identity_missing'),
    ([member()], [identity('changed@example.org')], 'identity_mismatch'),
    ([member(), member(id='u2')], [identity()], 'duplicate_member_email'),
    ([member(), member('other@example.org')], [identity()], 'directory_invalid'),
    ([member()], [identity(), identity()], 'duplicate_identity'),
    ([member('other@example.org')], [identity()], 'member_missing'),
])
def test_binding_fails_closed_for_unverified_or_ambiguous_identity(tmp_path, members, identities, status):
    record = bind(roster(tmp_path), members, identities)['records'][0]
    assert record['eligible'] is False
    assert record['binding']['status'] == status


@pytest.mark.parametrize('admission', ['否', '', '待确认'])
def test_only_explicitly_included_roster_rows_eligible(tmp_path, admission):
    record = bind(roster(tmp_path, admission=admission), [member()], [identity()])['records'][0]
    assert record['eligible'] is False
    assert record['binding']['status'] == 'bound'
    assert record['binding']['member_id'] == 'u1'
    assert 'not_included' in record['binding']['issues']


def test_incomplete_directory_never_eligible(tmp_path):
    record = bind(roster(tmp_path), [member()], [identity()], directory_complete=False)['records'][0]
    assert not record['eligible']
    assert record['binding']['status'] == 'directory_incomplete'


def test_duplicate_roster_identity_never_recommended_twice(tmp_path):
    source = import_roster(write_roster(tmp_path, [['甲', '机构', '是', 'a@example.org', '', ''], ['乙', '机构', '是', 'a@example.org', '', '']]))
    records = bind(source, [member()], [identity()])['records']
    assert all(not record['eligible'] for record in records)
    assert all(record['binding']['status'] == 'duplicate_roster_email' for record in records)


def test_invalid_roster_email_does_not_name_bind(tmp_path):
    record = bind(roster(tmp_path, 'A <a@example.org>'), [member()], [identity()])['records'][0]
    assert not record['eligible']
    assert record['binding']['status'] == 'invalid_email'


def test_case_only_mailbox_difference_requires_confirmation(tmp_path):
    record = bind(roster(tmp_path, 'A@example.org'), [member()], [identity()])['records'][0]
    assert not record['eligible']
    assert record['binding']['status'] == 'email_case_mismatch'


def test_malformed_csv_record_cannot_become_eligible(tmp_path):
    source = import_roster(write_roster(tmp_path, [['甲', '机构', '是', 'a@example.org']]))
    record = bind(source, [member()], [identity()])['records'][0]
    assert not record['eligible']
    assert record['binding']['status'] == 'source_row_invalid'


class ReadOnlyClient:
    def __init__(self, replies):
        self.replies = iter(replies)
        self.calls = []

    def rpc(self, name, payload):
        self.calls.append((name, payload))
        result = next(self.replies)
        if isinstance(result, Exception):
            raise result
        return result

    def command(self, *args, **kwargs):
        raise AssertionError('Writes are forbidden')


def page(start, stop, total):
    return [dict(member(email=f'expert{i}@example.org', id=f'u{i}'), total_count=total) for i in range(start, stop)]


def test_adapter_reads_more_than_100_members_including_last_page():
    client = ReadOnlyClient([page(0, 50, 121), page(50, 100, 121), page(100, 121, 121)])
    result = ExpertAPI(client).get_all_members()
    assert len(result) == 121
    assert result[-1]['user_id'] == 'u120'
    assert [payload['p_page'] for _, payload in client.calls] == [1, 2, 3]
    assert all(name == 'qry_review_get_member_list' and payload == {
        'p_page': index, 'p_page_size': 50, 'p_sort_by': 'email', 'p_sort_order': 'asc', 'p_role': 'review-member'
    } for index, (name, payload) in enumerate(client.calls, start=1))


@pytest.mark.parametrize('replies', [
    [[]],
    [{'data': []}],
    [[{'user_id': 'u1', 'email': 'a@example.org', 'role': 'review-member'}]],
    [page(0, 50, 51), []],
    [page(0, 50, 51), page(0, 1, 51)],
    [page(0, 50, 51), page(50, 51, 52)],
    [page(0, 2, 1)],
    [[dict(member(), total_count='1')]],
    [[dict(member(), total_count=True)]],
    [[dict(member(), role='admin', total_count=1)]],
    [page(0, 50, 51), RuntimeError('page failed')],
])
def test_adapter_never_returns_silent_success_for_unknown_or_broken_directory(replies):
    with pytest.raises((ExpertDirectoryError, RuntimeError)):
        ExpertAPI(ReadOnlyClient(replies)).get_all_members()


def test_adapter_propagates_explicit_rpc_failure():
    with pytest.raises(RuntimeError, match='permission denied'):
        ExpertAPI(ReadOnlyClient([RuntimeError('permission denied')])).get_all_members()


def test_roster_over_100_rows_binds_last_account_without_dropping_rows(tmp_path):
    rows = [[f'专家{i}', '合成机构', '是', f'expert{i}@example.org', '电力', 'LCA'] for i in range(121)]
    source = import_roster(write_roster(tmp_path, rows))
    members = page(0, 121, 121)
    identities = [identity(f'expert{i}@example.org', f'u{i}') for i in range(121)]
    result = bind(source, members, identities)
    assert len(result['records']) == 121
    assert result['records'][-1]['eligible']


def test_identity_readback_is_bounded_and_retains_individual_missing_users():
    requested = [f'u{i}' for i in range(95)]
    client = ReadOnlyClient([
        [identity(f'expert{i}@example.org', f'u{i}') for i in range(39)],
        [identity(f'expert{i}@example.org', f'u{i}') for i in range(40, 80)],
        [identity(f'expert{i}@example.org', f'u{i}') for i in range(80, 95)],
    ])
    results = ExpertAPI(client).read_users(requested)
    assert len(results) == 94
    assert all(name == 'qry_identity_get_visible_users' for name, _ in client.calls)
    assert [len(payload['p_user_ids']) for _, payload in client.calls] == [40, 40, 15]
    assert [id for _, payload in client.calls for id in payload['p_user_ids']] == requested
    assert 'u39' not in {item['id'] for item in results}


@pytest.mark.parametrize('response', [
    {'data': []}, None, ['invalid'], [{'id': 'u1'}],
    [identity(id='unexpected')], [identity(), identity()],
    [identity(email='invalid-email')], [identity(id=None)],
])
def test_identity_readback_rejects_malformed_duplicate_and_unrequested_users(response):
    with pytest.raises(ExpertDirectoryError):
        ExpertAPI(ReadOnlyClient([response])).read_users(['u1'])


def test_identity_readback_propagates_rpc_failure():
    with pytest.raises(RuntimeError, match='permission denied'):
        ExpertAPI(ReadOnlyClient([RuntimeError('permission denied')])).read_users(['u1'])


def test_identity_missing_visibility_does_not_invalidate_successful_binding(tmp_path):
    source = import_roster(write_roster(tmp_path, [['甲', '机构', '是', 'a@example.org', '', ''], ['乙', '机构', '是', 'b@example.org', '', '']]))
    records = bind(source, [member(), member('b@example.org', 'u2')], [identity()])['records']
    assert records[0]['eligible']
    assert not records[1]['eligible']
    assert records[1]['binding']['status'] == 'identity_missing'


def test_identity_readback_empty_request_does_not_call_platform():
    client = ReadOnlyClient([])
    assert ExpertAPI(client).read_users([]) == []
    assert client.calls == []


@pytest.mark.parametrize('broken_member', [
    dict(member(), user_id=[]), dict(member(), user_id=None),
    dict(member(), role=None), dict(member(), role=42),
    dict(member(), roles={'review-member': True}),
])
def test_malformed_directory_values_fail_closed_without_incidental_type_errors(tmp_path, broken_member):
    record = bind(roster(tmp_path), [broken_member], [identity()])['records'][0]
    assert not record['eligible']
    assert record['binding']['status'] == 'directory_invalid'


def test_binding_preserves_exact_platform_emails_and_roles(tmp_path):
    platform_member = dict(member('a@EXAMPLE.ORG'), roles=['review-member', 'review-lead'])
    record = bind(roster(tmp_path), [platform_member], [identity('a@Example.Org')])['records'][0]
    assert record['eligible']
    assert record['binding']['member_email'] == 'a@EXAMPLE.ORG'
    assert record['binding']['identity_email'] == 'a@Example.Org'
    assert record['binding']['roles'] == ['review-member', 'review-lead']
