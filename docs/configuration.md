# Configuration and data

Run commands from the repository root. Copy `.env.example` to `.env` and supply your own resources. Never place real secrets in a Google Doc, issue, recording, or commit.

## Environment variables

| Variable | Purpose | Requirement/default |
| --- | --- | --- |
| `AZURE_TENANT_ID` | Microsoft Entra tenant | Required for sign-in |
| `AZURE_CLIENT_ID` | Entra confidential application client | Required for sign-in |
| `AZURE_CLIENT_SECRET` | Entra client secret | Required for sign-in |
| `AZURE_REDIRECT_URI` | Registered web callback | `http://localhost:8501` |
| `AZURE_DOC_INTEL_ENDPOINT` | Document Intelligence resource endpoint | Required when OCR runs |
| `AZURE_DOC_INTEL_KEY` | Document Intelligence resource key | Required when OCR runs |
| `EXCEL_PATH` | Workbook path | Sample: `examples/orders.xlsx`; relative paths depend on launch directory |
| `SCAN_PDF_PATH` | Incoming scan directory | Repository `Scans/incoming_scans/`; immediate lowercase `*.pdf` files only |
| `USE_AZURE_KEYVAULT` | Enable Key Vault loading | Off; accepts `1`, `true`, `yes`, `on` |
| `AZURE_KEY_VAULT_URL` | Your Key Vault URL | Required when Key Vault is enabled |
| `OCR_HEADER_NOISE` | Exact text fragments removed before matching | Optional, separated by `|` |
| `OCR_EXCLUDED_NUMBERS` | Numeric fallback candidates to ignore | Optional, comma-separated |

Key Vault loads OCR endpoint/key and Entra client ID/secret/tenant from the hyphenated secret names declared in `config.py`. Successful values override local environment values. Individual missing secrets are skipped; other failures fall back to environment configuration. The redirect URI and workbook/scan paths are not loaded from Key Vault.

## Workbook contract

All non-empty worksheets are combined; `Source_Sheet` records the original worksheet name. The loader is permissive and does not enforce a formal schema.

| Column | Meaning |
| --- | --- |
| `Order_ID` | Work-order identifier, for example `W-100001` |
| `SO` | Shipment/sales-order identifier, for example `3501` |
| `Customer_name` | Customer display name; `Customer` is accepted as an alias |
| `Ship_to` | Destination display value; use the underscore spelling |
| `Status` | Workbook workflow state; views interpret completion values |
| `Deadline` | Optional deadline display/filter input |
| `Deadline Status` | Optional deadline state; `Deadline status` is an alias |
| `Requested by` | Optional assignment/display value |

Keep identifiers as text when possible. `Order_ID` and `SO` are trimmed and trailing `.0` artifacts removed. Some lookups remove leading zeroes or the `W-` prefix; this is heuristic matching, not a universal ID contract. Missing columns can produce blank or reduced views instead of a schema error.

## Local files

| Location | Contents | Lifecycle |
| --- | --- | --- |
| `Scans/incoming_scans/` | Source ticket PDFs | Operator managed |
| `ADK_Agentic/cache/excel_cache.pkl` | Workbook data/signature | Rebuilt as needed; trusted pickle only |
| `ADK_Agentic/cache/scan_index.json` | OCR associations/signatures | Retained across runs |
| `ADK_Agentic/cache/downloads*.json` | Download flags | Local workflow state |
| `ADK_Agentic/cache/scan_review_status.json` | Review flags | Local workflow state |
| `ADK_Agentic/upload_ready/` | Extracted order PDFs and previews | Retained; no automatic age cleanup |
| `ADK_Agentic/output/` | Final PDFs from downstream/manual workflow | Files older than seven days removed after authenticated execution |

Generated files and workbooks are excluded from Git. Backups, retention, and deletion must account for copies, previews, and index entries as well as original scans.
