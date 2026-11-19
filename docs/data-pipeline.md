# Database and ETL guide

## What is implemented

The project has a SQLAlchemy data layer for PostgreSQL and SQLite, versioned migrations, Excel/CSV ETL, synthetic-manifest registration, reconciliation queries, and page-level OCR attempts/retries. The current web app is document-driven and uses SQLite; workbook imports are separate CLI tools.

Excel is retained as an import/export boundary. Database tables hold normalized orders, customers, document/page records, expected or OCR-derived associations, source rows, validation failures, and processing history. PDF bytes stay in managed files; the database stores paths and SHA-256 checksums.

## Local workspace

Follow the [README](../README.md) to prepare the workspace, generate current PDF samples, and run `uv run --locked python -m ocr_workspace`. Open http://127.0.0.1:8700. Uploading a PDF creates order rows through OCR; generating samples does not preload them.

The former Streamlit preview and `run_demo.sh` launcher have been removed. `prepare_demo.py` remains a CLI fixture utility for older generated datasets, separate from the current workspace startup.

Manifest-derived associations are test expectations, not verified provider readings. Generated sample sizes are not accuracy or throughput measurements.

## PostgreSQL setup

Requires Docker with Compose, or an existing PostgreSQL instance. Docker/PostgreSQL are not prerequisites for the SQLite workspace.

1. Copy `.env.example` to `.env` if no local file exists. Preserve existing credentials.
2. Set a local `POSTGRES_PASSWORD` and start `docker compose up -d postgres`.
3. Set `DATABASE_URL=postgresql+psycopg://ocr:YOUR_URL_ENCODED_PASSWORD@127.0.0.1:5432/ocr` locally. URL-encode reserved password characters. Never commit this value.
4. Run the ingestion command:

```sh
python3 scripts/ingest_data.py --tracker demo_data/orders.xlsx --source-system demo --manifest demo_data/manifest.json
```

The CLI loads the local `.env`, applies pending schema migrations, stages tracker rows, normalizes and loads orders/customers, then registers synthetic expected page associations. For real documents, omit `--manifest` and use `--pdf /path/to/ticket.pdf` to register the document and pages.

The database role must be allowed to create the `staging`, `core`, and `ops` schemas for initial migration. No database is silently substituted if PostgreSQL connection/setup fails.

## Schemas and constraints

| Schema | Tables |
| --- | --- |
| `staging` | `source_files`, `tracker_rows`, `rejected_rows` |
| `core` | `customers`, `orders`, `rental_orders`, `rental_order_tickets`, `rental_order_pages`, `documents`, `document_pages`, `order_document_pages` |
| `ops` | `schema_versions`, `ingestion_runs`, `ocr_attempts`, `review_events`, `manual_page_approvals`, `page_extractions`, `ticket_downloads`, `ocr_result_cache` |

How the order numbering maps onto these tables (see [order numbering](demo-workflow.md#order-numbering)):

| Table | Holds |
| --- | --- |
| `core.orders` | One row per work order or shipment. `order_number` is `W-0000001` or `Shipment 00001`; `order_type` is `RENTAL` or `SALE`. |
| `core.rental_orders` | One row per parent order, rental **and** sales. `rental_number` is `RO-0000002` or `SO-0000001`. Despite its name, this table holds sales orders too. |
| `core.rental_order_tickets` | Links each work order or shipment to its one parent order (`rental_id`). |
| `core.rental_order_pages` | Each scanned page on which a parent order was identified, with its locally extracted fields. This keeps a page under its RO or SO even when its work order or shipment was not read. |

SQLite maps these logical schemas into one local namespace, while retaining the same table/constraint model. Primary and foreign keys enforce relationships. Uniqueness covers source checksums, source-system/order numbers, document checksums, document/page pairs, and association methods. Check constraints restrict statuses and require positive page numbers/counts. SQLite foreign keys are enabled explicitly.

`ocr_workspace/storage.py` defines the schema and versioned startup migrations. Migration 2 adds manual page approvals; migration 3 adds the parent-order tables (`rental_orders`, `rental_order_tickets`, `rental_order_pages`). Migration 4 retains local extraction for every page independently of its match status. Migration 5 adds version-specific download receipts. Migration 6 adds the OCR result cache. Migration 7 leaves one number per `orders` row by dropping the `shipment_number` column (`database/007_single_order_number.sql`). Schema versions run from 1 to 7. Existing pages, attempts and approvals survive upgrades. The numbered SQL files in `database/` describe the PostgreSQL changes. Run `python3 scripts/export_schema.py` to export a current schema snapshot to `database/current_schema.sql`; it does not rewrite historical migrations.

## ETL behavior

Extraction retains file checksum/name, worksheet, row number, run ID, and original string-rendered values. Normalization preserves IDs as text, handles trailing numeric `.0`, trims strings, normalizes supported statuses, parses dates, and validates required customer/identifier values and positive expected page counts.

A tracker row is one work order or one shipment. Two columns identify it:

| Column | Rental row | Sales row |
| --- | --- | --- |
| `Order` | `RO-0000002` | `SO-0000001` |
| `Work order` | `W-0000001` | `Shipment 00001` |

`Work order` must hold exactly one work order or shipment; it sets the order type to `RENTAL` or `SALE`. `Order` must hold the matching parent: an `RO-…` for a work order, an `SO-…` for a shipment. Rows that break these rules are quarantined, as is a second row for the same work order or shipment in one tracker. The optional `Address` column is stored on the parent order.

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

Each attempt records provider, timestamps, status, extracted identifier, and a safe error category. Raw OCR text is not stored. Successful processing is linked to a uniquely matching order. Errors remain available for explicit retry, and successful pages are skipped.

Provider results are cached in `ops.ocr_result_cache` by the SHA-256 of the exact header crop sent to Azure, together with the parser version that read them. An identical crop in a re-synced, renamed or appended PDF reuses the stored identifiers and its attempt is recorded with provider `ocr_result_cache`, so billable calls and cache hits can be counted per run from `ops.ocr_attempts`. Failed reads are never cached. Bump `PARSER_VERSION` in `ocr_workspace/ocr.py` whenever identifier parsing changes; older entries are then ignored.

No-match and interrupted/running attempts require manual investigation; they are not automatically retried by the CLI. Changed documents fail checksum verification and must be re-registered.

## Verification and limits

Tests exercise idempotency, row quarantine, relational constraints, transaction rollback, manifest provenance, OCR error/retry and result-cache behavior with a mocked provider, and synthetic-only restrictions. PostgreSQL tests run when `TEST_DATABASE_URL` points to a disposable test database; those tests clear the project tables. Never point it at application data.

GitHub Actions provisions a disposable PostgreSQL 17 service and runs the same integration tests. Local checks use SQLite because the development host has no PostgreSQL/Docker installation. A successful SQLite run or compiled PostgreSQL DDL alone does not establish PostgreSQL integration success. Live Azure reads still need checks with the owner's resources.

The initial migration is not a general-purpose migration framework. The former JSON/pickle file caches have been removed. A worker queue, distributed processing, production role management, backup scheduling, and retention automation are not implemented by this change.

## Reference documentation

- [SQLAlchemy engine configuration](https://docs.sqlalchemy.org/en/20/core/engines.html)
- [SQLAlchemy transactions](https://docs.sqlalchemy.org/en/20/core/connections.html)
- [Azure Document Intelligence SDK quickstart](https://learn.microsoft.com/en-us/azure/ai-services/document-intelligence/quickstarts/get-started-sdks-rest-api?view=doc-intel-4.0.0)

## Verify the two new batches through Azure

The dedicated validator stages copies of the two generated 60-page batches under `demo_batches/ocr_validation/incoming_scans/`, combines their tracker rows, and uses an isolated SQLite database. The original PDF packets and the full-demo database are preserved. It does not require a PostgreSQL server. The batches come from `scripts/create_demo_data.py`; generate them first, because `demo_batches/` is not kept in Git.

```sh
python3 scripts/validate_ocr.py --prepare-only
python3 scripts/validate_ocr.py --limit 1
# After the smoke test passes, process the remaining pages:
python3 scripts/validate_ocr.py --limit 120
```

Configure the Azure endpoint/key in local `.env`. The first provider result must match its expected order number before additional pages are submitted. Existing completed attempts are reused; `--retry-errors` explicitly retries failed attempts. Access failures or three consecutive provider errors stop the run. Requests are sequential and separated by a pause; the SDK handles provider polling/retries. Azure usage charges may apply.

The validator compares every returned identifier against page-specific manifest ground truth, including a wrong identifier that happens to match a different valid order. JSON and CSV reports record passed, mismatch, error, and pending counts, plus expected/actual identifiers. Credentials, endpoints, and raw OCR text are excluded. Reports remain local in `demo_runtime/ocr_validation_report.json` and `.csv`.

Inspect a run through the local JSON/CSV report or the isolated `demo_runtime/ocr_validation.sqlite` database; the validator always calls the provider and bypasses the result cache. The validation database contains 20 distinct tickets and 120 pages and is separate from the browser workspace at http://127.0.0.1:8700. The latest recorded run is in [validation results](ocr-validation-results.md); it was made on an older numbering and has not been repeated on the current one.
