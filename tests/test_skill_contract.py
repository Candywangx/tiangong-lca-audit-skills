import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "skill/tiangong-lca-audit"
DOCUMENT_DECOMPOSE_SKILL = ROOT / "skill/document-granular-decompose"


def load_document_decompose_script():
    script = DOCUMENT_DECOMPOSE_SKILL / "scripts/mineru_fulltext_extract.py"
    spec = importlib.util.spec_from_file_location("mineru_fulltext_extract", script)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_skill_has_one_execution_guide():
    assert (SKILL / "SKILL.md").exists()
    assert not (SKILL / "prompts").exists()


def test_document_granular_decompose_skill_is_installed():
    assert (DOCUMENT_DECOMPOSE_SKILL / "SKILL.md").exists()
    assert (DOCUMENT_DECOMPOSE_SKILL / "agents/openai.yaml").exists()
    assert (DOCUMENT_DECOMPOSE_SKILL / "references/env.md").exists()
    assert (DOCUMENT_DECOMPOSE_SKILL / "references/request-response.md").exists()
    assert (DOCUMENT_DECOMPOSE_SKILL / "assets/config.example.env").exists()
    script = DOCUMENT_DECOMPOSE_SKILL / "scripts/mineru_fulltext_extract.py"
    assert script.exists()
    text = script.read_text(encoding="utf-8")
    assert "/mineru_with_images" in text
    assert "return_txt" in text


def test_env_example_contains_document_decompose_keys():
    env_example = (ROOT / ".env.example").read_text(encoding="utf-8")
    assert "UNSTRUCTURED_API_BASE_URL" in env_example
    assert "UNSTRUCTURED_AUTH_TOKEN" in env_example
    assert "UNSTRUCTURED_PROVIDER" in env_example
    assert "UNSTRUCTURED_MODEL" in env_example


def test_document_decompose_accepts_base_url_or_full_endpoint(monkeypatch):
    module = load_document_decompose_script()

    monkeypatch.setenv("UNSTRUCTURED_API_BASE_URL", "https://example.test")
    assert module.resolve_api_url("") == "https://example.test/mineru_with_images"

    monkeypatch.setenv(
        "UNSTRUCTURED_API_BASE_URL", "https://example.test/api/v1/mineru_with_images"
    )
    assert module.resolve_api_url("") == "https://example.test/api/v1/mineru_with_images"

    monkeypatch.setenv("UNSTRUCTURED_API_BASE_URL", "https://example.test/api/v1")
    assert module.resolve_api_url("") == "https://example.test/api/v1/mineru_with_images"


def test_skill_references_are_focused():
    expected = {
        "audit-policy.md",
        "input-contract.md",
        "process-audit.md",
        "model-audit.md",
        "output-contract.md",
        "correction-policy.md",
        "platform-operations.md",
        "taxonomy-guide.md",
    }
    assert expected == {path.name for path in (SKILL / "references").glob("*.md")}


def test_skill_navigation_mentions_every_reference():
    skill_text = (SKILL / "SKILL.md").read_text(encoding="utf-8")
    for reference in (SKILL / "references").glob("*.md"):
        assert f"references/{reference.name}" in skill_text


def test_skill_routes_batch_output_to_output_contract():
    skill_text = (SKILL / "SKILL.md").read_text(encoding="utf-8")
    assert "批量审核时逐条生成独立报告" in skill_text
    assert "references/output-contract.md" in skill_text


def test_skill_requires_strict_dataset_type_and_linked_evidence():
    skill_text = (SKILL / "SKILL.md").read_text(encoding="utf-8")
    audit_policy = (SKILL / "references/audit-policy.md").read_text(encoding="utf-8")
    input_contract = (SKILL / "references/input-contract.md").read_text(encoding="utf-8")
    process_audit = (SKILL / "references/process-audit.md").read_text(encoding="utf-8")
    assert "数据集类型是否有边界和聚合层级证据支撑" in skill_text
    assert "不能把字段值当作默认可信结论" in process_audit
    assert "Partly terminated system" in process_audit
    assert "关联证据" in input_contract
    assert "不得因为页面主表未显示底层流属性而默认流、单位或类型正确" in input_contract
    assert "平台状态为“已通过”或存在历史通过记录" in audit_policy


def test_process_audit_covers_cfia_recycling_allocation_water_and_dqr():
    process_audit = (SKILL / "references/process-audit.md").read_text(encoding="utf-8")
    assert "cut-off" in process_audit
    assert "recycled-content" in process_audit
    assert "avoided burden" in process_audit
    assert "共用流" in process_audit
    assert "废水处理边界" in process_audit
    assert "DQR" in process_audit


def test_source_review_requires_supplementary_material_followup():
    skill_text = (SKILL / "SKILL.md").read_text(encoding="utf-8")
    process_audit = (SKILL / "references/process-audit.md").read_text(encoding="utf-8")
    input_contract = (SKILL / "references/input-contract.md").read_text(encoding="utf-8")
    assert "document-granular-decompose" in skill_text
    assert "document-granular-decompose" in process_audit
    assert "related_artifact_requirements" in skill_text
    assert "Supplementary Table S8" in process_audit
    assert "出版商/DOI 页面" in process_audit
    assert "related_artifact_requirements" in input_contract


def test_skill_documents_dynamic_results_and_precise_wording_boundaries():
    audit_policy = (SKILL / "references/audit-policy.md").read_text(encoding="utf-8")
    output_contract = (SKILL / "references/output-contract.md").read_text(encoding="utf-8")
    assert "平台动态生成的 LCIA 结果" in audit_policy
    assert "无判定标准的程度词" in output_contract


def test_skill_routes_pass_results_to_draft_only_and_requires_taxonomy_search():
    skill_text = (SKILL / "SKILL.md").read_text(encoding="utf-8")
    platform_ops = (SKILL / "references/platform-operations.md").read_text(encoding="utf-8")
    taxonomy = (SKILL / "references/taxonomy-guide.md").read_text(encoding="utf-8")
    assert "只保存草稿" in skill_text
    assert "不得默认分配" in skill_text
    assert "不得调用 `cmd_review_assign_reviewers`" in platform_ops
    assert "app_review_save_comment_draft" in platform_ops
    assert "必须实际检索" in taxonomy
    assert "记录检索词、命中候选" in taxonomy


def test_classification_findings_must_carry_taxonomy_candidates_to_output():
    process_audit = (SKILL / "references/process-audit.md").read_text(encoding="utf-8")
    output_contract = (SKILL / "references/output-contract.md").read_text(encoding="utf-8")
    assert "检索词、命中候选和未采用候选" in process_audit
    assert "候选分类路径或候选范围" in output_contract
    assert "无法确认唯一候选" in output_contract


def test_platform_operations_define_review_scope_from_dataset_type():
    platform_ops = (SKILL / "references/platform-operations.md").read_text(encoding="utf-8")
    assert "范围名称" in platform_ops
    assert "建模信息-数据集类型" in platform_ops
    assert "typeOfDataSet" in platform_ops
    assert "中文名称" in platform_ops
    assert "单元过程，单一操作" in platform_ops


def test_platform_operations_define_process_pass_workflow_and_model_boundary():
    skill_text = (SKILL / "SKILL.md").read_text(encoding="utf-8")
    platform_ops = (SKILL / "references/platform-operations.md").read_text(encoding="utf-8")
    assert "过程数据通过流程" in skill_text
    assert "model-pass-flow" in skill_text
    assert "过程数据通过流程" in platform_ops
    assert "模型数据通过流程" in platform_ops
    assert "不得把模型数据套用过程数据的范围名称" in platform_ops
    assert "app_dataset_create" in platform_ops
    assert "app_review_save_comment_draft" in platform_ops
    assert "重新读取评论" in platform_ops


def test_platform_operations_have_explicit_checkpoints_and_blacklist():
    platform_ops = (SKILL / "references/platform-operations.md").read_text(encoding="utf-8")
    assert "STOP/CHECKPOINT" in platform_ops
    assert "禁止动作" in platform_ops
    assert "不得提交审核" in platform_ops
    assert "不得使用非分配审核员账号" in platform_ops
    assert "不得在真实平台使用创建函数探测字段" in platform_ops


def test_platform_read_entry_uses_admin_until_draft_writeback():
    platform_ops = (SKILL / "references/platform-operations.md").read_text(encoding="utf-8")
    assert "查看待审核队列" in platform_ops
    assert "默认都使用管理员账号 `admin`" in platform_ops
    assert "只有在写回建议" in platform_ops
    assert "`reject`" in platform_ops
    assert "`pass`" in platform_ops


def test_process_pass_workflow_forbids_direct_submit_comment():
    platform_ops = (SKILL / "references/platform-operations.md").read_text(encoding="utf-8")
    assert "通过审核" in platform_ops
    assert "不得解释为提交审核意见" in platform_ops
    assert "app_review_submit_comment" in platform_ops
    assert "会从 member 待审核队列移入已审核队列" in platform_ops
    assert "只能使用 app_review_save_comment_draft" in platform_ops


def test_platform_operations_use_reference_compliance_declarations():
    platform_ops = (SKILL / "references/platform-operations.md").read_text(encoding="utf-8")
    assert "0a263660-a557-491a-ab58-bdf6f9222765" in platform_ops
    assert "5 条合规系统声明样板" in platform_ops
    assert "不得简化为单条 ILCD Entry-level" in platform_ops


def test_skill_frontmatter_mentions_process_pass_workflow_trigger():
    skill_text = (SKILL / "SKILL.md").read_text(encoding="utf-8")
    header = skill_text.split("---", 2)[1]
    assert "过程数据通过流程" in header
    assert "平台暂存" in header
