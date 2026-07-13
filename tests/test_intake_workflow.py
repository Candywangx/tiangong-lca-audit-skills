import json
import re

from tiangong_audit.case_store import CaseStore
from tiangong_audit.workflows import intake_review


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

    def select(self, table, *, columns="*", filters=None, limit=None):
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


class FakeFlowPlatformClient(FakePlatformClient):
    def __init__(self):
        super().__init__()
        self.flow_calls = []

    def select(self, table, *, columns="*", filters=None, limit=None):
        if table == "processes":
            row = super().select(table, columns=columns, filters=filters, limit=limit)[0]
            process = row["json"]["processDataSet"]
            process["processInformation"]["dataSetInformation"][
                "referenceToReferenceFlow"
            ] = "0"
            process["exchanges"] = {
                "exchange": [
                    {
                        "@dataSetInternalID": "0",
                        "exchangeDirection": "Output",
                        "meanAmount": "1",
                        "referenceToFlowDataSet": {
                            "@refObjectId": "flow-steel",
                            "@version": "01.00.000",
                            "common:shortDescription": {
                                "@xml:lang": "zh",
                                "#text": "钢构件",
                            },
                        },
                    },
                    {
                        "@dataSetInternalID": "1",
                        "exchangeDirection": "Input",
                        "meanAmount": "2",
                        "referenceToFlowDataSet": {
                            "@refObjectId": "flow-steel",
                            "@version": "01.00.000",
                            "common:shortDescription": {
                                "@xml:lang": "zh",
                                "#text": "钢材",
                            },
                        },
                    },
                ]
            }
            return [row]
        if table == "flows":
            self.flow_calls.append((filters["id"], filters.get("version")))
            return [
                {
                    "id": "flow-steel",
                    "version": "01.00.000",
                    "json": {
                        "flowDataSet": {
                            "flowInformation": {
                                "dataSetInformation": {
                                    "name": {
                                        "baseName": {
                                            "@xml:lang": "zh",
                                            "#text": "钢材",
                                        }
                                    },
                                    "classificationInformation": {
                                        "common:classification": {
                                            "common:class": {
                                                "@level": "1",
                                                "#text": "Steel products",
                                            }
                                        }
                                    },
                                }
                            },
                            "modellingAndValidation": {
                                "LCIMethod": {"typeOfDataSet": "Product flow"}
                            },
                        }
                    },
                }
            ]
        return super().select(table, columns=columns, filters=filters, limit=limit)


def test_intake_enriches_unique_related_flows_before_precheck(tmp_path):
    store = CaseStore(tmp_path / "cases")
    client = FakeFlowPlatformClient()

    summary = intake_review(
        "review-1",
        root=tmp_path,
        account_role="member",
        batch_id="batch-flow",
        case_store=store,
        client=client,
    )

    case_dir = tmp_path / "cases" / summary["case_dir"]
    assert client.flow_calls == [("eq.flow-steel", "eq.01.00.000")]
    assert (case_dir / "snapshots/dataset.enriched.json").exists()
    assert (case_dir / "snapshots/flow-metadata.json").exists()
    normalized = json.loads(
        (case_dir / "snapshots/dataset.normalized.json").read_text(encoding="utf-8")
    )
    exchanges = [
        *normalized["exchanges"]["inputs"],
        *normalized["exchanges"]["outputs"],
    ]
    assert {item["flow_metadata_status"] for item in exchanges} == {"resolved"}
    assert {item["flow_type"] for item in exchanges} == {"Product flow"}
    assert all(item["classification"] for item in exchanges)
    precheck = json.loads(
        (case_dir / "precheck/precheck.json").read_text(encoding="utf-8")
    )
    assert not any(
        item["rule_id"] == "process.flow.semantic_match"
        for item in precheck["findings"]
    )


class MissingFlowPlatformClient(FakeFlowPlatformClient):
    def select(self, table, *, columns="*", filters=None, limit=None):
        if table == "flows":
            self.flow_calls.append((filters["id"], filters.get("version")))
            return []
        return super().select(table, columns=columns, filters=filters, limit=limit)


def test_intake_flow_lookup_gap_does_not_blame_submitter(tmp_path):
    store = CaseStore(tmp_path / "cases")
    client = MissingFlowPlatformClient()

    summary = intake_review(
        "review-1",
        root=tmp_path,
        account_role="member",
        batch_id="batch-missing-flow",
        case_store=store,
        client=client,
    )

    case_dir = tmp_path / "cases" / summary["case_dir"]
    precheck = json.loads(
        (case_dir / "precheck/precheck.json").read_text(encoding="utf-8")
    )
    metadata_findings = [
        item
        for item in precheck["findings"]
        if item["rule_id"] == "process.flow.semantic_match"
    ]
    assert len(metadata_findings) == 2
    assert {item["severity"] for item in metadata_findings} == {"input_gap"}
    assert all("不能据此认定提交者" in item["judgment"] for item in metadata_findings)
    flow_metadata = json.loads(
        (case_dir / "snapshots/flow-metadata.json").read_text(encoding="utf-8")
    )
    assert flow_metadata["flows"][0]["status"] == "not_found"


class IncompleteFlowPlatformClient(FakeFlowPlatformClient):
    def select(self, table, *, columns="*", filters=None, limit=None):
        if table == "flows":
            self.flow_calls.append((filters["id"], filters.get("version")))
            return [
                {
                    "id": "flow-steel",
                    "version": "01.00.000",
                    "json": {"flowDataSet": {"flowInformation": {}}},
                }
            ]
        return super().select(table, columns=columns, filters=filters, limit=limit)


def test_intake_resolved_flow_with_genuinely_missing_metadata_is_blocking(tmp_path):
    store = CaseStore(tmp_path / "cases")
    client = IncompleteFlowPlatformClient()

    summary = intake_review(
        "review-1",
        root=tmp_path,
        account_role="member",
        batch_id="batch-incomplete-flow",
        case_store=store,
        client=client,
    )

    case_dir = tmp_path / "cases" / summary["case_dir"]
    precheck = json.loads(
        (case_dir / "precheck/precheck.json").read_text(encoding="utf-8")
    )
    metadata_findings = [
        item
        for item in precheck["findings"]
        if item["rule_id"] == "process.flow.semantic_match"
    ]
    assert len(metadata_findings) == 2
    assert {item["severity"] for item in metadata_findings} == {"blocking"}


class VersionlessFlowPlatformClient(FakeFlowPlatformClient):
    def select(self, table, *, columns="*", filters=None, limit=None):
        rows = super().select(table, columns=columns, filters=filters, limit=limit)
        if table == "processes":
            exchanges = rows[0]["json"]["processDataSet"]["exchanges"]["exchange"]
            for exchange in exchanges:
                exchange["referenceToFlowDataSet"].pop("@version", None)
        return rows


def test_intake_does_not_guess_version_for_versionless_flow_reference(tmp_path):
    store = CaseStore(tmp_path / "cases")
    client = VersionlessFlowPlatformClient()

    summary = intake_review(
        "review-1",
        root=tmp_path,
        account_role="member",
        batch_id="batch-versionless-flow",
        case_store=store,
        client=client,
    )

    case_dir = tmp_path / "cases" / summary["case_dir"]
    assert client.flow_calls == []
    flow_metadata = json.loads(
        (case_dir / "snapshots/flow-metadata.json").read_text(encoding="utf-8")
    )
    assert flow_metadata["flows"] == [
        {
            "flow_id": "flow-steel",
            "version": "",
            "status": "not_fetched",
            "reference_count": 2,
            "error": "exchange flow reference has no version",
        }
    ]


class FakeModelPlatformClient:
    def __init__(self):
        self.flow_calls = []

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

    def select(self, table, *, columns="*", filters=None, limit=None):
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
                                            "@refObjectId": "flow-aluminium-powder",
                                            "@version": "01.00.000",
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
        if table == "flows":
            self.flow_calls.append((filters["id"], filters.get("version")))
            return [
                {
                    "id": "flow-aluminium-powder",
                    "version": "01.00.000",
                    "json": {
                        "flowDataSet": {
                            "flowInformation": {
                                "dataSetInformation": {
                                    "classificationInformation": {
                                        "common:classification": {
                                            "common:class": {
                                                "@level": "1",
                                                "#text": "Metal products",
                                            }
                                        }
                                    }
                                }
                            },
                            "modellingAndValidation": {
                                "LCIMethod": {"typeOfDataSet": "Product flow"}
                            },
                        }
                    },
                }
            ]
        raise AssertionError(f"unexpected table: {table}")


def test_model_intake_materializes_linked_process_evidence(tmp_path):
    store = CaseStore(tmp_path / "cases")
    client = FakeModelPlatformClient()
    summary = intake_review(
        "review-model-1",
        root=tmp_path,
        account_role="member",
        batch_id="batch-model",
        case_store=store,
        client=client,
    )

    case_dir = tmp_path / "cases" / summary["case_dir"]
    assert summary["dataset_type"] == "model"
    assert summary["model_evidence_summary"]["linked_process_ref_count"] == 1
    assert summary["model_evidence_summary"]["linked_process_fetched_count"] == 1
    assert (case_dir / "snapshots/model-linked-process-refs.json").exists()
    assert list((case_dir / "snapshots/linked-processes").glob("*.json"))
    assert client.flow_calls == [
        ("eq.flow-aluminium-powder", "eq.01.00.000")
    ]
    assert list(
        (case_dir / "snapshots/linked-processes").glob(
            "*.evidence/related-flows/*.json"
        )
    )
    assert list((case_dir / "precheck/linked-processes").glob("*.precheck.json"))
    precheck_path = next(
        (case_dir / "precheck/linked-processes").glob("*.precheck.json")
    )
    precheck = json.loads(precheck_path.read_text(encoding="utf-8"))
    assert not any(
        item["rule_id"] == "process.flow.semantic_match"
        for item in precheck["findings"]
    )
