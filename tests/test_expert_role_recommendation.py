import pytest

from tiangong_audit.experts.recommendation import context_digest, validate_recommendations
from tiangong_audit.experts.roles import role_input_digest


def context(dataset_type='process'):
    source = [
        {'expert_id': 'E1', 'eligible': True, 'fields_text': '基础金属', 'experience_text': '转炉生产工艺审核'},
        {'expert_id': 'E2', 'eligible': True, 'fields_text': '基础金属', 'experience_text': '炼钢工艺与数据建模审核'},
        {'expert_id': 'E3', 'eligible': True, 'fields_text': '化工', 'experience_text': '化工LCA功能单位、系统边界及分配方法评估'},
    ]
    profiles = []
    for expert in source:
        profiles.append({'expert_id': expert['expert_id'], 'roles': [
            {'role': role, 'support': 'supported', 'scope': '限所引履历覆盖内容',
             'evidence': [{'field': 'experience_text', 'quote': expert['experience_text']}], 'limits': []}
            for role in ('domain', 'method', 'data_model')]})
    # Method expertise can cross industries without claiming direct steel experience.
    profiles[2]['roles'][0].update(support='insufficient', evidence=[], limits=['无钢铁工艺经历'])
    return {'schema_version': 'tiangong-expert-context-v2', 'binding_sha256': '1' * 64,
            'experts': source,
            'role_profiles': {'schema_version': 'tiangong-expert-roles-v1',
                              'input_sha256': role_input_digest(source), 'profiles': profiles},
            'datasets': [{'case_id': 'B01', 'dataset_type': dataset_type,
                          'evidence': [{'ref': '/technology', 'text': '转炉粗钢生产；系统边界与数据集连接'}]}]}


def result(bundle):
    roles = ['domain', 'domain', 'method'] if bundle['datasets'][0]['dataset_type'] == 'process' else ['domain', 'data_model', 'method']
    return {'schema_version': 'tiangong-expert-recommendation-v2', 'input_sha256': context_digest(bundle),
            'cases': [{'case_id': 'B01', 'status': 'proposed', 'gaps': [],
                       'team_rationale': '由工艺专家与方法专家分工互补审核',
                       'selected': [
                           {'expert_id': expert['expert_id'], 'primary_role': role,
                            'responsibility': '审核所分配的工艺、方法或建模问题', 'suitability': 'supported',
                            'reason': '履历有对应职责经历',
                            'expert_evidence': [{'field': 'experience_text', 'quote': expert['experience_text']}],
                            'dataset_evidence': [{'ref': '/technology', 'quote': '转炉粗钢生产'}]}
                           for expert, role in zip(bundle['experts'], roles)]}]}


def rebind(bundle, proposal):
    proposal['input_sha256'] = context_digest(bundle)


def test_process_team_accepts_cross_industry_method_expert_and_reports_declarations():
    bundle = context(); checked = validate_recommendations(bundle, result(bundle))
    assert checked['valid'], checked['errors']
    assert checked['semantic_accuracy_verified'] is False
    assert checked['assignment_authorized'] is False
    assert checked['live_identity_rechecked'] is False
    diagnostic = checked['case_diagnostics'][0]
    assert diagnostic['declared_composition'] == {'domain': 2, 'method': 1, 'data_model': 0}
    assert diagnostic['declared_coverage'] == {'required': ['domain', 'method'],
                                               'present': ['domain', 'method'], 'missing': []}
    assert diagnostic['coverage_basis'] == 'declared_primary_roles'


def test_model_team_requires_one_each_of_domain_method_and_data_model():
    bundle = context('model'); proposal = result(bundle)
    assert validate_recommendations(bundle, proposal)['valid']
    proposal['cases'][0]['selected'][1]['primary_role'] = 'domain'
    assert not validate_recommendations(bundle, proposal)['valid']


def test_method_only_team_cannot_claim_complete_panel():
    bundle = context(); proposal = result(bundle)
    for candidate in proposal['cases'][0]['selected']:
        candidate['primary_role'] = 'method'
    proposal['cases'][0]['composition_exception'] = '方法工作量较大'
    assert not validate_recommendations(bundle, proposal)['valid']
    proposal['cases'][0].update(status='needs_context', gaps=['缺少核心工艺专家'])
    assert validate_recommendations(bundle, proposal)['valid']


def test_process_nondefault_composition_requires_explanation_and_minimum_coverage():
    bundle = context(); proposal = result(bundle)
    proposal['cases'][0]['selected'][1]['primary_role'] = 'data_model'
    assert not validate_recommendations(bundle, proposal)['valid']
    proposal['cases'][0]['composition_exception'] = '过程含复杂数据模型，增加建模职责'
    assert validate_recommendations(bundle, proposal)['valid']


def test_supported_profile_can_have_conditional_case_fit_only_with_explicit_gap():
    bundle = context(); proposal = result(bundle)
    proposal['cases'][0]['selected'][2]['suitability'] = 'conditional'
    assert not validate_recommendations(bundle, proposal)['valid']
    proposal['cases'][0]['status'] = 'needs_context'
    assert not validate_recommendations(bundle, proposal)['valid']
    proposal['cases'][0]['gaps'] = ['需确认跨行业分配方法经验是否适用']
    assert validate_recommendations(bundle, proposal)['valid']


def test_conditional_role_profile_cannot_be_upgraded_by_suitability():
    bundle = context(); profile = bundle['role_profiles']['profiles'][2]['roles'][1]
    profile.update(support='conditional', limits=['需确认边界范围'])
    proposal = result(bundle)
    proposal['cases'][0].update(status='needs_context', gaps=['方法经验适用性需确认'])
    assert not validate_recommendations(bundle, proposal)['valid']
    proposal['cases'][0]['selected'][2]['suitability'] = 'conditional'
    assert validate_recommendations(bundle, proposal)['valid']
    proposal['cases'][0]['status'] = 'proposed'
    assert not validate_recommendations(bundle, proposal)['valid']


def test_insufficient_profile_never_supports_assigned_role():
    bundle = context(); proposal = result(bundle)
    proposal['cases'][0]['selected'][2]['primary_role'] = 'domain'
    proposal['cases'][0].update(status='needs_context', gaps=['尚待补充工艺履历'])
    assert not validate_recommendations(bundle, proposal)['valid']


def test_short_panel_uses_insufficient_candidates_and_explains_gap():
    bundle = context(); proposal = result(bundle)
    proposal['cases'][0]['selected'].pop()
    assert not validate_recommendations(bundle, proposal)['valid']
    proposal['cases'][0].update(status='insufficient_candidates', gaps=['缺少方法专家'])
    assert validate_recommendations(bundle, proposal)['valid']


@pytest.mark.parametrize('mutation', [
    lambda b, r: r['cases'][0].update(team_rationale=''),
    lambda b, r: r['cases'][0]['selected'][0].update(primary_role=['domain', 'method']),
    lambda b, r: r['cases'][0]['selected'][0].update(primary_role='all_industries'),
    lambda b, r: r['cases'][0]['selected'][0].update(responsibility=''),
    lambda b, r: r['cases'][0]['selected'][0].update(suitability='insufficient'),
    lambda b, r: r['cases'][0]['selected'][1].update(expert_id='E1'),
    lambda b, r: r['cases'][0]['selected'][0].update(expert_evidence=[{'field': 'experience_text', 'quote': '捏造经历'}]),
    lambda b, r: b['role_profiles'].update(input_sha256='0' * 64),
    lambda b, r: b['role_profiles'].update(profiles=[]),
    lambda b, r: b.update(role_profiles=None),
    lambda b, r: b['role_profiles']['profiles'][0].update(roles=[None]),
    lambda b, r: b['datasets'][0].update(dataset_type='unknown'),
])
def test_v2_rejects_malformed_role_assignment_and_stale_or_bad_profiles(mutation):
    bundle = context(); proposal = result(bundle)
    mutation(bundle, proposal); rebind(bundle, proposal)
    checked = validate_recommendations(bundle, proposal)
    assert not checked['valid']


@pytest.mark.parametrize('context_version,result_version', [
    ('v1', 'v2'), ('v2', 'v1'), ('v1', 'v1')])
def test_role_contract_cannot_be_downgraded_or_mix_versions(context_version, result_version):
    bundle = context(); proposal = result(bundle)
    bundle['schema_version'] = 'tiangong-expert-context-' + context_version
    proposal['schema_version'] = 'tiangong-expert-recommendation-' + result_version
    rebind(bundle, proposal)
    assert not validate_recommendations(bundle, proposal)['valid']


def test_v1_result_cannot_smuggle_role_assignments_after_profiles_are_removed():
    bundle = context(); proposal = result(bundle)
    bundle.pop('role_profiles')
    bundle['schema_version'] = 'tiangong-expert-context-v1'
    proposal['schema_version'] = 'tiangong-expert-recommendation-v1'
    rebind(bundle, proposal)
    assert not validate_recommendations(bundle, proposal)['valid']
