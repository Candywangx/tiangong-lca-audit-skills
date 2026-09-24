import hashlib
import json

import pytest

from tiangong_audit.contracts import SourceRef
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


@pytest.fixture
def extraction_case(tmp_path):
    store = CaseStore(tmp_path / "cases")
    case = store.create_case(review_id="bundle-review", batch_id="b", dataset_type="process")
    source = tmp_path / "cases" / case.case_dir / "sources/source-001"
    source.mkdir(parents=True)
    (source / "extracted.md").write_bytes(b"old text")
    (source / "source.pdf").write_bytes(b"synthetic source")
    (source / "manifest.json").write_text(json.dumps({
        "ref": {"source_id": "s", "custom_ref": "preserve"},
        "status": "extracted", "extracted_text_path": "extracted.md",
        "file_path": "source.pdf", "sha256": hashlib.sha256(b"synthetic source").hexdigest(),
        "reviewer_note": {"keep": True},
    }))
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    (bundle / "result.json").write_text(json.dumps({
        "result": [{"text": "Supplementary Table S8", "page_number": 2, "type": None}],
        "txt": "Raw service text differs from page blocks.\r\n",
    }))
    (bundle / "extracted.md").write_bytes(b"## Page 2\r\n\n### Block 1\nSupplementary Table S8\n")
    (bundle / "fulltext.txt").write_bytes(b"Raw service text differs from page blocks.\r\n")
    (bundle / "openapi.json").write_text(json.dumps({"openapi": "3.1.0", "paths": {}}))
    (bundle / "request.json").write_text(json.dumps({
        "state": "SUCCESS", "task_id": "synthetic-task",
        "identity": {"endpoint": "/mineru/task", "sha256": hashlib.sha256(b"synthetic source").hexdigest(),
                     "fields": {"tier": "advanced"}, "query": {"chunk_type": True}},
        "schema_sha256": hashlib.sha256((bundle / "openapi.json").read_bytes()).hexdigest(),
        "result_sha256": hashlib.sha256((bundle / "result.json").read_bytes()).hexdigest(),
    }))
    return source, bundle, dict(review_id="bundle-review", root=tmp_path,
        source_dir_name="source-001", extracted_text=bundle / "extracted.md",
        extraction_dir=bundle, case_store=store, batch_id="b")


def _snapshot_tree(path):
    return {str(item.relative_to(path)): item.read_bytes() for item in path.rglob("*") if item.is_file()}


def test_attach_imports_five_local_artifacts_with_hashes(extraction_case):
    source, bundle, kwargs = extraction_case
    (bundle / "unrelated.txt").write_text("not part of the bundle")
    summary = attach_extraction(**kwargs)
    payload = json.loads((source / "manifest.json").read_text())
    assert payload["reviewer_note"] == {"keep": True}
    assert payload["ref"]["custom_ref"] == "preserve"
    files = payload["extraction_bundle"]["files"]
    assert set(files) == {"result.json", "extracted.md", "fulltext.txt", "request.json", "openapi.json"}
    case = kwargs["case_store"].get_case("bundle-review", batch_id="b")
    for name, metadata in files.items():
        assert metadata["path"] == f"parsing/{name}"
        data = (source / metadata["path"]).read_bytes()
        assert data == (bundle / name).read_bytes()
        assert metadata["sha256"] == hashlib.sha256(data).hexdigest()
        assert (kwargs["root"] / "cases" / case.artifacts[f"source_parsing:source-001:{name}"]).read_bytes() == data
    assert (source / "extracted.md").read_bytes() == (bundle / "extracted.md").read_bytes()
    assert not (source / "parsing/unrelated.txt").exists()
    assert summary["extraction_bundle"] == payload["extraction_bundle"]
    assert payload["related_artifact_requirements"][0]["reference"] == "Supplementary Table S8"


@pytest.mark.parametrize("already_imported", [False, True])
@pytest.mark.parametrize("damage", [
    "result-hash", "schema-hash", "text-mismatch", "source-hash", "state", "identity",
    "result-list", "blocks-empty", "blank-text", "page-zero", "page-bool", "page-string",
    "text-type", "block-type", "txt-type", "raw-mismatch", "missing", "symlink", "dir-symlink",
])
def test_attach_rejects_invalid_bundle_without_changes(extraction_case, damage, already_imported):
    source, bundle, kwargs = extraction_case
    if already_imported:
        attach_extraction(**kwargs)
    request = json.loads((bundle / "request.json").read_text())
    result = json.loads((bundle / "result.json").read_text())
    if damage == "result-hash":
        request["result_sha256"] = "0" * 64
    elif damage == "schema-hash":
        request["schema_sha256"] = "0" * 64
    elif damage == "text-mismatch":
        supplied = bundle.parent / "different.md"
        supplied.write_text("different text")
        kwargs["extracted_text"] = supplied
    elif damage == "source-hash":
        request["identity"]["sha256"] = "0" * 64
    elif damage == "state":
        request["state"] = "PENDING"
    elif damage == "identity":
        request["identity"] = []
    elif damage == "result-list":
        result = result["result"]
    elif damage == "blocks-empty":
        result["result"] = []
    elif damage == "blank-text":
        result["result"][0]["text"] = " \n"
    elif damage.startswith("page-"):
        result["result"][0]["page_number"] = {"page-zero": 0, "page-bool": True, "page-string": "2"}[damage]
    elif damage == "text-type":
        result["result"][0]["text"] = 123
    elif damage == "block-type":
        result["result"][0]["type"] = []
    elif damage == "txt-type":
        result["txt"] = 123
    elif damage == "raw-mismatch":
        (bundle / "fulltext.txt").write_text("changed")
    (bundle / "result.json").write_text(json.dumps(result))
    if damage != "result-hash":
        request["result_sha256"] = hashlib.sha256((bundle / "result.json").read_bytes()).hexdigest()
    (bundle / "request.json").write_text(json.dumps(request))
    if damage in {"missing", "symlink"}:
        (bundle / "openapi.json").unlink()
        if damage == "symlink":
            outside = bundle.parent / "external-schema.json"
            outside.write_text(json.dumps({"openapi": "3.1.0", "paths": {}}))
            (bundle / "openapi.json").symlink_to(outside)
    elif damage == "dir-symlink":
        alias = bundle.parent / "alias"
        alias.symlink_to(bundle, target_is_directory=True)
        kwargs["extraction_dir"] = alias
    before = _snapshot_tree(kwargs["root"] / "cases")
    with pytest.raises(ValueError):
        attach_extraction(**kwargs)
    assert _snapshot_tree(kwargs["root"] / "cases") == before


def test_attach_replacements_preserve_bundle_history_and_text_backups(extraction_case):
    source, bundle, kwargs = extraction_case
    attach_extraction(**kwargs)
    first = _snapshot_tree(source / "parsing")
    for text in (b"second rendering", b"third rendering"):
        (bundle / "extracted.md").write_bytes(text)
        attach_extraction(**kwargs)
    payload = json.loads((source / "manifest.json").read_text())
    history = payload["extraction_history"]
    assert len(history) == 2
    assert history[0]["directory"] != history[1]["directory"]
    for name, data in first.items():
        assert (source / history[0]["directory"] / name).read_bytes() == data
    assert (source / history[1]["directory"] / "extracted.md").read_bytes() == b"second rendering"
    backups = [path.read_bytes() for path in source.glob("extracted.*.md")]
    assert b"old text" in backups and first["extracted.md"] in backups and b"second rendering" in backups
    # A later text-only attachment must not claim the old bundle produced its text.
    kwargs.pop("extraction_dir")
    (bundle / "extracted.md").write_bytes(b"manual text")
    attach_extraction(**kwargs)
    payload = json.loads((source / "manifest.json").read_text())
    assert "extraction_bundle" not in payload
    assert len(payload["extraction_history"]) == 3
    case = kwargs["case_store"].get_case("bundle-review", batch_id="b")
    assert not any(key.startswith("source_parsing:") for key in case.artifacts)
    history_paths = [value for key, value in case.artifacts.items() if key.startswith("source_parsing_history:")]
    assert len(history_paths) == 3
    assert all((kwargs["root"] / "cases" / path / "source-manifest.json").is_file() for path in history_paths)


@pytest.mark.parametrize("field,value", [("source_dir_name", "../source-001"),
    ("source_dir_name", "/tmp/source-001"), ("method", "../escape"), ("method", "bad/name")])
def test_attach_rejects_unsafe_names(extraction_case, field, value):
    source, bundle, kwargs = extraction_case
    kwargs.pop("extraction_dir")
    kwargs[field] = value
    before = _snapshot_tree(kwargs["root"] / "cases")
    with pytest.raises(ValueError):
        attach_extraction(**kwargs)
    assert _snapshot_tree(kwargs["root"] / "cases") == before


@pytest.mark.parametrize("linked", ["source", "sources", "manifest.json", "extracted.md", "parsing", "parsing-history", "supplied"])
def test_attach_rejects_symlinks_in_inputs_and_destinations(extraction_case, linked):
    source, bundle, kwargs = extraction_case
    if linked == "source":
        original = source
    elif linked == "sources":
        original = source.parent
    elif linked == "supplied":
        original = kwargs["extracted_text"]
    else:
        original = source / linked
    if not original.exists():
        original.mkdir()
    outside = kwargs["root"] / "outside"
    original.rename(outside)
    original.symlink_to(outside, target_is_directory=outside.is_dir())
    before = _snapshot_tree(kwargs["root"])
    with pytest.raises(ValueError, match="Unsafe attachment path"):
        attach_extraction(**kwargs)
    assert _snapshot_tree(kwargs["root"]) == before


@pytest.mark.parametrize("optional", ["absent", "null", "empty"])
def test_attach_accepts_optional_result_fields_and_unknown_source_hash(extraction_case, optional):
    source, bundle, kwargs = extraction_case
    result = {"result": [{"text": "Evidence", "page_number": 1}]}
    if optional == "null":
        result["txt"] = None
        result["result"][0]["type"] = None
    elif optional == "empty":
        result["txt"] = ""
    (bundle / "result.json").write_text(json.dumps(result))
    # The standalone parser may derive fulltext from blocks when txt is absent.
    (bundle / "fulltext.txt").write_bytes(b"Evidence")
    request = json.loads((bundle / "request.json").read_text())
    request.pop("task_id")
    request["result_sha256"] = hashlib.sha256((bundle / "result.json").read_bytes()).hexdigest()
    (bundle / "request.json").write_text(json.dumps(request))
    payload = json.loads((source / "manifest.json").read_text())
    payload.pop("sha256")
    (source / "manifest.json").write_text(json.dumps(payload))
    attach_extraction(**kwargs)
    assert (source / "parsing/result.json").read_bytes() == (bundle / "result.json").read_bytes()
