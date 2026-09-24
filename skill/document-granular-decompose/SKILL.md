---
name: document-granular-decompose
description: Use when local PDF, Office, or image sources need high-fidelity extraction, page-level evidence for review, optional image descriptions, or resumable long-document parsing through TianGong AI Unstructure.
---

# Document Granular Decompose

## Execution

1. Read [environment setup](references/env.md) and export existing service credentials. The Python entry point runs standalone using the standard library on POSIX (file locking uses `fcntl`).
2. Read the [request and response contract](references/request-response.md) for supported inputs, modes, schema validation, outputs, and recovery. Default to high-fidelity advanced parsing; add image enrichment when the evidence requires independent image descriptions. Use synchronous parsing for small sources and asynchronous tasks for long documents or image enrichment.
3. Run `scripts/mineru_fulltext_extract.py` from this Skill directory. For audit evidence, save a bundle:

   ```bash
   python3 scripts/mineru_fulltext_extract.py \
     --file /absolute/path/to/document.pdf \
     --output-dir /absolute/path/to/case/parser-output
   ```

   For long sources, add `--async`. For image enrichment, select a mode using the contract. Before each new submission the client checks the target deployment's live schema.
4. If waiting stops, follow the contract's recovery procedure and keep the task record. Do not upload again when submission or completion is uncertain.
5. Read the page/block-labelled `extracted.md` alongside `result.json` and the original source. Verify relevant tables, units, and image-derived claims. For audit attachment, follow the audit Skill's input contract to import the bundle. For plain-text consumers, use the compatibility output described in the API contract.

## Resources

- [Request and response contract](references/request-response.md): authoritative API/CLI details, formats, evidence semantics, and recovery.
- [Environment setup](references/env.md): configuration and credential loading.
- [Environment example](assets/config.example.env): configuration names.
- [Extraction entry point](scripts/mineru_fulltext_extract.py): standalone Python client.
- [HTTP and schema support](scripts/mineru_client.py), [task persistence](scripts/mineru_jobs.py), and [result rendering](scripts/mineru_results.py): keep these standard-library modules beside the entry point when distributing the Skill.
