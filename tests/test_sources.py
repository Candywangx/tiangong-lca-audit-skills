import json

from tiangong_audit.contracts import SourceCheck, SourceRef
from tiangong_audit.contracts.platform import PlatformProjection
from tiangong_audit.contracts.source import validate_source_checks
from tiangong_audit.sources import (
    download_platform_external_doc,
    download_source_artifact,
    extract_source_text,
    generate_source_claims,
    resolve_source_refs,
    with_external_doc_base,
)
from tiangong_audit.case_store import CaseStore
from tiangong_audit.workflows import attach_extraction, fetch_sources


def _source_check_payload(status, **overrides):
    payload = {
        "field": "process.time.referenceYear",
        "dataset_value": "2021",
        "source_ref_id": "source-1",
        "status": status,
    }
    payload.update(overrides)
    return payload


def test_source_check_defaults_severity_by_status():
    expected = {
        "matched": None,
        "not_applicable": None,
        "conflict": "blocking",
        "ambiguous": "manual_review",
        "not_found": "manual_review",
        "source_unavailable": "input_gap",
        "download_failed": "input_gap",
        "extraction_failed": "input_gap",
    }

    for status, severity in expected.items():
        check = SourceCheck.from_dict(_source_check_payload(status))
        assert check.resolved_severity() == severity


def test_source_check_platform_round_trip():
    original = SourceCheck(
        field="process.time.referenceYear",
        dataset_value="2021",
        source_ref_id="source-1",
        status="conflict",
        severity="blocking",
        platform=PlatformProjection(
            disposition="required",
            message="请修正参考年，或补充来源依据。",
        ),
    )

    restored = SourceCheck.from_dict(original.to_dict())

    assert restored.severity == "blocking"
    assert restored.platform == original.platform
    assert restored.to_dict() == original.to_dict()


def test_source_check_full_field_round_trip_and_legacy_positional_order():
    legacy = SourceCheck(
        "process.name.zh",
        "叶片制造",
        "source-1",
        "ambiguous",
        "来源仅说明叶片",
        3,
        "需要补充依据",
        "source.name.match",
        "source-checked",
        "blade manufacturing",
        "措辞不完全一致",
        {"reviewer": "synthetic"},
    )
    assert legacy.evidence == "来源仅说明叶片"
    assert legacy.page == 3
    assert legacy.extra == {"reviewer": "synthetic"}
    assert legacy.severity is None
    assert legacy.platform is None

    original = SourceCheck(
        field=legacy.field,
        dataset_value=legacy.dataset_value,
        source_ref_id=legacy.source_ref_id,
        status=legacy.status,
        evidence=legacy.evidence,
        page=legacy.page,
        notes=legacy.notes,
        rule_id=legacy.rule_id,
        checked_source_id=legacy.checked_source_id,
        matched_excerpt=legacy.matched_excerpt,
        confidence_reason=legacy.confidence_reason,
        extra=legacy.extra,
        severity="advisory",
        platform={
            "disposition": "suggested",
            "message": "建议补充来源中的完整名称。",
        },
    )
    assert isinstance(original.platform, PlatformProjection)
    assert SourceCheck.from_dict(original.to_dict()).to_dict() == original.to_dict()


def test_source_check_direct_platform_construction_rejects_invalid_type():
    try:
        SourceCheck("field", "value", "source-1", "conflict", platform="required")
    except ValueError as exc:
        assert "platform projection must be an object" in str(exc)
    else:
        raise AssertionError("invalid direct platform construction must fail")


def test_platform_projection_direct_construction_enforces_invariants():
    invalid = [
        {"disposition": 1, "message": "请修正。"},
        {"disposition": "unknown", "message": "请修正。"},
        {"disposition": "required", "message": 1},
        {"disposition": "required", "message": "   "},
        {"disposition": "internal_only", "message": "不应出现"},
        {"disposition": "internal_only", "message": "   "},
    ]
    for kwargs in invalid:
        try:
            PlatformProjection(**kwargs)
        except ValueError:
            pass
        else:
            raise AssertionError(f"direct construction must reject {kwargs!r}")

    projection = PlatformProjection(
        disposition="clarification",
        message="  请说明参考年的依据。  ",
    )
    assert projection.message == "请说明参考年的依据。"


def test_validate_source_checks_rejects_invalid_status_severity():
    valid_matrix = {
        "matched": (None,),
        "not_applicable": (None,),
        "conflict": (None, "blocking", "advisory"),
        "ambiguous": (None, "manual_review", "advisory"),
        "not_found": (None, "manual_review", "advisory"),
        "source_unavailable": (None, "input_gap", "manual_review", "advisory"),
        "download_failed": (None, "input_gap", "manual_review", "advisory"),
        "extraction_failed": (None, "input_gap", "manual_review", "advisory"),
    }
    all_severities = {"blocking", "advisory", "manual_review", "input_gap"}

    for status, allowed in valid_matrix.items():
        for severity in allowed:
            payload = _source_check_payload(status)
            if severity is not None:
                payload["severity"] = severity
            assert validate_source_checks([payload]) == []
        for severity in all_severities - set(allowed):
            errors = validate_source_checks(
                [_source_check_payload(status, severity=severity)]
            )
            assert errors
            assert f"source_checks[0]" in errors[0]
            assert status in errors[0]

    assert validate_source_checks([_source_check_payload("unknown")])
    assert validate_source_checks([_source_check_payload("conflict", severity=" ")])
    assert validate_source_checks([_source_check_payload("conflict", severity=1)])
    assert validate_source_checks([_source_check_payload("conflict", page=True)])
    assert validate_source_checks({"status": "conflict"})
    assert validate_source_checks(["not an object"])


def test_validate_source_checks_rejects_unknown_fields_and_aggregates_row_errors():
    unknown = validate_source_checks(
        [_source_check_payload("conflict", reviewer_note="must live in extra")]
    )
    assert unknown == [
        "source_checks[0]: source check contains unknown properties: reviewer_note"
    ]

    errors = validate_source_checks(
        [
            {
                "field": 7,
                "dataset_value": "2021",
                "source_ref_id": [],
                "status": "conflict",
                "severity": 1,
                "page": True,
                "extra": "not an object",
                "platform": {
                    "disposition": "clarification",
                    "message": "请说明。",
                },
            }
        ]
    )
    assert len(errors) >= 5
    assert all(error.startswith("source_checks[0]:") for error in errors)
    assert any("field must be a string" in error for error in errors)
    assert any("source_ref_id must be a string" in error for error in errors)
    assert any("severity must be a string" in error for error in errors)
    assert any("page must be an integer or null" in error for error in errors)
    assert any("extra must be an object" in error for error in errors)


def test_validate_source_checks_rejects_invalid_disposition():
    assert validate_source_checks(
        [
            _source_check_payload(
                "conflict",
                platform={
                    "disposition": "required",
                    "message": "请修正参考年。",
                },
            )
        ]
    ) == []
    assert validate_source_checks(
        [
            _source_check_payload(
                "ambiguous",
                platform={
                    "disposition": "clarification",
                    "message": "请说明参考年的依据。",
                },
            )
        ]
    ) == []
    assert validate_source_checks(
        [
            _source_check_payload(
                "not_found",
                severity="advisory",
                platform={
                    "disposition": "suggested",
                    "message": "建议补充参考年依据。",
                },
            )
        ]
    ) == []

    mismatched = validate_source_checks(
        [
            _source_check_payload(
                "conflict",
                platform={
                    "disposition": "clarification",
                    "message": "请说明。",
                },
            )
        ]
    )
    assert mismatched and "does not permit" in mismatched[0]

    for status in ("matched", "not_applicable"):
        errors = validate_source_checks(
            [
                _source_check_payload(
                    status,
                    platform={
                        "disposition": "suggested",
                        "message": "建议补充。",
                    },
                )
            ]
        )
        assert errors and "submitter-facing" in errors[0]

    assert validate_source_checks(
        [_source_check_payload("conflict", platform="required")]
    )
    assert validate_source_checks(
        [
            _source_check_payload(
                "conflict",
                platform={"disposition": "required", "message": "   "},
            )
        ]
    )


def test_resolve_source_refs_from_nested_dataset_and_text_url():
    payload = {
        "modellingAndValidation": {
            "dataSourcesTreatmentAndRepresentativeness": {
                "referenceToDataSource": {
                    "@type": "source data set",
                    "@refObjectId": "source-1",
                    "@version": "01.00.000",
                    "@uri": "../sources/source-1.xml",
                    "common:shortDescription": [{"@xml:lang": "en", "#text": "Background report"}],
                }
            }
        },
        "comment": "Download https://example.test/report.pdf for verification.",
    }

    refs = resolve_source_refs(payload)

    assert {ref.source_id for ref in refs} >= {"source-1"}
    assert any(ref.url == "https://example.test/report.pdf" for ref in refs)
    source = next(ref for ref in refs if ref.source_id == "source-1")
    assert source.version == "01.00.000"
    assert source.label == "Background report"


def test_resolve_source_refs_ignores_non_source_dataset_references():
    payload = {
        "processDataSet": {
            "@xmlns": "http://lca.jrc.it/ILCD/Process",
            "@xmlns:xsi": "http://www.w3.org/2001/XMLSchema-instance",
            "exchanges": {
                "exchange": [
                    {
                        "referenceToFlowDataSet": {
                            "@type": "flow data set",
                            "@refObjectId": "flow-1",
                            "@uri": "../flows/flow-1.xml",
                        }
                    }
                ]
            },
            "modellingAndValidation": {
                "LCIAResults": {
                    "referenceToLCIAMethodDataSet": {
                        "@type": "LCIA method data set",
                        "@uri": "../lciamethods/method-1.xml",
                    }
                },
                "publicationAndOwnership": {
                    "common:referenceToDataSetFormat": {
                        "@type": "source data set",
                        "@refObjectId": "format-1",
                        "@uri": "http://lca.jrc.ec.europa.eu",
                    }
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
            "permanentDataSetURI": (
                "https://lcdn.tiangong.earth/datasetdetail/process.xhtml"
                "?uuid=process-1&version=01.01.000"
            ),
        }
    }

    refs = resolve_source_refs(payload)

    assert [ref.source_id for ref in refs] == ["source-1"]


def test_resolve_source_dataset_digital_file_and_materialize_external_doc_url():
    payload = {
        "sourceDataSet": {
            "sourceInformation": {
                "dataSetInformation": {
                    "common:UUID": "source-dataset-1",
                    "common:shortName": [{"@xml:lang": "zh", "#text": "审核报告"}],
                    "referenceToDigitalFile": {"@uri": "../external_docs/report-1.pdf"},
                }
            },
            "administrativeInformation": {
                "publicationAndOwnership": {
                    "common:dataSetVersion": "01.01.000",
                }
            },
        }
    }

    refs = with_external_doc_base(
        resolve_source_refs(payload),
        "https://example.supabase.co/storage/v1/object/external_docs",
    )

    source = next(ref for ref in refs if ref.source_id == "source-dataset-1")
    assert source.version == "01.01.000"
    assert source.uri == "../external_docs/report-1.pdf"
    assert source.url == "https://example.supabase.co/storage/v1/object/external_docs/report-1.pdf"
    assert source.label == "审核报告"


def test_generate_claims_from_raw_process_dataset():
    payload = {
        "processDataSet": {
            "processInformation": {
                "dataSetInformation": {
                    "name": {
                        "baseName": [
                            {"@xml:lang": "zh", "#text": "单晶硅棒"},
                            {"@xml:lang": "en", "#text": "Monocrystalline silicon rod"},
                        ],
                        "treatmentStandardsRoutes": [
                            {"@xml:lang": "en", "#text": "Czochralski Technique"}
                        ],
                    },
                },
                "time": {"referenceYear": "2021"},
            },
            "modellingAndValidation": {
                "LCIMethodAndAllocation": {"typeOfDataSet": "Unit process, black box"}
            },
            "exchanges": {
                "exchange": [
                    {
                        "exchangeDirection": "Input",
                        "meanAmount": "2.5",
                        "referenceToFlowDataSet": {
                            "common:shortDescription": [
                                {"@xml:lang": "zh", "#text": "多晶硅"},
                                {"@xml:lang": "en", "#text": "Polycrystalline silicon"},
                            ]
                        },
                    },
                    {
                        "exchangeDirection": "Output",
                        "resultingAmount": "1",
                        "referenceToFlowDataSet": {
                            "common:shortDescription": [
                                {"@xml:lang": "zh", "#text": "单晶硅棒"},
                                {"@xml:lang": "en", "#text": "Monocrystalline silicon rod"},
                            ]
                        },
                    },
                ]
            },
        }
    }

    claims = generate_source_claims(payload)

    assert claims["process.name.zh"] == "单晶硅棒"
    assert claims["process.name.en"] == "Monocrystalline silicon rod"
    assert claims["process.route.en"] == "Czochralski Technique"
    assert claims["process.time.referenceYear"] == "2021"
    assert claims["process.exchange.input.1.name.zh"] == "多晶硅"
    assert claims["process.exchange.input.1.name.en"] == "Polycrystalline silicon"
    assert claims["process.exchange.input.1.amount"] == "2.5"
    assert claims["process.exchange.output.1.name.zh"] == "单晶硅棒"
    assert claims["process.exchange.output.1.amount"] == "1"


def test_download_and_extract_local_text_source(tmp_path):
    source_file = tmp_path / "report.txt"
    source_file.write_text("# Page 2\n\nThe process covers tap water production in 2021.", encoding="utf-8")
    source_dir = tmp_path / "source"

    artifact = download_source_artifact(
        SourceRef(source_id="source-1", path=str(source_file)),
        source_dir,
    )
    artifact = extract_source_text(artifact, source_dir)

    assert artifact.status == "extracted"
    extracted = source_dir / "extracted.md"
    assert extracted.exists()

    assert "tap water production" in extracted.read_text(encoding="utf-8")


def test_fetch_sources_traces_platform_source_dataset_and_writes_claims(tmp_path):
    class FakeClient:
        def __init__(self):
            self.downloads = []

        def select(self, table, *, columns="*", filters=None, limit=None):
            assert table == "sources"
            assert filters["id"] == "eq.source-1"
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

        def download_external_doc(self, object_name, output_path):
            self.downloads.append(object_name)
            output_path.write_text(
                "# Page 1\n\nMonocrystalline silicon rod production data for 2021.",
                encoding="utf-8",
            )
            return {"content_type": "text/plain", "path": str(output_path)}

    payload = {
        "processDataSet": {
            "processInformation": {
                "dataSetInformation": {
                    "name": {
                        "baseName": [
                            {"@xml:lang": "en", "#text": "Monocrystalline silicon rod"}
                        ]
                    }
                },
                "time": {"referenceYear": "2021"},
            },
            "modellingAndValidation": {
                "dataSourcesTreatmentAndRepresentativeness": {
                    "referenceToDataSource": {
                        "@type": "source data set",
                        "@refObjectId": "source-1",
                        "@version": "01.00.000",
                        "@uri": "../sources/source-1.xml",
                    }
                }
            },
        }
    }

    claims = generate_source_claims(payload)
    summary = fetch_sources(
        payload,
        root=tmp_path,
        output_dir=tmp_path / "case/sources",
        platform_client=FakeClient(),
        claims=claims,
    )

    assert summary["source_count"] == 1
    assert summary["claim_count"] >= 2
    assert summary["check_count"] == 0
    assert "report.txt" in (tmp_path / "case/sources/source-001/manifest.json").read_text(
        encoding="utf-8"
    )
    assert (tmp_path / "case/source-checks/claims.json").exists()
    assert not (tmp_path / "case/source-checks/checks.json").exists()


def test_fetch_sources_flags_supplementary_material_requirements(tmp_path):
    source_file = tmp_path / "main-article.txt"
    source_file.write_text(
        "Blade material and mass details are reported in Supplementary Table S8.",
        encoding="utf-8",
    )
    payload = {
        "modellingAndValidation": {
            "dataSourcesTreatmentAndRepresentativeness": {
                "referenceToDataSource": {
                    "@type": "source data set digital file",
                    "@uri": str(source_file),
                }
            }
        }
    }

    summary = fetch_sources(
        payload,
        root=tmp_path,
        output_dir=tmp_path / "case/sources",
    )

    requirement = summary["artifacts"][0]["related_artifact_requirements"][0]
    assert requirement["kind"] == "supplementary_material"
    assert requirement["reference"] == "Supplementary Table S8"
    assert requirement["status"] == "requires_followup"
    manifest = json.loads(
        (tmp_path / "case/sources/source-001/manifest.json").read_text(encoding="utf-8")
    )
    assert manifest["related_artifact_requirements"][0]["reference"] == "Supplementary Table S8"


def test_download_platform_external_doc_uses_authenticated_client(tmp_path):
    class FakeClient:
        def __init__(self):
            self.calls = []

        def download_external_doc(self, object_name, output_path):
            self.calls.append((object_name, output_path))
            output_path.write_bytes(b"PDF bytes")
            return {"content_type": "application/pdf", "path": str(output_path)}

    client = FakeClient()
    artifact = download_platform_external_doc(
        SourceRef(source_id="source-1", uri="../external_docs/report.pdf"),
        tmp_path,
        client=client,
    )

    assert client.calls[0][0] == "report.pdf"
    assert artifact.status == "downloaded"
    assert artifact.content_type == "application/pdf"
    assert artifact.sha256


def test_extract_json_source_as_markdown(tmp_path):
    source_file = tmp_path / "source.json"
    source_file.write_text(json.dumps({"boundary": "gate-to-gate"}), encoding="utf-8")
    source_dir = tmp_path / "source"

    artifact = download_source_artifact(SourceRef(source_id="source-json", path=str(source_file)), source_dir)
    artifact = extract_source_text(artifact, source_dir)

    assert artifact.status == "extracted"
    assert "gate-to-gate" in (source_dir / "extracted.md").read_text(encoding="utf-8")


def test_fetch_sources_flags_chinese_supplementary_references(tmp_path):
    source_file = tmp_path / "main-article.txt"
    source_file.write_text(
        "叶片材料的详细清单见附表 S2，工艺参数见附录 B，另见补充材料。",
        encoding="utf-8",
    )
    payload = {
        "modellingAndValidation": {
            "dataSourcesTreatmentAndRepresentativeness": {
                "referenceToDataSource": {
                    "@type": "source data set digital file",
                    "@uri": str(source_file),
                }
            }
        }
    }

    summary = fetch_sources(
        payload,
        root=tmp_path,
        output_dir=tmp_path / "case/sources",
    )

    references = {
        item["reference"]
        for item in summary["artifacts"][0]["related_artifact_requirements"]
    }
    assert any("附表" in reference for reference in references)
    assert any("附录" in reference for reference in references)
    assert any("补充材料" in reference for reference in references)


def test_attach_extraction_backfills_image_aware_fulltext(tmp_path):
    store = CaseStore(tmp_path / "cases")
    manifest = store.create_case(
        review_id="review-1",
        batch_id="b-1",
        dataset_type="process",
    )
    case_root = tmp_path / "cases" / manifest.case_dir
    source_dir = case_root / "sources/source-001"
    source_dir.mkdir(parents=True, exist_ok=True)
    (source_dir / "extracted.md").write_text("low fidelity pypdf text", encoding="utf-8")
    (source_dir / "manifest.json").write_text(
        json.dumps(
            {
                "schema_version": "tiangong-audit-source-v1",
                "ref": {"source_id": "source-1"},
                "status": "extracted",
                "file_path": "source.pdf",
                "extracted_text_path": "extracted.md",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    fulltext = tmp_path / "mineru-fulltext.md"
    fulltext.write_text(
        "image-aware fulltext with tables; details in Supplementary Table S8",
        encoding="utf-8",
    )

    summary = attach_extraction(
        "review-1",
        root=tmp_path,
        source_dir_name="source-001",
        extracted_text=fulltext,
        case_store=store,
        batch_id="b-1",
    )

    assert summary["extraction_method"] == "document-granular-decompose"
    text = (source_dir / "extracted.md").read_text(encoding="utf-8")
    assert "image-aware fulltext" in text
    # The previous low-fidelity extraction is preserved for provenance.
    assert (source_dir / "extracted.basic.md").read_text(encoding="utf-8") == (
        "low fidelity pypdf text"
    )
    manifest_payload = json.loads((source_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest_payload["extraction_method"] == "document-granular-decompose"
    assert manifest_payload["extracted_text_path"] == "extracted.md"
    assert manifest_payload["status"] == "extracted"
    # The richer text is re-scanned for supplementary references.
    assert any(
        "Supplementary Table S8" == item["reference"]
        for item in manifest_payload["related_artifact_requirements"]
    )
    updated = store.get_case("review-1", batch_id="b-1")
    assert "source_extraction:source-001" in updated.artifacts
