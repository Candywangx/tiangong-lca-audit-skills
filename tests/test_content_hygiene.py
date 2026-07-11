from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "skill/tiangong-lca-audit"
BANNED_TEXT = {
    "Tiangong-Data-Audit",
    "legacy-browser-extension",
    "runtimeAuditContext.js",
    "audit-rules-v0",
    "references/reference-summaries",
    "references/report-examples",
    "styles/approved-",
    "placeholder for future",
    "可将有明确修改价值的阻断问题、建议修改和人工确认项合并进平台意见",
    "以上【建议】项不作为本轮通过前提，可结合本次修改一并完善。",
}


def test_skill_contains_no_source_project_residue():
    for path in SKILL.rglob("*"):
        if not path.is_file() or path.suffix not in {".md", ".json", ".yaml", ".yml", ".py"}:
            continue
        text = path.read_text(encoding="utf-8")
        for banned in BANNED_TEXT:
            assert banned not in text, f"{banned!r} found in {path}"


def test_skill_has_no_empty_or_redundant_resource_folders():
    assert not (SKILL / "scripts").exists()
    assert not (SKILL / "references/reference-summaries").exists()
    assert not (SKILL / "assets/report-templates").exists()


def test_context_documents_stay_small():
    for path in [SKILL / "SKILL.md", *(SKILL / "references").glob("*.md")]:
        assert path.stat().st_size < 20_000, f"{path} is too large for routine context"
