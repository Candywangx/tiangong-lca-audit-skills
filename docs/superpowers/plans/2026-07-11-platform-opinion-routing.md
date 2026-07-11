# Platform Opinion Routing Implementation Plan

> **For Codex:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task, with a fresh implementer and two-stage review for each task.

**Goal:** Separate audit severity from submitter communication, generate the approved version-one platform opinion, and ensure only safe routed content reaches the platform draft API.

**Architecture:** Add one shared platform-projection contract and one central routing/rendering module. Agent reviews, deterministic findings, and source checks retain their evidence-report shape while optionally carrying a validated projection. Semantic review builds a distinct `platform_comment`; the CLI submits only that projection and rejects invalid drafts before constructing a write client.

**Tech Stack:** Python 3, dataclasses, JSON Schema, pytest, Markdown reference contracts, existing Tiangong API client.

---

### Task 1: Add the platform projection contract and Agent findings v2

**Files:**
- Create: `src/tiangong_audit/contracts/platform.py`
- Modify: `src/tiangong_audit/contracts/__init__.py`
- Modify: `src/tiangong_audit/contracts/agent_review.py`
- Modify: `src/tiangong_audit/contracts/schemas/agent-findings.schema.json`
- Modify: `src/tiangong_audit/cli.py`
- Modify: `tests/test_agent_review.py`
- Modify: `tests/test_cli.py`

**Step 1: Write failing contract tests**

Add these named tests before implementation:
- v2 templates containing `platform: {"disposition": "internal_only"}` and `platform_overrides: []`;
- v1 artifacts remaining readable;
- required/non-empty messages for non-internal projections;
- messages forbidden for `internal_only`;
- the severity/disposition matrix;
- non-internal projection forbidden on `pass` and `not_applicable` reviews;
- exact `rule_id` + `location` override shape and duplicate-target rejection;
- `test_python_and_json_schema_accept_same_valid_v2_payload`;
- `test_python_and_json_schema_reject_same_invalid_v2_payload` for an advisory/required mismatch;
- `test_required_paths_include_platform_modules_and_test` asserting both new product modules and `tests/test_platform_opinion.py` are registered.

Define the minimal public interface before implementation: `PlatformProjection.from_dict()`, `validate_platform_projection(severity, payload)`, controlled `PLATFORM_ORIGINS = {agent, deterministic, source_check, semantic_context, validation, extraction, workflow}`, and `is_internal_blocking_origin(origin)`. Export the contract symbols from `contracts/__init__.py`.

**Step 2: Run tests to verify RED**

Run: `pytest -q tests/test_agent_review.py tests/test_cli.py -k 'agent or required_paths'`
Expected failures include missing `platform_overrides`, import failure for `contracts.platform`, and the new required-path assertion.

**Step 3: Implement the minimal contract**

Create shared constants/dataclass/parser in `contracts/platform.py`. Promote the writer constant to `tiangong-audit-agent-findings-v2`, retain v1 in the supported read versions, add projection fields and override validation, and update the schema without loosening `additionalProperties`.

**Step 4: Run tests to verify GREEN**

Run: `pytest -q tests/test_agent_review.py tests/test_cli.py -k 'agent or required_paths'`
Expected: PASS.

**Step 5: Commit**

```bash
git add src/tiangong_audit/contracts/platform.py src/tiangong_audit/contracts/__init__.py src/tiangong_audit/contracts/agent_review.py src/tiangong_audit/contracts/schemas/agent-findings.schema.json src/tiangong_audit/cli.py tests/test_agent_review.py tests/test_cli.py
git commit -m "feat: add platform projection contract"
```

### Task 2: Extend and validate field-level source checks

**Files:**
- Modify: `src/tiangong_audit/contracts/source.py`
- Modify: `tests/test_sources.py`

**Step 1: Write failing source-contract tests**

Add named tests `test_source_check_defaults_severity_by_status`, `test_source_check_platform_round_trip`, `test_validate_source_checks_rejects_invalid_status_severity`, and `test_validate_source_checks_rejects_invalid_disposition`. Cover the complete matrix, blocking conflict defaulting to required, and matched/not-applicable checks rejecting submitter-facing projections. The minimal interface is `SourceCheck.resolved_severity()`, `SourceCheck.platform`, and `validate_source_checks(payload) -> list[str]`.

**Step 2: Run tests to verify RED**

Run: `pytest -q tests/test_sources.py`
Expected failures are missing constructor fields/methods and missing `validate_source_checks` import.

**Step 3: Implement source-check validation**

Add optional `severity` and `platform`, deterministic default resolution, and a validator that reports invalid combinations without silently coercing them.

**Step 4: Run tests to verify GREEN**

Run: `pytest -q tests/test_sources.py`
Expected: PASS.

**Step 5: Commit**

```bash
git add src/tiangong_audit/contracts/source.py tests/test_sources.py
git commit -m "feat: classify source check impact"
```

### Task 3: Centralize platform routing and version-one rendering

**Files:**
- Create: `src/tiangong_audit/report/platform.py`
- Modify: `src/tiangong_audit/report/markdown.py`
- Create: `tests/test_platform_opinion.py`
- Modify: `tests/test_rule_engine.py`

**Step 1: Write failing routing/rendering tests**

Add named tests `test_legacy_severity_defaults_are_conservative`, `test_explicit_platform_items_render_in_priority_order`, `test_approved_comment_is_none`, `test_internal_origin_always_invalidates_comment`, `test_blocking_cannot_be_hidden`, and `test_blocking_source_conflict_defaults_to_required`. Test:
- legacy blocking -> required while legacy advisory/manual/input-gap stay internal;
- explicit required, clarification, and suggestion labels and ordering;
- continuous circled numbering and the non-blocking suggestion footer;
- approved result -> `无`, with suggestions suppressed;
- rejected/manual/information-insufficient invariants;
- each controlled internal origin (`semantic_context`, `validation`, `extraction`, `workflow`) making the comment invalid, including one required finding plus one internal extraction gap;
- explicit blocking + `internal_only` being rejected rather than hidden;
- blocking source conflict without an explicit platform object rendering as required.

**Step 2: Run tests to verify RED**

Run: `pytest -q tests/test_platform_opinion.py tests/test_rule_engine.py`
Expected failures are missing `report.platform`, current advisory leakage, and current renderer returning platform text for approved suggestions.

**Step 3: Implement central routing**

Build `build_platform_comment(result)` with `valid`, `validation_errors`, `opinion`, and safe routed findings. It must read a controlled `origin` field rather than infer origin from free text. Keep approved opinion exactly `无`. Update the Markdown renderer to consume this module and preserve legacy blocking composition.

**Step 4: Run tests to verify GREEN**

Run: `pytest -q tests/test_platform_opinion.py tests/test_rule_engine.py`
Expected: PASS.

**Step 5: Commit**

```bash
git add src/tiangong_audit/report/platform.py src/tiangong_audit/report/markdown.py tests/test_platform_opinion.py tests/test_rule_engine.py
git commit -m "feat: route and render platform opinions"
```

### Task 4: Integrate routing into semantic review and source reconciliation

**Files:**
- Modify: `src/tiangong_audit/workflows/semantic_review.py`
- Modify: `tests/test_semantic_review_workflow.py`
- Create: `tests/fixtures/regressions/generator-platform-opinion.json`

**Step 1: Write failing workflow tests**

Before changing the workflow, add the sanitized generator fixture and named test `test_generator_platform_opinion_has_one_required_and_two_suggestions`; it must fail because advisory/manual routing is not explicit yet. Assert exact labels/messages and absence of steel-shape, cutoff-coverage, DQR, and aggregate-source text. Also add named tests proving:
- advisory-only source uncertainty produces `基本一致，有建议补充` and does not cap the result;
- mixed source statuses follow blocking > input gap > manual review > advisory > matched;
- field-level findings are emitted once and aggregate ambiguity is not duplicated;
- a deterministic advisory promoted through one exact `platform_overrides` target appears once in the evidence report and once in the platform opinion;
- unmatched, ambiguous, and duplicate overrides fail validation;
- `audit-result.platform.json` contains the routed `platform_comment` while retaining all evidence findings separately.
- invalid source checks create a controlled `origin="validation"` internal finding and make `platform_comment.valid=false` even when another required finding exists;
- deterministic, Agent, source-check, semantic-context, validation, extraction, and workflow construction paths each assign their explicit controlled origin.

**Step 2: Run tests to verify RED**

Run: `pytest -q tests/test_semantic_review_workflow.py`
Expected failures include the generator opinion mismatch, no `platform_comment`, missing origin values, and invalid source checks being silently consumed.

**Step 3: Implement semantic integration**

Call `validate_source_checks()` immediately after reading `checks.json`. Convert any contract error into one internal validation-origin finding; do not continue source impact coercion for invalid rows. Assign controlled origins at every finding construction/ingestion boundary, carry Agent and source projections, merge deterministic overrides by exact `rule_id` + `location`, remove duplicate aggregate source reminders, implement source impact priority, and construct `platform_comment` in `_platform_result()`.

**Step 4: Run tests to verify GREEN**

Run: `pytest -q tests/test_semantic_review_workflow.py`
Expected: PASS.

**Step 5: Commit**

```bash
git add src/tiangong_audit/workflows/semantic_review.py tests/test_semantic_review_workflow.py tests/fixtures/regressions/generator-platform-opinion.json
git commit -m "feat: project semantic findings to platform"
```

### Task 5: Make platform draft payload safe and exact

**Files:**
- Modify: `src/tiangong_audit/cli.py`
- Modify: `tests/test_cli.py`

**Step 1: Write failing CLI tests**

Add named tests `test_comment_payload_uses_only_platform_comment`, `test_legacy_platform_result_adapter_is_conservative`, `test_invalid_dry_run_has_no_side_effects`, and `test_invalid_execute_stops_before_client_factory`. Assert the exact `app_review_save_comment_draft` envelope and comment JSON:
- `summary` equals `platform_comment.opinion` byte for byte;
- only routed findings are present;
- `auditor_notes` is null;
- internal summary, notes, source/tool limitations, and Agent/workflow state are absent;
- approved draft uses `无` and empty findings;
- invalid comments fail in dry-run and execute before client construction;
- legacy artifacts receive conservative routing.

The legacy test must use the real v1 platform-result shape (`title`, `description`, `related_field`, `suggested_fix`; internal top-level `summary` object), cover all four severities, and assert only blocking is routed. Conclusion normalization accepts `approved/pass/passed/通过`, `rejected/fail/不通过`, manual-review variants, and information-insufficient variants; unknown conclusions fail closed. Legacy text maps only `title`, `description`, `related_field`, and `suggested_fix` into the safe projection and never reads legacy internal summary/auditor notes. Invalid dry-run must create no client, operation-log row, case mutation, or pending-write output.

**Step 2: Run tests to verify RED**

Run: `pytest -q tests/test_cli.py -k 'save_result_draft or comment_payload'`
Expected failures show the current payload still contains internal summary/auditor notes and all four findings, and invalid dry-run currently reaches payload preparation without the required safety error.

**Step 3: Implement safe payload creation**

Read only `platform_comment`, map the opinion to submitter-facing `summary`, force `auditor_notes=None`, and reject invalid comments before any logging, case mutation, pending-write output, or client factory call. Add an explicit `adapt_legacy_platform_result()` that maps only the safe v1 fields listed above into central-router input, normalizes known conclusions, routes only blocking by default, and fails closed on malformed/unknown input.

**Step 4: Run tests to verify GREEN**

Run: `pytest -q tests/test_cli.py -k 'save_result_draft or comment_payload'`
Expected: PASS.

**Step 5: Commit**

```bash
git add src/tiangong_audit/cli.py tests/test_cli.py
git commit -m "fix: submit only routed platform comments"
```

### Task 6: Update the Skill contracts and templates

**Files:**
- Modify: `skill/tiangong-lca-audit/references/output-contract.md`
- Modify: `skill/tiangong-lca-audit/references/audit-policy.md`
- Modify: `skill/tiangong-lca-audit/references/input-contract.md`
- Modify: `skill/tiangong-lca-audit/references/process-audit.md`
- Modify: `skill/tiangong-lca-audit/references/platform-operations.md`
- Modify: `skill/tiangong-lca-audit/assets/audit-result-template.md`
- Modify: `tests/test_content_hygiene.py`
- Modify: `tests/test_skill_contract.py`

**Step 1: Write failing content/contract tests**

Require the four dispositions, three labels, approved opinion `无`, suggestion non-blocking language, source status/impact separation, and the no-platform-write-without-human-confirmation boundary. Add assertions that old hardcoded “blocking + advisory enter platform opinion” language is absent.

**Step 2: Run tests to verify RED**

Run: `pytest -q tests/test_content_hygiene.py tests/test_skill_contract.py`
Expected: FAIL because the references describe the old routing behavior.

**Step 3: Update normative documentation once**

Keep severity and evidence boundaries in `audit-policy.md`, input shape in `input-contract.md`, output routing in `output-contract.md`, process guidance in `process-audit.md`, and platform execution in `platform-operations.md`. Update the asset to show version-one density without duplicating normative rules.

**Step 4: Run tests to verify GREEN**

Run: `pytest -q tests/test_content_hygiene.py tests/test_skill_contract.py`
Expected: PASS.

**Step 5: Commit**

```bash
git add skill/tiangong-lca-audit/references skill/tiangong-lca-audit/assets/audit-result-template.md tests/test_content_hygiene.py tests/test_skill_contract.py
git commit -m "docs: define platform opinion routing"
```

### Task 7: Run compatibility and repository verification

**Files:**
- Modify only if a verification failure exposes a defect in the files already changed.

**Step 1: Run focused compatibility suites**

Run:

```bash
pytest -q tests/test_agent_review.py tests/test_sources.py tests/test_platform_opinion.py
pytest -q tests/test_semantic_review_workflow.py -k 'generator_platform_opinion or source or override'
pytest -q tests/test_cli.py -k 'save_result_draft or comment_payload or required_paths'
```

Expected: PASS. The generator regression was already introduced RED-first in Task 4; this task does not add post-hoc behavior tests.

**Step 2: Run repository verification**

Run:

```bash
PYTHONPATH=src python3 -m tiangong_audit.cli check
pytest -q
git diff --check
```

Expected: Skill check PASS, complete suite PASS, no whitespace errors.

**Step 3: Fix only demonstrated integration defects**

If any command fails, first add or refine the smallest reproducing test in the owning task’s test file, confirm it fails, implement the minimal correction, and rerun both focused and full checks. Commit such a correction separately as `fix: resolve platform routing integration`.

### Task 8: Final scope and branch review

**Files:**
- Review only: all changed files on `feature/platform-opinion-routing`

**Step 1: Inspect branch scope**

Run:

```bash
git status --short
git log --oneline --decorate --max-count=12
git diff main...HEAD --stat
```

Confirm no `cases/`, credentials, platform writes, or unrelated user files are included.

**Step 2: Re-run the mandatory checks**

Run:

```bash
PYTHONPATH=src python3 -m tiangong_audit.cli check
pytest -q
```

**Step 3: Perform final code review**

Review implementation against `docs/superpowers/specs/2026-07-11-platform-opinion-routing-design.md`, with particular attention to payload safety, backward compatibility, conclusion invariants, and duplicate findings.

**Step 4: Hand off the branch**

Report the branch name, commits, verification results, and any remaining operational limitation. Do not merge or perform a platform write without a separate user request.
