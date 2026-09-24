# Platform Opinion Clarity Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development to implement this plan.

**Goal:** Restore explicit severity labels and readable actionable platform comments across the reporting pipeline and the 20 reviewed local cases.

**Architecture:** Audit policy remains the source for severity; output-contract owns public label and wording rules. Preserve evidence and conclusions. Add minimal presentation support and validation to the renderer; rewrite each case from verified findings and retain issue-to-evidence traceability. The case batch and previous user changes stay local and intact.

**Tech Stack:** Python, pytest, Markdown, local JSON case artifacts.

## Chunk 1: Contract and renderer

- [x] Extend renderer regression tests using anonymized findings: all four labels, sorted order, missing evidence versus confirmed error, unknown severity, deduplication without merging severity, explicit authored wording, core input gaps versus internal tool limitations. Run them before implementing; record expected failures.
- [x] Update `src/tiangong_audit/report/markdown.py` and minimal relevant workflow/contract code. Use actual severity, never text keywords or report conclusion. Keep human writing as authored text; do not attempt regex paraphrasing.
- [x] Update `skill/tiangong-lca-audit/references/output-contract.md` as the sole writing-policy source; template and SKILL navigation refer to it. Preserve source/identity evidence and only include actionable submitter requests.
- [x] Add meaningful contract and integration checks, then run targeted tests.

## Chunk 2: Local case repair

- [x] Preserve original report/draft snapshots and record user correction in the ignored batch directory.
- [x] PET worker rewrites selected indices 0,1,2,4,5,7,8,9,10; industrial worker rewrites 3,6,15–19; root rewrites hydro 11–14. Read original evidence and severity before writing.
- [x] Each issue carries existing severity and source references, with 2–3 clear sentences about field, fact and action. Label and sort centrally, merge only the same actionable cause without silently changing severity.
- [x] Synchronize independent report, semantic report platform section and local platform-comment.json from final reviewed wording; retain previous versions.
- [x] Update batch summary and verify all 20 report/draft copies agree, conclusions and audit evidence are unchanged, every issue is labeled and ordered, and source links exist.

## Chunk 3: Verification

- [x] Independent review: public labels match the actual findings; core evidence gaps do not become proved errors; natural language does not lose units, page references or change conditions.
- [x] Run `PYTHONPATH=src .venv/bin/python -m tiangong_audit.cli check`.
- [x] Run `PYTHONPATH=src .venv/bin/python -m pytest -q`.
- [x] Review final diff for duplicate policy sources, unrelated changes, case privacy and invalid paths. Deliver corrected batch index and a brief summary of validation.

## Representation decision

- Entity: authored platform-opinion projection.
- Product role/consumers: Agent-written text reproduced by local Markdown and draft renderers for human review.
- Maturity/truth: grounded in real reviewed cases; derived presentation, never audit or platform truth.
- Freedom level: F2, natural-language text with only severity and finding references constrained.
- Representation: optional `agent-review/platform-opinions.json`, items carry `severity`, `text`, `finding_refs` (case-relative file plus JSON pointer). Do not replicate rule verdicts or infer severity from prose.
- Evidence: every item references an existing actionable finding; same-severity grouping preserves every linked issue. Verified blockers remain visible when authored items are incomplete.
- Allowed mutations: rewrite wording and regroup the same cause; severity must match the authoritative reviewed finding. Source-conflict default severity can be reconciled only through an explicit reference to the existing Agent judgment.
- Promotion/demotion: formal API changes only if this projection becomes an external submission contract; keep optional and local while authoring conventions evolve.
- Validation: reject invalid refs/tags/severities, compare all output copies, test missing labels and mixed-severity regressions, human-check the 20 real rewrites and evidence retention.

## Completion evidence

CLI Skill check passed; all 317 tests passed. Independent review confirmed both final runtime guard fixes. All 20 local cases share identical authored platform text across independent report, semantic report, local draft and exported result. Original case evidence and conclusions are preserved. No platform writes were executed.
