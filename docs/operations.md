# Operations guide

## Start locally

Follow the [README](../README.md) to install the locked dependencies and configure Azure OCR. Run:

```sh
uv run --locked python scripts/create_rental_hierarchy_sample.py --all-batches
uv run --locked python -m ocr_workspace
```

Open http://127.0.0.1:8700. Select a sample from `Scans/incomming_scan/` and upload it in the browser. Copying a file into the folder does not submit it. Processing uses Azure and may incur charges; sample generation does not.

The former Streamlit interfaces and demo launcher have been removed. There is no Microsoft sign-in flow in the current localhost synthetic workspace.

## Diagnose problems

| Symptom | Check |
| --- | --- |
| App does not start | Python version, locked dependencies and port 8700 availability |
| OCR worker reports missing credentials | `AZURE_DOC_INTEL_ENDPOINT` and `AZURE_DOC_INTEL_KEY` in `.env` |
| PDF is refused | Current synthetic manifest allowlist and 50 MB upload limit |
| Processing has no match | Identifier position within the crop and processing evidence |
| Order is incomplete | Flags, missing printed pages and conflicting extracted fields |
| Failed provider attempt | The provider client retries rate limits, server errors and network failures with bounded backoff. A page that still fails is saved as an error and flagged; submit the PDF again (or use `--retry-errors` in the CLI) to read only the failed pages |

## Recovery and retention

Stop the app before changing local state. Back up `demo_runtime/workspace.sqlite` and the complete `Scans/` directory together to preserve database references, original uploads, page reports and compiled files. Preserve any SQLite journal sidecars when present. No backup scheduler is included.

Startup applies migrations and recovers pending durable upload markers. Do not use `scripts/rebuild_scan_dataset.py` for ordinary recovery: it is a destructive reset tool that requires `--confirm-reset` and deletes scans, uploads, databases and workflow history. Sample regeneration preserves uploaded originals and workflow history.

OCR results are cached in the database by the SHA-256 of the header crop sent to the provider, so a re-synced, renamed or appended PDF does not pay again for pages already read. A page whose attempt failed is never cached and is read again the next time its PDF is submitted. The former workbook/index utilities and their pickle/JSON caches have been removed; a leftover `ocr_workspace/cache/` directory is unused and can be deleted.

## Validation

Run the checks in the README after changes. Automated tests use generated PDFs and mocked Azure responses. They do not establish live provider connectivity or production readiness. Review logs for paths, identifiers and credentials before sharing them.
