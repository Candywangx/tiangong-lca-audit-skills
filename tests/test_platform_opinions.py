from copy import deepcopy

import pytest

from tiangong_audit.report.markdown import render_platform_return_opinion


def finding(severity="blocking", index=0, **changes):
    return {
        "rule_id": f"process.example.{index}",
        "severity": severity,
        "location": "参考流 / 单位",
        "evidence": "来源第 3 页以 1 kg 产品为基准，当前录入为 1 t。",
        "judgment": "数量基准与来源不一致。",
        "suggestion": "请核对换算，并同步修正清单。",
        "finding_ref": {"path": "agent-review/agent-findings.json", "pointer": f"/rule_reviews/{index}"},
        **changes,
    }


def opinion(item, text="参考流的单位与来源第 3 页不一致。请核对 kg 与 t 的换算。"):
    return {"severity": item["severity"], "text": text, "finding_refs": [item["finding_ref"]]}


def test_labels_and_order_follow_actual_severity_not_conclusion_or_verbs():
    findings = [finding(severity, index, platform_actionable=True) for index, severity in enumerate(
        ("advisory", "manual_review", "input_gap", "blocking")
    )]
    text = render_platform_return_opinion({"conclusion": "不通过", "findings": findings})
    assert [line[:7] for line in text.splitlines() if line and line[0] in "①②③④"] == [
        "①【需修改】参", "②【需补充】参", "③【需确认】参", "④【建议优化】",
    ]
    assert "来源第 3 页" in text


def test_authored_same_cause_grouping_preserves_text_and_uncovered_blockers():
    first, duplicate, uncovered = [finding(index=index) for index in range(3)]
    uncovered["evidence"] = "第二个独立问题。"
    authored = opinion(first, "单位填写存在换算错误。请按来源第 3 页修正 1 kg 基准。")
    authored["finding_refs"].append(duplicate["finding_ref"])
    text = render_platform_return_opinion({
        "findings": [first, duplicate, uncovered], "platform_opinions": [authored],
    })
    assert "①【需修改】单位填写存在换算错误。请按来源第 3 页修正 1 kg 基准。" in text
    assert "②【需修改】" in text
    assert "第二个独立问题" in text
    assert "当前录入" not in text


def test_exact_duplicates_are_removed_only_within_the_same_severity():
    first = finding()
    advisory = finding("advisory", 2)
    text = render_platform_return_opinion({"findings": [first, deepcopy(first), advisory]})
    assert text.count("【需修改】") == 1
    assert text.count("【建议优化】") == 1


@pytest.mark.parametrize("severity", [None, "", "critical", 3])
def test_invalid_finding_severity_is_not_silently_omitted(severity):
    with pytest.raises(ValueError, match="severity"):
        render_platform_return_opinion({"findings": [finding(severity)]})


@pytest.mark.parametrize("change", [
    {"severity": "input_gap"},
    {"severity": "critical"},
    {"text": ""},
    {"text": "【建议优化】请修正单位。"},
    {"finding_refs": []},
    {"finding_refs": [{"path": "missing.json", "pointer": "/0"}]},
    {"finding_refs": [{"path": "agent-review/agent-findings.json", "pointer": "/rule_reviews/404"}]},
])
def test_authored_opinions_reject_unverifiable_or_mislabeled_items(change):
    item = finding()
    authored = {**opinion(item), **change}
    with pytest.raises(ValueError):
        render_platform_return_opinion({"findings": [item], "platform_opinions": [authored]})


def test_same_cause_group_cannot_merge_severities():
    first, second = finding(), finding("advisory", 1)
    authored = opinion(first)
    authored["finding_refs"].append(second["finding_ref"])
    with pytest.raises(ValueError, match="severity"):
        render_platform_return_opinion({"findings": [first, second], "platform_opinions": [authored]})


def test_internal_limitations_and_unselected_manual_findings_are_not_submitter_requests():
    internal = finding("input_gap", platform_actionable=False, evidence="抽取工具未成功读取附件。")
    pending = finding("manual_review", 1, suggestion="由审核员读取原文确认。")
    text = render_platform_return_opinion({"findings": [internal, pending]})
    assert text == "## 平台退回意见\n\n无\n"
    with pytest.raises(ValueError, match="actionable"):
        render_platform_return_opinion({"findings": [internal], "platform_opinions": [opinion(internal)]})


def test_missing_required_data_can_still_be_a_confirmed_blocking_error():
    item = finding(evidence="必填参考流为空。", suggestion="请补充参考流。")
    text = render_platform_return_opinion({"findings": [item]})
    assert "①【需修改】" in text
    assert "【需补充】" not in text


def test_authored_text_must_not_include_a_public_prefix():
    item = finding()
    with pytest.raises(ValueError, match="tag"):
        render_platform_return_opinion({
            "findings": [item], "platform_opinions": [opinion(item, "【需修改】请核对单位。")],
        })


@pytest.mark.parametrize("field", ["location", "evidence", "judgment", "suggestion"])
def test_blank_optional_finding_content_cannot_be_published(field):
    item = finding("manual_review", **{field: ""})
    with pytest.raises(ValueError, match="actionable"):
        render_platform_return_opinion({"findings": [item], "platform_opinions": [opinion(item)]})


def test_conflicting_reference_cannot_hide_a_blocker():
    first = finding()
    other = {**first, "severity": "advisory"}
    with pytest.raises(ValueError, match="finding_ref"):
        render_platform_return_opinion({
            "findings": [first, other], "platform_opinions": [opinion(other)],
        })


@pytest.mark.parametrize("text", ["①请核对单位。", "  ⑳请核对单位。", "1.请核对单位。", "21. 请核对单位。"])
def test_authored_opinion_rejects_leading_enumeration(text):
    item = finding()
    with pytest.raises(ValueError, match="number"):
        render_platform_return_opinion({"findings": [item], "platform_opinions": [opinion(item, text)]})


@pytest.mark.parametrize("text", ["1 kg 产品的基准不一致。请核对单位。", "1.5 kg 产品的基准不一致。请核对单位。"])
def test_authored_opinion_preserves_leading_numeric_facts(text):
    item = finding()
    rendered = render_platform_return_opinion({"findings": [item], "platform_opinions": [opinion(item, text)]})
    assert rendered.endswith("①【需修改】" + text + "\n")


def test_platform_return_opinion_allows_exactly_1000_characters():
    item = finding()
    prefix = "## 平台退回意见\n\n①【需修改】"
    authored = opinion(item, "请修正单位。" + "字" * (1000 - len(prefix) - len("请修正单位。\n")))

    rendered = render_platform_return_opinion({"findings": [item], "platform_opinions": [authored]})

    assert len(rendered) == 1000


def test_platform_return_opinion_rejects_more_than_1000_characters():
    item = finding()
    prefix = "## 平台退回意见\n\n①【需修改】"
    authored = opinion(item, "请修正单位。" + "字" * (1001 - len(prefix) - len("请修正单位。\n")))

    with pytest.raises(ValueError, match="1000"):
        render_platform_return_opinion({"findings": [item], "platform_opinions": [authored]})


def test_platform_return_opinion_limit_covers_all_items():
    first, second = finding(index=0), finding(index=1)
    authored = [opinion(first, "字" * 490), opinion(second, "文" * 490)]

    with pytest.raises(ValueError, match="1000"):
        render_platform_return_opinion({"findings": [first, second], "platform_opinions": authored})
