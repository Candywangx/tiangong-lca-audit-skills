# Document parser upgrade implementation plan

**Goal:** Preserve page-level source evidence and support resumable MinerU parsing using the current service contract.

**Architecture:** A standalone stdlib Skill client handles HTTP, schema validation, durable task records and evidence rendering. The audit attachment workflow imports the resulting bundle into the case; audit judgment remains with the Agent.

**Reference:** unstructure-serve f0d4097c3352d41a0a69066b563ccd20e845c4da, verified against its routers and AI integration guide. Actual deployment OpenAPI is checked before submission.

- [x] Add regression tests for endpoint routing, multipart placement, formats, page/type retention, DOCX text differences, and asynchronous recovery without reposting.
- [x] Implement scripts/mineru_client.py (HTTP/schema), mineru_results.py (validation/output), mineru_jobs.py (durable lifecycle), and update mineru_fulltext_extract.py (CLI).
- [x] Add --extraction-dir to source attach-extraction; validate and import complete provenance under source parsing/, preserving prior text and supplementary scanning.
- [x] Update Skill navigation, authoritative request contract, environment examples and audit documentation.
- [x] Run targeted tests, full pytest, PYTHONPATH=src python -m tiangong_audit.cli check, and git diff --check. Review links and duplicate instructions.

Acceptance: sync and async HTTP test server exercises actual client requests; timeout/unknown-submit/recovery tests assert POST counts; invalid payloads never become successful evidence. No live source uploads are required for offline regression. Real deployment/model accuracy remains a separate integration check.

Verification completed: 255 tests passed, including 28 standalone client/HTTP integration cases; repository check, parser lint and local-link checks passed. Independent review findings on source snapshot identity and response-body deadlines were reproduced, fixed and rechecked. No live document/model service quality test was performed.
