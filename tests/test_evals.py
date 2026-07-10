import json
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
            },
            {
                "topic": "关键词命中",
                "ruleId": "process.some.rule_not_reported",
                "evidenceKeywords": ["废旧LFP电池", "氯化锂"],
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
    assert score["issue_points"][0]["matched_by"] == "rule_id"
    assert score["issue_points"][1]["matched_by"] == "keywords"
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
    # A result that reports exactly the historical opinion should score fully.
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
    assert score["issue_point_coverage"] == 1.0

    # An empty result must be visibly bad, not silently fine.
    empty = score_review_result(case, {"conclusion": "通过", "findings": []})
    assert empty["conclusion_match"] is False
    assert empty["issue_point_covered"] == 0
