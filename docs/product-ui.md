# Product UI and automatic scan intake

Run `sh scripts/run_web.sh` from the repository. It uses `.venv` when available, prepares `demo_runtime/workspace.sqlite` from generated tracker manifests if absent, and serves http://127.0.0.1:8700.

The left tabs are **Overview**, **Dataset**, **Documents**, **OCR activity**, **Review queue**, and **Ingestion history**. Dataset displays the tracker records. There is one live workspace, without Azure-verified/full-demo/new-test choices. Older local fixture databases are retained as archives, not visible stages.

## Folder workflow

1. Keep sample inputs outside intake. The three six-page PDFs are in `demo_batches/intake_test_03/ready_to_scan/`.
2. With the server running, move or copy a generated PDF into `Scans/incoming/`.
3. The worker polls every two seconds and waits for two identical size/time observations. It only accepts content matching a generated synthetic fixture manifest. Symlinks and non-PDF files are skipped.
4. A checksum-verified snapshot is preserved under `Scans/processed/<sha256>/`. Database page references use that snapshot so replacing an incoming filename cannot change an earlier preview or download.
5. Each previously unattempted page is sent to Azure. The returned typed identifier is matched against the tracker; expectations alone never create provider evidence. Attempts and actual associations are committed to SQL. Existing attempts, including failures, are not automatically resubmitted.
6. OCR activity, Overview, and Documents refresh every five seconds while visible and no ticket drawer is open. Matched tickets can be opened and downloaded. Unreadable, unknown-order, provider-error, pending and running outcomes remain distinct.

Configure Azure endpoint/key in local `.env`; the worker reads them without returning credentials to the browser. Calls incur provider charges. Missing credentials disable the worker and produce a safe startup log. `/api/health` reports whether the worker thread is alive and the relative intake directory. A process-level OS file lock permits one live worker for this database; this does not coordinate separate CLI tools, which must not be run against the active intake simultaneously.

## Counts and provenance

Summary metrics count source PDF documents: **PDF files received**, **OCR complete**, and **Files remaining**. One multi-ticket PDF still counts as one file. A file is complete only when every registered page's latest attempt succeeded. Known tracker records remain visible even before any file is scanned. The current activity response shows up to 200 newest pages, but counts cover the whole workspace.

The parser reads the shipment/work-order identifier from the page header. Company, jobsite, addresses, and equipment are tracker/manifest data, not OCR-extracted fields. A distinct rental agreement number is not present in the generated forms and is labeled not recorded. Downloads assemble only the selected order's associated pages. The current demo registers duplicate identical file content once.

## Scope and checks

This is a localhost synthetic workspace; it does not replace production authentication. Unknown PDFs are deliberately skipped and never silently relabeled synthetic. The legacy signed-in Streamlit interface and office repository are unchanged. Full-page unknown-document extraction, authentication for private scans, durable distributed job leasing, and an explicit failed-page retry UI remain future work.

Local tests cover stable-copy detection, outside samples remaining unprocessed, per-page matching, immutable snapshots, no duplicate provider calls on watcher restart, unknown-file rejection, API source boundaries, restored tabs, file counts, and ticket drawers. Azure is mocked in regression tests. The earlier three-PDF manual live test matched 18/18 pages; those results are retained in the archived fixture database, not preloaded into the live intake.

## Live OCR Verification

Overview and OCR activity contain a connected progress display driven by the worker's thread-safe status. Server-sent events deliver the latest state about once a second; the UI updates the progress panel without replacing the scan list or an open drawer. Reconnection keeps the last known status and labels the connection interruption. The five-second list refresh remains independent.

The display connects **PDF detected → OCR reading → Matching orders → Ticket PDF ready**. Page counters reflect completed attempts and successful matches, not elapsed-time estimates. Reading and matching can both remain active because each page is matched as soon as its OCR response arrives. Reduced-motion preferences disable animations.

Readiness requires successful current-page attempts, unambiguous actual associations, enough associated pages for the order's expected count, and successful PDF creation/reopening. The worker writes checked ticket artifacts under `Scans/output/`. Unreadable/unmatched pages or PDF write failures display attention/error states and never show a ready confirmation. Download actions appear on the live panel only after completion.

`GET /api/workspaces/{dataset}/progress` returns the current snapshot; `/progress/stream` streams it. This status is per live worker process and resets on server restart; SQL attempts and PDF outputs persist. Existing incoming PDFs are reconciled on restart without new OCR calls for already attempted pages. Generator manifests retain PDF checksums so moving a sample before server startup still permits recognition. No input samples were placed into intake or submitted to Azure for this UI revision.
