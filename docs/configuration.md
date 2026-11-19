# Configuration and data

Run from the repository root. Copy `.env.example` to `.env` if no local file exists and supply your Azure resources. Preserve existing credentials; never commit `.env`.

## Current web app

| Setting | Purpose |
| --- | --- |
| `AZURE_DOC_INTEL_ENDPOINT` | Azure Document Intelligence endpoint, required for OCR |
| `AZURE_DOC_INTEL_KEY` | Azure Document Intelligence key, required for OCR |
| `OCR_HEADER_NOISE` | Optional form-specific text exclusions, separated by `|` |
| `OCR_EXCLUDED_NUMBERS` | Optional comma-separated numeric exclusions |
| `OCR_ALLOW_UNLABELED_FALLBACK` | Legacy ambiguous-number fallback; off by default |
| `OCR_MAX_PAGES_PER_FILE` | Optional cost guard: stop a scan after this many billable OCR pages; `0` or unset means no limit |
| `OCR_CAPTURE_PATH` | Optional, development only: local JSONL file that receives OCR header text and its parsed result for promotion into the golden corpus. Leave unset in normal use |

The intake worker reads the two Azure credentials from `.env`, falling back to environment values. The app uses `demo_runtime/workspace.sqlite` and managed PDFs in `Scans/`. It serves the browser UI on http://127.0.0.1:8700.

Streamlit, Microsoft Entra sign-in and Key Vault configuration belonged to the removed interfaces. Their environment variables are no longer required by the current app. The local `.env` is not automatically rewritten.

## Separate tools

| Setting | Purpose |
| --- | --- |
| `DATABASE_URL` | Relational store used by ingestion CLI tools |
| `POSTGRES_PASSWORD` | Password required by the optional Compose PostgreSQL service |

Workbook imports and older demo preparation are separate from browser uploads. The current tracker derives orders from uploaded documents. See [the data-pipeline guide](data-pipeline.md) for CLI ingestion.

## Local files

| Location | Contents |
| --- | --- |
| `Scans/incomming_scan/` | Selectable samples and submitted uploads |
| `Scans/processed/` | Preserved original PDFs |
| `Scans/flag_order/` | Scans and reports needing attention |
| `Scans/output/` | Compiled PDFs |
| `Scans/manifest.json` | Synthetic sample allowlist and expected cases |
| `demo_runtime/workspace.sqlite` | Orders, pages, attempts, cached OCR results, approvals and download receipts |
| `demo_runtime/read-scan` | Compiled local extraction helper |

Generated data and runtime files are excluded from Git. Back up the database and its referenced files together. See [operations](operations.md) for recovery guidance.
