from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

EVAL_CASES_PATH = Path(__file__).resolve().parents[3] / 'tests/evals/audit-evaluation-cases.json'


def load_eval_cases(path: Path | None = None) -> list[dict[str, Any]]:
    payload = json.loads(Path(path or EVAL_CASES_PATH).read_text(encoding='utf-8'))
    cases = payload.get('cases') if isinstance(payload, dict) else payload
    if not isinstance(cases, list):
        raise ValueError("Eval catalog must contain a 'cases' list")
    return [case for case in cases if isinstance(case, dict)]


def get_eval_case(case_id: str, *, path: Path | None = None) -> dict[str, Any]:
    for case in load_eval_cases(path):
        if str(case.get('caseId')) == case_id:
            return case
    raise ValueError(f'Eval case not found: {case_id}')


def _text(finding: dict, key: str, alias: str = '') -> str:
    value = finding.get(key) or (finding.get(alias) if alias else '')
    return value.strip() if isinstance(value, str) else ''


def _groups_match(groups: Any, text: str) -> bool:
    # Groups are authored benchmark criteria, not universal semantic truth.
    return bool(groups) and isinstance(groups, list) and all(
        isinstance(group, list) and any(isinstance(term, str) and term and term.casefold() in text.casefold() for term in group)
        for group in groups
    )


def _score_issue_point(point: dict, findings: list[dict], index: int) -> dict:
    rule_id = str(point.get('ruleId') or '')
    evidence_groups = point.get('evidenceGroups') or [[word] for word in point.get('evidenceKeywords', [])]
    required_suggestion = point.get('shouldMentionSuggestion', True)
    candidates = []
    for finding_index, finding in enumerate(findings):
        evidence = _text(finding, 'evidence')
        judgment = _text(finding, 'judgment', 'description')
        suggestion = _text(finding, 'suggestion', 'suggested_fix')
        same_rule = bool(rule_id) and finding.get('rule_id') == rule_id
        evidence_match = _groups_match(evidence_groups, evidence)
        if not same_rule and not evidence_match:
            continue
        missing = []
        if not evidence:
            missing.append('evidence')
        if not judgment:
            missing.append('judgment')
        if required_suggestion and not suggestion:
            missing.append('suggestion')
        confirmed = (
            evidence_match and _groups_match(point.get('judgmentGroups'), judgment)
            and (not required_suggestion or _groups_match(point.get('suggestionGroups'), suggestion))
            and (not point.get('locationGroups') or _groups_match(point['locationGroups'], _text(finding, 'location', 'related_field')))
            and (point.get('expectedSeverity') not in {'blocking', 'advisory', 'manual_review', 'input_gap'}
                 or point['expectedSeverity'] == finding.get('severity'))
        )
        candidates.append((finding_index, 'invalid' if missing else 'covered' if confirmed else 'needs_manual_review', missing))
    winner = next((item for item in candidates if item[1] == 'covered'), None)
    if winner is None:
        winner = next((item for item in candidates if item[1] == 'needs_manual_review'), None)
    if winner is None and candidates:
        winner = candidates[0]
    status = winner[1] if winner else 'needs_manual_review' if findings else 'missing'
    return {
        'point_id': str(point.get('pointId') or f'point-{index + 1}'),
        'topic': str(point.get('topic') or ''), 'rule_id': rule_id,
        'covered': status == 'covered', 'status': status,
        'matched_by': 'criteria' if status == 'covered' else '',
        'matched_finding_index': winner[0] if winner else None,
        'candidate_finding_indexes': [item[0] for item in candidates],
        'missing_fields': winner[2] if winner else [],
    }


def score_review_result(case: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    """Score explicit benchmark criteria; uncertain prose needs human review.

    Rule IDs only nominate candidates. Evidence, judgment and action are checked
    separately. Coverage is confirmed coverage, not a semantic accuracy claim.
    """
    if not isinstance(result, dict) or not isinstance(result.get('findings', []), list):
        raise ValueError('Audit result must be an object with a findings list')
    raw_findings = result.get('findings') or []
    findings = [item for item in raw_findings if isinstance(item, dict)]
    expected = str(case.get('expectedConclusion') or '')
    actual = _normalize_conclusion(str(result.get('conclusion') or ''))
    points = [point for point in case.get('expectedIssuePoints', []) if isinstance(point, dict)]
    point_results = [_score_issue_point(point, findings, i) for i, point in enumerate(points)]
    covered = sum(point['covered'] for point in point_results)
    hard_failures = []
    if expected != actual:
        hard_failures.append('conclusion_mismatch')
    conclusion_rank = {'通过': 0, '需人工确认': 1, '信息不足': 2, '不通过': 3}
    severity_rank = {'advisory': 0, 'manual_review': 1, 'input_gap': 2, 'blocking': 3}
    strongest = max((severity_rank.get(_text(f, 'severity'), 0) for f in findings), default=0)
    if conclusion_rank.get(actual, -1) < strongest:
        hard_failures.append('conclusion_severity_conflict')
    if actual == '不通过' and not any(f.get('severity') == 'blocking' for f in findings):
        hard_failures.append('conclusion_severity_conflict')
    if len(raw_findings) != len(findings):
        hard_failures.append('invalid_findings')
    for i, finding in enumerate(findings):
        if (not _text(finding, 'evidence') or not _text(finding, 'judgment', 'description')
                or _text(finding, 'severity') not in severity_rank):
            hard_failures.append(f'invalid_finding:{i}')
        for forbidden in case.get('forbiddenIssuePoints', []):
            if not isinstance(forbidden, dict):
                continue
            if forbidden.get('ruleId') and finding.get('rule_id') != forbidden['ruleId']:
                continue
            if forbidden.get('severities') and finding.get('severity') not in forbidden['severities']:
                continue
            judgment = _text(finding, 'judgment', 'description')
            # Exact authored forbidden assertions avoid treating a policy quote
            # or a negated warning as a prohibited audit assertion.
            if forbidden.get('judgmentExact'):
                clauses = {clause.strip() for clause in re.split(r'[。；;！？!?\n]', judgment) if clause.strip()}
                assertions = {text.strip().rstrip('。；;！？!?') for text in forbidden['judgmentExact'] if isinstance(text, str)}
                hit = bool(clauses & assertions) or judgment in forbidden['judgmentExact']
            else:
                hit = _groups_match(forbidden.get('judgmentGroups'), judgment)
            if hit and (not forbidden.get('evidenceGroups') or _groups_match(forbidden['evidenceGroups'], _text(finding, 'evidence'))):
                hard_failures.append(f"forbidden_issue:{forbidden.get('pointId', 'unnamed')}")
    for point in point_results:
        if point['status'] in {'missing', 'invalid'}:
            hard_failures.append(f"{point['status']}_issue:{point['point_id']}")
    accounted = {point['matched_finding_index'] for point in point_results if point['matched_finding_index'] is not None}
    extra_indexes = [i for i in range(len(findings)) if i not in accounted]
    pending = sum(point['status'] == 'needs_manual_review' for point in point_results)
    positive_review_count = len(case.get('expectedPositivePoints') or [])
    needs_review = bool(pending or extra_indexes or positive_review_count)
    status = 'failed' if hard_failures else 'needs_manual_review' if needs_review else 'passed'
    return {
        'case_id': str(case.get('caseId') or ''),
        'expected_conclusion': expected, 'actual_conclusion': actual,
        'conclusion_match': expected == actual,
        'issue_point_total': len(point_results), 'issue_point_covered': covered,
        'issue_point_coverage': covered / len(point_results) if point_results else 1.0,
        'issue_points': point_results, 'finding_count': len(findings),
        'hard_failures': list(dict.fromkeys(hard_failures)),
        'pending_issue_count': pending, 'unreviewed_finding_indexes': extra_indexes,
        'positive_points_require_review': positive_review_count,
        'acceptance_status': status,
    }


def _normalize_conclusion(value: str) -> str:
    return {
        'approved': '通过', 'rejected': '不通过', 'manual_review': '需人工确认',
        '预检通过': '通过', '预检不通过': '不通过',
        '预检需人工确认': '需人工确认', '预检信息不足': '信息不足',
    }.get(value, value)
