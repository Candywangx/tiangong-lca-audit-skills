import json
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "skill/tiangong-lca-audit"


def test_output_templates_are_self_contained():
    templates = {
        "audit-result-template.md": "审核结论",
        "approval-report-template.md": "审查报告草稿",
        "correction-record-template.md": "人工修正",
    }
    for name, required_text in templates.items():
        text = (SKILL / "assets" / name).read_text(encoding="utf-8")
        assert required_text in text
        assert "references/" not in text


def test_approval_report_docx_template_is_an_asset():
    template = SKILL / "assets/approval-report-template.docx"
    assert template.exists()
    assert template.stat().st_size > 0
    assert not list((SKILL / "references").glob("*.docx"))
    assert not list(SKILL.rglob("~$*.docx"))


def test_approval_report_docx_template_uses_stable_placeholders():
    template = SKILL / "assets/approval-report-template.docx"
    with zipfile.ZipFile(template) as docx:
        xml = docx.read("word/document.xml").decode("utf-8")

    for placeholder in (
        "DATASET_NAME",
        "DATASET_UUID_VERSION",
        "DATASET_LOCATION",
        "REVIEW_METHOD_SCOPE",
        "REVIEW_COMPLETION_DATE",
    ):
        assert "{{" + placeholder + "}}" in xml
    assert "2026年5月" not in xml
    assert "422e633a-f026-4ddf-ad76-5489e600a596" not in xml


def test_approval_report_instructions_require_chinese_scope_and_current_date():
    text = (SKILL / "assets/approval-report-template.md").read_text(encoding="utf-8")
    assert "审查方法及范围" in text
    assert "中文名称" in text
    assert "审查完成日期" in text
    assert "当天日期" in text


def test_audit_result_template_has_copy_ready_platform_feedback():
    text = (SKILL / "assets/audit-result-template.md").read_text(encoding="utf-8")
    assert "## 平台退回意见" in text
    assert "①【{标识}】{位置}" in text


def test_output_contract_defines_copy_ready_platform_feedback():
    text = (SKILL / "references/output-contract.md").read_text(encoding="utf-8")
    assert "可直接复制到天工平台" in text
    assert "使用 `①②③……` 连续编号" in text
    assert "位置 + 可见证据 + 问题判断 + 明确修改建议" in text


def test_output_contract_requires_one_report_per_dataset_for_batch_audits():
    text = (SKILL / "references/output-contract.md").read_text(encoding="utf-8")
    assert "一条数据集一份独立 Markdown 审核报告" in text
    assert "汇总索引不能代替独立报告" in text


def test_output_contract_defines_case_archive_and_training_boundary():
    text = (SKILL / "references/output-contract.md").read_text(encoding="utf-8")
    assert "原始输入或平台响应" in text
    assert "复核、人工纠偏和回归评测" in text
    assert "未经人工确认" in text
    assert "训练真值" in text


def test_taxonomy_assets_are_valid_json():
    for name in ("cfia-category-taxonomy.json", "tiangong-category-paths.json"):
        payload = json.loads((SKILL / "assets/taxonomies" / name).read_text(encoding="utf-8"))
        assert payload


def test_projected_api_fixtures_are_valid_json():
    fixtures = list((ROOT / "tests/fixtures/projected-api").glob("*.json"))
    assert len(fixtures) == 3
    for fixture in fixtures:
        assert json.loads(fixture.read_text(encoding="utf-8"))


def test_output_contract_requires_visible_severity_and_readable_opinions():
    text = (SKILL / "references/output-contract.md").read_text(encoding="utf-8")
    for severity, label in (("blocking", "需修改"), ("input_gap", "需补充"),
                            ("manual_review", "需确认"), ("advisory", "建议优化")):
        assert f"`{severity}` | 【{label}】" in text
    assert "不能根据“补充”“确认”“建议”等动词" in text
    assert "编号和排序不能代替标识" in text
    assert "两到三句" in text
    assert "不得把工具读取失败" in text
