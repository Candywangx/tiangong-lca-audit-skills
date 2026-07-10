from __future__ import annotations

import json
import zipfile
from datetime import date
from pathlib import Path

from tiangong_audit.process_pass_flow import (
    ModelPassWorkflow,
    ProcessPassWorkflow,
    build_pass_compliance_declarations,
    normalize_scope_name_en,
    render_approval_report_docx,
)


def make_docx(path: Path) -> None:
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as docx:
        docx.writestr(
            "word/document.xml",
            (
                "<w:document>"
                "{{DATASET_NAME}}|{{DATASET_UUID_VERSION}}|{{DATASET_LOCATION}}|"
                "{{REVIEW_METHOD_SCOPE}}|{{REVIEW_COMPLETION_DATE}}"
                "</w:document>"
            ),
        )


def test_render_approval_report_docx_replaces_stable_placeholders(tmp_path):
    template = tmp_path / "template.docx"
    output = tmp_path / "report.docx"
    make_docx(template)

    render_approval_report_docx(
        template,
        output,
        {
            "DATASET_NAME": "单晶硅棒 / Monocrystalline silicon rod",
            "DATASET_UUID_VERSION": "dataset-1_01.01.000",
            "DATASET_LOCATION": "https://example.test/process?uuid=dataset-1&version=01.01.000",
            "REVIEW_METHOD_SCOPE": "单元过程，黑箱；质量平衡",
            "REVIEW_COMPLETION_DATE": "2026年6月23日 23/6/2026",
        },
    )

    with zipfile.ZipFile(output) as docx:
        xml = docx.read("word/document.xml").decode("utf-8")

    assert "{{" not in xml
    assert "单晶硅棒 / Monocrystalline silicon rod" in xml
    assert "2026年6月23日 23/6/2026" in xml


class FakeClient:
    supabase_url = "https://example.supabase.co"
    publishable_key = "public-key"
    access_token = "member-token"

    def __init__(self):
        self.uploads = []
        self.functions = []
        self.comment_rows = [
            {
                "review_id": "review-1",
                "reviewer_id": "reviewer-1",
                "state_code": 0,
                "json": {},
            }
        ]
        self.source_rows = []

    def upload_external_doc(self, object_name, path, content_type):
        self.uploads.append((object_name, Path(path).name, content_type))
        return {"Key": f"external_docs/{object_name}"}

    def invoke_function(self, name, payload):
        self.functions.append((name, payload))
        if name == "app_dataset_create":
            source_id = payload["id"]
            source = {
                "id": source_id,
                "version": "01.01.000",
                "json": payload["jsonOrdered"],
                "user_id": "reviewer-1",
            }
            self.source_rows = [source]
            return {"data": [source], "error": None}
        raise AssertionError(f"unexpected function: {name}")

    def select(self, table, *, columns="*", filters=None, limit=None):
        if table == "comments":
            return self.comment_rows
        if table == "sources":
            return self.source_rows
        raise AssertionError(f"unexpected table: {table}")


class FakeReviewAPI:
    def __init__(self, client):
        self.client = client
        self.saved = []
        self.submitted = []

    def get_task(self, review_id):
        assert review_id == "review-1"
        return {
            "id": "review-1",
            "data_id": "process-1",
            "data_version": "01.01.000",
            "state_code": 1,
            "reviewer_id": ["reviewer-1"],
        }

    def save_comment_draft(self, task_id, comment):
        self.saved.append((task_id, comment))
        self.client.comment_rows = [
            {
                "review_id": task_id,
                "reviewer_id": "reviewer-1",
                "state_code": 0,
                "json": comment,
            }
        ]
        return {"data": [{"comment": {"review_id": task_id}}], "error": None}

    def submit_result(self, task_id, result):
        self.submitted.append((task_id, result))
        raise AssertionError("process pass flow must not submit review comments")


class FakeDatasetAPI:
    def get_dataset(self, dataset_id, version, dataset_type):
        assert (dataset_id, version, dataset_type.value) == ("process-1", "01.01.000", "process")
        return {
            "id": dataset_id,
            "version": version,
            "json": {
                "processDataSet": {
                    "processInformation": {
                        "dataSetInformation": {
                            "name": {
                                "baseName": [
                                    {"@xml:lang": "zh", "#text": "单晶硅棒"},
                                    {"@xml:lang": "en", "#text": "Monocrystalline silicon rod"},
                                ],
                                "treatmentStandardsRoutes": [
                                    {"@xml:lang": "zh", "#text": "直拉法"},
                                    {"@xml:lang": "en", "#text": "Czochralski Technique"},
                                ],
                                "mixAndLocationTypes": [
                                    {"@xml:lang": "zh", "#text": "生产混合，在工厂"},
                                    {"@xml:lang": "en", "#text": "Production mix, at plant"},
                                ],
                            }
                        }
                    },
                    "modellingAndValidation": {
                        "LCIMethodAndAllocation": {
                            "typeOfDataSet": "Unit process, black box"
                        }
                    },
                }
            },
        }


class FakeModelDatasetAPI:
    def get_dataset(self, dataset_id, version, dataset_type):
        assert (dataset_id, version, dataset_type.value) == ("process-1", "01.01.000", "model")
        return {
            "id": dataset_id,
            "version": version,
            "json": {
                "lifeCycleModelDataSet": {
                    "lifeCycleModelInformation": {
                        "dataSetInformation": {
                            "name": {
                                "baseName": [
                                    {"@xml:lang": "zh", "#text": "高纯球形铝粉"},
                                    {"@xml:lang": "en", "#text": "High purity spherical aluminum powder"},
                                ],
                                "treatmentStandardsRoutes": [
                                    {"@xml:lang": "zh", "#text": "铝锭熔化，氮气雾化制粉"},
                                    {
                                        "@xml:lang": "en",
                                        "#text": "Aluminum ingot melting and nitrogen atomization",
                                    },
                                ],
                                "mixAndLocationTypes": [
                                    {"@xml:lang": "zh", "#text": "生产混合, 在工厂"},
                                    {"@xml:lang": "en", "#text": "Production mix, at plant"},
                                ],
                            }
                        }
                    }
                }
            },
        }


def test_process_pass_workflow_creates_source_and_saves_draft_without_submit(tmp_path):
    template = tmp_path / "template.docx"
    make_docx(template)
    client = FakeClient()
    review_api = FakeReviewAPI(client)
    workflow = ProcessPassWorkflow(
        client=client,
        review_api=review_api,
        dataset_api=FakeDatasetAPI(),
        template_path=template,
        current_user_id="reviewer-1",
        uuid_factory=iter(["docx-1", "source-1"]).__next__,
        today=lambda: date(2026, 6, 23),
        validate_source=lambda payload: {"success": True, "validationIssues": []},
    )

    result = workflow.execute("review-1", tmp_path / "case", execute=True)

    assert result["source_id"] == "source-1"
    assert result["scope_name"] == "单元过程，黑箱"
    assert result["comment_state_code"] == 0
    assert client.uploads[0][0] == "docx-1.docx"
    assert [name for name, _ in client.functions] == ["app_dataset_create"]
    assert review_api.saved[0][0] == "review-1"
    assert review_api.submitted == []
    review = review_api.saved[0][1]["modellingAndValidation"]["validation"]["review"][0]
    compliance = review_api.saved[0][1]["modellingAndValidation"]["complianceDeclarations"]
    assert review["@type"] == "Independent external review"
    assert review["common:scope"][0]["@name"] == "单元过程，黑箱"
    assert review["common:scope"][0]["common:method"]["@name"] == "质量平衡"
    assert review["common:referenceToCompleteReviewReport"]["@refObjectId"] == "source-1"
    assert compliance == build_pass_compliance_declarations()
    assert len(compliance["compliance"]) == 5
    assert compliance["compliance"][0]["common:qualityCompliance"] == "Not defined"
    assert json.loads((tmp_path / "case" / "summary.json").read_text())["source_id"] == "source-1"


def test_model_pass_workflow_creates_model_report_source_and_saves_draft(tmp_path):
    template = tmp_path / "template.docx"
    make_docx(template)
    client = FakeClient()
    review_api = FakeReviewAPI(client)
    workflow = ModelPassWorkflow(
        client=client,
        review_api=review_api,
        dataset_api=FakeModelDatasetAPI(),
        template_path=template,
        current_user_id="reviewer-1",
        uuid_factory=iter(["docx-1", "source-1"]).__next__,
        today=lambda: date(2026, 6, 24),
        validate_source=lambda payload: {"success": True, "validationIssues": []},
    )

    result = workflow.execute("review-1", tmp_path / "case", execute=True)

    assert result["dataset_type"] == "model"
    assert result["scope_name"] == "生命周期模型"
    assert review_api.submitted == []
    review = review_api.saved[0][1]["modellingAndValidation"]["validation"]["review"][0]
    compliance = review_api.saved[0][1]["modellingAndValidation"]["complianceDeclarations"]
    source_ref = review["common:referenceToCompleteReviewReport"]
    assert review["common:scope"][0]["@name"] == "生命周期模型"
    assert source_ref["@refObjectId"] == "source-1"
    assert source_ref["common:shortDescription"][0]["#text"].startswith("模型“高纯球形铝粉")
    assert "生命周期模型数据集" in review["common:reviewDetails"][0]["#text"]
    assert compliance == build_pass_compliance_declarations()


def test_process_pass_english_scope_follows_dataset_type():
    assert normalize_scope_name_en("Unit process, single operation") == (
        "unit process, single operation"
    )
    assert normalize_scope_name_en("Unit process, black box") == "unit process, black box"
    assert normalize_scope_name_en("Partly terminated system") == "partly terminated system"
