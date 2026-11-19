# Audit hardening

Last updated 2026-11-18.

## Scope and evidence

This audit covers this repository's current product: the localhost FastAPI workspace in `ocr_workspace/`, its ingestion CLI, the static client in `web/`, and CI. Issue numbers below are this repository's own issues.

The repository has independent history. The CI secret scan (Gitleaks 8.30.1) covers all fetched history on every push and pull request. Tracked paths contain no PDF, XLSX, XLS or `.env` files. This does not certify all text and media as free of private information or establish publication rights.

Verification on 2026-11-18, macOS, Python 3.12: 256 Python tests passed with 40 skips (PostgreSQL variants, which need `TEST_DATABASE_URL`); 30 frontend tests passed; Ruff's configured correctness rules passed. Cloud OCR is mocked in the test suite; the separate live validation is described below. The bounded-retry options were checked against the installed Azure SDK client without network access. Remote CI is authoritative for Linux/PostgreSQL and Windows and must be green before merging.

## What changed: order numbering

After the verification above, order numbering was replaced by the model below. This is the only place in the current guides that mentions earlier schemes.

- Rental orders (`RO-0000002`) and sales orders (`SO-0000001`) are the parent orders; their numbers come from one shared count. A rental order creates work orders (`W-0000001`). A sales order creates shipments (`Shipment 00001`). Work orders and shipments each have their own count. See [order numbering](demo-workflow.md#order-numbering).
- A page prints its order and its own document: RO + work order, or SO + shipment. Digits are kept as printed, including leading zeros.
- No longer recognised: `WO-`, `OD-`, `TK-`, `RA-`, customer-order numbers, a work order number without the `W-` prefix, and "Shipment No." meaning a sales order.
- Migration 7 drops the `shipment_number` column from orders; the shipment is now the order row's own number. `PARSER_VERSION` is 3, so cached results from earlier parsers are ignored.
- The `OCR_ALLOW_UNLABELED_FALLBACK` and `OCR_EXCLUDED_NUMBERS` settings and the `scripts/link_existing_rental_numbers.py` script no longer exist.
- The live Azure validation has not been repeated on this numbering.

## Issue status

| Issue | Status |
| --- | --- |
| #16 dependency lock and updates | Done. `uv.lock` locks Python resolution and CI installs with `--locked`; npm has its own lock. Dependabot covers uv, npm and Actions weekly, with minor/patch updates grouped. `.python-version` pins local runs to 3.12, matching CI. Dependabot security alerts are a repository setting and must be enabled by the owner. |
| #17 secret scanning | Done. Gitleaks scans full history in CI and runs as a pre-commit hook. `.env.example` documents variable names without credentials; `.env` stays ignored. The Key Vault integration and its URL were removed with the old sign-in flow. |
| #20 OCR golden corpus | Done. `tests/fixtures/ocr_golden.json` holds 39 text-only cases (identifier forms that must be read, retired prefixes that must not match, postal/year/customer-code noise, short fragments, overlong numbers) and gates every parser change in CI. Setting `OCR_CAPTURE_PATH` appends header text and its parsed result to a local file for review and promotion into the corpus; it is off by default. |
| #24 unversioned Excel pickle cache | Closed by removal. The workbook loader, the JSON scan index and both file caches were deleted; no pickle is read or written. The replacement OCR result cache stores a parser version with every entry. |
| #27 dead code and stale text | Done. Removed the unused workbook loader, scan index, filename utilities, their tests, four unreferenced sample scripts, the dead test stubs for Pillow and Azure, and the duplicate import fallbacks. Imports use `pymupdf` directly. The remaining `print()` calls are command-line output in `scripts/`. |
| #29 transient OCR failures dropping pages | Done. Every page attempt is committed before the provider call and ends as `success`, `no_match` or `error`; errored pages are flagged for review, never silently skipped. One provider client is reused per process with four bounded retries (exponential backoff, `Retry-After` honoured) and explicit connection/read timeouts. A page whose latest attempt errored is read again when its PDF is next submitted. |
| #30 OCR results re-billed on re-sync | Done. Results are cached by the SHA-256 of the exact header crop sent to Azure, so re-synced, renamed or appended PDFs do not pay again for pages already read. Cache hits are recorded as attempts with provider `ocr_result_cache`, which makes billable calls countable per run. Failed reads are never cached. `OCR_MAX_PAGES_PER_FILE` optionally stops a scan after a set number of billable pages. |

## Behavior notes

The parser reads four identifiers: rental order (`RO-…`), sales order (`SO-…`), work order (`W-…`) and shipment (`Shipment …`). A page belongs to its own document: its work order or its shipment. If only the order (RO or SO) is readable in the crop, the page is kept under that order and flagged (`work_order_not_read` or `shipment_not_read`); the order number never stands in for the work order or shipment. A page that mixes rental numbers (RO, W) with sales numbers (SO, Shipment) is rejected and flagged (`rental_and_sales_numbers_on_one_page`). There is no fallback for unlabeled numbers. `OCR_HEADER_NOISE` can remove form-specific header text before parsing. Review no-match pages rather than inferring an association from a postcode.

The result cache applies only to the built-in Azure provider. Bump `PARSER_VERSION` in `ocr_workspace/ocr.py` whenever identifier parsing changes so stored results from the older parser are ignored. `scripts/validate_ocr.py` always calls the provider, because its purpose is to validate live reads.

## Remaining priorities

- The intake worker is guarded by a single process lock. Atomic job claiming, worker leasing and duplicate-call protection across several processes are not implemented.
- The workspace is a localhost synthetic demonstration with no authentication; do not expose it on a network.
- Live Azure validation has not been repeated on the current numbering (RO/SO orders, `W-` work orders, shipments; parser version 3). The last recorded run, on 2026-11-16, was made on an older identifier scheme: 120 of 120 synthetic pages matched, after fixing a tracker-matching bug that run exposed. It does not validate the current numbering. See [validation results](ocr-validation-results.md) for scope and limits.
- Publication still requires rights/license review and a deliberate data/media review. Branch protection and repository access settings are the owner's to configure.

Dependabot's uv configuration follows the [official uv integration guide](https://docs.astral.sh/uv/guides/integration/dependabot/). CI checks do not deploy the app. Install local hooks with `uv run --locked pre-commit install`.
