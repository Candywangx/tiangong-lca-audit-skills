import copy
import json

from tiangong_audit.experts.recommendation import context_digest, validate_recommendations


def context():
    return {
        'schema_version': 'tiangong-expert-context-v1',
        'binding_sha256': '1' * 64,
        'experts': [{'expert_id': f'E{i}', 'eligible': i < 4,
                     'fields_text': '基础金属', 'experience_text': '转炉钢铁生命周期评价'}
                    for i in range(1, 5)],
        'datasets': [{'case_id': 'B01', 'dataset_type': 'process',
                      'evidence': [{'ref': '/process/technology', 'text': '转炉粗钢生产'}]}],
    }


def result(bundle):
    return {'schema_version': 'tiangong-expert-recommendation-v1',
            'input_sha256': context_digest(bundle),
            'cases': [{'case_id': 'B01', 'status': 'proposed', 'gaps': [],
                       'selected': [{'expert_id': f'E{i}', 'reason': '工艺与经验吻合',
                                     'expert_evidence': [{'field': 'experience_text', 'quote': '转炉钢铁'}],
                                     'dataset_evidence': [{'ref': '/process/technology', 'quote': '转炉粗钢'}]}
                                    for i in range(1, 4)]}]}


def test_valid_proposal_is_not_platform_authorization():
    b = context()
    checked = validate_recommendations(b, result(b))
    assert checked['valid'] is True
    assert checked['assignment_authorized'] is False
    assert checked['semantic_accuracy_verified'] is False


def test_changed_context_invalidates_old_proposal():
    b = context(); r = result(b)
    b['experts'][0]['experience_text'] = '资料更新'
    assert not validate_recommendations(b, r)['valid']


def test_duplicate_unknown_or_ineligible_experts_are_rejected():
    b = context()
    for replacement in ('E1', 'missing', 'E4'):
        r = result(b); r['cases'][0]['selected'][2]['expert_id'] = replacement
        assert not validate_recommendations(b, r)['valid']


def test_fabricated_or_wrong_field_evidence_is_rejected():
    b = context()
    for field, quote in [('experience_text', '航空航天'), ('name', '转炉钢铁')]:
        r = result(b); r['cases'][0]['selected'][0]['expert_evidence'] = [{'field': field, 'quote': quote}]
        assert not validate_recommendations(b, r)['valid']
    r = result(b); r['cases'][0]['selected'][0]['dataset_evidence'][0]['ref'] = '/unseen'
    assert not validate_recommendations(b, r)['valid']


def test_short_list_requires_explicit_status_and_gap():
    b = context(); r = result(b)
    r['cases'][0]['selected'].pop()
    assert not validate_recommendations(b, r)['valid']
    r['cases'][0].update(status='insufficient_candidates', gaps=['只有两位有相关证据'])
    assert validate_recommendations(b, r)['valid']


def test_every_case_must_be_accounted_for_once():
    b = context(); r = result(b)
    for cases in ([], r['cases'] * 2, [{**r['cases'][0], 'case_id': 'unknown'}]):
        other = {**r, 'cases': cases}
        assert not validate_recommendations(b, other)['valid']


def test_malformed_json_shapes_return_validation_errors():
    b = context()
    for malformed in ([], None, {'cases': [None]}, {'cases': 'bad'}):
        assert not validate_recommendations(b, malformed)['valid']
    r = result(b); r['cases'][0]['selected'][0]['expert_evidence'] = [None]
    assert not validate_recommendations(b, r)['valid']


def test_context_ids_and_boolean_eligibility_are_strict():
    b = context(); b['experts'][0]['eligible'] = 'false'
    assert not validate_recommendations(b, result(b))['valid']
    b = context(); b['experts'].append(copy.deepcopy(b['experts'][0]))
    assert not validate_recommendations(b, result(b))['valid']


def test_dataset_evidence_cannot_come_from_another_case():
    b = context(); b['datasets'].append({'case_id': 'B02', 'dataset_type': 'model', 'evidence': []})
    r = result(b); r['cases'].append({'case_id':'B02', 'status':'needs_context','selected':[], 'gaps':['关联过程未提供']})
    assert validate_recommendations(b, r)['valid']
    r['cases'][0]['selected'][0]['dataset_evidence'][0]['quote'] = '关联过程'
    assert not validate_recommendations(b, r)['valid']


def test_context_requires_binding_snapshot_provenance():
    for value in (None, '', 'not-a-digest'):
        b = context(); b['binding_sha256'] = value
        assert not validate_recommendations(b, result(b))['valid']
