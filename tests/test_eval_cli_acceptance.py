import argparse
import json

import pytest

from tiangong_audit.cli import eval_score


@pytest.mark.parametrize('mode, expected', [('contradiction', 1), ('pending', 2), ('pass', 0)])
def test_eval_cli_never_hides_hard_failures_or_pending_review(tmp_path, mode, expected):
    catalog = tmp_path / 'eval.json'
    result = tmp_path / 'result.json'
    case = {'caseId': 'example', 'expectedConclusion': '通过', 'expectedIssuePoints': []}
    finding = {'severity': 'blocking' if mode == 'contradiction' else 'advisory',
               'evidence': '可选说明为空', 'judgment': '建议补充说明', 'suggestion': '补充用途说明'}
    catalog.write_text(json.dumps({'cases': [case]}))
    result.write_text(json.dumps({'conclusion': '通过', 'findings': [] if mode == 'pass' else [finding]}))
    args = argparse.Namespace(case_id='example', result=str(result), evals=str(catalog), output=None,
                              require_conclusion_match=False, fail_under=0)
    assert eval_score(args) == expected
