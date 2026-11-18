# Architecture

The current product is a localhost document and order workspace. A static HTML/CSS/JavaScript client in `web/` is served by FastAPI on port 8700. The former Streamlit interfaces and their sign-in/configuration code have been removed.

## Components

| Location | Responsibility |
| --- | --- |
| `web/` | Uploads, order tracker, processing activity, flags, previews and downloads |
| `ocr_workspace/web_api.py` | HTTP API, static client, upload queue and worker lifecycle |
| `ocr_workspace/intake_watcher.py` | Upload processing, worker locking, progress and compiled PDFs |
| `ocr_workspace/ocr.py` | Azure identifier extraction and parsing |
| `ocr_workspace/document_data.py` | Local page fields and rental-order context |
| `ocr_workspace/processing.py` | Document registration and persisted page OCR attempts |
| `ocr_workspace/page_review.py` | Field comparison and manual assignment rules |
| `ocr_workspace/ticket_names.py` | Download filename generation |
| `ocr_workspace/storage.py` | SQL schema and startup migrations |
| `ocr_workspace/etl.py` | SQL upserts and separate tracker-import utilities |
| `scripts/` | Startup, sample generation, maintenance and validation |

`ocr_workspace` is the application package. The former workbook loader, JSON scan index and their file caches have been removed; every module in the package serves the current web app or its ingestion CLI.

## Processing and persistence

Uploads create durable queue markers and preserve originals. Local extraction reads customer, address and printed-page details; Azure reads the identifier crop. The worker groups pages under orders, records attempts and checks completeness. Manual approvals preserve review decisions separately from source OCR. Complete orders can be compiled and downloaded with versioned receipts.

The local database is `demo_runtime/workspace.sqlite`. PDFs and reports remain under `Scans/`; database rows reference their paths and checksums. Startup migrations preserve existing workflow history. PostgreSQL references are in `database/` and support the separate ingestion tooling.

## Boundaries

The current application accepts allowlisted synthetic PDFs and binds to localhost. It has no production sign-in. Raster extraction requires macOS Vision and Swift tools. Azure calls occur during processing and may incur charges. A process lock coordinates the local intake worker; distributed worker coordination is outside this scope.

See [the product guide](product-ui.md), [operations](operations.md), [configuration](configuration.md) and [data pipeline](data-pipeline.md). Earlier decisions in `docs/decisions/` describe historical proposals and evidence.
