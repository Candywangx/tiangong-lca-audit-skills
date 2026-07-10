"""Regression harness that scores audit results against historical opinions.

``tests/evals/audit-evaluation-cases.json`` stores desensitized historical
audit cases: the projected input, the human conclusion, and the individual
issue points reviewers raised. This module makes those cases executable — a
produced result (``semantic-review.json``, precheck output, or any payload
with ``findings``) is scored for conclusion agreement and issue-point
coverage, so prompt, rule, or model changes can be measured instead of
eyeballed.
"""

from .harness import (
    EVAL_CASES_PATH,
    load_eval_cases,
    score_review_result,
)

__all__ = [
    "EVAL_CASES_PATH",
    "load_eval_cases",
    "score_review_result",
]
