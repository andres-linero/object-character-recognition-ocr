# Database and ETL guide

## What is implemented

The project now has a SQLAlchemy data layer for PostgreSQL and SQLite, an initial versioned schema, Excel/CSV ETL, synthetic-manifest registration, SQL reconciliation queries, page-level OCR attempts/retries, and a separate synthetic preview. The original signed-in dashboard can read SQL orders when `DATABASE_URL` is configured. Its scan/download/review workflow still uses the legacy file-backed index; migrating that UI completely remains a separate step.

Excel is retained as an import/export boundary. Database tables hold normalized orders, customers, document/page records, expected or OCR-derived associations, source rows, validation failures, and processing history. PDF bytes stay in managed files; the database stores paths and SHA-256 checksums.

## Local synthetic preview

```sh
python3 -m venv .venv
. .venv/bin/activate
python3 -m pip install -r requirements.txt -r requirements-data.txt
# Generate only if demo_data does not already exist:
python3 scripts/create_demo_data.py --count 100 --seed 42 --output demo_data
python3 scripts/prepare_demo.py
sh scripts/run_demo.sh
```

Open http://127.0.0.1:8502. Preparation imports `demo_data` and the two additional generated batches if present. The existing local dataset yields 120 orders and 1,050 pages. A clean clone with only the default generator output yields 100 orders and 930 pages. No generated dataset or database is committed.

`run_demo.sh` uses the repository virtual environment, then the existing parent environment if available, then `python3`. Set `OCR_PYTHON` to an explicit interpreter if needed. This avoids relying on a shell command named `python`.

The preview does not load `.env`, connect to Azure, or change the live app's authentication. It reads an isolated database in `demo_runtime/`, refuses sources/documents marked non-synthetic, and restricts PDF downloads to the generated dataset directories. `DEMO_DATABASE_PATH` optionally chooses a different local demo database. The preview is intended for localhost; it has no production authentication.

Manifest-derived associations appear as **Manifest_Pages**, while verified provider associations appear as **OCR_Verified_Pages**. The manifest is test ground truth, not a substitute for OCR. Generated sample sizes are not accuracy or throughput measurements.

## PostgreSQL setup

Requires Docker with Compose, or an existing PostgreSQL instance. Docker/PostgreSQL are not prerequisites for the SQLite preview.

1. Copy `.env.example` to `.env` if no local file exists. Preserve existing credentials.
2. Set a local `POSTGRES_PASSWORD` and start `docker compose up -d postgres`.
3. Set `DATABASE_URL=postgresql+psycopg://ocr:YOUR_URL_ENCODED_PASSWORD@127.0.0.1:5432/ocr` locally. URL-encode reserved password characters. Never commit this value.
4. Run the ingestion command:

```sh
python3 scripts/ingest_data.py --tracker demo_data/orders.xlsx --source-system demo --manifest demo_data/manifest.json
```

The CLI loads the local `.env`, applies migration version 1, stages tracker rows, normalizes and loads orders/customers, then registers synthetic expected page associations. For real documents, omit `--manifest` and use `--pdf /path/to/ticket.pdf` to register the document and pages.

The database role must be allowed to create the `staging`, `core`, and `ops` schemas for initial migration. No database is silently substituted if PostgreSQL connection/setup fails.

## Schemas and constraints

| Schema | Tables |
| --- | --- |
| `staging` | `source_files`, `tracker_rows`, `rejected_rows` |
| `core` | `customers`, `orders`, `documents`, `document_pages`, `order_document_pages` |
| `ops` | `schema_versions`, `ingestion_runs`, `ocr_attempts`, `review_events` |

SQLite maps these logical schemas into one local namespace, while retaining the same table/constraint model. Primary and foreign keys enforce relationships. Uniqueness covers source checksums, source-system/order numbers, source-system/shipment numbers, document checksums, document/page pairs, and association methods. Check constraints restrict statuses and require positive page numbers/counts. SQLite foreign keys are enabled explicitly.

`ADK_Agentic/storage.py` is the canonical initial migration model. `database/001_initial.sql` is a generated PostgreSQL DDL reference; regenerate it with `python3 scripts/export_schema.py`. The application records schema version 1 once. Future changes require a new explicit migration; changing the model alone does not upgrade an existing database.

## ETL behavior

Extraction retains file checksum/name, worksheet, row number, run ID, and original string-rendered values. Normalization preserves IDs as text, handles trailing numeric `.0`, trims strings, normalizes supported statuses, parses dates, and validates required customer/identifier values and positive expected page counts.

`Customer_ID` is used as the source customer identity when supplied. Legacy trackers fall back to a normalized-name hash. That fallback can merge same-named customers; production source contracts should supply stable IDs. Business keys are scoped by `--source-system`; use the same value for tracker ingestion and OCR processing.

Valid rows are upserted with conflict handling. Invalid or conflicting rows are quarantined with their source locations and reasons, and the run is marked partial. This is a deliberate partial-load policy, not all-or-nothing validation. An unexpected file/database failure rolls the business/staging transaction back and records a failed run separately.

Repeat imports append raw/run history but do not duplicate business orders, customers, pages, or associations. Imports update existing orders; absent source rows do not delete orders. Source history and current state must be interpreted separately.

## Live Azure processing

For the existing Azure wrapper, configure these values in local `.env`:

```dotenv
AZURE_DOC_INTEL_ENDPOINT=
AZURE_DOC_INTEL_KEY=
DATABASE_URL=
```

The Azure portal's Document Intelligence resource provides the endpoint/key under **Keys and Endpoint**. An OpenAI API key is not used by this integration.

After tracker import and PDF registration, invoke processing explicitly:

```sh
python3 scripts/process_documents.py --limit 10 --source-system tracker
python3 scripts/process_documents.py --limit 10 --source-system tracker --retry-errors
```

These commands call Azure and can incur charges. They are never invoked by the synthetic preview. Pages are cropped to the top-right half of the top quarter at 200 dpi. A geometric crop does not guarantee absence of private information; inspect layouts before using real files.

Each attempt records provider, timestamps, status, extracted identifier, and a safe error category. Raw OCR text is not stored. Successful processing is linked to a uniquely matching order. Errors remain available for explicit retry, and successful pages are skipped. No-match and interrupted/running attempts require manual investigation; they are not automatically retried by this initial CLI. Changed documents fail checksum verification and must be re-registered.

The existing live dashboard also requires Microsoft Entra tenant/client/client-secret/redirect configuration as documented in `.env.example`. No credentials are needed for the separate synthetic preview.

## Verification and limits

Tests exercise idempotency, row quarantine, relational constraints, transaction rollback, manifest provenance, OCR error/retry behavior with a mocked provider, preview filtering, synthetic-only restrictions, and the live sign-in gate. PostgreSQL tests run when `TEST_DATABASE_URL` points to a disposable test database; those tests clear the project tables. Never point it at application data.

GitHub Actions provisions a disposable PostgreSQL 17 service and runs the same integration tests. Local checks use SQLite because the development host has no PostgreSQL/Docker installation. A successful SQLite run or compiled PostgreSQL DDL alone does not establish PostgreSQL integration success. Live Azure and Microsoft sign-in still need checks with the owner's resources.

The initial migration is not a general-purpose migration framework. The legacy dashboard is not fully migrated away from JSON/pickle. A worker queue, distributed processing, production role management, backup scheduling, and retention automation are not implemented by this change.

## Reference documentation

- [SQLAlchemy engine configuration](https://docs.sqlalchemy.org/en/20/core/engines.html)
- [SQLAlchemy transactions](https://docs.sqlalchemy.org/en/20/core/connections.html)
- [Azure Document Intelligence SDK quickstart](https://learn.microsoft.com/en-us/azure/ai-services/document-intelligence/quickstarts/get-started-sdks-rest-api?view=doc-intel-4.0.0)
