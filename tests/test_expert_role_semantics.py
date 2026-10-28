"""Check provenance and admission of the archived independent semantic run.

This does not execute an Agent or establish future recommendation accuracy.
Changing the policy requires re-running the four hidden-expectation scenarios.
"""
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_archived_role_boundary_run_matches_policy_and_synthetic_cases():
    fixtures = ROOT / 'tests/fixtures/expert-role-teams'
    scenarios = json.loads((fixtures/'scenarios.json').read_text())
    expected = json.loads((fixtures/'expected.json').read_text())
    actual = json.loads((fixtures/'agent-results.json').read_text())
    policy = ROOT/'skill/tiangong-lca-audit/references/expert-selection.md'
    assert actual['policy_sha256'] == hashlib.sha256(policy.read_bytes()).hexdigest()
    cases = {case['id']: case for case in scenarios['cases']}
    assert len(actual['cases']) == len(cases) == len(expected) == 4
    assert {case['id'] for case in actual['cases']} == set(expected)
    for result in actual['cases']:
        assert result['team_supported'] is expected[result['id']]['team_supported']
        ids = [expert['expert_id'] for expert in result['selected']]
        assert len(ids) == len(set(ids))
        assert set(ids) <= {expert['id'] for expert in cases[result['id']]['experts']}
        assert result['rationale'] and result['limits']
        if result['team_supported']:
            assert len(ids) == 3
            assert {'domain', 'method'} <= {expert['primary_role'] for expert in result['selected']}
