from argparse import Namespace
import json
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from tiangong_audit.cli import (
    _comment_payload_from_result_data,
    _draft_account_role_for_result,
    adapt_legacy_platform_result,
    agent_findings_template,
    agent_findings_validate,
    audit_bundle,
    build_parser,
    case_coverage,
    case_list,
    case_status,
    case_update,
    create_case,
    fetch_dataset,
    fetch_tasks,
    list_actions,
    process_pass_flow,
    review_intake,
    review_semantic_review,
    save_result_draft,
    eval_score,
    source_attach_extraction,
    source_claims,
    source_fetch,
    source_resolve,
    submit_result,
    validate_structure,
)
from tiangong_audit.workflows.semantic_review import _platform_result

ROOT = Path(__file__).resolve().parents[1]


def _routed_result(*, conclusion="rejected", valid=True):
    finding = {
        "id": "process.object.consistency",
        "severity": "blocking",
        "disposition": "required",
        "title": "【需修改】统一过程对象描述。",
        "description": "统一过程对象描述。",
        "evidence": "",
        "suggested_fix": "统一过程对象描述。",
        "related_field": "",
        "tags": ["required"],
        "internal_state": "must never leave the audit workspace",
    }
    return {
        "review_task_id": "review-1",
        "dataset_id": "dataset-1",
        "conclusion": conclusion,
        "summary": {"internal": "do not leak"},
        "auditor_notes": "source/tool limitation: extractor timed out; do not leak",
        "findings": [
            {
                "severity": "manual_review",
                "description": "Agent workflow state: cannot_judge; internal evidence",
            }
        ],
        "platform_comment": {
            "valid": valid,
            "validation_errors": [] if valid else ["unsafe internal origin"],
            "opinion": "①【需修改】统一过程对象描述。",
            "findings": [finding],
            "workflow_state": "do not leak",
        },
    }


def test_comment_payload_uses_only_platform_comment():
    result = _routed_result()

    assert _comment_payload_from_result_data(result) == {
        "conclusion": "rejected",
        "summary": "①【需修改】统一过程对象描述。",
        "findings": [
            {
                "id": "process.object.consistency",
                "severity": "blocking",
                "disposition": "required",
                "title": "【需修改】统一过程对象描述。",
                "description": "统一过程对象描述。",
                "evidence": "",
                "suggested_fix": "统一过程对象描述。",
                "related_field": "",
                "tags": ["required"],
            }
        ],
        "auditor_notes": None,
    }
    serialized = json.dumps(_comment_payload_from_result_data(result), ensure_ascii=False)
    for internal_text in (
        "do not leak",
        "internal evidence",
        "must never leave",
        "workflow_state",
        "source/tool limitation",
        "Agent workflow state",
    ):
        assert internal_text not in serialized


def test_comment_payload_approved_draft_is_exactly_none():
    result = _routed_result(conclusion="passed")
    result["platform_comment"] = {
        "valid": True,
        "validation_errors": [],
        "opinion": "无",
        "findings": [],
    }
    assert _comment_payload_from_result_data(result) == {
        "conclusion": "approved",
        "summary": "无",
        "findings": [],
        "auditor_notes": None,
    }


@pytest.mark.parametrize(
    ("conclusion", "expected_role"),
    [
        ("approved", "pass"), ("pass", "pass"), ("passed", "pass"),
        ("通过", "pass"), ("预检通过", "pass"),
        ("rejected", "reject"), ("reject", "reject"), ("fail", "reject"),
        ("不通过", "reject"), ("manual review", "reject"),
        ("needs_manual_review", "reject"), ("需人工审核", "reject"),
        ("insufficient_information", "reject"), ("预检信息不足", "reject"),
    ],
)
def test_draft_account_role_uses_shared_conclusion_aliases(conclusion, expected_role):
    assert _draft_account_role_for_result({"conclusion": conclusion}) == expected_role


def test_semantic_platform_result_flows_into_comment_payload_without_shape_drift():
    platform_result = _platform_result(
        {
            "review_task_id": "review-1",
            "dataset_id": "dataset-1",
            "dataset_type": "process",
            "version": "01.01.000",
            "conclusion": "不通过",
            "platform_conclusion": "rejected",
            "summary": {"blocking": 1},
            "source_consistency": {"conclusion": "一致"},
            "rule_compliance": {"conclusion": "存在阻断问题"},
            "agent_review": {"status": "completed"},
            "audit_completeness": {"status": "complete"},
            "source_summary": {"status": "complete"},
            "report_note": "internal only",
            "findings": [
                {
                    "rule_id": "process.dataset_type.consistency",
                    "severity": "blocking",
                    "origin": "agent",
                    "location": "数据集类型",
                    "evidence": "当前类型与内容不一致。",
                    "judgment": "需要修改。",
                    "suggestion": "改为过程数据集。",
                    "platform": {
                        "disposition": "required",
                        "message": "当前类型与内容不一致，请改为过程数据集。",
                    },
                }
            ],
        }
    )

    payload = _comment_payload_from_result_data(platform_result)

    assert payload["conclusion"] == "rejected"
    assert payload["summary"] == platform_result["platform_comment"]["opinion"]
    assert [item["id"] for item in payload["findings"]] == [
        "process.dataset_type.consistency"
    ]
    assert payload["auditor_notes"] is None

def test_comment_payload_rejects_noncanonical_opinion_bytes():
    result = _routed_result()
    result["platform_comment"]["opinion"] = "①【需修改】第一行。\n②【建议】第二行。  "

    with pytest.raises(ValueError, match="does not match canonical"):
        _comment_payload_from_result_data(result)


def test_comment_payload_rebuilds_canonical_findings_and_drops_forged_fields():
    result = _routed_result()
    routed = result["platform_comment"]["findings"][0]
    routed.update(
        {
            "title": "INTERNAL_SECRET title",
            "evidence": "INTERNAL_SECRET source/tool limitation",
            "suggested_fix": "INTERNAL_SECRET Agent workflow",
            "related_field": "INTERNAL_SECRET path",
            "tags": ["INTERNAL_SECRET"],
        }
    )

    payload = _comment_payload_from_result_data(result)

    assert "INTERNAL_SECRET" not in json.dumps(payload, ensure_ascii=False)
    assert payload["findings"] == [
        {
            "id": "process.object.consistency",
            "severity": "blocking",
            "disposition": "required",
            "title": "【需修改】统一过程对象描述。",
            "description": "统一过程对象描述。",
            "evidence": "",
            "suggested_fix": "统一过程对象描述。",
            "related_field": "",
            "tags": ["required"],
        }
    ]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("id", 7),
        ("rule_id", {"nested": "id"}),
        ("title", ["nested"]),
        ("description", 42),
        ("related_field", {"nested": "path"}),
        ("suggested_fix", ["nested"]),
    ],
)
def test_legacy_adapter_rejects_non_string_safe_fields(field, value):
    finding = {
        "severity": "blocking",
        "title": "对象冲突",
        "description": "名称冲突",
        "related_field": "过程对象",
        "suggested_fix": "统一描述",
    }
    if field == "rule_id":
        finding.pop("id", None)
    finding[field] = value

    with pytest.raises(ValueError, match=field):
        adapt_legacy_platform_result({"conclusion": "rejected", "findings": [finding]})


def test_legacy_adapter_treats_optional_none_as_missing():
    adapted = adapt_legacy_platform_result(
        {
            "conclusion": "rejected",
            "findings": [
                {
                    "id": None,
                    "rule_id": None,
                    "severity": "blocking",
                    "title": None,
                    "description": None,
                    "related_field": None,
                    "suggested_fix": None,
                }
            ],
        }
    )

    assert adapted["platform_comment"]["findings"][0]["id"] == "finding_0"


def test_legacy_platform_result_adapter_is_conservative():
    legacy = {
        "review_task_id": "review-1",
        "conclusion": "不通过",
        "summary": {"internal": "never map this"},
        "auditor_notes": "never map this",
        "findings": [
            {
                "id": "block",
                "severity": "blocking",
                "title": "对象冲突",
                "description": "名称与技术描述冲突",
                "related_field": "过程对象",
                "suggested_fix": "统一描述",
                "evidence": "internal raw evidence",
                "tags": ["internal"],
            },
            {"id": "advise", "severity": "advisory", "title": "建议完善"},
            {"id": "manual", "severity": "manual_review", "title": "人工判断"},
            {"id": "gap", "severity": "input_gap", "title": "工具限制"},
        ],
    }

    adapted = adapt_legacy_platform_result(legacy)

    assert adapted["conclusion"] == "rejected"
    assert [item["id"] for item in adapted["platform_comment"]["findings"]] == ["block"]
    assert "internal raw evidence" not in json.dumps(adapted, ensure_ascii=False)
    assert "never map this" not in json.dumps(adapted, ensure_ascii=False)
    assert adapted["platform_comment"]["valid"] is True


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("approved", "approved"), ("pass", "approved"), ("passed", "approved"),
        ("通过", "approved"), ("rejected", "rejected"), ("fail", "rejected"),
        ("不通过", "rejected"), ("manual-review", "manual_review"),
        ("manual review", "manual_review"), ("需人工确认", "manual_review"),
        ("information-insufficient", "information_insufficient"),
        ("insufficient information", "information_insufficient"),
        ("信息不足", "information_insufficient"),
    ],
)
def test_legacy_platform_result_adapter_normalizes_known_conclusions(raw, expected):
    finding = {
        "severity": "blocking" if expected == "rejected" else "manual_review",
        "title": "待处理",
        "description": "请补充",
        "related_field": "字段",
        "suggested_fix": "补充说明",
    }
    adapted = adapt_legacy_platform_result({"conclusion": raw, "findings": [finding]})

    assert adapted["conclusion"] == expected


def test_legacy_platform_result_adapter_rejects_unknown_conclusion():
    with pytest.raises(ValueError, match="unknown platform conclusion"):
        adapt_legacy_platform_result({"conclusion": "maybe", "findings": []})


def test_invalid_dry_run_has_no_side_effects(tmp_path, monkeypatch, capsys):
    result_path = tmp_path / "invalid.json"
    result_path.write_text(json.dumps(_routed_result(valid=False), ensure_ascii=False), encoding="utf-8")
    touched = []
    monkeypatch.setattr("tiangong_audit.cli._append_operation_if_case", lambda *a, **k: touched.append("log"))
    monkeypatch.setattr("tiangong_audit.cli._write_output", lambda *a, **k: touched.append("output"))
    monkeypatch.setattr(
        "tiangong_audit.cli.tiangong_api.TiangongAPIClient",
        lambda **kwargs: touched.append("client"),
    )

    code = save_result_draft(
        Namespace(
            result=str(result_path), review_id=None, batch_id=None,
            account_role="reject", execute=False, output=None,
        )
    )

    assert code == 1
    assert touched == []
    assert "Invalid result format" in capsys.readouterr().err


def test_invalid_execute_stops_before_client_factory(tmp_path, monkeypatch, capsys):
    result_path = tmp_path / "invalid.json"
    result_path.write_text(json.dumps(_routed_result(valid=False), ensure_ascii=False), encoding="utf-8")
    touched = []
    monkeypatch.setattr(
        "tiangong_audit.cli.tiangong_api.TiangongAPIClient",
        lambda **kwargs: touched.append("client"),
    )

    code = save_result_draft(
        Namespace(
            result=str(result_path), review_id=None, batch_id=None,
            account_role="reject", execute=True, output=None,
        )
    )

    assert code == 1
    assert touched == []
    assert "Invalid result format" in capsys.readouterr().err


def test_save_result_draft_sends_exact_app_review_save_comment_draft_envelope(
    tmp_path, monkeypatch, capsys
):
    result_path = tmp_path / "result.json"
    result_path.write_text(json.dumps(_routed_result(), ensure_ascii=False), encoding="utf-8")
    calls = []

    class FakeClient:
        def invoke_function(self, name, payload):
            calls.append((name, payload))
            return {"ok": True}

    monkeypatch.setattr(
        "tiangong_audit.cli.tiangong_api.TiangongAPIClient",
        lambda **kwargs: FakeClient(),
    )

    assert save_result_draft(
        Namespace(
            result=str(result_path), review_id=None, batch_id=None,
            account_role="reject", execute=True, output=None,
        )
    ) == 0
    expected_comment = {
        "conclusion": "rejected",
        "summary": "①【需修改】统一过程对象描述。",
        "findings": [
            {
                "id": "process.object.consistency",
                "severity": "blocking",
                "disposition": "required",
                "title": "【需修改】统一过程对象描述。",
                "description": "统一过程对象描述。",
                "evidence": "",
                "suggested_fix": "统一过程对象描述。",
                "related_field": "",
                "tags": ["required"],
            }
        ],
        "auditor_notes": None,
    }
    assert calls == [
        (
            "app_review_save_comment_draft",
            {"reviewId": "review-1", "json": expected_comment},
        )
    ]
    capsys.readouterr()


def test_audit_command_creates_review_bundle():
    with TemporaryDirectory() as temporary:
        output_dir = Path(temporary) / "audit"
        args = Namespace(
            input=str(ROOT / "tests/fixtures/projected-api/process-audit-input-noapproved-projected.json"),
            output_dir=str(output_dir),
        )
        assert audit_bundle(args) == 0
        assert {
            "normalized.json",
            "precheck.json",
            "precheck.md",
            "agent-review-request.md",
        } == {path.name for path in output_dir.iterdir()}
        request = (output_dir / "agent-review-request.md").read_text(encoding="utf-8")
        assert "程序预检不是最终审核结论" in request
        assert "最终审核意见必须合并程序预检中已经成立的问题" in request
        assert "不得因为问题已出现在预检中就在最终退回意见中省略" in request
        assert "process.object.consistency" in request
        assert "process.type.boundary_match" in request
        assert "process.boundary.cutoff_and_exclusions" in request
        assert "process.classification.process_fit" in request
        assert "处理、标准、路线" in request
        assert "上游背景过程" in request
        assert "总质量" in request
        assert "候选分类路径或候选范围" in request
        assert "核实条件" in request


def test_fetch_tasks_selects_admin_queue(monkeypatch, capsys):
    class FakeReviewAPI:
        def __init__(self, client):
            pass

        def get_admin_tasks(self, **kwargs):
            assert kwargs == {"status": "unassigned", "page": 1, "page_size": 10}
            return {"items": [], "total": 0, "page": 1, "page_size": 10}

    monkeypatch.setattr(
        "tiangong_audit.cli.tiangong_api.TiangongAPIClient",
        lambda **kwargs: object(),
    )
    monkeypatch.setattr("tiangong_audit.cli.tiangong_api.ReviewAPI", FakeReviewAPI)

    args = Namespace(
        role="admin",
        status="unassigned",
        page=1,
        page_size=10,
        output=None,
    )
    assert fetch_tasks(args) == 0
    assert '"total": 0' in capsys.readouterr().out


def test_fetch_tasks_uses_member_account_for_member_queue(monkeypatch, capsys):
    class FakeReviewAPI:
        def __init__(self, client):
            assert client == "member-client"

        def get_member_tasks(self, **kwargs):
            assert kwargs == {"status": "pending", "page": 1, "page_size": 10}
            return {"items": [], "total": 0, "page": 1, "page_size": 10}

    def fake_client(*, account_role=None):
        assert account_role == "member"
        return "member-client"

    monkeypatch.setattr("tiangong_audit.cli.tiangong_api.TiangongAPIClient", fake_client)
    monkeypatch.setattr("tiangong_audit.cli.tiangong_api.ReviewAPI", FakeReviewAPI)

    args = Namespace(
        role="member",
        account_role=None,
        status=None,
        page=1,
        page_size=10,
        output=None,
    )
    assert fetch_tasks(args) == 0
    assert '"total": 0' in capsys.readouterr().out


def test_fetch_dataset_uses_explicit_account_role(monkeypatch, capsys):
    class FakeDatasetAPI:
        def __init__(self, client):
            assert client == "member-client"

        def resolve_dataset(self, dataset_id, version):
            return {"dataset_type": "process", "data": {"id": dataset_id, "version": version}}

    def fake_client(*, account_role=None):
        assert account_role == "member"
        return "member-client"

    monkeypatch.setattr("tiangong_audit.cli.tiangong_api.TiangongAPIClient", fake_client)
    monkeypatch.setattr("tiangong_audit.cli.tiangong_api.DatasetAPI", FakeDatasetAPI)

    args = Namespace(
        dataset_id="dataset-1",
        version="01.01.000",
        dataset_type="auto",
        account_role="member",
        output=None,
    )
    assert fetch_dataset(args) == 0
    assert '"dataset_type": "process"' in capsys.readouterr().out


def test_intake_review_parser_defaults_to_admin_account():
    args = build_parser().parse_args(["intake-review", "--review-id", "review-1"])

    assert args.account_role == "admin"


def test_fetch_dataset_reads_requested_type(monkeypatch, capsys):
    class FakeDatasetAPI:
        def __init__(self, client):
            pass

        def get_dataset(self, dataset_id, version, dataset_type):
            assert dataset_id == "dataset-1"
            assert version == "01.01.000"
            assert dataset_type.value == "process"
            return {"id": dataset_id, "version": version}

    monkeypatch.setattr(
        "tiangong_audit.cli.tiangong_api.TiangongAPIClient",
        lambda **kwargs: object(),
    )
    monkeypatch.setattr("tiangong_audit.cli.tiangong_api.DatasetAPI", FakeDatasetAPI)

    args = Namespace(
        dataset_id="dataset-1",
        version="01.01.000",
        dataset_type="process",
        output=None,
    )
    assert fetch_dataset(args) == 0
    assert '"id": "dataset-1"' in capsys.readouterr().out


def test_fetch_dataset_auto_resolves_type(monkeypatch, capsys):
    class FakeDatasetAPI:
        def __init__(self, client):
            pass

        def resolve_dataset(self, dataset_id, version):
            return {"dataset_type": "model", "data": {"id": dataset_id, "version": version}}

    monkeypatch.setattr(
        "tiangong_audit.cli.tiangong_api.TiangongAPIClient",
        lambda **kwargs: object(),
    )
    monkeypatch.setattr("tiangong_audit.cli.tiangong_api.DatasetAPI", FakeDatasetAPI)

    args = Namespace(
        dataset_id="dataset-1",
        version="01.01.000",
        dataset_type="auto",
        output=None,
    )
    assert fetch_dataset(args) == 0
    assert '"dataset_type": "model"' in capsys.readouterr().out


def test_list_actions_defaults_to_save_draft_without_platform_credentials(
    tmp_path, monkeypatch, capsys
):
    for name in (
        "TIANGONG_SUPABASE_URL",
        "TIANGONG_SUPABASE_ANON_KEY",
        "TIANGONG_SUPABASE_ACCESS_TOKEN",
    ):
        monkeypatch.delenv(name, raising=False)
    result_path = tmp_path / "result.json"
    result_path.write_text(
        '{"review_task_id":"review-1","dataset_id":"dataset-1",'
        '"conclusion":"manual_review","summary":"Needs review","findings":[]}',
        encoding="utf-8",
    )

    args = Namespace(result=str(result_path), output=None, format="json")

    assert list_actions(args) == 0
    output = capsys.readouterr().out
    assert '"operation": "save-draft"' in output
    assert '"action_type": "save_comment_draft"' in output
    assert '"action_type": "submit_review_comment"' not in output


def test_list_actions_can_explicitly_list_submit_action(tmp_path, monkeypatch, capsys):
    for name in (
        "TIANGONG_SUPABASE_URL",
        "TIANGONG_SUPABASE_ANON_KEY",
        "TIANGONG_SUPABASE_ACCESS_TOKEN",
    ):
        monkeypatch.delenv(name, raising=False)
    result_path = tmp_path / "result.json"
    result_path.write_text(
        '{"review_task_id":"review-1","dataset_id":"dataset-1",'
        '"conclusion":"approved","summary":"Ready to submit","findings":[]}',
        encoding="utf-8",
    )

    args = Namespace(
        result=str(result_path),
        output=None,
        format="json",
        operation="submit",
    )

    assert list_actions(args) == 0
    output = capsys.readouterr().out
    assert '"operation": "submit"' in output
    assert '"action_type": "submit_review_comment"' in output
    assert '"action_type": "save_comment_draft"' not in output


def test_submit_result_force_requires_explicit_confirm_phrase(tmp_path, monkeypatch, capsys):
    result_path = tmp_path / "result.json"
    result_path.write_text(
        '{"review_task_id":"review-1","dataset_id":"dataset-1",'
        '"conclusion":"approved","summary":"Approved","findings":[]}',
        encoding="utf-8",
    )

    def fail_client(**kwargs):
        raise AssertionError("write client must not be created without explicit confirmation")

    monkeypatch.setattr("tiangong_audit.cli.tiangong_api.TiangongAPIClient", fail_client)

    args = Namespace(
        result=str(result_path),
        output=None,
        force=True,
        confirm_submit=None,
        account_role="member",
    )

    assert submit_result(args) == 1
    assert "--confirm-submit app_review_submit_comment" in capsys.readouterr().err


def test_save_result_draft_dry_run_does_not_create_write_client(tmp_path, monkeypatch, capsys):
    result_path = tmp_path / "result.json"
    result_path.write_text(json.dumps(_routed_result(), ensure_ascii=False), encoding="utf-8")

    def fail_client(**kwargs):
        raise AssertionError("dry-run must not create a platform client")

    monkeypatch.setattr("tiangong_audit.cli.tiangong_api.TiangongAPIClient", fail_client)

    args = Namespace(
        result=str(result_path),
        review_id=None,
        account_role="reject",
        execute=False,
        output=None,
    )

    assert save_result_draft(args) == 0
    output = capsys.readouterr().out
    assert '"dry_run": true' in output
    assert '"operation": "app_review_save_comment_draft"' in output
    assert '"submitted": false' in output


def test_save_result_draft_execute_uses_reject_account(monkeypatch, tmp_path, capsys):
    result_path = tmp_path / "result.json"
    result_path.write_text(
        json.dumps(
            {
                "review_task_id": "review-1",
                "dataset_id": "dataset-1",
                "conclusion": "rejected",
                "summary": "Needs revision",
                "findings": [
                    {
                        "rule_id": "process.object.consistency",
                        "severity": "blocking",
                        "title": "对象不一致",
                        "description": "名称和技术描述冲突",
                        "related_field": "过程对象",
                        "suggested_fix": "统一过程对象描述。",
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    calls = {}

    def fake_client(**kwargs):
        calls["client"] = kwargs
        return "reject-client"

    class FakeReviewAPI:
        def __init__(self, client):
            assert client == "reject-client"

        def save_comment_draft(self, task_id, comment):
            calls["draft"] = {"task_id": task_id, "comment": comment}
            return {"ok": True}

    monkeypatch.setattr("tiangong_audit.cli.tiangong_api.TiangongAPIClient", fake_client)
    monkeypatch.setattr("tiangong_audit.cli.tiangong_api.ReviewAPI", FakeReviewAPI)

    args = Namespace(
        result=str(result_path),
        review_id=None,
        account_role="reject",
        execute=True,
        output=None,
    )

    assert save_result_draft(args) == 0
    assert calls["client"] == {"account_role": "reject", "allow_writes": True}
    assert calls["draft"]["task_id"] == "review-1"
    assert "统一过程对象描述。" in calls["draft"]["comment"]["findings"][0]["suggested_fix"]
    assert '"submitted": false' in capsys.readouterr().out


def test_save_result_draft_defaults_account_role_from_conclusion(monkeypatch, tmp_path, capsys):
    result_path = tmp_path / "result.json"
    result_path.write_text(
        json.dumps(
            {
                "review_task_id": "review-1",
                "dataset_id": "dataset-1",
                "conclusion": "approved",
                "summary": "Can pass",
                "findings": [],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    calls = {}

    def fake_client(**kwargs):
        calls["client"] = kwargs
        return "pass-client"

    class FakeReviewAPI:
        def __init__(self, client):
            assert client == "pass-client"

        def save_comment_draft(self, task_id, comment):
            calls["draft"] = {"task_id": task_id, "comment": comment}
            return {"ok": True}

    monkeypatch.setattr("tiangong_audit.cli.tiangong_api.TiangongAPIClient", fake_client)
    monkeypatch.setattr("tiangong_audit.cli.tiangong_api.ReviewAPI", FakeReviewAPI)

    assert save_result_draft(
        Namespace(
            result=str(result_path),
            review_id=None,
            batch_id=None,
            account_role=None,
            execute=True,
            output=None,
        )
    ) == 0

    assert calls["client"] == {"account_role": "pass", "allow_writes": True}
    assert calls["draft"]["task_id"] == "review-1"
    assert '"account_role": "pass"' in capsys.readouterr().out


def test_save_result_draft_execute_updates_case_and_operation_log(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr("tiangong_audit.cli.ROOT", tmp_path)
    assert create_case(
        Namespace(
            case_id="review-1",
            title="",
            batch_id="batch-1",
            dataset_id="dataset-1",
            version="01.01.000",
            dataset_type="process",
            name_zh="",
            name_en="",
            force=False,
        )
    ) == 0
    capsys.readouterr()
    result_path = (
        tmp_path
        / "cases/active/review-1/reports/audit-result.platform.json"
    )
    result_path.parent.mkdir(parents=True, exist_ok=True)
    result_path.write_text(json.dumps(_routed_result(), ensure_ascii=False), encoding="utf-8")

    def fake_client(**kwargs):
        return "reject-client"

    class FakeReviewAPI:
        def __init__(self, client):
            assert client == "reject-client"

        def save_comment_draft(self, task_id, comment):
            return {"ok": True, "review_id": task_id}

    monkeypatch.setattr("tiangong_audit.cli.tiangong_api.TiangongAPIClient", fake_client)
    monkeypatch.setattr("tiangong_audit.cli.tiangong_api.ReviewAPI", FakeReviewAPI)

    assert save_result_draft(
        Namespace(
            result=str(result_path),
            review_id=None,
            batch_id="batch-1",
            account_role="reject",
            execute=True,
            output=None,
        )
    ) == 0

    case_json = json.loads(
        (tmp_path / "cases/active/review-1/case.json").read_text(
            encoding="utf-8"
        )
    )
    assert case_json["status"] == "draft_saved"
    assert case_json["platform_state"] == "draft_saved"
    assert case_json["steps"]["platform_written"] is True
    oplog = (
        tmp_path / "cases/active/review-1/operations/oplog.jsonl"
    ).read_text(encoding="utf-8")
    assert '"operation": "app_review_save_comment_draft"' in oplog
    assert '"status": "completed"' in oplog


def test_validate_structure_writes_tidas_enhanced_result(tmp_path, monkeypatch, capsys):
    input_path = tmp_path / "dataset.json"
    input_path.write_text('{"processDataSet": {"processInformation": {}}}', encoding="utf-8")

    def fake_validate(payload, *, entity_type, mode, include_warnings, timeout):
        assert payload == {"processDataSet": {"processInformation": {}}}
        assert entity_type == "process"
        assert mode == "weak"
        assert include_warnings is True
        assert timeout == 15
        return {
            "success": False,
            "mode": "weak",
            "validationIssues": [{"code": "required_missing", "path": ["name"]}],
        }

    monkeypatch.setattr("tiangong_audit.cli.validate_enhanced", fake_validate)

    args = Namespace(
        input=str(input_path),
        output=None,
        entity_type="process",
        mode="weak",
        include_warnings=True,
        timeout=15,
        fail_on_error=True,
    )

    assert validate_structure(args) == 1
    output = capsys.readouterr().out
    assert '"success": false' in output
    assert '"required_missing"' in output


def test_process_pass_flow_cli_runs_workflow(monkeypatch, tmp_path, capsys):
    calls = {}

    class FakeWorkflow:
        def __init__(self, **kwargs):
            calls["init"] = kwargs

        def execute(self, review_id, output_dir, *, execute):
            calls["execute"] = {
                "review_id": review_id,
                "output_dir": output_dir,
                "execute": execute,
            }
            return {
                "task_id": review_id,
                "source_id": "source-1",
                "comment_state_code": 0,
            }

    monkeypatch.setattr("tiangong_audit.cli.ProcessPassWorkflow", FakeWorkflow)
    def fake_client(**kwargs):
        assert kwargs["account_role"] == "pass"
        return "pass-client"

    monkeypatch.setattr("tiangong_audit.cli.tiangong_api.TiangongAPIClient", fake_client)
    monkeypatch.setattr("tiangong_audit.cli.tiangong_api.ReviewAPI", lambda client: "review-api")
    monkeypatch.setattr("tiangong_audit.cli.tiangong_api.DatasetAPI", lambda client: "dataset-api")
    monkeypatch.setattr("tiangong_audit.cli._get_current_user_id", lambda client: "reviewer-1")

    args = Namespace(
        review_id="review-1",
        output_dir=str(tmp_path),
        account_role="pass",
        execute=True,
    )

    assert process_pass_flow(args) == 0
    assert calls["init"]["client"] == "pass-client"
    assert calls["init"]["review_api"] == "review-api"
    assert calls["init"]["dataset_api"] == "dataset-api"
    assert calls["init"]["current_user_id"] == "reviewer-1"
    assert calls["execute"] == {
        "review_id": "review-1",
        "output_dir": tmp_path,
        "execute": True,
    }
    assert '"source_id": "source-1"' in capsys.readouterr().out


def test_process_pass_flow_defaults_to_case_operations_dir(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr("tiangong_audit.cli.ROOT", tmp_path)
    assert create_case(
        Namespace(
            case_id="review-1",
            title="",
            batch_id="batch-1",
            dataset_id="dataset-1",
            version="01.01.000",
            dataset_type="process",
            name_zh="",
            name_en="",
            force=False,
        )
    ) == 0
    capsys.readouterr()
    calls = {}

    class FakeWorkflow:
        def __init__(self, **kwargs):
            pass

        def execute(self, review_id, output_dir, *, execute):
            calls["output_dir"] = output_dir
            calls["execute"] = execute
            return {"task_id": review_id, "dry_run": True}

    monkeypatch.setattr("tiangong_audit.cli.ProcessPassWorkflow", FakeWorkflow)
    monkeypatch.setattr(
        "tiangong_audit.cli.tiangong_api.TiangongAPIClient",
        lambda **kwargs: "pass-client",
    )
    monkeypatch.setattr("tiangong_audit.cli.tiangong_api.ReviewAPI", lambda client: "review-api")
    monkeypatch.setattr("tiangong_audit.cli.tiangong_api.DatasetAPI", lambda client: "dataset-api")
    monkeypatch.setattr("tiangong_audit.cli._get_current_user_id", lambda client: "reviewer-1")

    assert process_pass_flow(
        Namespace(
            review_id="review-1",
            batch_id="batch-1",
            output_dir=None,
            account_role="pass",
            execute=False,
            output=None,
        )
    ) == 0

    assert calls["output_dir"] == (
        tmp_path / "cases/active/review-1/operations/process-pass"
    )
    assert calls["execute"] is False
    oplog = (
        tmp_path / "cases/active/review-1/operations/oplog.jsonl"
    ).read_text(encoding="utf-8")
    assert '"operation": "process_pass_flow"' in oplog
    assert '"status": "dry_run"' in oplog


def test_case_cli_uses_canonical_case_store(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr("tiangong_audit.cli.ROOT", tmp_path)
    args = Namespace(
        case_id="review-1",
        title="自来水生产",
        batch_id="batch-1",
        dataset_id="dataset-1",
        version="01.01.000",
        dataset_type="process",
        name_zh="",
        name_en="Tap water production",
        force=False,
    )

    assert create_case(args) == 0
    assert (tmp_path / "cases/index.jsonl").exists()

    list_args = Namespace(status=None, format="jsonl", output=None)
    assert case_list(list_args) == 0
    assert '"review_id": "review-1"' in capsys.readouterr().out

    status_args = Namespace(review_id="review-1", batch_id=None, output=None)
    assert case_status(status_args) == 0
    assert '"dataset_id": "dataset-1"' in capsys.readouterr().out

    update_args = Namespace(
        review_id="review-1",
        batch_id=None,
        status="reported",
        conclusion="通过",
        platform_state="drafted",
        report="active/review-1/reports/audit-report.md",
        set_step=["reported"],
        clear_step=[],
        output=None,
    )
    assert case_update(update_args) == 0
    assert '"reported": true' in capsys.readouterr().out

    list_reported_args = Namespace(status="reported", format="jsonl", output=None)
    assert case_list(list_reported_args) == 0
    assert '"status": "reported"' in capsys.readouterr().out


def test_case_coverage_compares_queue_snapshot_with_local_cases(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr("tiangong_audit.cli.ROOT", tmp_path)
    assert create_case(
        Namespace(
            case_id="review-1",
            title="",
            batch_id="batch-1",
            dataset_id="dataset-1",
            version="01.01.000",
            dataset_type="process",
            name_zh="已写草稿数据",
            name_en="",
            force=False,
        )
    ) == 0
    assert create_case(
        Namespace(
            case_id="review-2",
            title="",
            batch_id="batch-1",
            dataset_id="dataset-2",
            version="01.01.000",
            dataset_type="process",
            name_zh="只完成 intake 数据",
            name_en="",
            force=False,
        )
    ) == 0
    capsys.readouterr()

    assert case_update(
        Namespace(
            review_id="review-1",
            batch_id="batch-1",
            status="draft_saved",
            conclusion="rejected",
            platform_state="draft_saved",
            report="active/review-1/reports/audit-result.platform.json",
            set_step=["reported", "platform_written"],
            clear_step=[],
            output=None,
        )
    ) == 0
    assert case_update(
        Namespace(
            review_id="review-2",
            batch_id="batch-1",
            status="intake_completed",
            conclusion=None,
            platform_state=None,
            report=None,
            set_step=["fetched", "normalized", "prechecked"],
            clear_step=[],
            output=None,
        )
    ) == 0
    capsys.readouterr()

    queue_path = tmp_path / "queue.json"
    queue_path.write_text(
        json.dumps(
            {
                "total": 3,
                "items": [
                    {
                        "id": "review-1",
                        "data_id": "dataset-1",
                        "data_version": "01.01.000",
                        "state_code": 1,
                    },
                    {
                        "id": "review-2",
                        "data_id": "dataset-2",
                        "data_version": "01.01.000",
                        "state_code": 1,
                    },
                    {
                        "id": "review-3",
                        "data_id": "dataset-3",
                        "data_version": "01.01.000",
                        "state_code": 1,
                        "json": {
                            "data": {
                                "name": {
                                    "baseName": [
                                        {"@xml:lang": "zh", "#text": "未开始数据"}
                                    ]
                                }
                            }
                        },
                    },
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    assert case_coverage(
        Namespace(queue=str(queue_path), format="json", output=None)
    ) == 0

    output = json.loads(capsys.readouterr().out)
    assert output["summary"] == {
        "draft_saved": 1,
        "intake_completed": 1,
        "not_started": 1,
    }
    assert output["items"][0]["reviewed"] is True
    assert output["items"][1]["next_step"] == "run semantic review and prepare report"
    assert output["items"][2]["name_zh"] == "未开始数据"


def test_source_cli_resolves_fetches_and_verifies_local_source(tmp_path, capsys):
    source_file = tmp_path / "report.txt"
    source_file.write_text("# Page 1\n\nReference year: 2021.", encoding="utf-8")
    dataset_path = tmp_path / "dataset.json"
    dataset_path.write_text(
        '{"referenceToDataSource":{"@type":"source data set",'
        f'"@refObjectId":"source-1","@uri":"{source_file}"}}}}',
        encoding="utf-8",
    )

    assert source_resolve(Namespace(input=str(dataset_path), output=None)) == 0
    assert '"source_id": "source-1"' in capsys.readouterr().out

    output_dir = tmp_path / "sources"
    assert source_fetch(Namespace(input=str(dataset_path), output_dir=str(output_dir), output=None)) == 0
    fetch_output = capsys.readouterr().out
    assert '"source_count": 1' in fetch_output
    extracted = output_dir / "source-001/extracted.md"
    assert extracted.exists()

    assert '"check_count": 0' in fetch_output


def test_source_claims_cli_generates_claim_json(tmp_path, capsys):
    dataset_path = tmp_path / "dataset.json"
    dataset_path.write_text(
        json.dumps(
            {
                "processDataSet": {
                    "processInformation": {
                        "dataSetInformation": {
                            "name": {
                                "baseName": [
                                    {
                                        "@xml:lang": "en",
                                        "#text": "Monocrystalline silicon rod",
                                    }
                                ]
                            }
                        },
                        "time": {"referenceYear": "2021"},
                    },
                    "exchanges": {
                        "exchange": [
                            {
                                "exchangeDirection": "Input",
                                "meanAmount": "1.25",
                                "referenceToFlowDataSet": {
                                    "common:shortDescription": {
                                        "@xml:lang": "en",
                                        "#text": "Electricity, medium voltage",
                                    }
                                },
                            },
                            {
                                "exchangeDirection": "Output",
                                "resultingAmount": "1",
                                "referenceToFlowDataSet": {
                                    "common:shortDescription": {
                                        "@xml:lang": "en",
                                        "#text": "Monocrystalline silicon rod",
                                    }
                                },
                            },
                        ]
                    },
                }
            }
        ),
        encoding="utf-8",
    )

    assert source_claims(Namespace(input=str(dataset_path), output=None)) == 0

    output = capsys.readouterr().out
    claims = json.loads(output)
    assert claims["process.name.en"] == "Monocrystalline silicon rod"
    assert claims["process.time.referenceYear"] == "2021"
    assert claims["process.exchange.input.1.name.en"] == "Electricity, medium voltage"
    assert claims["process.exchange.input.1.amount"] == "1.25"
    assert claims["process.exchange.output.1.name.en"] == "Monocrystalline silicon rod"


def test_review_intake_cli_delegates_to_workflow(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr("tiangong_audit.cli.ROOT", tmp_path)

    def fake_intake(review_id, **kwargs):
        assert review_id == "review-1"
        assert kwargs["root"] == tmp_path
        assert kwargs["account_role"] == "member"
        assert kwargs["batch_id"] == "batch-1"
        return {"review_id": review_id, "case_dir": "active/review-1"}

    monkeypatch.setattr("tiangong_audit.cli.intake_review", fake_intake)

    assert review_intake(
        Namespace(
            review_id="review-1",
            account_role="member",
            batch_id="batch-1",
            output=None,
        )
    ) == 0
    assert '"case_dir": "active/review-1"' in capsys.readouterr().out


def test_semantic_review_cli_delegates_to_workflow(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr("tiangong_audit.cli.ROOT", tmp_path)

    def fake_semantic_review(review_id, **kwargs):
        assert review_id == "review-1"
        assert kwargs["root"] == tmp_path
        assert kwargs["batch_id"] == "batch-1"
        return {
            "review_id": review_id,
            "conclusion": "不通过",
            "outputs": {"audit_result_platform": "active/review-1/reports/audit-result.platform.json"},
        }

    monkeypatch.setattr("tiangong_audit.cli.semantic_review", fake_semantic_review)

    assert review_semantic_review(
        Namespace(review_id="review-1", batch_id="batch-1", output=None)
    ) == 0

    output = capsys.readouterr().out
    assert '"conclusion": "不通过"' in output
    assert "audit-result.platform.json" in output


def test_source_fetch_updates_case_manifest_without_semantic_verification(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr("tiangong_audit.cli.ROOT", tmp_path)
    source_file = tmp_path / "report.txt"
    source_file.write_text("# Page 1\n\nBoundary: gate-to-gate.", encoding="utf-8")
    dataset_path = tmp_path / "dataset.json"
    dataset_path.write_text(
        '{"referenceToDataSource":{"@type":"source data set",'
        f'"@refObjectId":"source-1","@uri":"{source_file}"}}}}',
        encoding="utf-8",
    )
    assert create_case(
        Namespace(
            case_id="review-1",
            title="",
            batch_id="batch-1",
            dataset_id="dataset-1",
            version="01.01.000",
            dataset_type="process",
            name_zh="",
            name_en="",
            force=False,
        )
    ) == 0
    capsys.readouterr()

    assert source_fetch(
        Namespace(
            input=str(dataset_path),
            output_dir=None,
            review_id="review-1",
            batch_id=None,
            external_doc_base_url=None,
            output=None,
        )
    ) == 0
    assert (tmp_path / "cases/active/review-1/sources/source-001/extracted.md").exists()
    capsys.readouterr()

    assert case_status(Namespace(review_id="review-1", batch_id=None, output=None)) == 0
    status = capsys.readouterr().out
    assert '"sources_resolved": true' in status
    assert '"sources_downloaded": true' in status
    assert '"source_verified": false' in status


def test_agent_findings_template_and_validate_roundtrip(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr("tiangong_audit.cli.ROOT", tmp_path)
    assert create_case(
        Namespace(
            case_id="review-1",
            title="",
            batch_id="batch-1",
            dataset_id="dataset-1",
            version="01.01.000",
            dataset_type="process",
            name_zh="",
            name_en="",
            force=False,
        )
    ) == 0
    capsys.readouterr()

    assert agent_findings_template(
        Namespace(review_id="review-1", batch_id="batch-1", force=False)
    ) == 0
    findings_path = tmp_path / "cases/active/review-1/agent-review/agent-findings.json"
    assert findings_path.exists()
    # Refuses to overwrite without --force.
    assert agent_findings_template(
        Namespace(review_id="review-1", batch_id="batch-1", force=False)
    ) == 1
    capsys.readouterr()

    # Unfilled template must fail contract validation.
    assert agent_findings_validate(
        Namespace(review_id="review-1", batch_id="batch-1", input=None, dataset_type=None)
    ) == 1
    capsys.readouterr()

    payload = json.loads(findings_path.read_text(encoding="utf-8"))
    payload["reviewed_by"] = "agent"
    for review in payload["rule_reviews"]:
        review.update(
            {
                "verdict": "pass",
                "evidence": "字段与 source 摘录一致。",
                "evidence_refs": ["sources/source-001/extracted.md:p3"],
            }
        )
    findings_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    assert agent_findings_validate(
        Namespace(review_id="review-1", batch_id="batch-1", input=None, dataset_type=None)
    ) == 0
    assert "passed" in capsys.readouterr().out


def test_source_attach_extraction_cli_updates_manifest(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr("tiangong_audit.cli.ROOT", tmp_path)
    assert create_case(
        Namespace(
            case_id="review-1",
            title="",
            batch_id="batch-1",
            dataset_id="dataset-1",
            version="01.01.000",
            dataset_type="process",
            name_zh="",
            name_en="",
            force=False,
        )
    ) == 0
    capsys.readouterr()
    source_dir = tmp_path / "cases/active/review-1/sources/source-001"
    source_dir.mkdir(parents=True, exist_ok=True)
    (source_dir / "manifest.json").write_text(
        json.dumps(
            {
                "schema_version": "tiangong-audit-source-v1",
                "ref": {"source_id": "source-1"},
                "status": "extracted",
                "extracted_text_path": "extracted.md",
            }
        ),
        encoding="utf-8",
    )
    (source_dir / "extracted.md").write_text("basic text", encoding="utf-8")
    fulltext = tmp_path / "fulltext.md"
    fulltext.write_text("image-aware fulltext", encoding="utf-8")

    assert source_attach_extraction(
        Namespace(
            review_id="review-1",
            batch_id="batch-1",
            source_dir="source-001",
            extracted_text=str(fulltext),
            method="document-granular-decompose",
            output=None,
        )
    ) == 0
    output = capsys.readouterr().out
    assert "document-granular-decompose" in output
    assert (source_dir / "extracted.md").read_text(encoding="utf-8") == "image-aware fulltext"


def test_eval_score_cli_fails_under_coverage_threshold(tmp_path, capsys):
    result_path = tmp_path / "result.json"
    result_path.write_text(
        json.dumps({"conclusion": "通过", "findings": []}, ensure_ascii=False),
        encoding="utf-8",
    )
    exit_code = eval_score(
        Namespace(
            case_id="hc-heavy-naphtha-not-approved",
            result=str(result_path),
            evals=None,
            fail_under=0.5,
            require_conclusion_match=True,
            output=None,
        )
    )
    assert exit_code == 1
    captured = capsys.readouterr()
    assert "conclusion mismatch" in captured.err
    assert "coverage" in captured.err


def test_new_subcommands_are_registered():
    parser = build_parser()
    args = parser.parse_args(
        [
            "agent-findings",
            "validate",
            "--input",
            "some.json",
            "--dataset-type",
            "process",
        ]
    )
    assert args.func is agent_findings_validate
    args = parser.parse_args(
        [
            "source",
            "attach-extraction",
            "--review-id",
            "r1",
            "--source-dir",
            "source-001",
            "--extracted-text",
            "full.md",
        ]
    )
    assert args.func is source_attach_extraction
    args = parser.parse_args(
        ["eval", "score", "--case-id", "c1", "--result", "r.json"]
    )
    assert args.func is eval_score


def test_required_paths_include_platform_modules_and_test():
    from tiangong_audit.cli import REQUIRED_PATHS

    assert "src/tiangong_audit/contracts/platform.py" in REQUIRED_PATHS
    assert "src/tiangong_audit/report/platform.py" in REQUIRED_PATHS
    assert "tests/test_platform_opinion.py" in REQUIRED_PATHS
