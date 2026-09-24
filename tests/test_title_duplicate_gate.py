import json

import pytest

from tiangong_audit.workflows.title_duplicate import (
    check_title_duplicates,
    require_title_duplicate_clearance,
)


def process_row(dataset_id, *, amount="1", title="单晶硅棒"):
    return {
        "id": dataset_id,
        "version": "01.01.000",
        "json": {
            "processDataSet": {
                "processInformation": {
                    "dataSetInformation": {
                        "common:UUID": dataset_id,
                        "name": {"baseName": [{"@xml:lang": "zh", "#text": title}]},
                    }
                },
                "exchanges": {"exchange": [{"amount": amount}]},
            }
        },
    }


def model_row(dataset_id):
    return {
        "id": dataset_id,
        "version": "01.01.000",
        "json_tg": {
            "lifeCycleModelDataSet": {
                "lifeCycleModelInformation": {
                    "dataSetInformation": {
                        "common:UUID": dataset_id,
                        "name": {"baseName": [
                            {"@xml:lang": "zh", "#text": "单晶硅模型"},
                            {"@xml:lang": "en", "#text": "Monocrystalline silicon model"},
                        ]},
                    }
                },
                "model": {"nodes": ["process-a"]},
            }
        },
    }


class FakeDatasetAPI:
    def __init__(self, rows):
        self.rows = rows
        self.calls = []

    def search_title(self, dataset_type, language, title):
        self.calls.append((dataset_type, language, title))
        return self.rows


def test_same_title_and_different_uuid_with_identical_content_pauses():
    current = process_row("current")
    api = FakeDatasetAPI([current, process_row("other")])

    result = check_title_duplicates(current, "process", api)

    assert api.calls == [("process", "zh", "单晶硅棒")]
    assert result["status"] == "awaiting_human_confirmation"
    assert result["identical_candidates"] == [{"id": "other", "version": "01.01.000"}]
    assert result["matches"][0]["content_identical"] is True
    assert result["candidate_rows"][0]["json"]["processDataSet"]["exchanges"]["exchange"] == [
        {"amount": "1"}
    ]


def test_model_search_checks_both_localized_titles_before_pausing():
    current = model_row("model-current")
    api = FakeDatasetAPI([current, model_row("model-other")])

    result = check_title_duplicates(current, "model", api)

    assert api.calls == [
        ("model", "zh", "单晶硅模型"),
        ("model", "en", "Monocrystalline silicon model"),
    ]
    assert result["identical_candidates"] == [{"id": "model-other", "version": "01.01.000"}]


def test_model_with_different_graph_json_is_not_identical():
    current = model_row("model-current")
    other = model_row("model-other")
    current["json"] = {"graph": {"nodes": ["process-a"]}}
    other["json"] = {"graph": {"nodes": ["process-b"]}}

    result = check_title_duplicates(current, "model", FakeDatasetAPI([current, other]))

    assert result["status"] == "clear"
    assert result["matches"][0]["content_identical"] is False


def test_same_title_with_different_content_can_continue():
    current = process_row("current")

    result = check_title_duplicates(
        current, "process", FakeDatasetAPI([current, process_row("other", amount="2")])
    )

    assert result["status"] == "clear"
    assert result["matches"] == [{"id": "other", "version": "01.01.000", "content_identical": False}]


def test_same_title_and_body_with_different_version_is_not_identical():
    current = process_row("current")
    other = process_row("other")
    other["version"] = "02.00.000"

    result = check_title_duplicates(current, "process", FakeDatasetAPI([current, other]))

    assert result["status"] == "clear"
    assert result["matches"][0]["content_identical"] is False


def test_search_without_current_row_cannot_claim_clear():
    with pytest.raises(ValueError, match="搜索结果无法验证"):
        check_title_duplicates(process_row("current"), "process", FakeDatasetAPI([]))


def test_stale_search_result_for_current_uuid_cannot_claim_clear():
    with pytest.raises(ValueError, match="搜索结果无法验证"):
        check_title_duplicates(
            process_row("current", amount="1"), "process",
            FakeDatasetAPI([process_row("current", amount="2")]),
        )


def test_exact_duplicate_needs_specific_human_confirmation(tmp_path):
    check = check_title_duplicates(
        process_row("current"), "process",
        FakeDatasetAPI([process_row("current"), process_row("other")]),
    )
    path = tmp_path / "snapshots/title-duplicate-check.json"
    path.parent.mkdir()
    path.write_text(json.dumps(check, ensure_ascii=False))
    (tmp_path / "snapshots/dataset.raw.json").write_text(
        json.dumps(process_row("current")["json"], ensure_ascii=False)
    )

    with pytest.raises(ValueError, match="人工确认"):
        require_title_duplicate_clearance(tmp_path, "current", "01.01.000", "process")

    confirmation = {
        "decision": "continue",
        "reviewer": "审核员甲",
        "confirmed_at": "2026-09-24T10:00:00+08:00",
        "search_fingerprint": check["search_fingerprint"],
        "candidate_ids": ["other@01.01.000"],
    }
    confirmation_path = tmp_path / "agent-review/title-duplicate-confirmation.json"
    confirmation_path.parent.mkdir()
    confirmation_path.write_text(json.dumps(confirmation, ensure_ascii=False))
    require_title_duplicate_clearance(tmp_path, "current", "01.01.000", "process")

    confirmation["search_fingerprint"] = "stale"
    confirmation_path.write_text(json.dumps(confirmation, ensure_ascii=False))
    with pytest.raises(ValueError, match="人工确认"):
        require_title_duplicate_clearance(tmp_path, "current", "01.01.000", "process")

    confirmation["search_fingerprint"] = check["search_fingerprint"]
    confirmation["candidate_ids"] = [{"id": "other", "version": "01.01.000"}]
    confirmation_path.write_text(json.dumps(confirmation, ensure_ascii=False))
    with pytest.raises(ValueError, match="人工确认"):
        require_title_duplicate_clearance(tmp_path, "current", "01.01.000", "process")


def test_changed_current_content_invalidates_prior_title_search(tmp_path):
    check = check_title_duplicates(
        process_row("current"), "process", FakeDatasetAPI([process_row("current")])
    )
    snapshots = tmp_path / "snapshots"
    snapshots.mkdir()
    (snapshots / "title-duplicate-check.json").write_text(json.dumps(check, ensure_ascii=False))
    (snapshots / "dataset.raw.json").write_text(
        json.dumps(process_row("current", amount="2")["json"], ensure_ascii=False)
    )

    with pytest.raises(ValueError, match="题目查重记录已过期"):
        require_title_duplicate_clearance(tmp_path, "current", "01.01.000", "process")


def test_missing_title_search_evidence_stops_audit(tmp_path):
    with pytest.raises(ValueError, match="题目查重"):
        require_title_duplicate_clearance(tmp_path, "current", "01.01.000", "process")
