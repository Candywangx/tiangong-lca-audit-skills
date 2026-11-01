import copy
import hashlib
import json

import pytest

from tiangong_audit.experts import roles


def experts():
    return [{'expert_id': 'E2', 'fields_text': '化工', 'experience_text': '参与化工生命周期评价'},
            {'expert_id': 'E1', 'fields_text': '基础金属', 'experience_text': '转炉工艺、LCA分配及数据建模审核'}]


def profile_payload(source):
    return {'schema_version': 'tiangong-expert-roles-v1',
            'input_sha256': roles.role_input_digest(source),
            'profiles': [{'expert_id': expert['expert_id'], 'roles': [
                {'role': role, 'support': 'supported', 'scope': '仅限所引经历范围',
                 'evidence': [{'field': 'experience_text', 'quote': expert['experience_text']}],
                 'limits': []}
                for role in ('domain', 'method', 'data_model')]}
                for expert in source]}


def test_digest_binds_only_sorted_professional_projection():
    source = experts()
    projection = sorted(copy.deepcopy(source), key=lambda row: row['expert_id'])
    expected = hashlib.sha256(json.dumps(projection, ensure_ascii=False, sort_keys=True,
                                        separators=(',', ':'), allow_nan=False).encode()).hexdigest()
    assert roles.role_input_digest(source) == expected
    other = list(reversed(copy.deepcopy(source)))
    other[0].update(display_id='私有显示标识', eligible=False)
    assert roles.role_input_digest(other) == expected
    other[0]['experience_text'] += '更新'
    assert roles.role_input_digest(other) != expected


def test_supported_profiles_validate_locations_without_certifying_semantics():
    source = experts()
    checked = roles.validate_role_profiles(source, profile_payload(source))
    assert checked == {'valid': True, 'errors': [], 'semantic_accuracy_verified': False}


def test_conditional_and_insufficient_require_explicit_limits():
    source = experts(); payload = profile_payload(source)
    conditional, insufficient = payload['profiles'][0]['roles'][:2]
    conditional.update(support='conditional', limits=['需确认适用工艺'])
    insufficient.update(support='insufficient', evidence=[], limits=['资料未提供方法经历'])
    assert roles.validate_role_profiles(source, payload)['valid']
    for role in (conditional, insufficient):
        saved = role['limits']; role['limits'] = []
        assert not roles.validate_role_profiles(source, payload)['valid']
        role['limits'] = saved
    conditional['evidence'] = []
    assert not roles.validate_role_profiles(source, payload)['valid']


@pytest.mark.parametrize('mutation', [
    lambda p: p.update(schema_version='other'),
    lambda p: p.update(input_sha256='0' * 64),
    lambda p: p['profiles'].pop(),
    lambda p: p['profiles'].append(copy.deepcopy(p['profiles'][0])),
    lambda p: p['profiles'][0].update(expert_id='unknown'),
    lambda p: p['profiles'][0]['roles'].pop(),
    lambda p: p['profiles'][0]['roles'][0].update(role='method'),
    lambda p: p['profiles'][0]['roles'][0].update(role='all_industries'),
    lambda p: p['profiles'][0]['roles'][0].update(support='certified'),
    lambda p: p['profiles'][0]['roles'][0].update(scope='  '),
    lambda p: p['profiles'][0]['roles'][0].update(all_industries=True),
    lambda p: p['profiles'][0]['roles'][0].update(limits=['']),
    lambda p: p['profiles'][0]['roles'][0].update(evidence=[]),
    lambda p: p['profiles'][0]['roles'][0].update(evidence=[{'field': 'fields_text', 'quote': '化工'}]),
    lambda p: p['profiles'][0]['roles'][0].update(evidence=[{'field': 'experience_text', 'quote': '虚构履历'}]),
    lambda p: p['profiles'][0]['roles'][0].update(evidence=[{'field': 'name', 'quote': '化工'}]),
    lambda p: p['profiles'][0]['roles'][0].update(evidence=[None]),
    lambda p: p['profiles'][0]['roles'][0].update(evidence='bad'),
])
def test_invalid_profile_shapes_and_unsupported_evidence_are_rejected(mutation):
    source = experts(); payload = profile_payload(source)
    mutation(payload)
    assert not roles.validate_role_profiles(source, payload)['valid']


@pytest.mark.parametrize('payload', [None, [], {}, {'profiles': [None]}, {'profiles': 'bad'}])
def test_malformed_payloads_return_errors(payload):
    assert not roles.validate_role_profiles(experts(), payload)['valid']


@pytest.mark.parametrize('source', [None, {}, [None], [{'expert_id': []}],
                                    [{'expert_id': 'E', 'fields_text': '', 'experience_text': None}],
                                    experts() + experts()])
def test_malformed_source_projection_returns_errors(source):
    assert not roles.validate_role_profiles(source, {})['valid']
