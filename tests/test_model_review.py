from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import shutil

import pytest

from tiangong_audit.case_store import CaseStore
from tiangong_audit.contracts.agent_review import new_agent_findings_template, required_rule_ids
from tiangong_audit.workflows.semantic_review import semantic_review
from tiangong_audit.workflows.title_duplicate import check_title_duplicates

ROOT = Path(__file__).resolve().parents[1]
VERSION = '01.00.000'


def write(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2))


def digest(payload):
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def process_row(process_id='p1'):
    return {'id': process_id, 'version': VERSION, 'json': {'processDataSet': {
        'processInformation': {
            'dataSetInformation': {'common:UUID': process_id},
            'quantitativeReference': {'@type': 'Reference flow(s)', 'referenceToReferenceFlow': '1'},
        },
        'administrativeInformation': {'publicationAndOwnership': {'common:dataSetVersion': VERSION}},
        'exchanges': {'exchange': {'@dataSetInternalID': '1', 'exchangeDirection': 'Output',
            'meanAmount': '1', 'referenceToFlowDataSet': {'@refObjectId': 'flow-1'}}},
    }}}


def process_report(row):
    total = len(required_rule_ids('process'))
    return {'schema_version': 'tiangong-audit-semantic-review-v1', 'review_task_id': 'process-review',
        'dataset_id': row['id'], 'version': row['version'], 'dataset_type': 'process',
        'audit_scope': 'full-lca-semantic-review', 'dataset_snapshot_sha256': digest(row['json']),
        'conclusion': '通过', 'findings': [],
        'source_consistency': {'conclusion': '一致'}, 'rule_compliance': {'conclusion': '符合规则'},
        'audit_completeness': {'complete': True, 'agent_review_valid': True, 'source_checks_present': True,
            'source_checks_valid': True, 'missing': []},
        'agent_review': {'present': True, 'valid': True, 'required_total': total, 'required_covered': total,
            'validation_error_count': 0}}


def model_raw(nodes=None):
    node = {'@dataSetInternalID': 'n1', '@multiplicationFactor': '1',
        'referenceToProcess': {'@type': 'process data set', '@refObjectId': 'p1', '@version': VERSION}}
    return {'lifeCycleModelDataSet': {'lifeCycleModelInformation': {
        'dataSetInformation': {'common:UUID': 'm1', 'name': {'baseName': [{'@xml:lang': 'zh', '#text': '产品模型'}]}},
        'quantitativeReference': {'referenceToReferenceProcess': 'n1'},
        'technology': {'processes': {'processInstance': nodes if nodes is not None else node}},
    }}}


def case(tmp_path, raw=None):
    skill = tmp_path / 'skill/tiangong-lca-audit'
    shutil.copytree(ROOT / 'skill/tiangong-lca-audit/references', skill / 'references')
    shutil.copytree(ROOT / 'skill/tiangong-lca-audit/rules', skill / 'rules')
    shutil.copyfile(ROOT / 'skill/tiangong-lca-audit/SKILL.md', skill / 'SKILL.md')
    store = CaseStore(tmp_path / 'cases')
    manifest = store.create_case(review_id='model-review', batch_id='models', dataset_id='m1', version=VERSION,
        dataset_type='model', name_zh='产品模型')
    target = tmp_path / 'cases' / manifest.case_dir
    save_model(target, raw or model_raw())
    write(target / 'source-checks/claims.json', {'dataset.name.zh': '产品模型'})
    write(target / 'sources/source-001/manifest.json', {'ref': {'source_id': 's1'}, 'status': 'extracted', 'extracted_text_path': 'extracted.md'})
    (target / 'sources/source-001/extracted.md').write_text('# Page 1\n产品模型与关联生产过程。')
    write(target / 'source-checks/checks.json', [{'field': 'dataset.name.zh', 'dataset_value': '产品模型',
        'status': 'matched', 'source_ref_id': 's1', 'evidence': '产品模型', 'page': 1}])
    agent = new_agent_findings_template(review_id='model-review', dataset_id='m1', dataset_type='model')
    agent['reviewed_by'] = 'agent'
    for review in agent['rule_reviews']:
        review.update(verdict='pass', evidence='模型目标、结构和过程报告可核对。', judgment='逐项核查一致。', evidence_refs=['snapshots/dataset.raw.json'])
    write(target / 'agent-review/agent-findings.json', agent)
    install_process(target)
    return store, target


def save_model(target, raw):
    row = {'id': 'm1', 'version': VERSION, 'json': raw}
    class API:
        def search_title(self, *args):
            return [row]
    write(target / 'snapshots/dataset.raw.json', raw)
    write(target / 'snapshots/dataset-row.json', row)
    write(target / 'snapshots/title-duplicate-check.json', check_title_duplicates(row, 'model', API()))
    write(target / 'snapshots/model-linked-process-refs.json', [{'process_id': 'p1', 'version': VERSION}])


def install_process(target, process_id='p1'):
    row = process_row(process_id)
    write(target / f'snapshots/linked-processes/{process_id}.json', row)
    write(target / f'agent-review/process-reports/{process_id}.json', process_report(row))
    write(target / 'snapshots/unit-evidence.json', {'reference_unit': 'kg', 'basis': '已核查关联流的质量参考属性及单位组。'})
    path = target / 'agent-review/model-process-audits.json'
    index = json.loads(path.read_text()) if path.exists() else {'schema_version': 'tiangong-audit-model-process-audits-v1', 'audit_scope': 'full-lca-semantic-review', 'process_audits': []}
    index['process_audits'].append({'process_id': process_id, 'version': VERSION,
        'snapshot_path': f'snapshots/linked-processes/{process_id}.json', 'snapshot_sha256': digest(row['json']),
        'report_path': f'agent-review/process-reports/{process_id}.json',
        'reference_unit': {'unit': 'kg', 'evidence_refs': ['snapshots/unit-evidence.json#/reference_unit']}})
    write(path, index)


def report(tmp_path, store, target):
    semantic_review('model-review', root=tmp_path, batch_id='models', case_store=store)
    return json.loads((target / 'reports/semantic-review.json').read_text())


def test_model_name_and_linked_ids_are_insufficient_even_with_all_agent_passes(tmp_path):
    raw = model_raw()
    info = raw['lifeCycleModelDataSet']['lifeCycleModelInformation']
    info.pop('quantitativeReference')
    info.pop('technology')
    store, target = case(tmp_path, raw)
    result = report(tmp_path, store, target)
    assert result['conclusion'] == '信息不足'
    assert not result['audit_completeness']['complete']
    assert any(f['rule_id'] == 'model.core.input_coverage' for f in result['findings'])


@pytest.mark.parametrize('damage', ['missing_snapshot', 'missing_report', 'wrong_report_version', 'wrong_snapshot_id', 'wrong_hash', 'wrong_report_hash', 'bare_complete', 'partial_report', 'incomplete_report'])
def test_model_requires_bound_complete_key_process_audits(tmp_path, damage):
    store, target = case(tmp_path)
    snapshot_path = target / 'snapshots/linked-processes/p1.json'
    report_path = target / 'agent-review/process-reports/p1.json'
    index_path = target / 'agent-review/model-process-audits.json'
    audit = json.loads(report_path.read_text())
    if damage == 'missing_snapshot': snapshot_path.unlink()
    elif damage == 'missing_report': report_path.unlink()
    elif damage == 'wrong_report_version': audit['version'] = '02.00.000'
    elif damage == 'wrong_snapshot_id':
        row = json.loads(snapshot_path.read_text()); row['id'] = 'another'; write(snapshot_path, row)
    elif damage == 'wrong_hash':
        index = json.loads(index_path.read_text()); index['process_audits'][0]['snapshot_sha256'] = '0' * 64; write(index_path, index)
    elif damage == 'wrong_report_hash': audit['dataset_snapshot_sha256'] = '0' * 64
    elif damage == 'bare_complete': audit = {'audit_completeness': {'complete': True}, 'agent_review': {'valid': True}}
    elif damage == 'partial_report': audit['audit_scope'] = 'partial'
    else: audit['audit_completeness']['complete'] = False
    if report_path.exists(): write(report_path, audit)
    result = report(tmp_path, store, target)
    assert result['conclusion'] == '信息不足'
    assert not result['audit_completeness']['complete']
    assert any(f['rule_id'] == 'model.linked_process.audit' for f in result['findings'])


def test_single_real_tidas_node_without_connections_can_pass(tmp_path):
    store, target = case(tmp_path)
    result = report(tmp_path, store, target)
    assert result['conclusion'] == '通过'
    assert result['audit_completeness']['complete']
    assert result['dataset_snapshot_sha256'] == digest(model_raw())


def two_nodes():
    first = model_raw()['lifeCycleModelDataSet']['lifeCycleModelInformation']['technology']['processes']['processInstance']
    second = copy.deepcopy(first)
    second['@dataSetInternalID'] = 'n2'
    first['connections'] = {'outputExchange': {'@flowUUID': 'flow-out', 'downstreamProcess': {'@id': 'n2', '@flowUUID': 'flow-in'}}}
    return [first, second]


def test_same_process_uuid_in_distinct_instances_and_different_link_flow_uuids_are_legal(tmp_path):
    store, target = case(tmp_path, model_raw(two_nodes()))
    result = report(tmp_path, store, target)
    assert result['conclusion'] == '通过'
    assert result['audit_completeness']['complete']


@pytest.mark.parametrize('damage', ['dangling_reference', 'duplicate_instance', 'dangling_downstream'])
def test_provable_model_structure_errors_are_blocking(tmp_path, damage):
    nodes = two_nodes()
    raw = model_raw(nodes)
    if damage == 'dangling_reference': raw['lifeCycleModelDataSet']['lifeCycleModelInformation']['quantitativeReference']['referenceToReferenceProcess'] = 'n404'
    elif damage == 'duplicate_instance': nodes[1]['@dataSetInternalID'] = 'n1'
    else: nodes[0]['connections']['outputExchange']['downstreamProcess']['@id'] = 'n404'
    store, target = case(tmp_path, raw)
    result = report(tmp_path, store, target)
    assert result['conclusion'] == '不通过'
    assert any(f['rule_id'] == 'model.structure.connectivity' and f['severity'] == 'blocking' for f in result['findings'])


def test_missing_one_of_two_processes_is_not_hidden_by_another_present_snapshot(tmp_path):
    nodes = two_nodes()
    nodes[1]['referenceToProcess']['@refObjectId'] = 'p2'
    store, target = case(tmp_path, model_raw(nodes))
    result = report(tmp_path, store, target)
    assert result['conclusion'] == '信息不足'
    assert not result['audit_completeness']['complete']


@pytest.mark.parametrize('factor', ['x * 2', '0', '-1'])
def test_complex_or_semantically_uncertain_scaling_needs_manual_review_not_automatic_rejection(tmp_path, factor):
    raw = model_raw(); raw['lifeCycleModelDataSet']['lifeCycleModelInformation']['technology']['processes']['processInstance']['@multiplicationFactor'] = factor
    store, target = case(tmp_path, raw)
    result = report(tmp_path, store, target)
    assert result['conclusion'] == '需人工确认'
    assert not result['audit_completeness']['complete']


def test_linked_precheck_blocker_does_not_automatically_propagate_to_model(tmp_path):
    store, target = case(tmp_path)
    write(target / 'precheck/linked-processes/p1.precheck.json', {'dataset': {'id': 'p1'}, 'summary': {'blocking': 1}})
    result = report(tmp_path, store, target)
    assert result['conclusion'] == '需人工确认'
    assert not any(f['severity'] == 'blocking' for f in result['findings'])


def test_partial_model_review_never_counts_as_complete(tmp_path):
    store, target = case(tmp_path)
    path = target / 'agent-review/model-process-audits.json'
    index = json.loads(path.read_text()); index['audit_scope'] = 'partial'; write(path, index)
    result = report(tmp_path, store, target)
    assert result['audit_scope'] == 'partial'
    assert result['conclusion'] != '通过'
    assert not result['audit_completeness']['complete']


def test_two_different_key_processes_with_complete_reports_can_pass(tmp_path):
    nodes = two_nodes(); nodes[1]['referenceToProcess']['@refObjectId'] = 'p2'
    store, target = case(tmp_path, model_raw(nodes)); install_process(target, 'p2')
    result = report(tmp_path, store, target)
    assert result['conclusion'] == '通过'
    assert result['audit_completeness']['model']['audited_process_count'] == 2


@pytest.mark.parametrize('damage', ['missing_factor', 'missing_unit', 'dangling_process_reference'])
def test_reference_quantity_needs_actual_process_amount_and_unit_evidence(tmp_path, damage):
    raw = model_raw()
    if damage == 'missing_factor': raw['lifeCycleModelDataSet']['lifeCycleModelInformation']['technology']['processes']['processInstance'].pop('@multiplicationFactor')
    store, target = case(tmp_path, raw)
    if damage == 'missing_unit':
        path = target / 'agent-review/model-process-audits.json'; index = json.loads(path.read_text()); index['process_audits'][0].pop('reference_unit'); write(path, index)
    elif damage == 'dangling_process_reference':
        path = target / 'snapshots/linked-processes/p1.json'; row = json.loads(path.read_text()); row['json']['processDataSet']['processInformation']['quantitativeReference']['referenceToReferenceFlow'] = '404'; write(path, row)
        index_path = target / 'agent-review/model-process-audits.json'; index = json.loads(index_path.read_text()); index['process_audits'][0]['snapshot_sha256'] = digest(row['json']); write(index_path, index)
        write(target / 'agent-review/process-reports/p1.json', process_report(row))
    result = report(tmp_path, store, target)
    assert result['conclusion'] == '信息不足'
    assert not result['audit_completeness']['complete']


def test_repeated_uuid_before_reference_instance_does_not_skip_quantity_check(tmp_path):
    nodes = two_nodes(); raw = model_raw(nodes)
    raw['lifeCycleModelDataSet']['lifeCycleModelInformation']['quantitativeReference']['referenceToReferenceProcess'] = 'n2'
    store, target = case(tmp_path, raw)
    path = target / 'agent-review/model-process-audits.json'; index = json.loads(path.read_text()); index['process_audits'][0].pop('reference_unit'); write(path, index)
    result = report(tmp_path, store, target)
    assert result['conclusion'] == '信息不足'


def test_legacy_report_requires_matching_explicit_context_snapshot(tmp_path):
    store, target = case(tmp_path)
    report_path = target / 'agent-review/process-reports/p1.json'; audit = json.loads(report_path.read_text()); audit.pop('dataset_snapshot_sha256'); write(report_path, audit)
    result = report(tmp_path, store, target)
    assert result['conclusion'] == '信息不足'
    context = {'schema_version': 'tiangong-audit-semantic-context-v1', 'review_id': 'process-review',
        'dataset_id': 'p1', 'version': VERSION, 'dataset_raw': process_row()['json']}
    write(target / 'agent-review/process-reports/p1.context.json', context)
    index_path = target / 'agent-review/model-process-audits.json'; index = json.loads(index_path.read_text()); index['process_audits'][0]['context_path'] = 'agent-review/process-reports/p1.context.json'; write(index_path, index)
    assert report(tmp_path, store, target)['conclusion'] == '通过'
    context['version'] = '02.00.000'; write(target / 'agent-review/process-reports/p1.context.json', context)
    assert report(tmp_path, store, target)['conclusion'] == '信息不足'


@pytest.mark.parametrize('reference_role', [False, True])
def test_evidenced_nonkey_role_can_exempt_other_instance_but_never_reference(tmp_path, reference_role):
    nodes = two_nodes(); nodes[1]['referenceToProcess']['@refObjectId'] = 'p2'
    store, target = case(tmp_path, model_raw(nodes))
    index_path = target / 'agent-review/model-process-audits.json'; index = json.loads(index_path.read_text())
    index['node_roles'] = [{'instance_id': 'n1' if reference_role else 'n2', 'is_key': False,
        'reason': '已核对这是边界明确排除的演示节点，未参与目标结果。', 'evidence_refs': ['snapshots/dataset.raw.json']}]
    if reference_role:
        index['process_audits'] = []
    else:
        install_process(target, 'p2')
        second = json.loads(index_path.read_text())['process_audits'][-1]
        second.pop('report_path')
        index['process_audits'].append(second)
    write(index_path, index)
    result = report(tmp_path, store, target)
    assert result['conclusion'] == ('信息不足' if reference_role else '通过')
    assert result['audit_completeness']['complete'] is (not reference_role)


def test_model_source_unverified_core_claims_cannot_count_as_complete(tmp_path):
    store, target = case(tmp_path)
    write(target / 'source-checks/claims.json', {'dataset.name.zh': '产品模型', 'process.time.reference_year': '2024'})
    result = report(tmp_path, store, target)
    assert result['conclusion'] == '需人工确认'
    assert not result['audit_completeness']['complete']


def test_valid_agent_model_blocker_can_propagate_process_impact(tmp_path):
    store, target = case(tmp_path)
    write(target / 'precheck/linked-processes/p1.precheck.json', {'dataset': {'id': 'p1'}, 'summary': {'blocking': 1}})
    path = target / 'agent-review/agent-findings.json'; agent = json.loads(path.read_text())
    review = next(item for item in agent['rule_reviews'] if item['rule_id'] == 'model.linked_process.audit')
    review.update(verdict='fail', severity='blocking', evidence='参考过程缺少一项关键材料输入，目标产品制造模型因此低估该材料负荷。', judgment='该问题影响参考节点的模型目标清单。', suggestion='修正过程并重新核对模型目标清单。')
    write(path, agent)
    result = report(tmp_path, store, target)
    assert result['conclusion'] == '不通过'
    assert any(f['severity'] == 'blocking' and f['source'].startswith('agent-review') for f in result['findings'])


def test_multiple_key_nodes_without_any_connection_is_incomplete_structure(tmp_path):
    nodes = two_nodes(); nodes[0].pop('connections')
    store, target = case(tmp_path, model_raw(nodes))
    result = report(tmp_path, store, target)
    assert result['conclusion'] == '信息不足'
    assert not result['audit_completeness']['complete']


def test_alternative_self_consistent_old_snapshot_cannot_replace_current_materialized_process(tmp_path):
    store, target = case(tmp_path)
    old_row = process_row()
    old_row['json']['processDataSet']['exchanges']['exchange']['meanAmount'] = '2'
    write(target / 'agent-review/old-process.json', old_row)
    write(target / 'agent-review/old-report.json', process_report(old_row))
    path = target / 'agent-review/model-process-audits.json'; index = json.loads(path.read_text())
    entry = index['process_audits'][0]
    entry.update(snapshot_path='agent-review/old-process.json', snapshot_sha256=digest(old_row['json']), report_path='agent-review/old-report.json')
    write(path, index)
    result = report(tmp_path, store, target)
    assert result['conclusion'] == '信息不足'
    assert not result['audit_completeness']['complete']


@pytest.mark.parametrize('invalid_role', ['missing_reason', 'missing_refs', 'wrong_ref'])
def test_unverified_nonkey_role_never_suppresses_missing_process(tmp_path, invalid_role):
    nodes = two_nodes(); nodes[1]['referenceToProcess']['@refObjectId'] = 'p2'
    store, target = case(tmp_path, model_raw(nodes))
    path = target / 'agent-review/model-process-audits.json'; index = json.loads(path.read_text())
    role = {'instance_id': 'n2', 'is_key': False, 'reason': '有意排除的演示节点。', 'evidence_refs': ['snapshots/dataset.raw.json']}
    if invalid_role == 'missing_reason': role.pop('reason')
    elif invalid_role == 'missing_refs': role.pop('evidence_refs')
    else: role['evidence_refs'] = ['missing.json']
    index['node_roles'] = [role]; write(path, index)
    assert report(tmp_path, store, target)['conclusion'] == '信息不足'


def test_tidas_array_connection_forms_can_pass(tmp_path):
    nodes = two_nodes()
    output = nodes[0]['connections']['outputExchange']; output['downstreamProcess'] = [output['downstreamProcess']]
    nodes[0]['connections']['outputExchange'] = [output]
    store, target = case(tmp_path, model_raw(nodes))
    assert report(tmp_path, store, target)['conclusion'] == '通过'


def test_isolated_evidenced_nonkey_node_is_not_mechanically_blocking(tmp_path):
    nodes = two_nodes(); nodes[0].pop('connections'); nodes[1]['referenceToProcess']['@refObjectId'] = 'p2'
    store, target = case(tmp_path, model_raw(nodes))
    path = target / 'agent-review/model-process-audits.json'; index = json.loads(path.read_text())
    install_process(target, 'p2')
    second = json.loads(path.read_text())['process_audits'][-1]; second.pop('report_path'); index['process_audits'].append(second)
    index['node_roles'] = [{'instance_id': 'n2', 'is_key': False, 'reason': '边界明确排除的独立演示节点。', 'evidence_refs': ['snapshots/dataset.raw.json']}]
    write(path, index)
    assert report(tmp_path, store, target)['conclusion'] == '通过'


def test_json_ordered_api_snapshot_is_a_valid_current_process(tmp_path):
    store, target = case(tmp_path)
    path = target / 'snapshots/linked-processes/p1.json'; row = json.loads(path.read_text()); row['json_ordered'] = row.pop('json'); write(path, row)
    assert report(tmp_path, store, target)['conclusion'] == '通过'


@pytest.mark.parametrize('connections', ['not a graph', {}, {'outputExchange': []}, {'outputExchange': 'bad'}])
def test_malformed_connection_container_does_not_prove_multi_node_structure(tmp_path, connections):
    nodes = two_nodes(); nodes[0]['connections'] = connections
    store, target = case(tmp_path, model_raw(nodes))
    assert report(tmp_path, store, target)['conclusion'] == '信息不足'


def test_nonkey_role_still_needs_basic_process_snapshot(tmp_path):
    nodes = two_nodes(); nodes[1]['referenceToProcess']['@refObjectId'] = 'p2'
    store, target = case(tmp_path, model_raw(nodes))
    path = target / 'agent-review/model-process-audits.json'; index = json.loads(path.read_text())
    index['node_roles'] = [{'instance_id': 'n2', 'is_key': False, 'reason': '非关键演示实例。', 'evidence_refs': ['snapshots/dataset.raw.json']}]
    write(path, index)
    assert report(tmp_path, store, target)['conclusion'] == '信息不足'


def test_missing_current_snapshot_cannot_be_replaced_by_alternative_old_snapshot(tmp_path):
    store, target = case(tmp_path)
    row = process_row(); write(target / 'agent-review/old-process.json', row)
    (target / 'snapshots/linked-processes/p1.json').unlink()
    path = target / 'agent-review/model-process-audits.json'; index = json.loads(path.read_text()); index['process_audits'][0]['snapshot_path'] = 'agent-review/old-process.json'; write(path, index)
    assert report(tmp_path, store, target)['conclusion'] == '信息不足'


def test_verified_structure_blockers_remain_in_platform_opinions(tmp_path):
    nodes = two_nodes(); nodes[1]['@dataSetInternalID'] = 'n1'
    store, target = case(tmp_path, model_raw(nodes))
    result = report(tmp_path, store, target)
    opinion = (target / 'reports/semantic-review.md').read_text().split('## 平台退回意见', 1)[1]
    assert result['conclusion'] == '不通过'
    assert '【需修改】' in opinion
    assert '实例ID重复' in opinion
    blocker = next(f for f in result['findings'] if '实例ID重复' in f['evidence'])
    assert blocker['platform_actionable'] is True


def test_raw_tidas_current_snapshot_identity_is_recognized(tmp_path):
    store, target = case(tmp_path)
    path = target / 'snapshots/linked-processes/p1.json'; row = json.loads(path.read_text()); write(path, row['json'])
    assert report(tmp_path, store, target)['conclusion'] == '通过'
