# Live Azure OCR validation: two synthetic batches

Date: 2026-11-16 (report written 2026-11-17 01:50 UTC). Replaces the first run of 2026-11-06, which gave the same totals on the earlier parser.

> This run used the current code: the typed identifier parser, the reused provider client with bounded retries, and migration 6. The result cache was bypassed, so all 120 pages were live provider calls. The two batches were regenerated with `scripts/create_demo_data.py` (seeds 2 and 3, ticket indexes 101–120, six pages each); they are equivalent fixtures, not the files from the first run.

## Result

**120/120 pages matched their expected shipment identifiers.** There were zero mismatches, zero provider errors, and zero pending pages. Each of the two staged batches contains 10 tickets and 60 pages.

| Batch | Tickets | Pages checked | Exact matches | Mismatches | Errors |
| --- | --- | --- | --- | --- | --- |
| Batch 02 | 10 | 60 | 60 | 0 | 0 |
| Batch 03 | 10 | 60 | 60 | 0 | 0 |
| Total | 20 | 120 | 120 | 0 | 0 |

## Method

The validator staged copies of the two generated batch PDFs and combined their trackers in an isolated SQL database. A one-page live smoke test passed first, followed by the remaining 119 pages. Azure Document Intelligence `prebuilt-read` processed a rendered top-right header crop from each page. The extraction parser returned the page's identifiers; the validator compared the shipment with that page's expected identifier and matched it to the imported order.

The first attempt of this rerun failed its smoke test: the provider read the header correctly, but the header also prints a rental agreement number, the parser now reports that as the primary identifier, and tracker-driven matching did not fall back to the shipment. That matching bug was fixed in `ocr_workspace/processing.py` with a regression test, the validation database was reset, and the full run was repeated from page one.

The page set includes equipment delivery, demo terms, and acknowledgement papers, each with white/yellow copies. All documents, contacts, locations, and identifiers are fictional. Originals were preserved. No office production data was used.

## Evidence and reproduction

- Runner: [scripts/validate_ocr.py](../scripts/validate_ocr.py)
- Procedure: [database and ETL guide](data-pipeline.md#verify-the-two-new-batches-through-azure)
- Local report: `demo_runtime/ocr_validation_report.json` and `.csv` (excluded from Git)
- Local database: `demo_runtime/ocr_validation.sqlite` (excluded from Git)

The database contains 120 successful provider attempts and 120 verified page/order associations, kept separately from 120 manifest expectations, and the report counts agree. Inspect a run through the local JSON/CSV report. For the current test suite, see [project reference](project-reference.md#validation).

## Scope and limits

This demonstrates a working Azure credential/resource configuration, crop, extraction parser, tracker ETL, and page/order reconciliation for these fixtures. It is not a general production OCR accuracy claim: the dataset consists of 20 generated packets using three clean form layouts with duplicate copies. Full-page business-field extraction, signatures and diverse real scans were not tested by this validation.

A defensible project description is: “Validated an Azure OCR and SQL reconciliation pipeline on 120 synthetic pages across 20 ticket packets, comparing extracted shipment IDs with page-level ground truth.”
