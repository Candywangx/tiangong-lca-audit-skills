"""Synthetic root/reference regressions; no platform writes or real identities."""
from copy import deepcopy

import pytest

from tiangong_audit.integrations.tiangong_api import ReviewAPI, TiangongAPIError


REVIEWERS = ['reviewer-a', 'reviewer-b', 'reviewer-c']


def task(uid, table='flows', *, state=0, reviewers=None, kind='reference'):
    return {'id': uid, 'data_id': 'data-' + uid, 'data_version': '01.00.000',
            'state_code': state, 'reviewer_id': reviewers or [], 'deadline': None,
            'json': {'review_kind': kind, 'data': {'table': table}}}


def reference(row):
    return {'reference_review_id': row['id'], 'target_table': row['json']['data']['table'],
            'data_id': row['data_id'], 'data_version': row['data_version'],
            'submitted_revision_checksum': 'checksum-' + row['id'],
            'state_code': row['state_code'], 'reviewer_count': len(row['reviewer_id'])}


class ReadClient:
    def __init__(self, count=2):
        self.rows = [task('root', 'processes', state=1, reviewers=REVIEWERS, kind='root')]
        self.rows += [task(f'child-{i}', 'sources' if i == 1 else 'flows') for i in range(count)]
        self.refs = [reference(row) for row in self.rows[1:]]
        self.calls = []
        self.omit = None
        self.ref_reads = 0
        self.change_refs = False

    def rpc_page(self, name, payload, *, limit, offset, order):
        if offset == 0:
            self.ref_reads += 1
        rows = self.rpc(name, payload)
        return rows[offset:offset + limit] if isinstance(rows, list) else rows

    def rpc(self, name, payload):
        self.calls.append((name, payload))
        if name == 'qry_root_review_reference_progress_v2':
            result = deepcopy(self.refs)
            if self.change_refs and self.ref_reads > 1:
                result[0]['submitted_revision_checksum'] = 'changed'
            return result
        if name == 'qry_review_get_items':
            return deepcopy([r for r in self.rows if r['id'] in payload['p_review_ids'] and r['id'] != self.omit])
        if name == 'qry_review_batch_eligibility_v1':
            return [{'review_id': uid, 'eligible': True} for uid in payload['p_review_ids']]
        raise AssertionError('Unexpected RPC: ' + name)

    def select(self, table, **kwargs):
        return [{'id': 'data-root', 'version': '01.00.000', 'json': {'processDataSet': {'test': 'content'}}}]


def package(client=None):
    return ReviewAPI(client or ReadClient()).get_assignment_package('root')


def plan(snapshot):
    from tiangong_audit.experts.assignment import plan_assignment
    return plan_assignment(snapshot, REVIEWERS)


def test_package_includes_root_flows_and_sources_with_bounded_reads():
    client = ReadClient(83)
    snapshot = package(client)
    assert len(snapshot['tasks']) == 84
    assert len(snapshot['references']) == 83
    assert snapshot['root_content_sha256']
    assert all(len(args['p_review_ids']) <= 40 for name, args in client.calls
               if name in ('qry_review_get_items', 'qry_review_batch_eligibility_v1'))


@pytest.mark.parametrize('problem', ['missing', 'wrong_version', 'duplicate', 'not_root', 'scope_changed'])
def test_package_fails_closed_on_incomplete_or_inconsistent_evidence(problem):
    client = ReadClient()
    if problem == 'missing': client.omit = 'child-0'
    if problem == 'wrong_version': client.rows[1]['data_version'] = '02.00.000'
    if problem == 'duplicate': client.refs.append(deepcopy(client.refs[0]))
    if problem == 'not_root': client.rows[0]['json']['review_kind'] = 'reference'
    if problem == 'scope_changed': client.change_refs = True
    with pytest.raises(TiangongAPIError):
        package(client)


def test_empty_reference_list_is_valid_but_rpc_failure_is_not_empty():
    assert len(package(ReadClient(0))['tasks']) == 1
    client = ReadClient()
    client.refs = None
    with pytest.raises(TiangongAPIError):
        package(client)


def test_plan_repairs_only_missing_children_and_does_not_reassign_root():
    result = plan(package())
    assert result['to_assign'] == ['child-0', 'child-1']
    assert result['already_assigned'] == ['root']
    assert result['blocked'] == []
    assert result['assignment_authorized'] is False


def test_existing_other_reviewers_are_a_conflict_not_a_replacement():
    snapshot = package()
    snapshot['tasks'][1].update(state_code=1, reviewer_id=['someone-else'])
    result = plan(snapshot)
    assert result['blocked'] == [{'review_id': 'child-0', 'reason': 'reviewer_conflict'}]
    assert 'child-0' not in result['to_assign']


def test_completed_reference_is_accounted_for_without_reopening():
    snapshot = package()
    snapshot['tasks'][1]['state_code'] = 2
    result = plan(snapshot)
    assert result['completed'] == ['child-0']
    assert 'child-0' not in result['to_assign']


def test_rejected_and_ineligible_tasks_block_the_plan():
    snapshot = package()
    snapshot['tasks'][1]['state_code'] = -1
    snapshot['eligibility'][2]['eligible'] = False
    result = plan(snapshot)
    assert len(result['blocked']) == 2
    assert not result['to_assign']


def test_missing_eligibility_and_duplicate_reviewers_are_not_accepted():
    from tiangong_audit.experts.assignment import plan_assignment
    snapshot = package()
    snapshot['eligibility'].pop()
    with pytest.raises(ValueError): plan(snapshot)
    with pytest.raises(ValueError): plan_assignment(package(), ['a', 'a', 'b'])


def test_root_only_success_cannot_pass_package_readback():
    from tiangong_audit.experts.assignment import verify_assignment
    snapshot = package()
    result = verify_assignment(plan(snapshot), snapshot)
    assert result['complete'] is False
    assert result['pending_review_ids'] == ['child-0', 'child-1']


def test_full_package_success_is_order_independent():
    from tiangong_audit.experts.assignment import verify_assignment
    snapshot = package(); prepared = plan(snapshot)
    for row in snapshot['tasks']:
        row.update(state_code=1, reviewer_id=list(reversed(REVIEWERS)))
    snapshot['references'].reverse(); snapshot['tasks'].reverse()
    assert verify_assignment(prepared, snapshot)['complete'] is True


@pytest.mark.parametrize('change', ['add', 'remove', 'checksum', 'root_content', 'version'])
def test_changed_package_scope_cannot_be_claimed_complete(change):
    from tiangong_audit.experts.assignment import verify_assignment
    snapshot = package(); prepared = plan(snapshot)
    for row in snapshot['tasks']: row.update(state_code=1, reviewer_id=REVIEWERS)
    if change == 'add':
        added = task('new', state=1, reviewers=REVIEWERS)
        snapshot['tasks'].append(added); snapshot['references'].append(reference(added))
    if change == 'remove': snapshot['references'].pop(); snapshot['tasks'].pop()
    if change == 'checksum': snapshot['references'][0]['submitted_revision_checksum'] = 'changed'
    if change == 'root_content': snapshot['root_content_sha256'] = 'changed'
    if change == 'version': snapshot['tasks'][0]['data_version'] = '02.00.000'
    assert verify_assignment(prepared, snapshot)['complete'] is False


def test_shared_reference_conflict_is_detected_before_batch_writes():
    from tiangong_audit.experts.assignment import check_shared_assignments, plan_assignment
    first = plan(package())
    second = plan_assignment(package(), ['d', 'e', 'f'])
    assert check_shared_assignments([first, first]) == []
    assert check_shared_assignments([first, second])


def test_reopened_completed_reference_cannot_pass_readback():
    from tiangong_audit.experts.assignment import verify_assignment
    snapshot = package()
    snapshot['tasks'][1]['state_code'] = 2
    prepared = plan(snapshot)
    for row in snapshot['tasks']: row.update(state_code=1, reviewer_id=REVIEWERS)
    assert verify_assignment(prepared, snapshot)['complete'] is False


def test_reference_pagination_reads_past_server_row_cap():
    class CappedClient(ReadClient):
        def rpc(self, name, payload):
            rows = super().rpc(name, payload)
            return rows[:2] if name == 'qry_root_review_reference_progress_v2' else rows

        def rpc_page(self, name, payload, *, limit, offset, order):
            assert order == 'target_table.asc,data_id.asc,data_version.asc,reference_review_id.asc'
            return deepcopy(self.refs[offset:offset + min(limit, 2)])

    assert len(package(CappedClient(5))['tasks']) == 6


@pytest.mark.parametrize('target', ['root', 'child'])
def test_same_count_reviewer_replacement_during_read_is_detected(target):
    class ChangingClient(ReadClient):
        def select(self, table, **kwargs):
            self.rows[0 if target == 'root' else 1]['reviewer_id'] = ['other-a', 'other-b', 'other-c']
            return super().select(table, **kwargs)
    client = ChangingClient()
    for row in client.rows: row.update(state_code=1, reviewer_id=REVIEWERS)
    client.refs = [reference(row) for row in client.rows[1:]]
    with pytest.raises(TiangongAPIError): package(client)


def test_root_kind_and_table_cannot_change_during_bulk_read():
    class ChangingClient(ReadClient):
        def rpc(self, name, payload):
            rows = super().rpc(name, payload)
            if name == 'qry_review_get_items' and len(payload['p_review_ids']) > 1:
                rows[0]['json'] = {'review_kind': 'reference', 'data': {'table': 'lifecyclemodels'}}
            return rows
    with pytest.raises(TiangongAPIError): package(ChangingClient())


def test_assignment_cli_stays_readonly_and_requires_full_package(private_repo, monkeypatch, capsys):
    import json
    from tiangong_audit import expert_commands
    from tiangong_audit.cli import main
    client = ReadClient()
    def make_client(**kwargs):
        assert kwargs == {'account_role': 'admin', 'allow_writes': False}
        return client
    monkeypatch.setattr(expert_commands, 'TiangongAPIClient', make_client)
    directory = private_repo / 'cases/expert-directory'
    args = ['experts', 'assignment-plan', '--review-id', 'root', '--directory', str(directory)]
    for uid in REVIEWERS: args += ['--reviewer-id', uid]
    assert main(args) == 0
    summary = json.loads(capsys.readouterr().out)
    assert summary['total_tasks'] == 3 and summary['to_assign'] == 2
    assert summary['platform_writes'] == 0
    assert not any(uid in json.dumps(summary) for uid in REVIEWERS)
    check = ['experts', 'assignment-check', '--plan', summary['plan_path'], '--directory', str(directory)]
    assert main(check) == 1
    assert json.loads(capsys.readouterr().out)['complete'] is False
    for row in client.rows: row.update(state_code=1, reviewer_id=REVIEWERS)
    client.refs = [reference(row) for row in client.rows[1:]]
    assert main(check) == 0
    checked = json.loads(capsys.readouterr().out)
    assert checked['complete'] is True and checked['assigned'] == 3
    assert checked['platform_writes'] == 0


@pytest.fixture
def private_repo(tmp_path):
    import subprocess
    subprocess.run(['git', 'init', '-q', str(tmp_path)], check=True)
    (tmp_path / '.gitignore').write_text('cases/*\n')
    return tmp_path
