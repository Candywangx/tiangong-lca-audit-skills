from __future__ import annotations

import json
import zipfile
from collections.abc import Callable
from copy import deepcopy
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from tiangong_audit.integrations.tiangong_api import DatasetType
from tiangong_audit.integrations.tidas_sdk import validate_enhanced


OWNER_CONTACT_ID = "a1d95758-6904-4802-a061-fedc6ac4b4b4"
OWNER_CONTACT_VERSION = "01.01.000"
DATASET_FORMAT_ID = "a97a0155-0234-4b87-b4ce-a45da52f2a40"
DATASET_FORMAT_VERSION = "03.00.003"
COMPLIANCE_SYSTEM_ID = "d92a1a12-2545-49e2-a585-55c259997756"
REVIEW_METHOD_NAME = "质量平衡"
PASS_COMPLIANCE_DECLARATIONS: dict[str, Any] = {
    "compliance": [
        {
            "common:reviewCompliance": "Fully compliant",
            "common:qualityCompliance": "Not defined",
            "common:nomenclatureCompliance": "Not defined",
            "common:documentationCompliance": "Not defined",
            "common:methodologicalCompliance": "Fully compliant",
            "common:approvalOfOverallCompliance": "Fully compliant",
            "common:referenceToComplianceSystem": {
                "@uri": "../sources/1ea48531-e397-4ca7-ac08-056e4fa11826.xml",
                "@type": "source data set",
                "@version": "20.20.002",
                "@refObjectId": "1ea48531-e397-4ca7-ac08-056e4fa11826",
                "common:shortDescription": [
                    {
                        "#text": (
                            "ISO 14040 Environmental Management – Life Cycle Assessment – "
                            "Principles and Framework, 2006"
                        ),
                        "@xml:lang": "en",
                    }
                ],
            },
        },
        {
            "common:reviewCompliance": "Not defined",
            "common:qualityCompliance": "Not defined",
            "common:nomenclatureCompliance": "Not defined",
            "common:documentationCompliance": "Fully compliant",
            "common:methodologicalCompliance": "Fully compliant",
            "common:approvalOfOverallCompliance": "Fully compliant",
            "common:referenceToComplianceSystem": {
                "@uri": "../sources/1adb438d-4a8b-4919-885e-0a66da3c0f2a.xml",
                "@type": "source data set",
                "@version": "20.20.002",
                "@refObjectId": "1adb438d-4a8b-4919-885e-0a66da3c0f2a",
                "common:shortDescription": [
                    {
                        "#text": (
                            "ISO 14044:2006. Environmental Management – Life Cycle Assessment – "
                            "Requirements and guidelines."
                        ),
                        "@xml:lang": "en",
                    }
                ],
            },
        },
        {
            "common:reviewCompliance": "Fully compliant",
            "common:qualityCompliance": "Not defined",
            "common:nomenclatureCompliance": "Fully compliant",
            "common:documentationCompliance": "Fully compliant",
            "common:methodologicalCompliance": "Fully compliant",
            "common:approvalOfOverallCompliance": "Fully compliant",
            "common:referenceToComplianceSystem": {
                "@uri": f"../sources/{COMPLIANCE_SYSTEM_ID}.xml",
                "@type": "source data set",
                "@version": "20.20.002",
                "@refObjectId": COMPLIANCE_SYSTEM_ID,
                "common:shortDescription": [
                    {"#text": "ILCD Data Network - Entry-level", "@xml:lang": "en"}
                ],
            },
        },
        {
            "common:reviewCompliance": "Not defined",
            "common:qualityCompliance": "Not defined",
            "common:nomenclatureCompliance": "Fully compliant",
            "common:documentationCompliance": "Not defined",
            "common:methodologicalCompliance": "Not defined",
            "common:approvalOfOverallCompliance": "Fully compliant",
            "common:referenceToComplianceSystem": {
                "@uri": "../sources/c84c4185-d1b0-44fc-823e-d2ec630c7906.xml",
                "@type": "source data set",
                "@version": "00.00.001",
                "@refObjectId": "c84c4185-d1b0-44fc-823e-d2ec630c7906",
                "common:shortDescription": [
                    {"#text": "Environmental Footprint (EF) 3.1", "@xml:lang": "en"}
                ],
            },
        },
        {
            "common:reviewCompliance": "Fully compliant",
            "common:qualityCompliance": "Fully compliant",
            "common:nomenclatureCompliance": "Fully compliant",
            "common:documentationCompliance": "Fully compliant",
            "common:methodologicalCompliance": "Fully compliant",
            "common:approvalOfOverallCompliance": "Fully compliant",
            "common:referenceToComplianceSystem": {
                "@uri": "../sources/779fb9ea-de54-4707-b7fc-6154661552b5.xml",
                "@type": "source data set",
                "@version": "01.00.000",
                "@refObjectId": "779fb9ea-de54-4707-b7fc-6154661552b5",
                "common:shortDescription": [
                    {
                        "#text": (
                            "Commission Recommendation (EU) 2021/2279. "
                            "(Annex I. Product Environmental Footprint Method)"
                        ),
                        "@xml:lang": "en",
                    }
                ],
            },
        },
    ]
}
PLACEHOLDERS = (
    "DATASET_NAME",
    "DATASET_UUID_VERSION",
    "DATASET_LOCATION",
    "REVIEW_METHOD_SCOPE",
    "REVIEW_COMPLETION_DATE",
)


class ProcessPassFlowError(RuntimeError):
    """Raised when a process pass workflow checkpoint fails."""


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def format_review_date(value: date) -> str:
    return f"{value.year}年{value.month}月{value.day}日 {value.day}/{value.month}/{value.year}"


def lang_text(items: list[dict[str, Any]] | None, lang: str) -> str:
    for item in items or []:
        if item.get("@xml:lang") == lang:
            return str(item.get("#text", ""))
    return ""


def normalize_scope_name(type_of_dataset: str | None) -> str:
    mapping = {
        "Unit process, single operation": "单元过程，单一操作",
        "Unit process, black box": "单元过程，黑箱",
        "Partly terminated system": "部分终止系统",
    }
    if type_of_dataset in mapping:
        return mapping[type_of_dataset]
    raise ProcessPassFlowError(f"Unknown process typeOfDataSet: {type_of_dataset}")


def normalize_scope_name_en(type_of_dataset: str | None) -> str:
    mapping = {
        "Unit process, single operation": "unit process, single operation",
        "Unit process, black box": "unit process, black box",
        "Partly terminated system": "partly terminated system",
    }
    if type_of_dataset in mapping:
        return mapping[type_of_dataset]
    raise ProcessPassFlowError(f"Unknown process typeOfDataSet: {type_of_dataset}")


def build_pass_compliance_declarations() -> dict[str, Any]:
    return deepcopy(PASS_COMPLIANCE_DECLARATIONS)


def render_approval_report_docx(
    template_path: Path,
    output_path: Path,
    values: dict[str, str],
) -> None:
    missing = [name for name in PLACEHOLDERS if name not in values]
    if missing:
        raise ProcessPassFlowError("Missing DOCX placeholder values: " + ", ".join(missing))

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(template_path, "r") as zin, zipfile.ZipFile(
        output_path, "w", zipfile.ZIP_DEFLATED
    ) as zout:
        document_xml = ""
        for item in zin.infolist():
            data = zin.read(item.filename)
            if item.filename == "word/document.xml":
                text = data.decode("utf-8")
                for name, value in values.items():
                    text = text.replace("{{" + name + "}}", value)
                unresolved = [name for name in PLACEHOLDERS if "{{" + name + "}}" in text]
                if unresolved:
                    raise ProcessPassFlowError(
                        "Unresolved DOCX placeholders: " + ", ".join(unresolved)
                    )
                document_xml = text
                data = text.encode("utf-8")
            zout.writestr(item, data)
    if not document_xml:
        raise ProcessPassFlowError("DOCX template does not contain word/document.xml")


class ProcessPassWorkflow:
    def __init__(
        self,
        *,
        client: Any,
        review_api: Any,
        dataset_api: Any,
        template_path: Path,
        current_user_id: str,
        uuid_factory: Callable[[], str],
        today: Callable[[], date] = date.today,
        validate_source: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
    ):
        self.client = client
        self.review_api = review_api
        self.dataset_api = dataset_api
        self.template_path = Path(template_path)
        self.current_user_id = current_user_id
        self.uuid_factory = uuid_factory
        self.today = today
        self.validate_source = validate_source or (
            lambda payload: validate_enhanced(payload, entity_type="source", mode="weak")
        )

    def execute(self, review_id: str, output_dir: Path, *, execute: bool = False) -> dict[str, Any]:
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        task = self.review_api.get_task(review_id)
        write_json(output_dir / "task-before.json", task)
        self._check_task(task)

        comment_before = self.client.select(
            "comments",
            columns="review_id,reviewer_id,json,state_code,modified_at",
            filters={"review_id": f"eq.{review_id}", "reviewer_id": f"eq.{self.current_user_id}"},
            limit=1,
        )
        write_json(output_dir / "comment-before.json", comment_before)
        if not comment_before:
            raise ProcessPassFlowError("Current reviewer comment row not found")
        if comment_before[0].get("state_code") != 0:
            raise ProcessPassFlowError(
                f"Current reviewer comment state_code is {comment_before[0].get('state_code')}, expected 0"
            )

        dataset = self.dataset_api.get_dataset(
            task["data_id"], task["data_version"], self.dataset_type()
        )
        write_json(output_dir / "dataset-before.json", dataset)
        dataset_json = dataset.get("json") or {}
        if self.dataset_root_key() not in dataset_json:
            raise ProcessPassFlowError(f"Dataset is not a {self.dataset_root_key()}")

        context = self._build_context(task, dataset_json)
        docx_uuid = self.uuid_factory()
        source_id = self.uuid_factory()
        docx_path = output_dir / f"{docx_uuid}.docx"
        render_approval_report_docx(
            self.template_path,
            docx_path,
            {
                "DATASET_NAME": context["full_name"],
                "DATASET_UUID_VERSION": f"{context['dataset_id']}_{context['version']}",
                "DATASET_LOCATION": context["permanent_uri"],
                "REVIEW_METHOD_SCOPE": context["method_scope"],
                "REVIEW_COMPLETION_DATE": format_review_date(self.today()),
            },
        )

        source_json = self._build_source_json(context, source_id, docx_uuid)
        write_json(output_dir / "source-payload.json", source_json)
        source_validation = self.validate_source(source_json)
        write_json(output_dir / "source-validation.json", source_validation)
        rule_verification = bool(source_validation.get("success"))
        if not rule_verification:
            raise ProcessPassFlowError("Generated source failed TIDAS validation")

        comment_json = self._build_comment_json(context, source_id)
        write_json(output_dir / "comment-draft-payload.json", comment_json)

        summary = {
            "task_id": review_id,
            "dataset_id": context["dataset_id"],
            "version": context["version"],
            "source_id": source_id,
            "source_version": context["version"],
            "docx_uuid": docx_uuid,
            "docx_uri": f"../external_docs/{docx_uuid}.docx",
            "dataset_type": self.dataset_type().value,
            "scope_name": context["scope_name"],
            "method_name": REVIEW_METHOD_NAME,
            "case_dir": str(output_dir),
        }

        if not execute:
            summary["dry_run"] = True
            write_json(output_dir / "summary.json", summary)
            return summary

        upload_result = self.client.upload_external_doc(
            f"{docx_uuid}.docx",
            docx_path,
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )
        write_json(output_dir / "upload-response.json", upload_result)
        create_payload = {
            "id": source_id,
            "table": "sources",
            "jsonOrdered": source_json,
            "ruleVerification": rule_verification,
        }
        write_json(output_dir / "create-source-payload.json", create_payload)
        create_result = self.client.invoke_function("app_dataset_create", create_payload)
        write_json(output_dir / "create-source-response.json", create_result)
        save_result = self.review_api.save_comment_draft(review_id, comment_json)
        write_json(output_dir / "save-comment-response.json", save_result)

        comment_rows = self.client.select(
            "comments",
            columns="review_id,reviewer_id,json,state_code,modified_at",
            filters={"review_id": f"eq.{review_id}", "reviewer_id": f"eq.{self.current_user_id}"},
            limit=1,
        )
        source_rows = self.client.select(
            "sources",
            columns="id,version,json,json_ordered,user_id,state_code,modified_at",
            filters={"id": f"eq.{source_id}", "version": f"eq.{context['version']}"},
            limit=1,
        )
        write_json(output_dir / "comment-readback.json", comment_rows)
        write_json(output_dir / "source-readback.json", source_rows)
        self._verify_readback(comment_rows, source_rows, context, source_id, docx_uuid)
        summary["comment_state_code"] = comment_rows[0].get("state_code")
        summary["source_user_id"] = source_rows[0].get("user_id")
        write_json(output_dir / "summary.json", summary)
        return summary

    def _check_task(self, task: dict[str, Any]) -> None:
        if task.get("state_code") != 1:
            raise ProcessPassFlowError(f"Task state_code is {task.get('state_code')}, expected 1")
        if self.current_user_id not in (task.get("reviewer_id") or []):
            raise ProcessPassFlowError("Current user is not in reviewer_id list")
        if not task.get("data_id") or not task.get("data_version"):
            raise ProcessPassFlowError("Task is missing data_id or data_version")

    def dataset_type(self) -> DatasetType:
        return DatasetType.PROCESS

    def dataset_root_key(self) -> str:
        return "processDataSet"

    def _build_context(self, task: dict[str, Any], process: dict[str, Any]) -> dict[str, str]:
        process_dataset = process["processDataSet"]
        name = process_dataset["processInformation"]["dataSetInformation"]["name"]
        zh_name = "；".join(
            filter(
                None,
                [
                    lang_text(name.get("baseName"), "zh"),
                    lang_text(name.get("treatmentStandardsRoutes"), "zh"),
                    lang_text(name.get("mixAndLocationTypes"), "zh"),
                ],
            )
        )
        en_name = "; ".join(
            filter(
                None,
                [
                    lang_text(name.get("baseName"), "en"),
                    lang_text(name.get("treatmentStandardsRoutes"), "en"),
                    lang_text(name.get("mixAndLocationTypes"), "en"),
                ],
            )
        )
        type_of_dataset = process_dataset["modellingAndValidation"]["LCIMethodAndAllocation"].get(
            "typeOfDataSet"
        )
        scope_name = normalize_scope_name(type_of_dataset)
        scope_name_en = normalize_scope_name_en(type_of_dataset)
        return {
            "dataset_id": task["data_id"],
            "version": task["data_version"],
            "zh_name": zh_name,
            "en_name": en_name,
            "full_name": f"{zh_name} / {en_name}",
            "scope_name": scope_name,
            "scope_name_en": scope_name_en,
            "method_scope": f"{scope_name}；{REVIEW_METHOD_NAME}",
            "permanent_uri": (
                "https://lcdn.tiangong.earth/datasetdetail/process.xhtml"
                f"?uuid={task['data_id']}&version={task['data_version']}"
            ),
        }

    def _owner_ref(self) -> dict[str, Any]:
        return {
            "@refObjectId": OWNER_CONTACT_ID,
            "@type": "contact data set",
            "@uri": f"../contacts/{OWNER_CONTACT_ID}.xml",
            "@version": OWNER_CONTACT_VERSION,
            "common:shortDescription": [
                {"#text": "TianGong Think Tank ", "@xml:lang": "en"},
                {"#text": "天工智库中心", "@xml:lang": "zh"},
            ],
        }

    def _build_source_json(
        self, context: dict[str, str], source_id: str, docx_uuid: str
    ) -> dict[str, Any]:
        owner_ref = self._owner_ref()
        now = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace(
            "+00:00", "Z"
        )
        return {
            "sourceDataSet": {
                "@xmlns:common": "http://lca.jrc.it/ILCD/Common",
                "@xmlns": "http://lca.jrc.it/ILCD/Source",
                "@xmlns:xsi": "http://www.w3.org/2001/XMLSchema-instance",
                "@version": "1.1",
                "@xsi:schemaLocation": "http://lca.jrc.it/ILCD/Source ../../schemas/ILCD_SourceDataSet.xsd",
                "sourceInformation": {
                    "dataSetInformation": {
                        "common:UUID": source_id,
                        "common:shortName": self._source_short_description(context),
                        "classificationInformation": {
                            "common:classification": {
                                "common:class": {
                                    "@level": "0",
                                    "@classId": "5",
                                    "#text": "Publications and communications",
                                }
                            }
                        },
                        "publicationType": "Personal written communication",
                        "referenceToDigitalFile": {
                            "@uri": f"../external_docs/{docx_uuid}.docx"
                        },
                        "referenceToContact": owner_ref,
                        "referenceToLogo": {},
                    }
                },
                "administrativeInformation": {
                    "dataEntryBy": {
                        "common:timeStamp": now,
                        "common:referenceToDataSetFormat": {
                            "@type": "source data set",
                            "@refObjectId": DATASET_FORMAT_ID,
                            "@uri": f"../sources/{DATASET_FORMAT_ID}.xml",
                            "@version": DATASET_FORMAT_VERSION,
                            "common:shortDescription": [
                                {"#text": "ILCD format", "@xml:lang": "en"},
                                {"#text": "ILCD 数据格式", "@xml:lang": "zh"},
                            ],
                        },
                    },
                    "publicationAndOwnership": {
                        "common:dataSetVersion": context["version"],
                        "common:permanentDataSetURI": (
                            "https://lcdn.tiangong.earth/datasetdetail/source.xhtml"
                            f"?uuid={source_id}&version={context['version']}"
                        ),
                        "common:referenceToOwnershipOfDataSet": owner_ref,
                        "common:referenceToPrecedingDataSetVersion": {},
                    },
                },
            }
        }

    def _build_comment_json(self, context: dict[str, str], source_id: str) -> dict[str, Any]:
        owner_ref = self._owner_ref()
        return {
            "modellingAndValidation": {
                "complianceDeclarations": build_pass_compliance_declarations(),
                "validation": {
                    "review": [
                        {
                            "@type": "Independent external review",
                            "common:scope": [
                                {
                                    "@name": context["scope_name"],
                                    "common:method": {"@name": REVIEW_METHOD_NAME},
                                }
                            ],
                            "common:referenceToNameOfReviewerAndInstitution": owner_ref,
                            "common:referenceToCompleteReviewReport": {
                                "@refObjectId": source_id,
                                "@type": "source data set",
                                "@uri": f"../sources/{source_id}.xml",
                                "@version": context["version"],
                                "common:shortDescription": self._source_short_description(context),
                            },
                            "common:reviewDetails": [
                                {
                                    "@xml:lang": "zh",
                                    "#text": (
                                        f"本次验证审查针对过程数据集“{context['zh_name']}”。"
                                        f"审查范围为{context['scope_name']}，方法为质量平衡。"
                                        "根据数据集的建模信息、技术描述、参考流、系统边界及输入输出清单，"
                                        "数据结构和主要物质、能量平衡能够支撑该生产混合过程的收录与复用。"
                                        "完整审查报告已作为来源数据集关联。"
                                    ),
                                },
                                {
                                    "@xml:lang": "en",
                                    "#text": (
                                        f"This validation review covers the process dataset \"{context['en_name']}\". "
                                        f"The review scope is {context['scope_name_en']} and the method is mass balance. "
                                        "Based on the modelling information, technology description, reference flow, "
                                        "system boundary, and input/output inventory, the dataset structure and main "
                                        "material and energy balances support publication and reuse of this "
                                        "production-mix process. The complete review report is linked as a source dataset."
                                    ),
                                },
                            ],
                        }
                    ]
                },
            }
        }

    def _source_short_description(self, context: dict[str, str]) -> list[dict[str, str]]:
        return [
            {"#text": f"过程“{context['zh_name']}”审核报告", "@xml:lang": "zh"},
            {
                "#text": f"Review report of '{context['en_name']}' process dataset",
                "@xml:lang": "en",
            },
        ]

    def _verify_readback(
        self,
        comment_rows: list[dict[str, Any]],
        source_rows: list[dict[str, Any]],
        context: dict[str, str],
        source_id: str,
        docx_uuid: str,
    ) -> None:
        if not comment_rows:
            raise ProcessPassFlowError("Comment readback missing")
        comment = comment_rows[0]
        review = comment["json"]["modellingAndValidation"]["validation"]["review"][0]
        if comment.get("state_code") != 0:
            raise ProcessPassFlowError(
                f"Comment state_code readback {comment.get('state_code')} != 0"
            )
        if review["common:scope"][0].get("@name") != context["scope_name"]:
            raise ProcessPassFlowError("Scope readback mismatch")
        if review["common:scope"][0]["common:method"].get("@name") != REVIEW_METHOD_NAME:
            raise ProcessPassFlowError("Method readback mismatch")
        if review["common:referenceToCompleteReviewReport"].get("@refObjectId") != source_id:
            raise ProcessPassFlowError("Report source ref mismatch")
        if not source_rows:
            raise ProcessPassFlowError("Source readback missing")
        source = source_rows[0]
        if source.get("user_id") != self.current_user_id:
            raise ProcessPassFlowError(
                f"Source user_id {source.get('user_id')} != {self.current_user_id}"
            )
        source_file_uri = source["json"]["sourceDataSet"]["sourceInformation"][
            "dataSetInformation"
        ]["referenceToDigitalFile"]["@uri"]
        if source_file_uri != f"../external_docs/{docx_uuid}.docx":
            raise ProcessPassFlowError("Source digital file uri mismatch")


class ModelPassWorkflow(ProcessPassWorkflow):
    def dataset_type(self) -> DatasetType:
        return DatasetType.MODEL

    def dataset_root_key(self) -> str:
        return "lifeCycleModelDataSet"

    def _build_context(self, task: dict[str, Any], model: dict[str, Any]) -> dict[str, str]:
        model_dataset = model["lifeCycleModelDataSet"]
        name = model_dataset["lifeCycleModelInformation"]["dataSetInformation"]["name"]
        zh_name = "；".join(
            filter(
                None,
                [
                    lang_text(name.get("baseName"), "zh"),
                    lang_text(name.get("treatmentStandardsRoutes"), "zh"),
                    lang_text(name.get("mixAndLocationTypes"), "zh"),
                ],
            )
        )
        en_name = "; ".join(
            filter(
                None,
                [
                    lang_text(name.get("baseName"), "en"),
                    lang_text(name.get("treatmentStandardsRoutes"), "en"),
                    lang_text(name.get("mixAndLocationTypes"), "en"),
                ],
            )
        )
        scope_name = "生命周期模型"
        return {
            "dataset_id": task["data_id"],
            "version": task["data_version"],
            "zh_name": zh_name,
            "en_name": en_name,
            "full_name": f"{zh_name} / {en_name}",
            "scope_name": scope_name,
            "scope_name_en": "life cycle model",
            "method_scope": f"{scope_name}；{REVIEW_METHOD_NAME}",
            "permanent_uri": (
                "https://lcdn.tiangong.earth/datasetdetail/lifecyclemodel.xhtml"
                f"?uuid={task['data_id']}&version={task['data_version']}"
            ),
        }

    def _source_short_description(self, context: dict[str, str]) -> list[dict[str, str]]:
        return [
            {"#text": f"模型“{context['zh_name']}”审核报告", "@xml:lang": "zh"},
            {
                "#text": f"Review report of '{context['en_name']}' life cycle model dataset",
                "@xml:lang": "en",
            },
        ]

    def _build_comment_json(self, context: dict[str, str], source_id: str) -> dict[str, Any]:
        owner_ref = self._owner_ref()
        return {
            "modellingAndValidation": {
                "complianceDeclarations": build_pass_compliance_declarations(),
                "validation": {
                    "review": [
                        {
                            "@type": "Independent external review",
                            "common:scope": [
                                {
                                    "@name": context["scope_name"],
                                    "common:method": {"@name": REVIEW_METHOD_NAME},
                                }
                            ],
                            "common:referenceToNameOfReviewerAndInstitution": owner_ref,
                            "common:referenceToCompleteReviewReport": {
                                "@refObjectId": source_id,
                                "@type": "source data set",
                                "@uri": f"../sources/{source_id}.xml",
                                "@version": context["version"],
                                "common:shortDescription": self._source_short_description(context),
                            },
                            "common:reviewDetails": [
                                {
                                    "@xml:lang": "zh",
                                    "#text": (
                                        f"本次验证审查针对生命周期模型数据集“{context['zh_name']}”。"
                                        "审查范围为生命周期模型，方法为质量平衡。"
                                        "根据模型目标、定量参考、模型结构、关联过程及主要连接关系，"
                                        "模型结构和主要物质、能量平衡能够支撑该模型数据集的收录与复用。"
                                        "完整审查报告已作为来源数据集关联。"
                                    ),
                                },
                                {
                                    "@xml:lang": "en",
                                    "#text": (
                                        f"This validation review covers the life cycle model dataset \"{context['en_name']}\". "
                                        "The review scope is life cycle model and the method is mass balance. "
                                        "Based on the model goal, quantitative reference, model structure, linked processes, "
                                        "and main connections, the model structure and main material and energy balances "
                                        "support publication and reuse of this model dataset. The complete review report "
                                        "is linked as a source dataset."
                                    ),
                                },
                            ],
                        }
                    ]
                },
            }
        }
