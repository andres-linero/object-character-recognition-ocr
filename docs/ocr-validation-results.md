# Live Azure OCR validation: two synthetic batches

Date: 2026-11-06

## Result

**120/120 pages matched their expected shipment identifiers.** There were zero mismatches, zero provider errors, and zero pending pages. Each of the two staged batches contains 10 tickets and 60 pages.

| Batch | Tickets | Pages checked | Exact matches | Mismatches | Errors |
| --- | --- | --- | --- | --- | --- |
| Batch 02 | 10 | 60 | 60 | 0 | 0 |
| Batch 03 | 10 | 60 | 60 | 0 | 0 |
| Total | 20 | 120 | 120 | 0 | 0 |

## Method

The validator staged copies of the two generated batch PDFs and combined their trackers in an isolated SQL database. A one-page live smoke test passed first, followed by the remaining 119 pages. Azure Document Intelligence `prebuilt-read` processed a rendered top-right header crop from each page. The existing extraction parser returned the shipment identifier; the validator compared it with that page's expected identifier and matched it to the imported order.

The page set includes equipment delivery, demo terms, and acknowledgement papers, each with white/yellow copies. All documents, contacts, locations, and identifiers are fictional. Originals were preserved. No office production data was used.

## Evidence and reproduction

- Runner: [scripts/validate_ocr.py](../scripts/validate_ocr.py)
- Procedure: [database and ETL guide](data-pipeline.md#verify-the-two-new-batches-through-azure)
- Local report: `demo_runtime/ocr_validation_report.json` and `.csv` (excluded from Git)
- Local database: `demo_runtime/ocr_validation.sqlite` (excluded from Git)
- Viewer: http://127.0.0.1:8502, dataset **Azure OCR validation — new batches**

The database contains 120 completed provider attempts and 120 verified page/order associations, kept separately from 120 manifest expectations. The viewer and report counts agree. The regression suite passed locally with 39 tests; six PostgreSQL cases run separately in CI.

## Scope and limits

This demonstrates a working Azure credential/resource configuration, crop, extraction parser, tracker ETL, and page/order reconciliation for these fixtures. It is not a general production OCR accuracy claim: the dataset consists of 20 generated packets using three clean form layouts with duplicate copies. Full-page business-field extraction, signatures, diverse real scans, and Microsoft sign-in were not tested by this validation.

A defensible project description is: “Validated an Azure OCR and SQL reconciliation pipeline on 120 synthetic pages across 20 ticket packets, comparing extracted shipment IDs with page-level ground truth.”
