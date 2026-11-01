import json
from pathlib import Path

from tiangong_audit.cli import main
from tiangong_audit.experts.roles import role_input_digest
from test_expert_cli import private_repo


def setup(private_repo):
    directory = private_repo / 'cases/expert-directory'; directory.mkdir(parents=True)
    expert = {'expert_id':'expert-fake','eligible':True,'admission':'included','binding':{'status':'bound'},
              'fields_text':'建材','experience_text':'参与建材LCA审核、数据库开发'}
    bindings = directory/'bindings.json'; bindings.write_text(json.dumps({'records':[expert]}))
    roles = directory/'roles.json'
    payload = {'schema_version':'tiangong-expert-roles-v1','input_sha256':role_input_digest([expert]),
               'profiles':[{'expert_id':expert['expert_id'],'roles':[
                   {'role':role,'support':'supported','scope':'有资料支持的有限职责',
                    'evidence':[{'field':'experience_text','quote':'参与建材LCA审核、数据库开发'}],
                    'limits':['具体任务适配仍需人工核对']} for role in ('domain','method','data_model')]}]}
    roles.write_text(json.dumps(payload))
    case = private_repo/'cases/active/test'; (case/'snapshots').mkdir(parents=True)
    (case/'case.json').write_text(json.dumps({'review_id':'test'}))
    (case/'snapshots/dataset.raw.json').write_text(json.dumps({'processDataSet': {'processInformation': {'dataSetInformation':{'name':'测试建材'}}}}))
    return directory, bindings, roles, case


def test_roles_validate_and_prepare_v2(private_repo, capsys):
    directory,bindings,roles,case=setup(private_repo)
    assert main(['experts','roles-validate','--bindings',str(bindings),'--roles',str(roles),'--directory',str(directory)]) == 0
    checked=json.loads(capsys.readouterr().out)
    assert checked['valid'] and checked['platform_writes']==0
    assert main(['experts','prepare','--bindings',str(bindings),'--roles',str(roles),'--case-dir',str(case),'--directory',str(directory)]) == 0
    context=json.loads(Path(json.loads(capsys.readouterr().out)['context_path']).read_text())
    assert context['schema_version']=='tiangong-expert-context-v2'
    assert context['role_profiles']['profiles'][0]['expert_id']=='expert-fake'


def test_prepare_rejects_stale_role_text(private_repo):
    directory,bindings,roles,case=setup(private_repo)
    data=json.loads(bindings.read_text());data['records'][0]['experience_text']='专业资料已更新'
    bindings.write_text(json.dumps(data))
    assert main(['experts','prepare','--bindings',str(bindings),'--roles',str(roles),'--case-dir',str(case),'--directory',str(directory)]) == 1
    assert not list(directory.glob('context.*.json'))


def test_role_template_is_pending_and_never_validated_as_finished(private_repo,capsys):
    directory,bindings,roles,case=setup(private_repo)
    assert main(['experts','roles-template','--bindings',str(bindings),'--directory',str(directory)]) == 0
    output=json.loads(capsys.readouterr().out)
    assert output['expert_count']==1
    assert main(['experts','roles-validate','--bindings',str(bindings),'--roles',output['template_path'],'--directory',str(directory)]) == 1
    assert not json.loads(capsys.readouterr().out)['valid']
