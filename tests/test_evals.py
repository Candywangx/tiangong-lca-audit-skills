import json
import pytest
from pathlib import Path

from tiangong_audit.evals import load_eval_cases, score_review_result
from tiangong_audit.evals.harness import get_eval_case

ROOT = Path(__file__).resolve().parents[1]
EVALS = ROOT / "tests/evals/audit-evaluation-cases.json"


def test_eval_suite_covers_pass_and_fail_boundaries():
    payload = json.loads(EVALS.read_text(encoding="utf-8"))
    conclusions = {case["expectedConclusion"] for case in payload["cases"]}
    assert {"通过", "不通过"} <= conclusions


def test_failed_eval_cases_have_teaching_suggestions():
    payload = json.loads(EVALS.read_text(encoding="utf-8"))
    failed = [case for case in payload["cases"] if case["expectedConclusion"] == "不通过"]
    assert failed
    for case in failed:
        assert case["expectedIssuePoints"]
        assert all(point["shouldMentionSuggestion"] for point in case["expectedIssuePoints"])


def test_expected_issue_points_map_to_current_rules():
    payload = json.loads(EVALS.read_text(encoding="utf-8"))
    rule_ids = set()
    for path in [
        ROOT / "skill/tiangong-lca-audit/rules/common.json",
        ROOT / "skill/tiangong-lca-audit/rules/process.json",
        ROOT / "skill/tiangong-lca-audit/rules/model.json",
    ]:
        rule_payload = json.loads(path.read_text(encoding="utf-8"))
        rule_ids.update(rule["id"] for rule in rule_payload["rules"])

    for case in payload["cases"]:
        for point in case.get("expectedIssuePoints", []):
            assert point["ruleId"] in rule_ids


def test_harness_loads_catalog_cases():
    cases = load_eval_cases(EVALS)
    assert cases
    assert all(case.get("caseId") for case in cases)


def test_harness_scores_rule_id_and_keyword_coverage():
    case = {
        "caseId": "synthetic",
        "expectedConclusion": "不通过",
        "expectedIssuePoints": [
            {
                "topic": "参考流口径",
                "ruleId": "process.reference_flow.quantity_unit",
                "evidenceKeywords": ["1 kg", "1000 kg"],
                "judgmentGroups": [["口径不一致"]],
                "suggestionGroups": [["统一"], ["口径"]],
            },
            {
                "topic": "关键词命中",
                "ruleId": "process.some.rule_not_reported",
                "evidenceKeywords": ["废旧LFP电池", "氯化锂"],
                "judgmentGroups": [["清单不守恒"]],
                "suggestionGroups": [["复核"], ["质量平衡"]],
            },
            {
                "topic": "未覆盖",
                "ruleId": "process.never.matched",
                "evidenceKeywords": ["不存在的关键词"],
            },
        ],
    }
    result = {
        "conclusion": "不通过",
        "findings": [
            {
                "rule_id": "process.reference_flow.quantity_unit",
                "evidence": "年产量为 1 kg，输出为 1000 kg。",
                "judgment": "口径不一致。",
                "suggestion": "统一口径。",
            },
            {
                "rule_id": "process.inventory.boundary_consistency",
                "evidence": "废旧LFP电池 输入与 氯化锂 输出质量不守恒。",
                "judgment": "清单不守恒。",
                "suggestion": "复核质量平衡。",
            },
        ],
    }

    score = score_review_result(case, result)

    assert score["conclusion_match"] is True
    assert score["issue_point_total"] == 3
    assert score["issue_point_covered"] == 2
    assert score["issue_points"][0]["matched_by"] == "criteria"
    assert score["issue_points"][1]["matched_by"] == "criteria"
    assert score["issue_points"][2]["covered"] is False


def test_harness_normalizes_platform_and_precheck_conclusions():
    case = {"caseId": "s", "expectedConclusion": "不通过", "expectedIssuePoints": []}
    assert score_review_result(case, {"conclusion": "rejected", "findings": []})[
        "conclusion_match"
    ]
    assert score_review_result(case, {"conclusion": "预检不通过", "findings": []})[
        "conclusion_match"
    ]
    assert not score_review_result(case, {"conclusion": "approved", "findings": []})[
        "conclusion_match"
    ]


def test_harness_scores_historical_case_from_catalog():
    case = get_eval_case("hc-heavy-naphtha-not-approved", path=EVALS)
    # Repeating historical keywords and a generic suggestion is not verified quality.
    findings = [
        {
            "rule_id": point["ruleId"],
            "evidence": " ".join(point.get("evidenceKeywords", [])),
            "judgment": point.get("topic", ""),
            "suggestion": "按历史意见修改。",
        }
        for point in case["expectedIssuePoints"]
    ]
    score = score_review_result(case, {"conclusion": "不通过", "findings": findings})
    assert score["conclusion_match"] is True
    assert score["issue_point_coverage"] == 0.0
    assert score["pending_issue_count"] == len(case["expectedIssuePoints"])

    # An empty result must be visibly bad, not silently fine.
    empty = score_review_result(case, {"conclusion": "通过", "findings": []})
    assert empty["conclusion_match"] is False
    assert empty["issue_point_covered"] == 0


def _specific_case():
    return {"caseId": "specific", "expectedConclusion": "不通过", "expectedIssuePoints": [
        {"pointId": "quantity", "ruleId": "process.example", "topic": "数量",
         "evidenceGroups": [["1 kg"], ["1000 kg"]], "judgmentGroups": [["数量不符", "数量冲突"]],
         "shouldMentionSuggestion": True, "suggestionGroups": [["修正", "改为"], ["数量"]]},
        {"pointId": "year", "ruleId": "process.example", "topic": "年份",
         "evidenceGroups": [["2023"], ["2024"]], "judgmentGroups": [["年份不符"]],
         "shouldMentionSuggestion": True, "suggestionGroups": [["修正"], ["年份"]]},
    ]}


def _quantity_finding():
    return {"rule_id": "process.example", "severity": "blocking", "location": "参考流",
            "evidence": "参考流1 kg，数据1000 kg", "judgment": "数量不符", "suggestion": "修正数量"}


def test_rule_ids_alone_are_not_evidence():
    score = score_review_result(_specific_case(), {"conclusion": "不通过", "findings": [{"rule_id": "process.example"}]})
    assert score['issue_point_coverage'] == 0
    assert score['acceptance_status'] == 'failed'


def test_same_rule_id_does_not_cover_distinct_issues():
    score = score_review_result(_specific_case(), {"conclusion": "不通过", "findings": [_quantity_finding()]})
    assert score['issue_point_covered'] == 1
    assert score['issue_points'][1]['status'] == 'needs_manual_review'


def test_combined_finding_can_cover_independent_supported_points():
    finding = _quantity_finding()
    finding.update(evidence='1 kg与1000 kg；2023与2024', judgment='数量不符，年份不符', suggestion='修正数量和年份')
    score = score_review_result(_specific_case(), {'conclusion': '不通过', 'findings': [finding]})
    assert score['issue_point_coverage'] == 1
    assert score['acceptance_status'] == 'passed'


def test_missing_suggestion_is_a_failure_not_full_coverage():
    finding = _quantity_finding()
    finding['suggestion'] = ''
    score = score_review_result(_specific_case(), {'conclusion': '不通过', 'findings': [finding]})
    assert score['issue_points'][0]['covered'] is False
    assert score['acceptance_status'] == 'failed'


def test_suggestion_keywords_cannot_substitute_for_evidence():
    finding = _quantity_finding()
    finding.update(evidence='请查阅报告', suggestion='修正数量1 kg和1000 kg')
    score = score_review_result(_specific_case(), {'conclusion': '不通过', 'findings': [finding]})
    assert score['issue_point_covered'] == 0
    assert score['acceptance_status'] == 'needs_manual_review'


def test_pass_with_blocking_is_a_hard_failure():
    score = score_review_result({'caseId': 'pass', 'expectedConclusion': '通过'}, {'conclusion': '通过', 'findings': [_quantity_finding()]})
    assert score['acceptance_status'] == 'failed'
    assert 'conclusion_severity_conflict' in score['hard_failures']


def test_forbidden_claim_and_unrecognized_extra_finding_are_distinguished():
    case = {'caseId': 'pass', 'expectedConclusion': '通过', 'forbiddenIssuePoints': [
        {'pointId': 'optional', 'judgmentGroups': [['非必填'], ['必须补齐']], 'severities': ['blocking', 'advisory']}
    ]}
    finding = {'rule_id': 'anything', 'severity': 'advisory', 'evidence': '可选字段为空',
               'judgment': '非必填字段必须补齐', 'suggestion': '补齐字段'}
    score = score_review_result(case, {'conclusion': '通过', 'findings': [finding]})
    assert 'forbidden_issue:optional' in score['hard_failures']
    finding['judgment'] = '建议增加说明便于复用'
    assert score_review_result(case, {'conclusion': '通过', 'findings': [finding]})['acceptance_status'] == 'needs_manual_review'
    assert score_review_result(case, {'conclusion': '通过', 'findings': []})['acceptance_status'] == 'passed'


def test_platform_aliases_and_equivalent_unrecognized_prose():
    case = _specific_case()
    case['expectedIssuePoints'] = case['expectedIssuePoints'][:1]
    finding = _quantity_finding()
    finding['description'] = finding.pop('judgment')
    finding['suggested_fix'] = finding.pop('suggestion')
    assert score_review_result(case, {'conclusion': 'rejected', 'findings': [finding]})['acceptance_status'] == 'passed'
    finding['description'] = '清单用量与基准量之间存在三个数量级的差异'
    score = score_review_result(case, {'conclusion': 'rejected', 'findings': [finding]})
    assert score['acceptance_status'] == 'needs_manual_review'
    assert score['issue_points'][0]['status'] == 'needs_manual_review'


def test_unverified_extra_candidate_cannot_hide_behind_a_correct_finding():
    case = _specific_case()
    case['expectedIssuePoints'] = case['expectedIssuePoints'][:1]
    extra = {**_quantity_finding(), 'evidence': '另一个无关参数', 'judgment': '可能有问题', 'suggestion': '核实参数来源'}
    score = score_review_result(case, {'conclusion': '不通过', 'findings': [_quantity_finding(), extra]})
    assert score['issue_point_coverage'] == 1
    assert score['acceptance_status'] == 'needs_manual_review'
    assert score['unreviewed_finding_indexes'] == [1]


def test_a_rejected_conclusion_requires_a_blocking_finding():
    finding = {**_quantity_finding(), 'severity': 'advisory'}
    case = _specific_case()
    case['expectedIssuePoints'] = case['expectedIssuePoints'][:1]
    score = score_review_result(case, {'conclusion': '不通过', 'findings': [finding]})
    assert 'conclusion_severity_conflict' in score['hard_failures']


def test_forbidden_exact_assertion_cannot_hide_inside_a_valid_combined_finding():
    case = _specific_case()
    case['expectedIssuePoints'] = case['expectedIssuePoints'][:1]
    case['forbiddenIssuePoints'] = [{'pointId': 'optional', 'judgmentExact': ['非必填字段必须补齐']}]
    finding = {**_quantity_finding(), 'judgment': '数量不符；非必填字段必须补齐'}
    score = score_review_result(case, {'conclusion': '不通过', 'findings': [finding]})
    assert 'forbidden_issue:optional' in score['hard_failures']


def test_blocking_cannot_be_downgraded_to_input_gap_by_result_label():
    case = _specific_case()
    case['expectedConclusion'] = '信息不足'
    score = score_review_result(case, {'conclusion': '信息不足', 'findings': [_quantity_finding()]})
    assert 'conclusion_severity_conflict' in score['hard_failures']


@pytest.mark.parametrize('severity', [None, 'urgent', [], {}])
def test_invalid_severity_never_crashes_or_passes_evaluation(severity):
    case = _specific_case()
    case['expectedIssuePoints'] = case['expectedIssuePoints'][:1]
    score = score_review_result(case, {'conclusion': '不通过', 'findings': [{**_quantity_finding(), 'severity': severity}]})
    assert 'invalid_finding:0' in score['hard_failures']
