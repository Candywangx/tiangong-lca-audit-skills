import csv
import json
from pathlib import Path
import subprocess

import pytest

from tiangong_audit.cli import main
from tiangong_audit import expert_commands


@pytest.fixture
def private_repo(tmp_path):
    subprocess.run(['git', 'init', '-q', str(tmp_path)], check=True)
    (tmp_path / '.gitignore').write_text('cases/*\n')
    return tmp_path


def roster_file(root):
    source = root / 'source.csv'
    with source.open('w', encoding='utf-8-sig', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(['姓名', '单位名称', '是否入库', '电子邮箱', '评审领域', 'LCA/碳足迹领域主要经验'])
        writer.writerow(['虚构甲', '测试机构', '是', 'alpha@example.test', '基础金属', '炼钢生命周期评价'])
    return source


def test_import_defaults_to_local_only_and_redacts_console(private_repo, capsys):
    source = roster_file(private_repo); directory = private_repo / 'cases/expert-directory'
    args = ['experts', 'import', '--csv', str(source), '--directory', str(directory)]
    assert main(args) == 0
    first = json.loads(capsys.readouterr().out)
    assert first['rows'] == 1
    assert 'alpha@example.test' not in json.dumps(first)
    assert '虚构甲' not in json.dumps(first, ensure_ascii=False)
    assert main(args) == 0
    assert len(list(directory.glob('roster.*.json'))) == 1
    assert len(list((directory / 'imports').glob('*.csv'))) == 1
    assert next((directory / 'imports').glob('*.csv')).read_bytes() == source.read_bytes()


def test_import_refuses_public_or_tracked_destination(private_repo, capsys):
    source = roster_file(private_repo)
    assert main(['experts','import','--csv',str(source),'--directory',str(private_repo/'docs')]) == 1
    assert not (private_repo/'docs').exists()
    directory = private_repo/'cases/expert-directory'; directory.mkdir(parents=True)
    (directory/'tracked.json').write_text('{}')
    subprocess.run(['git','-C',str(private_repo),'add','-f','cases/expert-directory/tracked.json'],check=True)
    assert main(['experts','import','--csv',str(source),'--directory',str(directory)]) == 1
    assert not list(directory.glob('roster.*.json'))


def test_bind_forces_readonly_and_keeps_partial_identity_gaps(private_repo, monkeypatch, capsys):
    directory = private_repo/'cases/expert-directory'
    assert main(['experts','import','--csv',str(roster_file(private_repo)),'--directory',str(directory)]) == 0
    imported = json.loads(capsys.readouterr().out)
    class Client:
        supabase_url = 'https://example.test'
        def __init__(self, **kwargs):
            assert kwargs == {'account_role':'admin', 'allow_writes':False}
    class API:
        def __init__(self, client): pass
        def get_all_members(self):
            return [{'user_id':'user-1','email':'alpha@example.test','role':'review-member','total_count':1}]
        def read_users(self, ids): return []
    monkeypatch.setattr(expert_commands, 'TiangongAPIClient', Client)
    monkeypatch.setattr(expert_commands, 'ExpertAPI', API)
    assert main(['experts','bind','--roster',imported['roster_path'],'--directory',str(directory)]) == 0
    summary = json.loads(capsys.readouterr().out)
    assert summary['eligible'] == 0
    assert summary['binding_statuses']['identity_missing'] == 1
    assert 'alpha@example.test' not in json.dumps(summary)


def test_expert_cli_has_no_assignment_or_execute_entrypoint():
    with pytest.raises(SystemExit):
        main(['experts','assign'])


def test_import_refuses_symlink_escape(private_repo):
    directory = private_repo/'cases/expert-directory'; directory.mkdir(parents=True)
    public = private_repo/'public'; public.mkdir()
    (directory/'imports').symlink_to(public, target_is_directory=True)
    assert main(['experts','import','--csv',str(roster_file(private_repo)),'--directory',str(directory)]) == 1
    assert not list(public.iterdir())


def test_import_requires_actual_csv_path_to_be_ignored(private_repo):
    (private_repo/'.gitignore').write_text('cases/*\n!cases/expert-directory/\ncases/expert-directory/*.json\ncases/expert-directory/imports/*.json\n')
    directory = private_repo/'cases/expert-directory'
    assert main(['experts','import','--csv',str(roster_file(private_repo)),'--directory',str(directory)]) == 1
    assert not list(directory.rglob('*.csv'))


def test_private_failure_does_not_print_source_details(private_repo, monkeypatch, capsys):
    directory = private_repo/'cases/expert-directory'
    def broken(path): raise ValueError('private alpha@example.test')
    monkeypatch.setattr(expert_commands, 'import_roster', broken)
    assert main(['experts','import','--csv',str(roster_file(private_repo)),'--directory',str(directory)]) == 1
    assert 'alpha@example.test' not in capsys.readouterr().err


def test_prepare_preserves_source_paths_and_reference_product(private_repo, capsys):
    directory = private_repo/'cases/expert-directory'; directory.mkdir(parents=True)
    bindings = directory/'bindings.json'
    bindings.write_text(json.dumps({'records':[{'expert_id':'E1','eligible':True,'admission':'included',
        'binding':{'status':'bound'},'fields_text':'建筑产品','experience_text':'木质板材评价'}]}))
    case = private_repo/'cases/active/example'; (case/'snapshots').mkdir(parents=True)
    (case/'case.json').write_text(json.dumps({'review_id':'example','name_zh':'板材'}))
    snapshot = {'processDataSet': {'processInformation':{'quantitativeReference':{'referenceToReferenceFlow':'1'}},
                                 'exchanges': {'exchange': {'@dataSetInternalID':'1','exchangeDirection':'Output',
                                 'referenceToFlow': {'common:shortDescription':'测试木质板材'}}}}}
    (case/'snapshots/dataset.raw.json').write_text(json.dumps(snapshot))
    assert main(['experts','prepare','--bindings',str(bindings),'--case-dir',str(case),'--directory',str(directory)]) == 0
    summary = json.loads(capsys.readouterr().out)
    prepared = json.loads(Path(summary['context_path']).read_text())
    assert len(prepared['binding_sha256']) == 64
    assert prepared['datasets'][0]['case_id'] == 'example'
    assert any(row['text'] == '测试木质板材' for row in prepared['datasets'][0]['evidence'])
    assert (directory/prepared['datasets'][0]['snapshot_ref']).is_file()


def test_import_rejects_source_changed_between_parsing_and_archive(private_repo, monkeypatch):
    source = roster_file(private_repo); directory = private_repo/'cases/expert-directory'
    original = expert_commands.import_roster
    def changed(path):
        parsed = original(path)
        Path(path).write_text('changed during spreadsheet save')
        return parsed
    monkeypatch.setattr(expert_commands, 'import_roster', changed)
    assert main(['experts','import','--csv',str(source),'--directory',str(directory)]) == 1
    assert not list(directory.rglob('*.csv'))
    assert not list(directory.glob('roster.*.json'))


def test_prepare_excludes_stale_linked_processes_and_keeps_reference_gaps(private_repo, capsys):
    directory = private_repo/'cases/expert-directory'; directory.mkdir(parents=True)
    bindings = directory/'bindings.json'; bindings.write_text('{"records": []}')
    case = private_repo/'cases/active/model'; linked = case/'snapshots/linked-processes'; linked.mkdir(parents=True)
    (case/'case.json').write_text(json.dumps({'review_id':'model'}))
    refs = [{'referenceToProcess': {'@type':'process data set','@refObjectId':key,'@version':'01.00.000'}}
            for key in ('current', 'missing')]
    (case/'snapshots/dataset.raw.json').write_text(json.dumps({'lifeCycleModelDataSet': {
        'lifeCycleModelInformation': {'technology': {'processes': {'processInstance':refs}}}}}))
    for identifier, version, name in [('current','01.00.000','当前过程'), ('current','00.00.001','旧版本过程'), ('old','01.00.000','无关历史过程')]:
        (linked/f'{identifier}-{version}.json').write_text(json.dumps({'id':identifier,'version':version,
            'json':{'processDataSet':{'processInformation':{'dataSetInformation':{'name':name}}}}}))
    assert main(['experts','prepare','--bindings',str(bindings),'--case-dir',str(case),'--directory',str(directory)]) == 0
    summary = json.loads(capsys.readouterr().out)
    prepared = json.loads(Path(summary['context_path']).read_text())['datasets'][0]
    assert len(prepared['linked_snapshots']) == 1
    text = json.dumps(prepared, ensure_ascii=False)
    assert '当前过程' in text and '无关历史过程' not in text and '旧版本过程' not in text
    assert any(gap['process_id'] == 'missing' for gap in prepared['linked_reference_gaps'])
