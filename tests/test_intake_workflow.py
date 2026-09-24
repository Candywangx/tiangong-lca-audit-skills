import json
import re
from copy import deepcopy

import pytest

from tiangong_audit.case_store import CaseStore
from tiangong_audit.workflows import intake_review
from tiangong_audit.workflows.title_duplicate import require_title_duplicate_clearance


class FakePlatformClient:
    def __init__(self):
        self.downloads = []

    def rpc(self, name, payload):
        assert name == "qry_review_get_items"
        assert payload["p_review_ids"] == ["review-1"]
        return [
            {
                "id": "review-1",
                "data_id": "process-1",
                "data_version": "01.01.000",
                "state_code": 1,
            }
        ]

    def select(self, table, *, columns="*", filters=None, limit=None, offset=None):
        if offset:
            return []
        if table == "lifecyclemodels":
            return []
        if table == "processes":
            return [
                {
                    "id": "process-1",
                    "version": "01.01.000",
                    "json": {
                        "processDataSet": {
                            "processInformation": {
                                "dataSetInformation": {
                                    "name": {
                                        "baseName": [
                                            {
                                                "@xml:lang": "zh",
                                                "#text": "单晶硅棒",
                                            },
                                            {
                                                "@xml:lang": "en",
                                                "#text": "Monocrystalline silicon rod",
                                            },
                                        ]
                                    }
                                },
                                "time": {"referenceYear": "2021"},
                            },
                            "modellingAndValidation": {
                                "LCIMethodAndAllocation": {
                                    "typeOfDataSet": "Unit process, black box"
                                },
                                "dataSourcesTreatmentAndRepresentativeness": {
                                    "referenceToDataSource": {
                                        "@type": "source data set",
                                        "@refObjectId": "source-1",
                                        "@version": "01.00.000",
                                        "@uri": "../sources/source-1.xml",
                                    }
                                },
                            },
                        }
                    },
                }
            ]
        if table == "sources":
            return [
                {
                    "id": "source-1",
                    "version": "01.00.000",
                    "json": {
                        "sourceDataSet": {
                            "sourceInformation": {
                                "dataSetInformation": {
                                    "common:UUID": "source-1",
                                    "referenceToDigitalFile": {
                                        "@uri": "../external_docs/report.txt"
                                    },
                                }
                            },
                            "administrativeInformation": {
                                "publicationAndOwnership": {
                                    "common:dataSetVersion": "01.00.000"
                                }
                            },
                        }
                    },
                }
            ]
        raise AssertionError(f"unexpected table: {table}")

    def download_external_doc(self, object_name, output_path):
        self.downloads.append(object_name)
        output_path.write_text(
            "# Page 1\n\n单晶硅棒 Monocrystalline silicon rod 2021.",
            encoding="utf-8",
        )
        return {"content_type": "text/plain", "path": str(output_path)}


def test_intake_review_fetches_task_dataset_sources_and_claims(tmp_path):
    store = CaseStore(tmp_path / "cases")
    summary = intake_review(
        "review-1",
        root=tmp_path,
        account_role="member",
        batch_id="batch-1",
        case_store=store,
        client=FakePlatformClient(),
    )

    case_dir = tmp_path / "cases" / summary["case_dir"]
    assert summary["dataset_id"] == "process-1"
    assert summary["dataset_type"] == "process"
    assert summary["claim_count"] >= 2
    assert summary["source_count"] == 1
    assert summary["check_count"] == 0
    assert (case_dir / "snapshots/review-task.json").exists()
    assert (case_dir / "snapshots/dataset.raw.json").exists()
    assert (case_dir / "sources/source-001/extracted.md").exists()
    assert (case_dir / "source-checks/claims.json").exists()
    assert not (case_dir / "source-checks/checks.json").exists()
    manifest = store.get_case("review-1", batch_id="batch-1")
    assert manifest.steps["fetched"] is True
    assert manifest.steps["sources_downloaded"] is True
    assert manifest.steps["source_verified"] is False
    assert manifest.status == "intake_completed"


def test_intake_pauses_before_audit_when_same_title_and_content_have_other_uuid(tmp_path):
    class DuplicatePlatformClient(FakePlatformClient):
        def select(self, table, *, columns="*", filters=None, limit=None, offset=None):
            if offset:
                return []
            if table == "processes" and "json" in (filters or {}):
                current = super().select(table, columns=columns, filters=filters, limit=limit)[0]
                duplicate = deepcopy(current)
                duplicate["id"] = "process-other"
                return [current, duplicate]
            return super().select(table, columns=columns, filters=filters, limit=limit)

    client = DuplicatePlatformClient()
    store = CaseStore(tmp_path / "cases")

    summary = intake_review(
        "review-1", root=tmp_path, batch_id="batch-1", case_store=store, client=client
    )

    case_root = tmp_path / "cases" / summary["case_dir"]
    check = json.loads((case_root / "snapshots/title-duplicate-check.json").read_text())
    assert summary["status"] == "paused_duplicate_confirmation"
    assert check["identical_candidates"] == [{"id": "process-other", "version": "01.01.000"}]
    assert store.get_case("review-1", batch_id="batch-1").status == "paused_duplicate_confirmation"
    assert not (case_root / "source-checks/claims.json").exists()
    assert client.downloads == []

    confirmation = {
        "decision": "continue",
        "reviewer": "审核员甲",
        "confirmed_at": "2026-09-24T10:00:00+08:00",
        "search_fingerprint": check["search_fingerprint"],
        "candidate_ids": ["process-other@01.01.000"],
    }
    confirmation_path = case_root / "agent-review/title-duplicate-confirmation.json"
    confirmation_path.parent.mkdir(exist_ok=True)
    confirmation_path.write_text(json.dumps(confirmation, ensure_ascii=False))

    resumed = intake_review(
        "review-1", root=tmp_path, batch_id="batch-1", case_store=store, client=client
    )

    assert resumed["status"] == "intake_completed"
    assert (case_root / "source-checks/claims.json").exists()


def test_failed_repeat_search_invalidates_previous_clearance(tmp_path):
    store = CaseStore(tmp_path / "cases")
    summary = intake_review(
        "review-1", root=tmp_path, batch_id="batch-1", case_store=store,
        client=FakePlatformClient(),
    )
    case_root = tmp_path / "cases" / summary["case_dir"]

    class SearchFailureClient(FakePlatformClient):
        def select(self, table, *, columns="*", filters=None, limit=None, offset=None):
            if "json" in (filters or {}):
                raise RuntimeError("search unavailable")
            return super().select(table, columns=columns, filters=filters, limit=limit, offset=offset)

    with pytest.raises(RuntimeError, match="search unavailable"):
        intake_review(
            "review-1", root=tmp_path, batch_id="batch-1", case_store=store,
            client=SearchFailureClient(),
        )
    with pytest.raises(ValueError, match="题目查重"):
        require_title_duplicate_clearance(case_root, "process-1", "01.01.000", "process")


def test_intake_review_default_batch_id_uses_date_and_account_role(tmp_path):
    store = CaseStore(tmp_path / "cases")
    summary = intake_review(
        "review-1",
        root=tmp_path,
        case_store=store,
        client=FakePlatformClient(),
    )

    assert re.fullmatch(r"\d{8}-admin", summary["batch_id"])
    assert summary["case_dir"] == "active/review-1"


class FakeModelPlatformClient:
    def rpc(self, name, payload):
        assert name == "qry_review_get_items"
        return [
            {
                "id": "review-model-1",
                "data_id": "model-1",
                "data_version": "01.01.000",
                "state_code": 1,
            }
        ]

    def select(self, table, *, columns="*", filters=None, limit=None, offset=None):
        if offset:
            return []
        if table == "lifecyclemodels":
            return [
                {
                    "id": "model-1",
                    "version": "01.01.000",
                    "json": {
                        "lifeCycleModelDataSet": {
                            "lifeCycleModelInformation": {
                                "dataSetInformation": {
                                    "name": {
                                        "baseName": [
                                            {"@xml:lang": "zh", "#text": "铝粉模型"}
                                        ]
                                    },
                                    "referenceToProcessDataSet": {
                                        "@type": "process data set",
                                        "@refObjectId": "process-1",
                                        "@version": "01.01.000",
                                        "@uri": "../processes/process-1.xml",
                                    },
                                }
                            }
                        }
                    },
                }
            ]
        if table == "processes":
            assert filters["id"] == "eq.process-1"
            return [
                {
                    "id": "process-1",
                    "version": "01.01.000",
                    "json": {
                        "processDataSet": {
                            "processInformation": {
                                "dataSetInformation": {
                                    "name": {
                                        "baseName": [
                                            {
                                                "@xml:lang": "zh",
                                                "#text": "铝粉生产",
                                            }
                                        ]
                                    },
                                    "referenceToReferenceFlow": "0",
                                },
                                "time": {"referenceYear": "2021"},
                            },
                            "modellingAndValidation": {
                                "LCIMethodAndAllocation": {
                                    "typeOfDataSet": "Unit process, black box"
                                }
                            },
                            "exchanges": {
                                "exchange": [
                                    {
                                        "@dataSetInternalID": "0",
                                        "referenceToReferenceFlow": True,
                                        "referenceToFlowDataSet": {
                                            "common:shortDescription": [
                                                {"@xml:lang": "zh", "#text": "铝粉"}
                                            ]
                                        },
                                        "resultingAmount": "1",
                                    }
                                ]
                            },
                        }
                    },
                }
            ]
        raise AssertionError(f"unexpected table: {table}")


def test_model_intake_materializes_linked_process_evidence(tmp_path):
    store = CaseStore(tmp_path / "cases")
    summary = intake_review(
        "review-model-1",
        root=tmp_path,
        account_role="member",
        batch_id="batch-model",
        case_store=store,
        client=FakeModelPlatformClient(),
    )

    case_dir = tmp_path / "cases" / summary["case_dir"]
    assert summary["dataset_type"] == "model"
    assert summary["model_evidence_summary"]["linked_process_ref_count"] == 1
    assert summary["model_evidence_summary"]["linked_process_fetched_count"] == 1
    assert (case_dir / "snapshots/model-linked-process-refs.json").exists()
    assert list((case_dir / "snapshots/linked-processes").glob("*.json"))
    assert list((case_dir / "precheck/linked-processes").glob("*.precheck.json"))
