# Flow Metadata Enrichment Design

## Goal

Prevent process exchanges from being reported as missing flow type or classification when the metadata exists in the referenced Tiangong flow dataset.

## Confirmed Root Cause

Process exchanges carry a flow UUID and version but usually do not embed the full `flowDataSet`. The intake workflow normalizes the process immediately, so type and classification become empty. The normalizer also omits the real `common:classification/common:class` path. The rule engine then treats every empty value as submitter-owned missing data.

## Design

1. Add read-only flow lookup to `DatasetAPI`.
2. Before process normalization, deduplicate exchange flow references, fetch each related flow, attach its payload to an enriched copy, and persist raw/enriched/evidence snapshots separately.
3. Normalize a controlled `flow_metadata_status`: `resolved`, `not_fetched`, `not_found`, `fetch_failed`, or `parse_failed`.
4. Parse both prefixed and unprefixed ILCD classification keys.
5. Emit a blocking metadata finding only for a resolved flow whose metadata is genuinely empty. Unresolved lookup states become internal `input_gap` findings that instruct the audit workflow to retry or inspect evidence; they do not blame the submitter.
6. Extend Agent findings with exact `precheck_resolutions` entries. A valid `refuted` resolution must match exactly one deterministic finding by `rule_id + location`, include a reason and evidence references, remove that finding from the active conclusion, and remain visible in the Agent-review audit summary.

## Safety and Compatibility

- The platform dataset remains read-only.
- `dataset.raw.json` is never mutated; normalization uses `dataset.enriched.json`.
- Projected inputs and legacy normalized fixtures default to `resolved`, preserving genuine missing-metadata checks.
- Lookup failures are recorded per flow and do not abort the rest of intake.
- Existing Agent findings v1/v2 remain readable because new resolution data is optional.

## Acceptance Criteria

1. Real `common:classification/common:class` values normalize correctly.
2. Repeated flow references are fetched once.
3. A raw process containing only flow references is enriched before precheck.
4. Fetch failures never create submitter-facing blocking metadata findings.
5. A resolved flow genuinely missing metadata still creates a blocking finding.
6. An exact, evidence-backed precheck refutation removes one deterministic finding; invalid or ambiguous targets fail validation.
7. Repository checks, full tests, and passing/failing metadata regression samples pass.
