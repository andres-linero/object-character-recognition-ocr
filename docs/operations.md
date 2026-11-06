# Operations guide

## First local run

Follow the root README to create an environment, install dependencies, copy `.env.example`, and generate synthetic data. Configure your own Azure OCR resource and Entra web app, then launch Streamlit from the repository root. Confirm successful sign-in before using real documents.

Use the synthetic shipment `3501` to check the end-to-end workflow: open the dashboard, sign in, allow scan indexing, confirm the workbook order matches the ticket, and open its preview/download. This invokes paid Azure OCR. Automated tests use mocked Azure and do not replace this check.

## Diagnose common problems

| Symptom | Check | Next action |
| --- | --- | --- |
| SSO configuration error | Tenant ID, client ID, and secret presence | Correct local configuration and restart |
| Redirect/state error | Entra callback URI and browser/session behavior | Restart sign-in; collect redacted error information; do not bypass state checks |
| Empty workbook view | `EXCEL_PATH`, readable file, exact headers | Use an absolute path and compare against the data contract |
| New PDF not visible | Scan directory, lowercase `.pdf`, dashboard rerun | Place PDF directly in configured folder and trigger a rerun |
| OCR has no match | Azure settings, crop position, labels, exclusions | Inspect a synthetic/redacted example and adjust form-specific configuration |
| OCR failure does not retry | Cached PDF signature may have been saved | Investigate first; controlled reindexing can repeat Azure charges |
| Final PDF disappeared | `output/` seven-day cleanup | Restore from approved backup if needed; distinguish it from retained `upload_ready/` artifacts |

Do not copy raw exception logs into public issues without checking paths, identifiers, and provider details.

## Recovery and retention

Stop the app before changing local state. Back up source files and the complete local state directories as a consistent set if workflow history must be preserved. Do not open untrusted pickle caches.

For a suspected corrupt workbook cache, move the cache file aside while stopped, then restart and allow it to rebuild. Preserve the original for diagnosis if permitted. Do not erase the scan index casually: it contains associations to source PDFs that may have been removed.

There is no dedicated retry CLI, transactional rollback, or backup scheduler. A full reindex requires deliberate invocation of the existing indexing API with `force=True` or a future supported operation; it should be tested on synthetic data first. Removed source PDFs cannot be re-OCRed unless restored.

Before shared deployment, define approved retention for incoming PDFs, previews, extracted PDFs, caches, final outputs, and backups. Source deletion alone does not remove derived copies.

## Validation and release

Run `python -m pytest -q` after behavior changes. Review environment-variable additions against `.env.example` and `docs/configuration.md`. Test real Entra sign-in, callback failure, sign-out, and a synthetic Azure OCR call before shared use. Record the tested revision and environment without recording secrets.

Review [PRP.md](../PRP.md) for unresolved dependency locking, vulnerability/license checks, and publication rights. Current docs do not establish production readiness.
