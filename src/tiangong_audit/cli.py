from __future__ import annotations

import argparse
from datetime import date
import json
from pathlib import Path
import re
import sys
import logging
from uuid import uuid4

from tiangong_audit.case_store import CaseStore, CaseStoreError
from tiangong_audit.contracts import OperationLogEntry
from tiangong_audit.contracts.agent_review import (
    new_agent_findings_template,
    validate_agent_findings,
)
from tiangong_audit.evals import load_eval_cases, score_review_result
from tiangong_audit.evals.harness import get_eval_case
from tiangong_audit.normalizer import normalize_dataset
from tiangong_audit.process_pass_flow import (
    ModelPassWorkflow,
    ProcessPassFlowError,
    ProcessPassWorkflow,
)
from tiangong_audit.report.markdown import render_findings
from tiangong_audit.report.review_request import render_review_request
from tiangong_audit.rule_engine import (
    GuardrailError,
    load_skill_guardrails,
    run_deterministic_checks,
)
from tiangong_audit.sources import generate_source_claims
from tiangong_audit.workflows import (
    attach_extraction,
    fetch_sources,
    intake_review,
    resolve_sources,
    semantic_review,
)
from tiangong_audit.integrations import tiangong_api
from tiangong_audit.integrations.tidas_sdk import (
    TidasSdkValidationError,
    validate_enhanced,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[2]
CASE_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
ACCOUNT_ROLE_CHOICES = ("admin", "member", "reject", "pass")
REQUIRED_PATHS = (
    "README.md",
    "AGENTS.md",
    "pyproject.toml",
    ".env.example",
    ".gitignore",
    "skill/tiangong-lca-audit/SKILL.md",
    "skill/tiangong-lca-audit/agents/openai.yaml",
    "skill/tiangong-lca-audit/references/audit-policy.md",
    "skill/tiangong-lca-audit/references/input-contract.md",
    "skill/tiangong-lca-audit/references/process-audit.md",
    "skill/tiangong-lca-audit/references/model-audit.md",
    "skill/tiangong-lca-audit/references/output-contract.md",
    "skill/tiangong-lca-audit/references/correction-policy.md",
    "skill/tiangong-lca-audit/references/platform-operations.md",
    "skill/tiangong-lca-audit/references/taxonomy-guide.md",
    "skill/tiangong-lca-audit/rules/common.json",
    "skill/tiangong-lca-audit/rules/process.json",
    "skill/tiangong-lca-audit/rules/model.json",
    "skill/tiangong-lca-audit/rules/schema.json",
    "skill/tiangong-lca-audit/rules/guardrails.json",
    "skill/tiangong-lca-audit/assets/taxonomies/cfia-category-taxonomy.json",
    "skill/tiangong-lca-audit/assets/taxonomies/tiangong-category-paths.json",
    "skill/tiangong-lca-audit/assets/audit-result-template.md",
    "skill/tiangong-lca-audit/assets/approval-report-template.md",
    "skill/tiangong-lca-audit/assets/correction-record-template.md",
    "skill/document-granular-decompose/SKILL.md",
    "skill/document-granular-decompose/agents/openai.yaml",
    "skill/document-granular-decompose/references/env.md",
    "skill/document-granular-decompose/references/request-response.md",
    "skill/document-granular-decompose/assets/config.example.env",
    "skill/document-granular-decompose/scripts/mineru_fulltext_extract.py",
    "src/tiangong_audit/__init__.py",
    "src/tiangong_audit/case_store.py",
    "src/tiangong_audit/contracts/__init__.py",
    "src/tiangong_audit/contracts/agent_review.py",
    "src/tiangong_audit/contracts/case.py",
    "src/tiangong_audit/contracts/finding.py",
    "src/tiangong_audit/contracts/operation.py",
    "src/tiangong_audit/contracts/source.py",
    "src/tiangong_audit/contracts/schemas/case.schema.json",
    "src/tiangong_audit/contracts/schemas/source-artifact.schema.json",
    "src/tiangong_audit/contracts/schemas/finding.schema.json",
    "src/tiangong_audit/contracts/schemas/agent-findings.schema.json",
    "src/tiangong_audit/evals/__init__.py",
    "src/tiangong_audit/evals/harness.py",
    "src/tiangong_audit/normalizer/projected.py",
    "src/tiangong_audit/process_pass_flow.py",
    "src/tiangong_audit/rule_engine/engine.py",
    "src/tiangong_audit/rule_engine/guardrails.py",
    "src/tiangong_audit/report/markdown.py",
    "src/tiangong_audit/report/review_request.py",
    "src/tiangong_audit/sources/__init__.py",
    "src/tiangong_audit/sources/downloader.py",
    "src/tiangong_audit/sources/extractor.py",
    "src/tiangong_audit/sources/claims.py",
    "src/tiangong_audit/sources/resolver.py",
    "src/tiangong_audit/workflows/__init__.py",
    "src/tiangong_audit/workflows/intake.py",
    "src/tiangong_audit/workflows/semantic_review.py",
    "src/tiangong_audit/workflows/source.py",
    "tests/test_skill_contract.py",
    "tests/test_rules.py",
    "tests/test_agent_review.py",
    "tests/test_content_hygiene.py",
    "tests/test_assets.py",
    "tests/test_case_store.py",
    "tests/test_contracts.py",
    "tests/test_evals.py",
    "tests/test_normalizer.py",
    "tests/test_process_pass_flow.py",
    "tests/test_rule_engine.py",
    "tests/test_sources.py",
    "tests/test_cli.py",
    "docs/architecture.md",
    "docs/workflow.md",
    "docs/environment.md",
    "docs/tiangong-integration.md",
    "docs/asset-boundaries.md",
    "cases/.gitkeep",
)


def _validate_id(value: str) -> None:
    if not CASE_ID_PATTERN.match(value):
        raise SystemExit("Invalid case id. Use letters, numbers, dots, underscores, or hyphens.")


def _read_json(path: str) -> dict:
    if path == "-":
        return json.load(sys.stdin)
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _write_output(path: str | None, content: str) -> None:
    if not path or path == "-":
        sys.stdout.write(content)
        return
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    print(f"Wrote: {target}")


def _case_path_label(path: Path, root: Path) -> str:
    try:
        return str(Path(path).relative_to(root / "cases"))
    except ValueError:
        return str(path)


def _case_store() -> CaseStore:
    return CaseStore(ROOT / "cases")


def _optional_case(review_id: str, batch_id: str | None = None):
    store = _case_store()
    try:
        return store, store.get_case(review_id, batch_id=batch_id)
    except CaseStoreError:
        return store, None


def _append_operation_if_case(
    review_id: str,
    *,
    batch_id: str | None = None,
    operation: str,
    status: str,
    dry_run: bool,
    details: dict | None = None,
    error: str = "",
):
    store, manifest = _optional_case(review_id, batch_id=batch_id)
    if manifest is None:
        return None
    store.append_operation(
        manifest,
        OperationLogEntry(
            operation=operation,
            status=status,
            target_id=review_id,
            dry_run=dry_run,
            details=details or {},
            error=error,
        ),
    )
    return manifest


def _default_batch_id(label: str | None = None) -> str:
    parts = [date.today().strftime("%Y%m%d")]
    if label:
        parts.append(label)
    return "-".join(parts)


def create_case(args: argparse.Namespace) -> int:
    _validate_id(args.case_id)
    batch_id = getattr(args, "batch_id", None) or _default_batch_id("manual")
    try:
        manifest = _case_store().create_case(
            review_id=args.case_id,
            batch_id=batch_id,
            dataset_id=getattr(args, "dataset_id", "") or "",
            version=getattr(args, "version", "") or "",
            dataset_type=getattr(args, "dataset_type", "") or "",
            name_zh=getattr(args, "name_zh", "") or getattr(args, "title", "") or "",
            name_en=getattr(args, "name_en", "") or "",
            force=getattr(args, "force", False),
        )
    except CaseStoreError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1

    print(f"Created audit case workspace: {ROOT / 'cases' / manifest.case_dir}")
    return 0


def case_init_batch(args: argparse.Namespace) -> int:
    try:
        batch_dir = _case_store().init_batch(args.batch_id)
    except CaseStoreError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    print(f"Created audit batch workspace: {batch_dir}")
    return 0


def case_list(args: argparse.Namespace) -> int:
    records = _case_store().list_cases(status=args.status)
    if args.format == "jsonl":
        content = "\n".join(json.dumps(record, ensure_ascii=False) for record in records)
        _write_output(args.output, (content + "\n") if content else "")
        return 0
    lines = ["# Audit Cases", ""]
    if not records:
        lines.append("No cases found.")
    for record in records:
        lines.append(
            "- "
            f"{record.get('review_id')} | {record.get('status')} | "
            f"{record.get('dataset_type') or '-'} | {record.get('name_zh') or record.get('dataset_id') or '-'}"
        )
    _write_output(args.output, "\n".join(lines).rstrip() + "\n")
    return 0


def case_status(args: argparse.Namespace) -> int:
    try:
        manifest = _case_store().get_case(args.review_id, batch_id=args.batch_id)
    except CaseStoreError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    _write_output(args.output, json.dumps(manifest.to_dict(), ensure_ascii=False, indent=2) + "\n")
    return 0


def case_update(args: argparse.Namespace) -> int:
    store = _case_store()
    try:
        manifest = store.get_case(args.review_id, batch_id=args.batch_id)
        if args.status:
            manifest.status = args.status
        if args.conclusion:
            manifest.conclusion = args.conclusion
        if args.platform_state:
            manifest.platform_state = args.platform_state
        if args.report:
            manifest.report = args.report
        for step in args.set_step or []:
            manifest.set_step(step, True)
        for step in args.clear_step or []:
            manifest.set_step(step, False)
        store.write_case(manifest)
    except (CaseStoreError, ValueError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    _write_output(args.output, json.dumps(manifest.to_dict(), ensure_ascii=False, indent=2) + "\n")
    return 0


def _case_lookup(store: CaseStore) -> dict[str, dict]:
    lookup: dict[str, dict] = {}
    rank = {
        "initialized": 0,
        "intake_fetched": 1,
        "intake_completed": 2,
        "reported": 3,
        "draft_saved": 4,
        "submitted": 5,
        "completed": 6,
    }
    for record in store.iter_index():
        review_id = str(record.get("review_id") or "")
        if not review_id:
            continue
        existing = lookup.get(review_id)
        if existing is None or rank.get(str(record.get("status") or ""), 0) >= rank.get(
            str(existing.get("status") or ""), 0
        ):
            lookup[review_id] = record
    return lookup


def _item_name_zh(item: dict) -> str:
    name = (
        item.get("json", {})
        .get("data", {})
        .get("name", {})
    )
    base_names = name.get("baseName") if isinstance(name, dict) else None
    if isinstance(base_names, list):
        for value in base_names:
            if value.get("@xml:lang") == "zh" and value.get("#text"):
                return str(value["#text"])
    return ""


def _audit_state(record: dict | None, manifest: dict | None) -> str:
    if record is None:
        return "not_started"
    steps = dict((manifest or {}).get("steps") or {})
    status = str(record.get("status") or "")
    if steps.get("platform_written") or status in {"draft_saved", "submitted", "completed"}:
        return "draft_saved" if status == "draft_saved" else status or "platform_written"
    if steps.get("reported") or status == "reported":
        return "reported_not_written"
    if steps.get("prechecked") or status == "intake_completed":
        return "intake_completed"
    if steps.get("fetched") or status == "intake_fetched":
        return "intake_fetched"
    return status or "local_case"


def _next_step(audit_state: str) -> str:
    return {
        "not_started": "run intake-review",
        "intake_fetched": "finish intake/source checks",
        "intake_completed": "run semantic review and prepare report",
        "reported_not_written": "save platform draft after human confirmation",
        "draft_saved": "review saved draft or submit manually",
        "submitted": "done",
        "completed": "done",
    }.get(audit_state, "inspect case")


def case_coverage(args: argparse.Namespace) -> int:
    try:
        queue = _read_json(args.queue)
    except (OSError, json.JSONDecodeError) as error:
        print(f"ERROR: Unable to read queue snapshot: {error}", file=sys.stderr)
        return 1
    items = queue.get("items") if isinstance(queue, dict) else None
    if not isinstance(items, list):
        print("ERROR: Queue snapshot must contain an items array.", file=sys.stderr)
        return 1

    store = _case_store()
    cases_by_review_id = _case_lookup(store)
    rows = []
    for item in items:
        review_id = str(item.get("id") or item.get("review_id") or "")
        record = cases_by_review_id.get(review_id)
        manifest = None
        if record and record.get("case_dir"):
            try:
                manifest = store.read_case_path(store.root / str(record["case_dir"]) / "case.json").to_dict()
            except (CaseStoreError, OSError, ValueError, json.JSONDecodeError):
                manifest = None
        audit_state = _audit_state(record, manifest)
        rows.append(
            {
                "review_id": review_id,
                "dataset_id": item.get("data_id") or item.get("dataset_id"),
                "version": item.get("data_version") or item.get("version"),
                "name_zh": (record or {}).get("name_zh") or _item_name_zh(item),
                "queue_state_code": item.get("state_code"),
                "local_status": (record or {}).get("status"),
                "audit_state": audit_state,
                "reviewed": audit_state in {"draft_saved", "submitted", "completed"},
                "case_dir": (record or {}).get("case_dir"),
                "next_step": _next_step(audit_state),
            }
        )

    summary: dict[str, int] = {}
    for row in rows:
        summary[row["audit_state"]] = summary.get(row["audit_state"], 0) + 1
    output = {
        "queue_total": queue.get("total", len(items)) if isinstance(queue, dict) else len(items),
        "queue_items": len(items),
        "summary": summary,
        "items": rows,
    }
    if args.format == "markdown":
        lines = [
            "# Case Coverage",
            "",
            f"- Queue total: {output['queue_total']}",
            f"- Queue items in snapshot: {output['queue_items']}",
            f"- Summary: {json.dumps(summary, ensure_ascii=False, sort_keys=True)}",
            "",
            "| Review ID | Dataset | Name | Audit State | Next Step |",
            "| --- | --- | --- | --- | --- |",
        ]
        for row in rows:
            lines.append(
                "| "
                f"{row['review_id']} | "
                f"{row['dataset_id'] or ''} | "
                f"{row['name_zh'] or ''} | "
                f"{row['audit_state']} | "
                f"{row['next_step']} |"
            )
        _write_output(args.output, "\n".join(lines) + "\n")
    else:
        _write_output(args.output, json.dumps(output, ensure_ascii=False, indent=2) + "\n")
    return 0


def source_resolve(args: argparse.Namespace) -> int:
    try:
        refs = resolve_sources(
            _read_json(args.input),
            case_store=_case_store() if getattr(args, "review_id", None) else None,
            review_id=getattr(args, "review_id", None),
            batch_id=getattr(args, "batch_id", None),
            external_doc_base_url=getattr(args, "external_doc_base_url", None),
        )
    except (OSError, json.JSONDecodeError, CaseStoreError, ValueError) as error:
        print(f"ERROR: Unable to resolve sources: {error}", file=sys.stderr)
        return 1
    _write_output(
        args.output,
        json.dumps([ref.to_dict() for ref in refs], ensure_ascii=False, indent=2) + "\n",
    )
    return 0


def source_fetch(args: argparse.Namespace) -> int:
    try:
        summary = fetch_sources(
            _read_json(args.input),
            root=ROOT,
            case_store=_case_store() if getattr(args, "review_id", None) else None,
            review_id=getattr(args, "review_id", None),
            batch_id=getattr(args, "batch_id", None),
            output_dir=Path(args.output_dir) if args.output_dir else None,
            external_doc_base_url=getattr(args, "external_doc_base_url", None),
            account_role=getattr(args, "account_role", None),
        )
    except (OSError, json.JSONDecodeError, CaseStoreError, ValueError, tiangong_api.TiangongAPIError) as error:
        print(f"ERROR: Unable to fetch sources: {error}", file=sys.stderr)
        return 1
    _write_output(args.output, json.dumps(summary, ensure_ascii=False, indent=2) + "\n")
    return 0


def source_claims(args: argparse.Namespace) -> int:
    try:
        claims = generate_source_claims(_read_json(args.input))
    except (OSError, json.JSONDecodeError, ValueError) as error:
        print(f"ERROR: Unable to generate source claims: {error}", file=sys.stderr)
        return 1
    _write_output(args.output, json.dumps(claims, ensure_ascii=False, indent=2) + "\n")
    return 0


def check_workspace(_: argparse.Namespace) -> int:
    errors: list[str] = []
    for rel_path in REQUIRED_PATHS:
        if not (ROOT / rel_path).exists():
            errors.append(f"missing required path: {rel_path}")

    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1

    print("Tiangong LCA audit skill check passed.")
    return 0


def normalize_input(args: argparse.Namespace) -> int:
    try:
        normalized = normalize_dataset(_read_json(args.input))
    except (OSError, json.JSONDecodeError, ValueError) as error:
        raise SystemExit(f"Unable to normalize input: {error}") from error
    content = json.dumps(normalized, ensure_ascii=False, indent=2) + "\n"
    _write_output(args.output, content)
    return 0


def check_rules(args: argparse.Namespace) -> int:
    try:
        normalized = normalize_dataset(_read_json(args.input))
        result = run_deterministic_checks(
            normalized,
            guardrails=load_skill_guardrails(ROOT),
        )
    except (OSError, json.JSONDecodeError, GuardrailError, ValueError) as error:
        raise SystemExit(f"Unable to check rules: {error}") from error

    content = (
        render_findings(result)
        if args.format == "markdown"
        else json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    )
    _write_output(args.output, content)
    return 1 if args.fail_on_blocking and result["summary"]["blocking"] else 0


def _has_validation_errors(result: dict) -> bool:
    if result.get("success") is False:
        return True
    return any(
        issue.get("severity") == "error"
        for issue in result.get("validationIssues", [])
        if isinstance(issue, dict)
    )


def validate_structure(args: argparse.Namespace) -> int:
    """Run schema-level validation through TIDAS SDK validateEnhanced()."""
    try:
        result = validate_enhanced(
            _read_json(args.input),
            entity_type=args.entity_type,
            mode=args.mode,
            include_warnings=args.include_warnings,
            timeout=args.timeout,
        )
    except (OSError, json.JSONDecodeError, TidasSdkValidationError) as error:
        print(f"ERROR: Unable to validate structure: {error}", file=sys.stderr)
        return 1

    _write_output(args.output, json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    return 1 if args.fail_on_error and _has_validation_errors(result) else 0


def _get_current_user_id(client: tiangong_api.TiangongAPIClient) -> str:
    user = client._request("GET", "auth/v1/user")
    user_id = user.get("id") if isinstance(user, dict) else None
    if not user_id:
        raise tiangong_api.TiangongAuthError("Unable to resolve current platform user id")
    return str(user_id)


def _pass_flow_output_dir(args: argparse.Namespace, operation_dir: str) -> Path:
    if getattr(args, "output_dir", None):
        return Path(args.output_dir)
    _, manifest = _optional_case(args.review_id, batch_id=getattr(args, "batch_id", None))
    if manifest is None:
        raise CaseStoreError("--output-dir is required when the review case cannot be found")
    return ROOT / "cases" / manifest.case_dir / "operations" / operation_dir


def _record_pass_flow_result(
    review_id: str,
    *,
    batch_id: str | None,
    operation: str,
    output_dir: Path,
    execute: bool,
    status: str,
    summary: dict | None = None,
    error: str = "",
) -> None:
    store, manifest = _optional_case(review_id, batch_id=batch_id)
    if manifest is None:
        return
    details = {
        "output_dir": str(output_dir),
        "execute": execute,
        "summary": summary or {},
    }
    if status == "completed" and execute:
        manifest.status = "draft_saved"
        manifest.platform_state = "draft_saved"
        manifest.set_step("platform_written", True)
        manifest.artifacts[operation] = _case_path_label(output_dir, ROOT)
        store.write_case(manifest)
    store.append_operation(
        manifest,
        OperationLogEntry(
            operation=operation,
            status=status,
            target_id=review_id,
            dry_run=not execute,
            details=details,
            error=error,
        ),
    )


def process_pass_flow(args: argparse.Namespace) -> int:
    """Run the fixed process-dataset pass workflow."""
    try:
        output_dir = _pass_flow_output_dir(args, "process-pass")
    except CaseStoreError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    try:
        client = tiangong_api.TiangongAPIClient(
            account_role=args.account_role,
            allow_writes=args.execute,
        )
        workflow = ProcessPassWorkflow(
            client=client,
            review_api=tiangong_api.ReviewAPI(client),
            dataset_api=tiangong_api.DatasetAPI(client),
            template_path=ROOT / "skill/tiangong-lca-audit/assets/approval-report-template.docx",
            current_user_id=_get_current_user_id(client),
            uuid_factory=lambda: str(uuid4()),
            today=date.today,
        )
        summary = workflow.execute(
            args.review_id,
            output_dir,
            execute=args.execute,
        )
    except (OSError, json.JSONDecodeError, tiangong_api.TiangongAPIError, ProcessPassFlowError) as error:
        _record_pass_flow_result(
            args.review_id,
            batch_id=getattr(args, "batch_id", None),
            operation="process_pass_flow",
            output_dir=output_dir,
            execute=args.execute,
            status="failed",
            error=str(error),
        )
        print(f"ERROR: Unable to run process pass flow: {error}", file=sys.stderr)
        return 1

    _record_pass_flow_result(
        args.review_id,
        batch_id=getattr(args, "batch_id", None),
        operation="process_pass_flow",
        output_dir=output_dir,
        execute=args.execute,
        status="completed" if args.execute else "dry_run",
        summary=summary,
    )
    _write_output(getattr(args, "output", None), json.dumps(summary, ensure_ascii=False, indent=2) + "\n")
    return 0


def model_pass_flow(args: argparse.Namespace) -> int:
    """Run the fixed life-cycle-model pass workflow."""
    try:
        output_dir = _pass_flow_output_dir(args, "model-pass")
    except CaseStoreError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    try:
        client = tiangong_api.TiangongAPIClient(
            account_role=args.account_role,
            allow_writes=args.execute,
        )
        workflow = ModelPassWorkflow(
            client=client,
            review_api=tiangong_api.ReviewAPI(client),
            dataset_api=tiangong_api.DatasetAPI(client),
            template_path=ROOT / "skill/tiangong-lca-audit/assets/approval-report-template.docx",
            current_user_id=_get_current_user_id(client),
            uuid_factory=lambda: str(uuid4()),
            today=date.today,
        )
        summary = workflow.execute(
            args.review_id,
            output_dir,
            execute=args.execute,
        )
    except (OSError, json.JSONDecodeError, tiangong_api.TiangongAPIError, ProcessPassFlowError) as error:
        _record_pass_flow_result(
            args.review_id,
            batch_id=getattr(args, "batch_id", None),
            operation="model_pass_flow",
            output_dir=output_dir,
            execute=args.execute,
            status="failed",
            error=str(error),
        )
        print(f"ERROR: Unable to run model pass flow: {error}", file=sys.stderr)
        return 1

    _record_pass_flow_result(
        args.review_id,
        batch_id=getattr(args, "batch_id", None),
        operation="model_pass_flow",
        output_dir=output_dir,
        execute=args.execute,
        status="completed" if args.execute else "dry_run",
        summary=summary,
    )
    _write_output(getattr(args, "output", None), json.dumps(summary, ensure_ascii=False, indent=2) + "\n")
    return 0


def audit_bundle(args: argparse.Namespace) -> int:
    try:
        normalized = normalize_dataset(_read_json(args.input))
        result = run_deterministic_checks(
            normalized,
            guardrails=load_skill_guardrails(ROOT),
        )
    except (OSError, json.JSONDecodeError, GuardrailError, ValueError) as error:
        raise SystemExit(f"Unable to prepare audit: {error}") from error

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    normalized_path = output_dir / "normalized.json"
    precheck_json_path = output_dir / "precheck.json"
    precheck_markdown_path = output_dir / "precheck.md"
    review_request_path = output_dir / "agent-review-request.md"

    normalized_path.write_text(
        json.dumps(normalized, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    precheck_json_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    precheck_markdown_path.write_text(render_findings(result), encoding="utf-8")
    review_request_path.write_text(
        render_review_request(
            normalized_path.name,
            precheck_json_path.name,
            result,
        ),
        encoding="utf-8",
    )
    print(f"Audit bundle created: {output_dir}")
    print(f"Precheck conclusion: {result['conclusion']}")
    print(f"Next: run Agent semantic review using {review_request_path}")
    return 0


def fetch_tasks(args: argparse.Namespace) -> int:
    """Fetch a review queue from the platform."""
    try:
        account_role = getattr(args, "account_role", None) or args.role
        client = tiangong_api.TiangongAPIClient(account_role=account_role)
        review_api = tiangong_api.ReviewAPI(client)

        if args.role == "admin":
            response = review_api.get_admin_tasks(
                status=args.status or "unassigned",
                page=args.page,
                page_size=args.page_size,
            )
        else:
            response = review_api.get_member_tasks(
                status=args.status or "pending",
                page=args.page,
                page_size=args.page_size,
            )

        _write_output(
            args.output,
            json.dumps(response, ensure_ascii=False, indent=2) + "\n",
        )
        return 0
    except tiangong_api.TiangongAPIError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1


def fetch_dataset(args: argparse.Namespace) -> int:
    """Fetch one process or lifecycle model from the platform."""
    try:
        client = tiangong_api.TiangongAPIClient(
            account_role=getattr(args, "account_role", None)
        )
        dataset_api = tiangong_api.DatasetAPI(client)
        if args.dataset_type == "auto":
            response = dataset_api.resolve_dataset(args.dataset_id, args.version)
        else:
            response = dataset_api.get_dataset(
                args.dataset_id,
                args.version,
                tiangong_api.DatasetType(args.dataset_type),
            )
        _write_output(
            args.output,
            json.dumps(response, ensure_ascii=False, indent=2) + "\n",
        )
        return 0
    except tiangong_api.TiangongAPIError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1


def _comment_payload_from_result_data(result_data: dict) -> dict:
    findings = []
    for index, finding in enumerate(result_data.get("findings", [])):
        findings.append(
            {
                "id": finding.get("id") or finding.get("rule_id") or f"finding_{index}",
                "severity": finding.get("severity", "manual_review"),
                "title": finding.get("title") or finding.get("rule_id") or f"Finding {index + 1}",
                "description": finding.get("description")
                or finding.get("judgment")
                or finding.get("evidence")
                or "",
                "evidence": finding.get("evidence", ""),
                "suggested_fix": finding.get("suggested_fix") or finding.get("suggestion"),
                "related_field": finding.get("related_field") or finding.get("location"),
                "tags": finding.get("tags", []),
            }
        )
    return {
        "conclusion": result_data["conclusion"],
        "summary": result_data["summary"],
        "findings": findings,
        "auditor_notes": result_data.get("auditor_notes"),
    }


def _draft_account_role_for_result(result_data: dict) -> str:
    conclusion = str(result_data.get("conclusion") or "").strip().lower()
    if conclusion in {"approved", "pass", "passed", "通过"}:
        return "pass"
    return "reject"


def save_result_draft(args: argparse.Namespace) -> int:
    """Save an audit comment draft without submitting the review."""
    try:
        result_data = _read_json(args.result)
        review_id = args.review_id or result_data.get("review_task_id")
        if not review_id:
            raise KeyError("review_task_id")
        comment = _comment_payload_from_result_data(result_data)
    except (OSError, json.JSONDecodeError, KeyError, TypeError) as error:
        print(f"ERROR: Invalid result format: {error}", file=sys.stderr)
        return 1

    account_role = args.account_role or _draft_account_role_for_result(result_data)
    operation_details = {
        "account_role": account_role,
        "result": args.result,
        "operation": "app_review_save_comment_draft",
        "submitted": False,
    }
    if not args.execute:
        _append_operation_if_case(
            review_id,
            batch_id=getattr(args, "batch_id", None),
            operation="app_review_save_comment_draft",
            status="dry_run",
            dry_run=True,
            details={**operation_details, "comment": comment},
        )
        _write_output(
            args.output,
            json.dumps(
                {
                    "dry_run": True,
                    "operation": "app_review_save_comment_draft",
                    "review_id": review_id,
                    "account_role": account_role,
                    "submitted": False,
                    "comment": comment,
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
        )
        return 0

    try:
        client = tiangong_api.TiangongAPIClient(
            account_role=account_role,
            allow_writes=True,
        )
        response = tiangong_api.ReviewAPI(client).save_comment_draft(review_id, comment)
    except tiangong_api.TiangongAPIError as error:
        _append_operation_if_case(
            review_id,
            batch_id=getattr(args, "batch_id", None),
            operation="app_review_save_comment_draft",
            status="failed",
            dry_run=False,
            details=operation_details,
            error=str(error),
        )
        print(f"ERROR: Unable to save review draft: {error}", file=sys.stderr)
        return 1

    store, manifest = _optional_case(review_id, batch_id=getattr(args, "batch_id", None))
    if manifest is not None:
        manifest.status = "draft_saved"
        manifest.platform_state = "draft_saved"
        manifest.conclusion = str(result_data.get("conclusion") or manifest.conclusion)
        manifest.set_step("platform_written", True)
        if args.result != "-":
            try:
                manifest.report = str(Path(args.result).resolve().relative_to(ROOT / "cases"))
            except ValueError:
                manifest.report = str(args.result)
        store.write_case(manifest)
        store.append_operation(
            manifest,
            OperationLogEntry(
                operation="app_review_save_comment_draft",
                status="completed",
                target_id=review_id,
                dry_run=False,
                details={**operation_details, "response": response},
            ),
        )
    _write_output(
        args.output,
        json.dumps(
            {
                "operation": "app_review_save_comment_draft",
                "review_id": review_id,
                "account_role": account_role,
                "submitted": False,
                "response": response,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
    )
    return 0


def review_intake(args: argparse.Namespace) -> int:
    """Fetch one review task, dataset, source evidence, and claims into cases/."""
    try:
        summary = intake_review(
            args.review_id,
            root=ROOT,
            account_role=args.account_role,
            batch_id=args.batch_id or _default_batch_id(args.account_role),
            case_store=_case_store(),
        )
    except (OSError, json.JSONDecodeError, CaseStoreError, ValueError, tiangong_api.TiangongAPIError) as error:
        print(f"ERROR: Unable to intake review: {error}", file=sys.stderr)
        return 1
    _write_output(args.output, json.dumps(summary, ensure_ascii=False, indent=2) + "\n")
    return 0


def _agent_findings_path(manifest) -> Path:
    return ROOT / "cases" / manifest.case_dir / "agent-review" / "agent-findings.json"


def agent_findings_template(args: argparse.Namespace) -> int:
    """Scaffold agent-review/agent-findings.json with every required rule pending."""
    store = _case_store()
    try:
        manifest = store.get_case(args.review_id, batch_id=args.batch_id)
    except CaseStoreError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    target = _agent_findings_path(manifest)
    if target.exists() and not args.force:
        print(f"ERROR: {target} already exists; use --force to overwrite.", file=sys.stderr)
        return 1
    payload = new_agent_findings_template(
        review_id=manifest.review_id,
        dataset_id=manifest.dataset_id,
        dataset_type=manifest.dataset_type,
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"Wrote agent findings template: {target}")
    print(
        "Fill every rule review with a pass/fail/cannot_judge/not_applicable verdict "
        "plus evidence_refs, then run `agent-findings validate`."
    )
    return 0


def agent_findings_validate(args: argparse.Namespace) -> int:
    """Validate agent-review/agent-findings.json against the evidence contract."""
    dataset_type = args.dataset_type or ""
    if not args.input and not args.review_id:
        print("ERROR: provide --review-id or --input.", file=sys.stderr)
        return 1
    if args.input:
        path = Path(args.input)
    else:
        store = _case_store()
        try:
            manifest = store.get_case(args.review_id, batch_id=args.batch_id)
        except CaseStoreError as error:
            print(f"ERROR: {error}", file=sys.stderr)
            return 1
        path = _agent_findings_path(manifest)
        dataset_type = dataset_type or manifest.dataset_type
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        print(f"ERROR: Unable to read agent findings: {error}", file=sys.stderr)
        return 1
    errors = validate_agent_findings(payload, dataset_type=dataset_type)
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        print(f"Agent findings failed contract validation: {len(errors)} error(s).", file=sys.stderr)
        return 1
    print(f"Agent findings contract check passed: {path}")
    return 0


def source_attach_extraction(args: argparse.Namespace) -> int:
    """Backfill a high-fidelity source extraction into the case source directory."""
    try:
        summary = attach_extraction(
            args.review_id,
            root=ROOT,
            source_dir_name=args.source_dir,
            extracted_text=Path(args.extracted_text),
            method=args.method,
            case_store=_case_store(),
            batch_id=args.batch_id,
        )
    except (OSError, json.JSONDecodeError, CaseStoreError, ValueError) as error:
        print(f"ERROR: Unable to attach extraction: {error}", file=sys.stderr)
        return 1
    _write_output(args.output, json.dumps(summary, ensure_ascii=False, indent=2) + "\n")
    return 0


def eval_list(args: argparse.Namespace) -> int:
    """List historical eval cases available for regression scoring."""
    try:
        cases = load_eval_cases(Path(args.evals) if args.evals else None)
    except (OSError, json.JSONDecodeError, ValueError) as error:
        print(f"ERROR: Unable to load eval cases: {error}", file=sys.stderr)
        return 1
    rows = [
        {
            "case_id": case.get("caseId"),
            "label": case.get("label"),
            "process_name": case.get("processName"),
            "expected_conclusion": case.get("expectedConclusion"),
            "issue_points": len(case.get("expectedIssuePoints") or []),
            "input": case.get("inputProjectedFile"),
        }
        for case in cases
    ]
    _write_output(args.output, json.dumps(rows, ensure_ascii=False, indent=2) + "\n")
    return 0


def eval_score(args: argparse.Namespace) -> int:
    """Score a produced audit result against one historical eval case."""
    try:
        case = get_eval_case(args.case_id, path=Path(args.evals) if args.evals else None)
        result = _read_json(args.result)
        score = score_review_result(case, result)
    except (OSError, json.JSONDecodeError, ValueError) as error:
        print(f"ERROR: Unable to score result: {error}", file=sys.stderr)
        return 1
    _write_output(args.output, json.dumps(score, ensure_ascii=False, indent=2) + "\n")
    failed = False
    if args.require_conclusion_match and not score["conclusion_match"]:
        print(
            f"FAIL: conclusion mismatch: expected {score['expected_conclusion']}, "
            f"got {score['actual_conclusion']}",
            file=sys.stderr,
        )
        failed = True
    if score["issue_point_coverage"] < args.fail_under:
        print(
            f"FAIL: issue point coverage {score['issue_point_coverage']:.2f} "
            f"is below --fail-under {args.fail_under:.2f}",
            file=sys.stderr,
        )
        failed = True
    return 1 if failed else 0


def review_semantic_review(args: argparse.Namespace) -> int:
    """Synthesize the full LCA semantic review report for one local case."""
    try:
        summary = semantic_review(
            args.review_id,
            root=ROOT,
            batch_id=args.batch_id,
            case_store=_case_store(),
        )
    except (OSError, json.JSONDecodeError, CaseStoreError, ValueError) as error:
        print(f"ERROR: Unable to run semantic review: {error}", file=sys.stderr)
        return 1
    _write_output(args.output, json.dumps(summary, ensure_ascii=False, indent=2) + "\n")
    return 0


def submit_result(args: argparse.Namespace) -> int:
    """Submit audit result to platform.

    IMPORTANT: This operation marks the task as completed.
    Ensure you have reviewed the findings before submitting.
    """
    try:
        # Load result from file
        result_data = _read_json(args.result)

        if args.force and args.confirm_submit != "app_review_submit_comment":
            print(
                "ERROR: --force requires --confirm-submit app_review_submit_comment.",
                file=sys.stderr,
            )
            return 1

        # Ask for confirmation
        if not args.force:
            print("\n" + "="*60)
            print("AUDIT RESULT SUBMISSION")
            print("="*60)
            print(f"Task ID: {result_data.get('review_task_id')}")
            print(f"Dataset ID: {result_data.get('dataset_id')}")
            print(f"Conclusion: {result_data.get('conclusion')}")
            print(f"Findings: {len(result_data.get('findings', []))}")
            print("="*60)

            confirm = input("\nSubmit this result to platform? (yes/no): ").lower()
            if confirm != "yes":
                print("Submission cancelled.")
                return 0

        # Convert to AuditResult model
        findings = [
            tiangong_api.AuditFinding(
                id=f.get("id", f"finding_{i}"),
                severity=tiangong_api.FindingSeverity(f["severity"]),
                title=f["title"],
                description=f["description"],
                evidence=f["evidence"],
                suggested_fix=f.get("suggested_fix"),
                related_field=f.get("related_field"),
                tags=f.get("tags", []),
            )
            for i, f in enumerate(result_data.get("findings", []))
        ]

        result = tiangong_api.AuditResult(
            review_task_id=result_data["review_task_id"],
            dataset_id=result_data["dataset_id"],
            conclusion=result_data["conclusion"],
            summary=result_data["summary"],
            findings=findings,
            auditor_notes=result_data.get("auditor_notes"),
        )

        # The write-capable client is created only after explicit confirmation.
        client = tiangong_api.TiangongAPIClient(
            account_role=getattr(args, "account_role", None),
            allow_writes=True,
        )
        review_api = tiangong_api.ReviewAPI(client)
        response = review_api.submit_result(result.review_task_id, result)

        print(f"✓ Audit result submitted successfully")
        print(f"  Task ID: {result.review_task_id}")
        print(f"  Conclusion: {result.conclusion}")

        if args.output:
            Path(args.output).write_text(
                json.dumps(response, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            print(f"  Response saved to: {args.output}")

        return 0
    except tiangong_api.TiangongAPIError as e:
        print(f"ERROR: Failed to submit result: {e}", file=sys.stderr)
        return 1
    except (OSError, json.JSONDecodeError, ValueError, KeyError) as e:
        print(f"ERROR: Invalid result format: {e}", file=sys.stderr)
        return 1


def list_actions(args: argparse.Namespace) -> int:
    """List platform operations that need to be executed based on audit result."""
    try:
        # Load audit result
        result_data = _read_json(args.result)

        # Convert to model
        findings = [
            tiangong_api.AuditFinding(
                id=f.get("id", f"finding_{i}"),
                severity=tiangong_api.FindingSeverity(f["severity"]),
                title=f["title"],
                description=f["description"],
                evidence=f["evidence"],
                suggested_fix=f.get("suggested_fix"),
                related_field=f.get("related_field"),
                tags=f.get("tags", []),
            )
            for i, f in enumerate(result_data.get("findings", []))
        ]

        result = tiangong_api.AuditResult(
            review_task_id=result_data["review_task_id"],
            dataset_id=result_data["dataset_id"],
            conclusion=result_data["conclusion"],
            summary=result_data["summary"],
            findings=findings,
            auditor_notes=result_data.get("auditor_notes"),
        )

        operation = getattr(args, "operation", "save-draft")
        actions = tiangong_api.ReviewAPI.generate_platform_actions(
            result,
            operation=operation,
        )

        # Format output
        warnings = [
            "⚠️  Platform operations are for review only.",
            "⚠️  User must confirm before execution.",
            "⚠️  Operation failures do not affect audit findings.",
        ]
        if operation == "save-draft":
            warnings.insert(2, "⚠️  Saving a draft does not submit or complete the review.")
        else:
            warnings.insert(2, "⚠️  Submitting completes the review result on the platform.")

        output = {
            "task_id": result.review_task_id,
            "dataset_id": result.dataset_id,
            "conclusion": result.conclusion,
            "operation": operation,
            "actions": [action.to_dict() for action in actions],
            "warnings": warnings,
        }

        if args.format == "markdown":
            content = _format_actions_markdown(output)
            _write_output(args.output, content)
        else:
            _write_output(args.output, json.dumps(output, ensure_ascii=False, indent=2) + "\n")

        return 0
    except tiangong_api.TiangongAPIError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1
    except (OSError, json.JSONDecodeError, ValueError, KeyError) as e:
        print(f"ERROR: Invalid result format: {e}", file=sys.stderr)
        return 1


def _format_actions_markdown(output: dict) -> str:
    """Format platform actions as markdown."""
    lines = [
        "# Platform Operations",
        "",
        f"**Task ID:** {output['task_id']}",
        f"**Dataset ID:** {output['dataset_id']}",
        f"**Conclusion:** {output['conclusion']}",
        f"**Operation:** {output['operation']}",
        "",
        "## Pending Actions",
        "",
    ]

    for i, action in enumerate(output["actions"], 1):
        lines.append(f"### Action {i}: {action['action_type']}")
        lines.append(f"- **Target:** {action['target_id']}")
        if action["description"]:
            lines.append(f"- **Description:** {action['description']}")
        if action["parameters"]:
            lines.append("- **Parameters:**")
            for key, value in action["parameters"].items():
                lines.append(f"  - `{key}`: {json.dumps(value)}")
        lines.append("")

    lines.append("## Warnings")
    lines.append("")
    for warning in output["warnings"]:
        lines.append(f"- {warning}")
    lines.append("")

    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="tiangong-audit")
    subparsers = parser.add_subparsers(dest="command", required=True)

    create_parser = subparsers.add_parser("create-case", help="Create an audit case workspace")
    create_parser.add_argument("case_id")
    create_parser.add_argument("--title", default="未命名审核对象")
    create_parser.add_argument("--batch-id", help="Batch id; defaults to today's date")
    create_parser.add_argument("--dataset-id", default="")
    create_parser.add_argument("--version", default="")
    create_parser.add_argument("--dataset-type", choices=("", "process", "model"), default="")
    create_parser.add_argument("--name-zh", default="")
    create_parser.add_argument("--name-en", default="")
    create_parser.add_argument("--created-at")
    create_parser.add_argument("--force", action="store_true")
    create_parser.set_defaults(func=create_case)

    case_parser = subparsers.add_parser("case", help="Manage canonical case storage")
    case_subparsers = case_parser.add_subparsers(dest="case_command", required=True)

    case_batch_parser = case_subparsers.add_parser("init-batch", help="Create a batch workspace")
    case_batch_parser.add_argument("batch_id")
    case_batch_parser.set_defaults(func=case_init_batch)

    case_create_parser = case_subparsers.add_parser("create", help="Create one review case")
    case_create_parser.add_argument("case_id", help="Review task id")
    case_create_parser.add_argument("--title", default="")
    case_create_parser.add_argument("--batch-id", help="Batch id; defaults to today's date")
    case_create_parser.add_argument("--dataset-id", default="")
    case_create_parser.add_argument("--version", default="")
    case_create_parser.add_argument("--dataset-type", choices=("", "process", "model"), default="")
    case_create_parser.add_argument("--name-zh", default="")
    case_create_parser.add_argument("--name-en", default="")
    case_create_parser.add_argument("--force", action="store_true")
    case_create_parser.set_defaults(func=create_case)

    case_list_parser = case_subparsers.add_parser("list", help="List cases from index.jsonl")
    case_list_parser.add_argument("--status")
    case_list_parser.add_argument("--format", choices=("jsonl", "markdown"), default="jsonl")
    case_list_parser.add_argument("--output")
    case_list_parser.set_defaults(func=case_list)

    case_coverage_parser = case_subparsers.add_parser(
        "coverage",
        help="Compare a platform queue snapshot with local cases",
    )
    case_coverage_parser.add_argument(
        "--queue",
        required=True,
        help="Queue JSON from fetch-tasks",
    )
    case_coverage_parser.add_argument(
        "--format",
        choices=("json", "markdown"),
        default="markdown",
    )
    case_coverage_parser.add_argument("--output")
    case_coverage_parser.set_defaults(func=case_coverage)

    case_status_parser = case_subparsers.add_parser("status", help="Show one case manifest")
    case_status_parser.add_argument("review_id")
    case_status_parser.add_argument("--batch-id")
    case_status_parser.add_argument("--output")
    case_status_parser.set_defaults(func=case_status)

    case_update_parser = case_subparsers.add_parser("update", help="Update one case status")
    case_update_parser.add_argument("review_id")
    case_update_parser.add_argument("--batch-id")
    case_update_parser.add_argument("--status")
    case_update_parser.add_argument("--conclusion")
    case_update_parser.add_argument("--platform-state")
    case_update_parser.add_argument("--report")
    case_update_parser.add_argument("--set-step", action="append", default=[])
    case_update_parser.add_argument("--clear-step", action="append", default=[])
    case_update_parser.add_argument("--output")
    case_update_parser.set_defaults(func=case_update)

    check_parser = subparsers.add_parser("check", help="Check workspace conventions")
    check_parser.set_defaults(func=check_workspace)

    lint_parser = subparsers.add_parser("lint", help="Alias for check")
    lint_parser.set_defaults(func=check_workspace)

    normalize_parser = subparsers.add_parser(
        "normalize", help="Normalize projected Tiangong process JSON"
    )
    normalize_parser.add_argument("--input", required=True, help="Input JSON path or - for stdin")
    normalize_parser.add_argument("--output", help="Output JSON path; defaults to stdout")
    normalize_parser.set_defaults(func=normalize_input)

    rules_parser = subparsers.add_parser(
        "check-rules", help="Run conservative deterministic checks on a process dataset"
    )
    rules_parser.add_argument("--input", required=True, help="Projected or normalized JSON path")
    rules_parser.add_argument("--output", help="Output path; defaults to stdout")
    rules_parser.add_argument("--format", choices=("json", "markdown"), default="json")
    rules_parser.add_argument("--fail-on-blocking", action="store_true")
    rules_parser.set_defaults(func=check_rules)

    source_parser = subparsers.add_parser("source", help="Resolve and verify dataset sources")
    source_subparsers = source_parser.add_subparsers(dest="source_command", required=True)

    source_resolve_parser = source_subparsers.add_parser(
        "resolve", help="Extract source references from a dataset JSON"
    )
    source_resolve_parser.add_argument("--input", required=True, help="Dataset JSON path or -")
    source_resolve_parser.add_argument("--review-id", help="Update the matching case manifest")
    source_resolve_parser.add_argument("--batch-id")
    source_resolve_parser.add_argument(
        "--external-doc-base-url",
        help="Base URL for relative external_docs references",
    )
    source_resolve_parser.add_argument("--output", help="Output JSON path; defaults to stdout")
    source_resolve_parser.set_defaults(func=source_resolve)

    source_fetch_parser = source_subparsers.add_parser(
        "fetch", help="Resolve, download, and extract dataset source artifacts"
    )
    source_fetch_parser.add_argument("--input", required=True, help="Dataset JSON path or -")
    source_fetch_parser.add_argument("--output-dir")
    source_fetch_parser.add_argument("--review-id", help="Use the case sources directory")
    source_fetch_parser.add_argument("--batch-id")
    source_fetch_parser.add_argument(
        "--account-role",
        choices=ACCOUNT_ROLE_CHOICES,
        help="Use authenticated platform storage for relative external_docs references",
    )
    source_fetch_parser.add_argument(
        "--external-doc-base-url",
        help="Base URL for relative external_docs references",
    )
    source_fetch_parser.add_argument("--output", help="Summary JSON path; defaults to stdout")
    source_fetch_parser.set_defaults(func=source_fetch)

    source_attach_parser = source_subparsers.add_parser(
        "attach-extraction",
        help="Backfill an image-aware or manual extraction into a case source",
    )
    source_attach_parser.add_argument("--review-id", required=True)
    source_attach_parser.add_argument("--batch-id", default=None)
    source_attach_parser.add_argument(
        "--source-dir",
        required=True,
        help="Case source directory name, e.g. source-001",
    )
    source_attach_parser.add_argument(
        "--extracted-text",
        required=True,
        help="Path to the full extracted text produced by document-granular-decompose",
    )
    source_attach_parser.add_argument(
        "--method",
        default="document-granular-decompose",
        help="Extraction method recorded in the source manifest",
    )
    source_attach_parser.add_argument("--output", default=None)
    source_attach_parser.set_defaults(func=source_attach_extraction)

    source_claims_parser = source_subparsers.add_parser(
        "claims", help="Generate conservative source-check claims from a dataset JSON"
    )
    source_claims_parser.add_argument("--input", required=True, help="Dataset JSON path or -")
    source_claims_parser.add_argument("--output", help="Output JSON path; defaults to stdout")
    source_claims_parser.set_defaults(func=source_claims)

    structure_parser = subparsers.add_parser(
        "validate-structure",
        help="Run TIDAS SDK validateEnhanced() schema validation",
    )
    structure_parser.add_argument("--input", required=True, help="TIDAS JSON path or - for stdin")
    structure_parser.add_argument("--output", help="Output JSON path; defaults to stdout")
    structure_parser.add_argument(
        "--entity-type",
        choices=(
            "process",
            "model",
            "lifeCycleModel",
            "contact",
            "flow",
            "source",
            "flowProperty",
            "unitGroup",
            "lciaMethod",
        ),
        default="process",
        help="TIDAS entity type; model is accepted as an alias for lifeCycleModel",
    )
    structure_parser.add_argument(
        "--mode",
        choices=("strict", "weak", "ignore"),
        default="strict",
        help="TIDAS SDK validation mode",
    )
    structure_parser.add_argument(
        "--include-warnings",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Include SDK warnings in enhanced validation output",
    )
    structure_parser.add_argument(
        "--timeout",
        type=int,
        default=30,
        help="Node SDK validation timeout in seconds",
    )
    structure_parser.add_argument(
        "--fail-on-error",
        action="store_true",
        help="Return non-zero when SDK validation reports errors",
    )
    structure_parser.set_defaults(func=validate_structure)

    pass_parser = subparsers.add_parser(
        "process-pass-flow",
        help="Create review report source and save process validation review draft",
    )
    pass_parser.add_argument("--review-id", required=True, help="Assigned review task id")
    pass_parser.add_argument(
        "--output-dir",
        help=(
            "Local evidence directory for generated payloads and readback snapshots; "
            "defaults to the case operations/process-pass directory"
        ),
    )
    pass_parser.add_argument("--batch-id", help="Batch id for updating the local case")
    pass_parser.add_argument("--output", help="Summary JSON path; defaults to stdout")
    pass_parser.add_argument(
        "--account-role",
        choices=("pass",),
        default="pass",
        help="Pass-draft account role (default: pass)",
    )
    pass_parser.add_argument(
        "--execute",
        action="store_true",
        help="Perform writes. Without this flag the command prepares payloads only.",
    )
    pass_parser.set_defaults(func=process_pass_flow)

    model_pass_parser = subparsers.add_parser(
        "model-pass-flow",
        help="Create review report source and save life-cycle-model validation review draft",
    )
    model_pass_parser.add_argument("--review-id", required=True, help="Assigned review task id")
    model_pass_parser.add_argument(
        "--output-dir",
        help=(
            "Local evidence directory for generated payloads and readback snapshots; "
            "defaults to the case operations/model-pass directory"
        ),
    )
    model_pass_parser.add_argument("--batch-id", help="Batch id for updating the local case")
    model_pass_parser.add_argument("--output", help="Summary JSON path; defaults to stdout")
    model_pass_parser.add_argument(
        "--account-role",
        choices=("pass",),
        default="pass",
        help="Pass-draft account role (default: pass)",
    )
    model_pass_parser.add_argument(
        "--execute",
        action="store_true",
        help="Perform writes. Without this flag the command prepares payloads only.",
    )
    model_pass_parser.set_defaults(func=model_pass_flow)

    audit_parser = subparsers.add_parser(
        "audit", help="Create a normalized audit bundle and run deterministic prechecks"
    )
    audit_parser.add_argument("--input", required=True, help="Projected or normalized JSON path")
    audit_parser.add_argument("--output-dir", required=True, help="Directory for the audit bundle")
    audit_parser.set_defaults(func=audit_bundle)

    # Platform integration commands
    fetch_parser = subparsers.add_parser("fetch-tasks", help="Fetch a platform review queue")
    fetch_parser.add_argument(
        "--role",
        choices=("admin", "member"),
        default="admin",
        help="Queue role: admin or member (default: admin)",
    )
    fetch_parser.add_argument(
        "--account-role",
        choices=ACCOUNT_ROLE_CHOICES,
        help="Login account role; defaults to the selected queue role",
    )
    fetch_parser.add_argument(
        "--status",
        help="Queue status; defaults to unassigned for admin and pending for member",
    )
    fetch_parser.add_argument("--page", type=int, default=1, help="Page number (default: 1)")
    fetch_parser.add_argument(
        "--page-size",
        type=int,
        default=10,
        help="Tasks per page (default: 10)",
    )
    fetch_parser.add_argument(
        "--output",
        help="Output JSON path; defaults to stdout"
    )
    fetch_parser.set_defaults(func=fetch_tasks)

    dataset_parser = subparsers.add_parser(
        "fetch-dataset", help="Fetch one process or lifecycle model from platform"
    )
    dataset_parser.add_argument("--dataset-id", required=True)
    dataset_parser.add_argument("--version", required=True)
    dataset_parser.add_argument(
        "--dataset-type",
        choices=("auto", "process", "model"),
        default="auto",
        help="Dataset type; defaults to automatic detection",
    )
    dataset_parser.add_argument(
        "--account-role",
        choices=ACCOUNT_ROLE_CHOICES,
        help="Login account role; defaults to TIANGONG_ACTIVE_ACCOUNT or legacy credentials",
    )
    dataset_parser.add_argument("--output", help="Output JSON path; defaults to stdout")
    dataset_parser.set_defaults(func=fetch_dataset)

    intake_parser = subparsers.add_parser(
        "intake-review",
        help="Fetch one review task, dataset, source docs, and generated claims into cases/",
    )
    intake_parser.add_argument("--review-id", required=True)
    intake_parser.add_argument(
        "--account-role",
        choices=ACCOUNT_ROLE_CHOICES,
        default="admin",
        help="Login account role for read-only intake and source downloads (default: admin)",
    )
    intake_parser.add_argument("--batch-id", help="Batch id; defaults to today's date")
    intake_parser.add_argument("--output", help="Summary JSON path; defaults to stdout")
    intake_parser.set_defaults(func=review_intake)

    semantic_parser = subparsers.add_parser(
        "semantic-review",
        help="Read Skill references, merge precheck/source checks, and write the formal audit result",
    )
    semantic_parser.add_argument("--review-id", required=True)
    semantic_parser.add_argument("--batch-id", help="Batch id for the local case")
    semantic_parser.add_argument("--output", help="Summary JSON path; defaults to stdout")
    semantic_parser.set_defaults(func=review_semantic_review)

    agent_findings_parser = subparsers.add_parser(
        "agent-findings",
        help="Scaffold and validate the Agent rule-review record for one case",
    )
    agent_findings_subparsers = agent_findings_parser.add_subparsers(
        dest="agent_findings_command", required=True
    )

    agent_template_parser = agent_findings_subparsers.add_parser(
        "template",
        help="Write agent-review/agent-findings.json with every required rule pending",
    )
    agent_template_parser.add_argument("--review-id", required=True)
    agent_template_parser.add_argument("--batch-id", default=None)
    agent_template_parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite an existing agent-findings.json",
    )
    agent_template_parser.set_defaults(func=agent_findings_template)

    agent_validate_parser = agent_findings_subparsers.add_parser(
        "validate",
        help="Check agent-findings.json against the evidence contract",
    )
    agent_validate_parser.add_argument("--review-id", default=None)
    agent_validate_parser.add_argument("--batch-id", default=None)
    agent_validate_parser.add_argument(
        "--input",
        default=None,
        help="Explicit agent-findings.json path; overrides --review-id lookup",
    )
    agent_validate_parser.add_argument(
        "--dataset-type",
        choices=("process", "model"),
        default=None,
        help="Dataset type for required-rule coverage; defaults to the case manifest",
    )
    agent_validate_parser.set_defaults(func=agent_findings_validate)

    eval_parser = subparsers.add_parser(
        "eval",
        help="Score audit results against historical eval cases",
    )
    eval_subparsers = eval_parser.add_subparsers(dest="eval_command", required=True)

    eval_list_parser = eval_subparsers.add_parser("list", help="List eval cases")
    eval_list_parser.add_argument("--evals", default=None, help="Eval catalog JSON path")
    eval_list_parser.add_argument("--output", default=None)
    eval_list_parser.set_defaults(func=eval_list)

    eval_score_parser = eval_subparsers.add_parser(
        "score",
        help="Score one produced result against one eval case",
    )
    eval_score_parser.add_argument("--case-id", required=True)
    eval_score_parser.add_argument(
        "--result",
        required=True,
        help="semantic-review.json, precheck.json, or any findings payload",
    )
    eval_score_parser.add_argument("--evals", default=None, help="Eval catalog JSON path")
    eval_score_parser.add_argument(
        "--fail-under",
        type=float,
        default=0.0,
        help="Exit 1 when issue point coverage is below this ratio",
    )
    eval_score_parser.add_argument(
        "--require-conclusion-match",
        action="store_true",
        help="Exit 1 when the produced conclusion disagrees with the historical one",
    )
    eval_score_parser.add_argument("--output", default=None)
    eval_score_parser.set_defaults(func=eval_score)

    draft_parser = subparsers.add_parser(
        "save-result-draft",
        help="Save audit result as a review comment draft without submitting",
    )
    draft_parser.add_argument("--result", required=True, help="Audit result JSON path or -")
    draft_parser.add_argument("--review-id", help="Override review_task_id in the result JSON")
    draft_parser.add_argument("--batch-id", help="Batch id for updating the local case")
    draft_parser.add_argument(
        "--account-role",
        choices=ACCOUNT_ROLE_CHOICES,
        default=None,
        help=(
            "Draft-writing semantic role. Defaults to reject for rejected results "
            "and pass for approved results."
        ),
    )
    draft_parser.add_argument(
        "--execute",
        action="store_true",
        help="Write the draft with app_review_save_comment_draft. Without this flag, emit payload only.",
    )
    draft_parser.add_argument("--output", help="Output JSON path; defaults to stdout")
    draft_parser.set_defaults(func=save_result_draft)

    submit_parser = subparsers.add_parser(
        "submit-result",
        help="Submit audit result to platform (REQUIRES CONFIRMATION)"
    )
    submit_parser.add_argument(
        "--result",
        required=True,
        help="Path to audit result JSON file or - for stdin"
    )
    submit_parser.add_argument(
        "--output",
        help="Output path for API response"
    )
    submit_parser.add_argument(
        "--force",
        action="store_true",
        help="Skip interactive prompt only with --confirm-submit app_review_submit_comment"
    )
    submit_parser.add_argument(
        "--confirm-submit",
        choices=("app_review_submit_comment",),
        help="Explicit acknowledgement that this completes the reviewer submit action"
    )
    submit_parser.add_argument(
        "--account-role",
        choices=ACCOUNT_ROLE_CHOICES,
        default="member",
        help="Login account role for submitting the review result (default: member)",
    )
    submit_parser.set_defaults(func=submit_result)

    actions_parser = subparsers.add_parser(
        "list-actions",
        help="List platform operations needed for audit result (no execution)"
    )
    actions_parser.add_argument(
        "--result",
        required=True,
        help="Path to audit result JSON file or - for stdin"
    )
    actions_parser.add_argument(
        "--operation",
        choices=("save-draft", "submit"),
        default="save-draft",
        help=(
            "Platform operation to list: save-draft writes a comment draft without "
            "submitting; submit lists the final submit action (default: save-draft)"
        ),
    )
    actions_parser.add_argument(
        "--output",
        help="Output path; defaults to stdout"
    )
    actions_parser.add_argument(
        "--format",
        choices=("json", "markdown"),
        default="json",
        help="Output format (default: json)"
    )
    actions_parser.set_defaults(func=list_actions)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
