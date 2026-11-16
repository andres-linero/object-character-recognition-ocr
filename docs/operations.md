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
| Failed provider attempt | Inspect the saved failure; failed attempts are not silently retried |

## Recovery and retention

Stop the app before changing local state. Back up `demo_runtime/workspace.sqlite` and the complete `Scans/` directory together to preserve database references, original uploads, page reports and compiled files. Preserve any SQLite journal sidecars when present. No backup scheduler is included.

Startup applies migrations and recovers pending durable upload markers. Do not use `scripts/rebuild_scan_dataset.py` for ordinary recovery: it is a destructive reset tool that requires `--confirm-reset` and deletes scans, uploads, databases and workflow history. Sample regeneration preserves uploaded originals and workflow history.

Older workbook/index utilities may retain file-backed caches. These are separate from the current app; do not open untrusted pickle files or erase old state without checking its purpose.

## Validation

Run the checks in the README after changes. Automated tests use generated PDFs and mocked Azure responses. They do not establish live provider connectivity or production readiness. Review logs for paths, identifiers and credentials before sharing them.
