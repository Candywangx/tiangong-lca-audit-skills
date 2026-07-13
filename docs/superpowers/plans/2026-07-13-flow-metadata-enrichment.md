# Flow Metadata Enrichment Implementation Plan

**Goal:** Fetch and normalize referenced flow metadata before deterministic checks, distinguish evidence-collection gaps from submitter data errors, and support auditable refutation of disproven precheck findings.

**Architecture:** Keep platform access in `DatasetAPI`, evidence materialization in intake, schema normalization in `projected.py`, conclusion semantics in the rule engine, and deterministic-finding resolution in the Agent review contract and semantic workflow.

## Task 1: Flow API and classification parsing

- Add failing API and normalizer tests.
- Add `DatasetAPI.get_flow()` and `FLOW_COLUMNS`.
- Support prefixed and unprefixed classification keys.
- Verify focused tests.

## Task 2: Intake enrichment

- Add an intake regression whose process exchanges contain only UUID/version references.
- Fetch unique referenced flows, persist evidence and enriched snapshots, attach lookup status, then normalize.
- Verify no false metadata finding and one lookup for duplicate references.

## Task 3: Metadata status semantics

- Add rule tests for resolved-missing and unresolved lookup states.
- Carry `flow_metadata_status` through both raw and projected normalization.
- Keep resolved-missing blocking; convert workflow evidence gaps to `input_gap`.

## Task 4: Deterministic finding refutation

- Add contract and semantic workflow tests for exact, ambiguous, duplicate, and evidence-free resolutions.
- Extend the v2 Agent findings schema with optional `precheck_resolutions`.
- Remove only exactly matched refuted findings and retain the resolution in Agent-review summary.

## Task 5: Product contract and verification

- Document enrichment evidence and precheck refutation in the Skill contracts.
- Run focused tests, `PYTHONPATH=src python3 -m tiangong_audit.cli check`, full pytest, and explicit passing/failing metadata regressions.
