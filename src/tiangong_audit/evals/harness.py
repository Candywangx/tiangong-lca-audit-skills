from __future__ import annotations

import json
from pathlib import Path
from typing import Any

EVAL_CASES_PATH = Path(__file__).resolve().parents[3] / "tests/evals/audit-evaluation-cases.json"
# An issue point counts as covered by keywords alone only when at least this
# share of its evidenceKeywords appears in one finding's text.
KEYWORD_COVERAGE_THRESHOLD = 0.5


def load_eval_cases(path: Path | None = None) -> list[dict[str, Any]]:
    payload = json.loads(Path(path or EVAL_CASES_PATH).read_text(encoding="utf-8"))
    cases = payload.get("cases") if isinstance(payload, dict) else payload
    if not isinstance(cases, list):
        raise ValueError("Eval catalog must contain a 'cases' list")
    return [case for case in cases if isinstance(case, dict)]


def get_eval_case(case_id: str, *, path: Path | None = None) -> dict[str, Any]:
    for case in load_eval_cases(path):
        if str(case.get("caseId")) == case_id:
            return case
    raise ValueError(f"Eval case not found: {case_id}")


def score_review_result(case: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    """Score one produced audit result against one historical eval case.

    ``result`` accepts any payload with a findings list (semantic-review.json,
    precheck output, or a platform result). Conclusion is read from
    ``conclusion`` and normalized to the eval vocabulary.
    """

    findings = [item for item in result.get("findings") or [] if isinstance(item, dict)]
    expected_conclusion = str(case.get("expectedConclusion") or "")
    actual_conclusion = _normalize_conclusion(str(result.get("conclusion") or ""))
    issue_points = [
        point for point in case.get("expectedIssuePoints") or [] if isinstance(point, dict)
    ]

    point_results = [_score_issue_point(point, findings) for point in issue_points]
    covered = sum(1 for item in point_results if item["covered"])
    return {
        "case_id": str(case.get("caseId") or ""),
        "expected_conclusion": expected_conclusion,
        "actual_conclusion": actual_conclusion,
        "conclusion_match": _conclusions_agree(expected_conclusion, actual_conclusion),
        "issue_point_total": len(point_results),
        "issue_point_covered": covered,
        "issue_point_coverage": (covered / len(point_results)) if point_results else 1.0,
        "issue_points": point_results,
        "finding_count": len(findings),
    }


def _score_issue_point(
    point: dict[str, Any], findings: list[dict[str, Any]]
) -> dict[str, Any]:
    rule_id = str(point.get("ruleId") or "")
    keywords = [str(item) for item in point.get("evidenceKeywords") or [] if str(item)]
    matched_by = ""
    matched_finding_index = None
    for index, finding in enumerate(findings):
        if rule_id and str(finding.get("rule_id") or "") == rule_id:
            matched_by = "rule_id"
            matched_finding_index = index
            break
    if matched_finding_index is None and keywords:
        for index, finding in enumerate(findings):
            text = _finding_text(finding)
            hits = sum(1 for keyword in keywords if keyword in text)
            if hits / len(keywords) >= KEYWORD_COVERAGE_THRESHOLD:
                matched_by = "keywords"
                matched_finding_index = index
                break
    return {
        "topic": str(point.get("topic") or ""),
        "rule_id": rule_id,
        "covered": matched_finding_index is not None,
        "matched_by": matched_by,
        "matched_finding_index": matched_finding_index,
    }


def _finding_text(finding: dict[str, Any]) -> str:
    return "\n".join(
        str(finding.get(key) or "")
        for key in ("location", "evidence", "judgment", "suggestion", "title", "description")
    )


def _normalize_conclusion(value: str) -> str:
    mapping = {
        "approved": "通过",
        "rejected": "不通过",
        "manual_review": "需人工确认",
        "预检通过": "通过",
        "预检不通过": "不通过",
        "预检需人工确认": "需人工确认",
        "预检信息不足": "信息不足",
    }
    return mapping.get(value, value)


def _conclusions_agree(expected: str, actual: str) -> bool:
    if expected == actual:
        return True
    # Historical opinions only distinguish 通过/不通过; treat the conservative
    # outcomes as agreeing with 不通过 only when they block an approval.
    if expected == "不通过":
        return actual in {"不通过"}
    if expected == "通过":
        return actual in {"通过"}
    return False
