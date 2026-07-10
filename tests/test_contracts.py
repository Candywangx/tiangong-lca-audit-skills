import pytest

from tiangong_audit.contracts import AuditCaseManifest, Finding, SourceArtifact, SourceRef


def test_case_manifest_round_trips_with_default_steps():
    manifest = AuditCaseManifest(
        review_id="review-1",
        batch_id="batch-1",
        dataset_id="dataset-1",
        dataset_type="process",
    )
    manifest.set_step("fetched")

    payload = manifest.to_dict()
    restored = AuditCaseManifest.from_dict(payload)

    assert restored.review_id == "review-1"
    assert restored.steps["fetched"] is True
    assert restored.steps["reported"] is False
    assert restored.index_record()["dataset_id"] == "dataset-1"


def test_case_manifest_rejects_unknown_steps():
    manifest = AuditCaseManifest(review_id="review-1", batch_id="batch-1")

    with pytest.raises(ValueError, match="Unknown case step"):
        manifest.set_step("made_up")


def test_source_artifact_round_trips_with_ref():
    artifact = SourceArtifact(
        ref=SourceRef(source_id="source-1", version="01.00.000", url="https://example.test/a.pdf"),
        status="downloaded",
        file_path="sources/source-1/a.pdf",
        related_artifact_requirements=[
            {
                "kind": "supplementary_material",
                "reference": "Supplementary Table S8",
                "status": "requires_followup",
                "action": "Download the supplement before source judgment.",
            }
        ],
    )

    restored = SourceArtifact.from_dict(artifact.to_dict())

    assert restored.ref.source_id == "source-1"
    assert restored.ref.locator() == "https://example.test/a.pdf"
    assert restored.status == "downloaded"
    assert restored.related_artifact_requirements[0]["reference"] == "Supplementary Table S8"


def test_finding_contract_validates_severity():
    finding = Finding(
        rule_id="process.source.value_conflict",
        severity="blocking",
        location="source",
        evidence="PDF states 2021.",
        judgment="Dataset states 2022.",
        suggestion="Align the year or explain the adjustment.",
    )

    assert finding.to_dict()["severity"] == "blocking"

    finding.severity = "bad"
    with pytest.raises(ValueError, match="Invalid finding severity"):
        finding.to_dict()
