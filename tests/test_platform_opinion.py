from __future__ import annotations

import pytest

from tiangong_audit.report.platform import build_platform_comment


def _finding(
    severity: str,
    *,
    rule_id: str = "test.rule",
    origin: str = "deterministic",
    platform: dict[str, str] | None = None,
    status: str = "",
) -> dict[str, object]:
    finding: dict[str, object] = {
        "rule_id": rule_id,
        "severity": severity,
        "origin": origin,
        "location": f"{rule_id} 字段",
        "evidence": f"{rule_id} 的可见证据不足。",
        "judgment": "该内容需要复核。",
        "suggestion": "请按证据补充或修正。",
    }
    if platform is not None:
        finding["platform"] = platform
    if status:
        finding["status"] = status
    return finding


def _result(conclusion: str, findings: list[dict[str, object]]) -> dict[str, object]:
    return {"conclusion": conclusion, "findings": findings}


def test_legacy_severity_defaults_are_conservative():
    comment = build_platform_comment(
        _result(
            "rejected",
            [
                _finding("blocking", rule_id="legacy.blocking"),
                _finding("advisory", rule_id="legacy.advisory"),
                _finding("manual_review", rule_id="legacy.manual"),
                _finding("input_gap", rule_id="legacy.gap"),
            ],
        )
    )

    assert comment["valid"] is True
    assert [item["id"] for item in comment["findings"]] == ["legacy.blocking"]
    assert "【需修改】" in comment["opinion"]
    assert "legacy.advisory" not in comment["opinion"]


def test_true_v1_finding_without_origin_remains_readable():
    finding = _finding("blocking", rule_id="legacy.no-origin")
    finding.pop("origin")

    comment = build_platform_comment(_result("rejected", [finding]))

    assert comment["valid"] is True
    assert [item["id"] for item in comment["findings"]] == ["legacy.no-origin"]


def test_explicit_empty_origin_is_not_treated_as_legacy():
    finding = _finding("blocking", rule_id="bad.empty-origin")
    finding["origin"] = ""

    comment = build_platform_comment(_result("rejected", [finding]))

    assert comment["valid"] is False
    assert any("unknown controlled origin" in error for error in comment["validation_errors"])
    assert comment["findings"] == []


@pytest.mark.parametrize("conclusion", ["预检需人工确认", "预检信息不足"])
def test_real_precheck_non_pass_conclusions_require_clarification(conclusion: str):
    comment = build_platform_comment(
        _result(
            conclusion,
            [
                _finding(
                    "manual_review",
                    platform={"disposition": "clarification", "message": "请补充事实依据。"},
                )
            ],
        )
    )

    assert comment["valid"] is True
    assert "【请补充】请补充事实依据。" in comment["opinion"]


def test_explicit_platform_items_render_in_priority_order():
    comment = build_platform_comment(
        _result(
            "rejected",
            [
                _finding(
                    "advisory",
                    rule_id="suggestion.first-in-input",
                    platform={"disposition": "suggested", "message": "可补充定量说明。"},
                ),
                _finding(
                    "manual_review",
                    rule_id="clarification",
                    platform={"disposition": "clarification", "message": "请说明参考年的依据。"},
                ),
                _finding(
                    "blocking",
                    rule_id="required",
                    platform={"disposition": "required", "message": "请修正数据集类型。"},
                ),
                _finding(
                    "advisory",
                    rule_id="suggestion.second",
                    platform={"disposition": "suggested", "message": "建议补充来源角色说明。"},
                ),
            ],
        )
    )

    assert comment["valid"] is True
    assert [item["disposition"] for item in comment["findings"]] == [
        "required",
        "clarification",
        "suggested",
        "suggested",
    ]
    assert comment["opinion"].splitlines() == [
        "①【需修改】请修正数据集类型。",
        "②【请补充】请说明参考年的依据。",
        "③【建议】可补充定量说明。",
        "④【建议】建议补充来源角色说明。",
        "以上【建议】项用于改善数据说明，不作为本轮审核通过的前置条件。",
    ]


def test_routed_finding_contains_only_safe_submitter_fields():
    finding = _finding(
        "advisory",
        rule_id="safe.finding",
        platform={"disposition": "suggested", "message": "可补充公开说明。"},
    )
    finding.update(
        {
            "evidence": "内部证据：工具只解析了前三页。",
            "judgment": "内部判断：置信度不足。",
            "suggestion": "内部建议：审核员检查原文。",
            "tags": ["internal-tool-state"],
        }
    )

    comment = build_platform_comment(_result("rejected", [
        _finding("blocking", rule_id="required.safe"),
        finding,
    ]))
    routed = comment["findings"][1]

    assert set(routed) == {
        "id",
        "severity",
        "disposition",
        "title",
        "description",
        "evidence",
        "suggested_fix",
        "related_field",
        "tags",
    }
    assert routed == {
        "id": "safe.finding",
        "severity": "advisory",
        "disposition": "suggested",
        "title": "【建议】可补充公开说明。",
        "description": "可补充公开说明。",
        "evidence": "",
        "suggested_fix": "可补充公开说明。",
        "related_field": "",
        "tags": ["suggested"],
    }
    assert "内部" not in str(routed)


def test_approved_comment_is_none():
    comment = build_platform_comment(
        _result(
            "approved",
            [
                _finding(
                    "advisory",
                    platform={"disposition": "suggested", "message": "建议补充说明。"},
                )
            ],
        )
    )

    assert comment == {
        "valid": True,
        "validation_errors": [],
        "opinion": "无",
        "findings": [],
    }


@pytest.mark.parametrize(
    ("severity", "platform"),
    [
        ("blocking", {"disposition": "required", "message": "请修改。"}),
        ("manual_review", {"disposition": "clarification", "message": "请补充。"}),
    ],
)
def test_approved_comment_with_required_or_clarification_is_invalid(
    severity: str, platform: dict[str, str]
):
    comment = build_platform_comment(
        _result("approved", [_finding(severity, platform=platform)])
    )

    assert comment["valid"] is False
    assert comment["opinion"] == "无"
    assert comment["findings"] == []


@pytest.mark.parametrize(
    ("field", "value", "error_text"),
    [
        ("origin", 7, "origin must be a string"),
        ("severity", 7, "severity must be a string"),
        ("conclusion", 7, "conclusion must be a string"),
    ],
)
def test_control_fields_reject_non_string_values(field: str, value: object, error_text: str):
    finding = _finding("blocking", rule_id=f"bad.{field}")
    result: dict[str, object] = _result("rejected", [finding])
    if field == "conclusion":
        result["conclusion"] = value
    else:
        finding[field] = value

    comment = build_platform_comment(result)

    assert comment["valid"] is False
    assert any(error_text in error for error in comment["validation_errors"])


@pytest.mark.parametrize("origin", ["semantic_context", "validation", "extraction", "workflow"])
def test_internal_origin_always_invalidates_comment(origin: str):
    comment = build_platform_comment(
        _result(
            "rejected",
            [
                _finding("blocking", rule_id="submitter.fix"),
                _finding("input_gap", rule_id=f"internal.{origin}", origin=origin),
            ],
        )
    )

    assert comment["valid"] is False
    assert any(origin in error for error in comment["validation_errors"])
    assert [item["id"] for item in comment["findings"]] == ["submitter.fix"]


def test_internal_origin_with_explicit_projection_is_not_routed():
    comment = build_platform_comment(
        _result(
            "rejected",
            [
                _finding("blocking", rule_id="submitter.fix"),
                _finding(
                    "advisory",
                    rule_id="internal.explicit",
                    origin="extraction",
                    platform={"disposition": "suggested", "message": "不应发送。"},
                ),
            ],
        )
    )

    assert comment["valid"] is False
    assert [item["id"] for item in comment["findings"]] == ["submitter.fix"]
    assert "不应发送" not in comment["opinion"]


def test_unknown_origin_is_invalid_and_not_routed():
    comment = build_platform_comment(
        _result(
            "rejected",
            [
                _finding("blocking", rule_id="submitter.fix"),
                _finding(
                    "advisory",
                    rule_id="unknown.explicit",
                    origin="free_text_origin",
                    platform={"disposition": "suggested", "message": "不应发送。"},
                ),
            ],
        )
    )

    assert comment["valid"] is False
    assert any("unknown controlled origin" in error for error in comment["validation_errors"])
    assert [item["id"] for item in comment["findings"]] == ["submitter.fix"]


def test_internal_row_aggregates_origin_severity_and_platform_errors_before_skip():
    finding = _finding("advisory", rule_id="internal.multiple", origin="extraction")
    finding["severity"] = 42
    finding["platform"] = {"disposition": "not-a-disposition", "message": "x"}

    comment = build_platform_comment(_result("rejected", [finding]))

    errors = "\n".join(comment["validation_errors"])
    assert "internal origin 'extraction'" in errors
    assert "severity must be a string" in errors
    assert "platform disposition must be one of" in errors
    assert comment["findings"] == []


def test_legacy_message_separates_evidence_judgment_and_suggestion_with_punctuation():
    finding = _finding("blocking", rule_id="legacy.punctuation")
    finding.update(
        {
            "location": "数据集类型",
            "evidence": "当前填写为过程数据集",
            "judgment": "可见证据显示其为模型数据集",
            "suggestion": "请选择匹配的数据集类型",
        }
    )

    comment = build_platform_comment(_result("rejected", [finding]))

    assert comment["opinion"] == (
        "①【需修改】数据集类型 中，当前填写为过程数据集；"
        "可见证据显示其为模型数据集。建议：请选择匹配的数据集类型。"
    )


def test_legacy_message_does_not_double_existing_terminal_punctuation():
    finding = _finding("blocking", rule_id="legacy.existing-punctuation")
    finding.update(
        {
            "location": "数据集类型",
            "evidence": "当前类型与证据冲突。",
            "judgment": "该问题影响通过！",
            "suggestion": "请选择正确类型？",
        }
    )

    opinion = build_platform_comment(_result("rejected", [finding]))["opinion"]

    assert opinion == (
        "①【需修改】数据集类型 中，当前类型与证据冲突。"
        "该问题影响通过！建议：请选择正确类型？"
    )


def test_platform_numbering_falls_back_after_twenty():
    findings = [
        _finding(
            "blocking",
            rule_id=f"required.{index}",
            platform={"disposition": "required", "message": f"请修改第 {index} 项。"},
        )
        for index in range(1, 22)
    ]

    lines = build_platform_comment(_result("rejected", findings))["opinion"].splitlines()

    assert lines[19].startswith("⑳【需修改】")
    assert lines[20].startswith("21.【需修改】")


def test_blocking_cannot_be_hidden():
    comment = build_platform_comment(
        _result(
            "rejected",
            [
                _finding(
                    "blocking",
                    platform={"disposition": "internal_only"},
                )
            ],
        )
    )

    assert comment["valid"] is False
    assert any("blocking" in error and "internal_only" in error for error in comment["validation_errors"])
    assert comment["findings"] == []


def test_blocking_source_conflict_defaults_to_required():
    comment = build_platform_comment(
        _result(
            "rejected",
            [
                _finding(
                    "blocking",
                    rule_id="source.field.conflict",
                    origin="source_check",
                    status="conflict",
                )
            ],
        )
    )

    assert comment["valid"] is True
    assert comment["findings"][0]["disposition"] == "required"
    assert "【需修改】" in comment["opinion"]


@pytest.mark.parametrize("conclusion", ["manual_review", "信息不足"])
def test_non_pass_without_submitter_clarification_is_invalid(conclusion: str):
    comment = build_platform_comment(
        _result(conclusion, [_finding("manual_review")])
    )

    assert comment["valid"] is False
    assert any("clarification" in error for error in comment["validation_errors"])
