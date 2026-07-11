# Platform Opinion Routing Design

## Goal

Separate audit severity from platform communication so that the semantic conclusion remains evidence-driven while the platform return opinion contains only proportionate, submitter-actionable messages written at the approved “版本一” density.

## Confirmed Product Rules

1. The platform rejection/comment box is the reviewer’s only communication channel with the submitter.
2. A verified blocking finding is a required correction and normally enters the platform opinion.
3. An advisory finding stays internal by default. When the case is already non-approved for a required correction or clarification, it enters the platform opinion only when the current review explicitly asks the submitter to address it, and is labelled `【建议】`. Suggestions never cause a rejection and are not written on an approved pass flow.
4. A manual-review or input-gap finding enters the platform opinion only when the submitter can resolve it by supplying facts or evidence, and is labelled `【请补充】`.
5. Internal tool limitations, aggregate source reminders, non-actionable DQR guidance, and requests that would force the submitter to invent unsupported data remain internal.
6. `【建议】` items are not prerequisites for approval. A non-approved platform opinion must state this when suggestions are present. A passing case continues to require platform return opinion `无`.
7. Platform text uses the approved “版本一” style: enough visible evidence to locate the issue, one clear judgment, and one executable action, without copying the entire internal finding.

## Root Cause

`render_platform_return_opinion()` currently selects findings using only severity:

```python
item["severity"] in {"blocking", "advisory"}
```

This mechanically includes every advisory finding and excludes every manual-review finding. Severity answers “does this affect the conclusion?”; it does not answer “must this be communicated to the submitter?”.

A second issue exists in source reconciliation: every `ambiguous` source check caps the source layer at `需人工确认`, even when the ambiguity is non-conflicting and immaterial to the core conclusion. Hiding such an item from the platform opinion would therefore leave the case unable to pass.

## Representation Decision

- Entity: platform communication projection attached to an audit finding.
- Product role: generate reviewer-approved, user-visible platform return text.
- Current maturity: repeated real-case evidence exists, but wording remains Agent-authored.
- Primary consumers: semantic-review, Markdown report renderer, platform draft payload, human reviewer, submitter.
- Truth status: draft projection until a human authorizes platform write; the platform write is F4 truth.
- Recommended freedom level: F3 contracted metadata plus free-form message text.
- Recommended representation: optional `platform` object with a controlled `disposition` enum and concise `message`, carried into a distinct platform-comment projection.
- Required evidence: the message must be traceable to the same finding’s location, evidence, judgment, and suggestion.
- Allowed mutations: Agent may select disposition and author message; validators enforce allowed values and required text.
- Promotion path: human confirmation promotes the draft message into a platform write.
- Demotion trigger: tool-only, duplicate, speculative, disproportional, or non-actionable findings become `internal_only`.
- Validation loop: schema validation, semantic workflow tests, renderer golden tests, and a regression based on the reviewed generator-manufacturing case.

## Finding Platform Projection

Add an optional object to Agent rule reviews and additional findings:

```json
{
  "platform": {
    "disposition": "required | clarification | suggested | internal_only",
    "message": "Concise platform-ready paragraph without the display label"
  }
}
```

Disposition meaning:

| Disposition | Display label | Meaning |
| --- | --- | --- |
| `required` | `【需修改】` | Must be corrected before approval |
| `clarification` | `【请补充】` | Submitter must provide a fact or evidence so review can continue |
| `suggested` | `【建议】` | Worth improving in this round but not an approval prerequisite |
| `internal_only` | none | Reviewer-only evidence or guidance |

New-code defaults for legacy artifacts:

- `blocking` -> `required`, using legacy composition when no explicit platform message exists.
- `advisory`, `manual_review`, `input_gap` -> `internal_only`.

An explicit non-internal disposition requires a trimmed non-empty message. `internal_only` forbids a message. Unknown properties are rejected. Invalid combinations are rejected:

- advisory may be `suggested` or `internal_only`;
- manual review and input gap may be `clarification` or `internal_only`;
- blocking must be `required`; tool and workflow defects must be represented as input gaps or manual review, never hidden blocking findings;
- only `fail` and `cannot_judge` rule reviews may carry non-internal projections because pass and not-applicable reviews do not materialize findings.

The Agent findings contract is promoted to `tiangong-audit-agent-findings-v2`. V2 adds per-finding `platform` metadata and the optional top-level `platform_overrides` array used only to project an already-existing deterministic finding without duplicating it. New code reads v1 artifacts using the defaults above and writes v2 templates. Old readers are not expected to accept v2 artifacts because their schema rejects unknown properties.

### Projection Resolution by Finding Origin

All finding origins receive a deterministic projection:

- Agent rule reviews and additional findings: use explicit `platform`, otherwise apply legacy defaults.
- Deterministic precheck findings: blocking -> required; advisory/manual/input-gap -> internal-only. An Agent may promote a deterministic non-blocking concern through a top-level `platform_overrides` entry targeting the existing finding by exact `rule_id` + `location`; the workflow merges the projection into that finding and does not create a duplicate finding. No match or multiple matches is a contract error, and more than one override for the same target is forbidden.
- Field-level source checks: blocking -> required and receives a legacy-composed message when no explicit projection exists; advisory/manual/input-gap -> internal-only unless a legal explicit source-check `platform` projection is present. Generated aggregate source reminders always remain internal.
- Semantic-context, validation, extraction, and workflow findings: remain internal. Any unresolved finding from these origins makes `platform_comment.valid=false` and blocks platform draft/write, even when another required or clarification finding is available for the submitter.
- Any verified blocking finding without a required message receives a legacy-composed required message; it may not be hidden.

## Source Check Conclusion Impact

Add optional `severity` and `platform` to field-level source checks. Status and impact remain separate:

- `status` describes the relationship to source: `matched`, `conflict`, `ambiguous`, `not_found`, etc.
- `severity` describes conclusion impact: `blocking`, `manual_review`, `advisory`, or `input_gap`.

Allowed combinations and conservative defaults when severity is absent:

- `matched`, `not_applicable` -> no severity and no finding;
- `conflict` -> `blocking` or `advisory`, default `blocking`;
- `ambiguous`, `not_found` -> `manual_review` or `advisory`, default `manual_review`;
- `source_unavailable`, `extraction_failed` -> `input_gap`, `manual_review`, or `advisory`, default `input_gap`.

Unknown severities and invalid status/severity combinations are contract errors; they are never silently coerced.

Source checks reuse the severity/disposition matrix above: blocking only permits `required`, advisory permits `suggested` or `internal_only`, and manual review/input gap permit `clarification` or `internal_only`. `matched` and `not_applicable` forbid a non-internal projection. Any invalid status/severity/disposition combination is a source contract error rather than a silently discarded message.

Deterministic source-layer aggregation uses the highest conclusion impact:

1. blocking conflict -> `不一致` -> overall floor `不通过`;
2. input gap -> `证据不足` -> overall floor `信息不足`;
3. manual review -> `需人工确认` -> overall floor `需人工确认`;
4. advisory-only source issues -> `基本一致，有建议补充` -> overall floor `通过`;
5. matched-only checks -> `一致` -> overall floor `通过`.

`_source_findings()` emits the field-level finding once with the declared severity. `_source_quality_findings()` does not add a duplicate aggregate ambiguity finding when field-level checks already cover the fields; aggregate source reminders are internal-only. Mixed cases follow the priority above. An advisory conflict remains visible and yields `基本一致，有建议补充`; it cannot be silently described as fully consistent.

## Rendering

`render_platform_return_opinion()` will:

1. Resolve each finding’s platform projection.
2. Exclude `internal_only`. For an approved result, exclude suggestions as well and render `无`.
3. Sort by `required`, then `clarification`, then `suggested`, preserving original order within a group.
4. Render continuous circled numbering.
5. Prefix each message with its user-facing label.
6. Append `以上【建议】项用于改善数据说明，不作为本轮审核通过的前置条件。` when at least one suggestion is present on a non-approved result.

Explicit `platform.message` is used verbatim after the label. Legacy blocking findings without the new object retain the existing location/evidence/judgment/suggestion composition for compatibility.

## Platform Artifact and Draft Payload

The evidence report retains every finding. `audit-result.platform.json` adds a distinct `platform_comment` projection containing only routed findings and the rendered opinion:

```json
{
  "platform_comment": {
    "valid": true,
    "validation_errors": [],
    "opinion": "无",
    "findings": []
  }
}
```

`_platform_result()` creates this projection. `_comment_payload_from_result_data()` reads `platform_comment.findings`, never the full internal `findings` list. For legacy platform-result artifacts without `platform_comment`, the CLI applies the same conservative routing defaults before producing a draft.

The complete submitter-facing comment JSON sent as the `json` argument of `app_review_save_comment_draft` is:

```json
{
  "conclusion": "rejected",
  "summary": "①【需修改】...",
  "findings": [
    {
      "id": "process.dataset_type.consistency",
      "severity": "blocking",
      "disposition": "required",
      "title": "【需修改】数据集类型",
      "description": "当前数据内容与所选类型不一致，请改为过程数据集后重新提交。",
      "evidence": "",
      "suggested_fix": "改为过程数据集后重新提交。",
      "related_field": "数据集类型",
      "tags": ["required"]
    }
  ],
  "auditor_notes": null
}
```

`summary` is exactly `platform_comment.opinion`, so the approved version-one text is what appears in the only communication channel. `findings` contains only the routed, submitter-facing finding projection and its safe message fields; it is not copied from the evidence report. `auditor_notes` is always `null` on this path. Internal `summary`, evidence-report notes, source limitations, contract errors, Agent status, and workflow/tool details never enter the submitter payload. Passing drafts use conclusion `approved`, summary `无`, empty findings, and null auditor notes. The API’s outer envelope remains `{"reviewId": ..., "json": <comment>}`.

Machine-testable invariants:

- approved conclusion: no `required` or `clarification`, platform return opinion is `无`, and suggestions remain internal;
- rejected conclusion: at least one `required` platform finding;
- manual-review/information-insufficient conclusion: at least one `clarification` platform finding unless the limitation is internal/system-only;
- any non-approved result without a submitter-actionable finding is `platform_comment.valid=false`.
- any unresolved semantic-context, validation, extraction, or workflow finding makes `platform_comment.valid=false`, regardless of other routed findings.

Semantic report generation still succeeds when the platform comment is invalid and records validation errors in the artifact. `save-result-draft` dry-run and execute both fail before creating a write client. Every unresolved internal semantic-context, validation, extraction, or workflow finding must first be resolved. Separately, a non-approved case that has no submitter-actionable finding becomes valid only after a legal clarification projection is added. Tests assert the entire exact `app_review_save_comment_draft` JSON payload contains no internal-only finding, internal summary, evidence-report note, tool limitation, or Agent/workflow status, and that its `summary` equals `platform_comment.opinion` byte for byte.

## Proportionality Policy

An advisory or clarification is promoted to the platform only when all are true:

1. The submitter can perform the requested action or provide the requested fact.
2. The action is supported by visible evidence and does not require inventing data absent from source material.
3. Expected quality gain is concrete and proportionate to the effort.
4. The request is not a duplicate aggregate of more specific findings.
5. The message identifies a field or record and gives a bounded action.

## Generator-Manufacturing Regression Expectation

The reviewed case should produce one required item and two non-blocking suggestions:

1. `【需修改】` Change `Unit process, single operation` to a boundary-compatible type or split the process.
2. `【建议】` Explain the basis for reference year 2014 when available.
3. `【建议】` Clarify or remove the indirect 2019 source.

The following remain internal and do not prevent approval after the dataset-type correction:

- steel-flow classification uncertainty without direct evidence of error;
- quantitative coverage/cut-off information unavailable from the source;
- broad DQR guidance;
- aggregate `source.check.ambiguous` reminders.

## Files and Responsibilities

- `skill/tiangong-lca-audit/references/output-contract.md`: normative routing, labels, proportionality, and version-one writing rules.
- `skill/tiangong-lca-audit/references/audit-policy.md`: distinguish unresolved material issues from non-conflicting advisory uncertainty.
- `skill/tiangong-lca-audit/references/input-contract.md`: source-check severity/platform field shape and validation boundary.
- `skill/tiangong-lca-audit/references/process-audit.md`: operational guidance for classifying source status separately from conclusion impact.
- `skill/tiangong-lca-audit/references/platform-operations.md`: preserve the invariant that passing cases have platform return opinion `无`; suggestions are only communicated when a case is already non-approved.
- `src/tiangong_audit/contracts/agent_review.py`: platform projection parsing and validation.
- `src/tiangong_audit/contracts/schemas/agent-findings.schema.json`: JSON contract for platform projection.
- `src/tiangong_audit/contracts/source.py`: optional source-check severity.
- `src/tiangong_audit/workflows/semantic_review.py`: carry platform projection and reconcile source severity.
- `src/tiangong_audit/report/markdown.py`: platform routing, labels, ordering, and suggestion footer.
- `src/tiangong_audit/cli.py`: build draft payloads exclusively from the routed platform-comment projection and block invalid drafts.
- `skill/tiangong-lca-audit/assets/audit-result-template.md`: document the user-facing output shape.
- `tests/`: contract, workflow, rendering, content, and regression coverage.

## Error Handling and Safety

- Invalid disposition values, source severities, and status/severity combinations fail their contracts.
- Non-internal platform projections without a message fail validation.
- Platform messages never authorize or perform a platform write.
- A non-pass result with no platform-actionable message produces a report artifact with `platform_comment.valid=false`; all draft/write paths are blocked.
- New code remains backward compatible with v1 case artifacts through conservative defaults; v2 artifacts intentionally require a v2-aware reader.

## Acceptance Criteria

1. Existing unannotated blocking findings remain visible in platform opinions.
2. Existing unannotated advisory and manual-review findings no longer enter automatically.
3. Explicit suggestions and clarification requests render with the correct labels on non-approved cases.
4. Suggestions are explicitly stated to be non-blocking and never appear on an approved pass flow.
5. Non-material source ambiguity can remain advisory without capping the conclusion; mixed source statuses follow the deterministic priority table.
6. Every finding origin has a safe projection default and verified blocking findings cannot be hidden; a blocking source conflict without `platform` is regression-tested as required.
7. `audit-result.platform.json` contains a valid routed platform-comment projection, and the exact draft payload excludes internal-only findings.
8. Invalid non-pass comments block dry-run and execute before creating a write client, including a case containing both one required finding and one unresolved internal extraction/workflow gap.
9. A deterministic advisory promoted through `platform_overrides` appears once in the evidence report and once in the platform opinion; unmatched, ambiguous, or duplicate overrides fail validation.
10. The generator regression yields exactly one required item and two suggestions at version-one density.
11. Skill check and the complete test suite pass.
