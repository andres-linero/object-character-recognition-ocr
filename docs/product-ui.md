# Product UI and automatic scan intake

Run `sh scripts/run_web.sh` from the repository. It uses `.venv` when available, initializes an empty `demo_runtime/workspace.sqlite` if absent, and serves http://127.0.0.1:8700.

The left tabs are **Overview**, **Dataset**, **OCR activity**, **Flags**, and **Ingestion history**. Dataset displays only orders extracted from submitted PDFs. There is one live workspace, without Azure-verified/full-demo/new-test choices. Sample refresh replaces named templates while preserving submitted originals and scan history.

## Upload workflow

1. Choose a shuffled multi-order PDF from `Scans/incomming_scan/`. Each of the current eight batches has 2 ROs, 8 OD orders, 4 shared SO shipments and all 48 pages. Six orders have normally positioned numbers. Two orders each have one OD line shifted just below the fixed OCR crop; their original full-page images still contain all identifiers. No page is deliberately omitted.
2. Drop it on the upload area or use Choose PDF. The filename stays visible with its upload status or rejection reason. Only generated synthetic files matching `Scans/manifest.json` are accepted.
3. A completed upload creates a `.pdf.queued` marker and enqueues the file immediately. The worker waits for submissions, with no folder polling. Pending markers are replayed once at startup. Copying a file into the sample directory does not submit it.
4. A checksum-verified snapshot is preserved under `Scans/processed/<sha256>/`. Database page references use that snapshot.
5. Each previously unattempted page's top-right crop is sent to Azure. Local text extraction (or macOS Vision for raster pages) reads the customer, address, rental order (RO), work order, shipment, and printed page numbering. Those fields form a dataframe row. The Azure identifier must agree before the row creates or updates a detected order. No Excel or manifest customer metadata is used. Attempts and actual associations are committed to SQL; failures are not automatically retried.
6. Live progress comes through the event stream. The Overview and OCR screens do not rebuild the upload controls on a timer. Scans needing attention are copied to `Scans/flag_order/` with page-status JSON reports. Completed output is saved under `Scans/output/`.

Configure Azure endpoint/key in local `.env`; the worker reads them without returning credentials to the browser. Calls incur provider charges. Missing credentials disable the worker and produce a safe startup log. `/api/health` reports whether the worker thread is alive and the relative intake directory. A process-level OS file lock permits one live worker for this database; this does not coordinate separate CLI tools, which must not be run against the active intake simultaneously.

## Counts and provenance

The Dataset tab is the order tracker and download surface. Each row shows rental agreement, customer/address, matched page count, and OCR status. A detected order remains incomplete until all expected pages have successful, unambiguous OCR associations. Ready rows expose a Download PDF link; the server also blocks incomplete downloads. Filenames include customer, work order, rental order (RO), and address. OCR event messages refresh tracker rows and filter counts while preserving the search field and current page. OCR activity contains upload controls, processing progress, page counts, and the ZIP download. Overview results contain flat Approved and In review rows showing only the customer/order label, status, and a download action for ready orders. Rows cannot expand or open a drawer. Counts represent orders, excluding unidentified page counts. Flags contains incomplete orders and unidentified pages, grouped by rental order or source scan. All extracted page details, candidate images and manual page repair controls are available there. Dataset drawers link to Review in Flags for repairs.

PDF files received and Files remaining count source PDFs. OCR complete counts processed pages in the current PDF: the total is read during upload validation before OCR begins (for example, 0 / 48), then the completed count advances through terminal page outcomes. Flagged and failed pages count as processed, with review status shown separately. The current PDF total is restored from registered page records after reload. One multi-ticket PDF still counts as one source file. A file is complete only when every registered page's latest attempt succeeded. The tracker is empty until a submitted PDF produces an identified order. The current activity response shows up to 200 newest pages, but counts cover the whole workspace.

The parser reads the shipment/work-order identifier from the page header. Customer, address, location, rental agreement, and page count are extracted locally from the current generated ticket layout. New layouts need their own field mappings. The manifest is an allowed-file checksum list for this synthetic workspace, not an order source. Printed page numbers must form a complete sequence without duplicates before a ticket is downloadable. Complete orders can be downloaded while other orders are missing pages. Downloads restore printed page order.

## Scope and checks

This is a localhost synthetic workspace; it does not replace production authentication. Unknown PDFs are deliberately skipped and never silently relabeled synthetic. The legacy signed-in Streamlit interface and office repository are unchanged. Full-page unknown-document extraction, authentication for private scans, durable distributed job leasing, and an explicit failed-page retry UI remain future work.

Local tests cover stable-copy detection, outside samples remaining unprocessed, per-page matching, immutable snapshots, no duplicate provider calls on watcher restart, unknown-file rejection, API source boundaries, restored tabs, file counts, and ticket drawers. Azure is mocked in regression tests. The earlier three-PDF manual live test matched 18/18 pages; those results are retained in the archived fixture database, not preloaded into the live intake.

## Live OCR Verification

Overview and OCR activity contain a connected progress display driven by the worker's thread-safe status. Server-sent events deliver the latest state about once a second; the UI updates the progress panel without replacing the scan list or an open drawer. Reconnection keeps the last known status and labels the connection interruption. The five-second list refresh remains independent.

The display connects **PDF detected → OCR reading → Matching orders → Ticket PDF ready**. Page counters reflect completed attempts and successful matches, not elapsed-time estimates. Reading and matching can both remain active because each page is matched as soon as its OCR response arrives. Reduced-motion preferences disable animations.

Readiness requires successful current-page attempts, unambiguous actual associations, enough associated pages for the order's expected count, and successful PDF creation/reopening. The worker writes checked ticket artifacts under `Scans/output/`. Unreadable/unmatched pages or PDF write failures display attention/error states and never show a ready confirmation. Download actions appear on the live panel only after completion.

`GET /api/workspaces/{dataset}/progress` returns the current snapshot; `/progress/stream` streams it. This status is per live worker process and resets on server restart; SQL attempts and PDF outputs persist. Existing incoming PDFs are reconciled on restart without new OCR calls for already attempted pages. Generator manifests retain PDF checksums so moving a sample before server startup still permits recognition. No input samples were placed into intake or submitted to Azure for this UI revision.

## Connected dots and drag-and-drop

The live verification display keeps the existing layout. Stage dots fill on completion; connecting lines fill from actual processed/matched page ratios and animate between updates. Reduced-motion settings disable transition/pulse effects.

Overview and OCR activity also provide a compact drop area with a Choose PDF button. Dropped files are streamed to temporary storage, checked as readable, unencrypted generated demo PDFs, and atomically moved into `Scans/incomming_scan/` and queued immediately. The submission worker handles OCR, matching and PDF creation. The browser reports queued intake separately from OCR completion. Original sample files are never moved by browser uploads.

Uploads are limited to 50 MB per PDF, validate filenames, enforce same-origin browser requests, and clean up temporary files after failure. The raw PDF request API is `POST /api/workspaces/{dataset}/intake`, using `Content-Type: application/pdf` and a URL-encoded `X-File-Name` header. Multiple selected files are queued sequentially. New generator manifests created while the server is running are recognized when an unknown input is checked.

Live-connection shutdown uses a bounded graceful timeout. A replacement worker waits for the old worker's OS lock rather than abandoning automatic detection during a server restart. Avoid restarting while a paid page call is in flight; interrupted attempts are retained for deliberate recovery.

An unidentified printed page is not proof that its image is absent. Order responses include page_gap_status and same-scan unidentified page references. If unidentified pages remain, the UI says Incomplete and links those pages for review. Only a fully processed scan with no unresolved pages can report that a numbered page was not found. The drawer uses the expected printed total and original printed page labels, rather than treating the associated subset as a complete ticket.

## Visual page repair

Expand an incomplete order in Flags and choose Fix missing page, or open its drawer and choose Fix pages. When an RO is identified, the image notebook contains only unassigned images under that RO, including images from other submitted scans. For older pages without an RO, candidates come from the same processed scan and exclude pages positively linked to a different RO. Select a thumbnail to inspect the full original image next to the order’s customer/address, choose an unaccounted printed page number, then approve that source image for that page. The action names both source and destination page numbers.

Manual assignment preserves the source PDF and original OCR attempt. A separate approval record stores the reviewer, time, page number, and original attempt reference. Approved pages are labeled Manually approved, and OCR evidence remains visible. The order becomes downloadable only when every expected printed page is accounted for without duplicates. PDF and ZIP generation include the approved original images in printed order. Invalid, duplicate, foreign-scan, already-owned, and still-processing assignments are blocked. Repeating the same approval is idempotent. Schema migration 2 adds approval storage without replacing existing scan data.

## Rental orders and child tickets

The current tickets have only three identifier namespaces: OD for order, RO for rental, and SO for shipment. A customer can own several ROs; an RO can group multiple OD orders and shared SO shipments. RO and SO do not substitute for the OD number. Legacy TK/W and RA labels remain readable for existing uploads.

Local extraction reads OD, RO and SO separately. Automatic verification of an OD page requires the same OD in the existing Azure crop. A readable RO is retained as context when the OD is outside that crop; SO never substitutes for the order. Those original images appear under the RO in Flags. Once other pages identify the order, Fix pages can explicitly approve its matching image for the unaccounted printed slot.

Flags collapses by RO, then OD. Overview keeps one flat row per detected order. Dataset lists RO and OD in separate columns. The scan ZIP groups completed OD files into RO folders. Individual filenames retain customer, OD, RO and address. `GET /api/workspaces/{dataset}/rental-orders` supplies parent groups, child tickets and unassigned-page counts. Migration 3 adds these links and removes the old unique-shipment constraint while retaining existing scans, OCR attempts and manual approvals.

`python3 scripts/create_rental_hierarchy_sample.py --all-batches` refreshes eight selectable PDFs: 64 OD orders, 16 ROs, 32 shared SO shipments and all 384 pages. Every order has six pages; two OD lines per batch are shifted below the fixed crop. RO/SO stay readable but cannot automatically pass those pages. Full-page local extraction retains the actual OD for manual comparison. Expected outcome: six automatically complete orders and two in review per batch. The standalone OD/RO/SO PDF is a byte-identical alias of batch 1. Named old templates and obsolete generator-owned supplements are backed up before replacement; submitted originals and database history remain intact. Generation makes no Azure calls and preloads no rows.

## Extracted page details

Every processed page keeps its local extraction independently of Azure matching, including pages with missing identifiers or provider errors. In Flags, the order drawer shows the selected page’s customer, billing and dispatch addresses, OD order number, SO shipment, RO rental, document type, printed numbering, and signature evidence. Fix pages shows the candidate image’s own details, with unreadable fields labeled Not read. These fields do not inherit expected order values and do not automatically approve or regroup the image. Extracted page details are not duplicated in Overview or Dataset drawers.

Signature status distinguishes an explicit unsigned statement, a PDF signature field with a value, signature text/an empty field requiring review, and an undetermined result. It does not authenticate a signature or infer handwriting from a document title. The generated acknowledgment pages explicitly say NOT SIGNED. Full-page details remain local; the Azure crop is unchanged.

Migration 4 adds per-page extraction storage. To populate details for existing registered scans, run `python3 scripts/extract_page_details.py` after current scan work finishes. It verifies source paths and checksums, skips already extracted pages unless `--refresh` is supplied, and makes no Azure calls. It preserves original PDFs, order matches, OCR attempts and manual approvals.

## Download marks

Dataset, Overview and the order drawer show Downloaded after a PDF download, with a separate Download again action. The mark persists in SQL across page refreshes and server restarts. ZIP downloads mark every ticket included only after the whole archive is prepared; inline PDF previews do not count. Failed preparation and incomplete orders do not create a receipt. The UI prevents simultaneous requests to the same download URL.

Migration 5 records the ticket, source-page version, time, filename and download type (PDF, scan ZIP, RO ZIP, or a user-reported previous download). A ticket whose original pages or printed arrangement change needs a new download; old receipts remain in history. Receipts record downloads prepared and served by the app, not verification of a file saved to disk by the browser. Downloads made before tracking existed are not inferred, except when the user identifies them.

## Stable image selection and field comparison

Selecting a page updates its preview, selection marker and comparison only. It keeps the drawer, image element, gallery, selected tab, scroll positions and keyboard focus. It makes no workspace reload or provider call. The page list shows document type, copy, printed page and verification state instead of repeating the shipment number.

Fix pages compares the target and selected image by customer, address, OD, RO, SO, customer/address and printed numbering. Rental agreement is the same RO field, not another independent identifier. Different known identity or page fields block linking on both client and server. Shipment differences and unreadable identity require explicit acknowledgment; the decision is stored with the manual approval. The original image and OCR attempt remain intact. Multiple missing pages stay in Fix pages after each link.

The header parser retains every labeled identifier namespace from one Azure response. Customer order, RO, work order/TK and shipment remain separate; a generic customer Order No. cannot fall back to a shipment lookup. Address extraction stays local. Provider/local identifier disagreements are flagged instead of hidden by one matching shipment. `python3 scripts/link_existing_rental_numbers.py` links older saved agreement labels to the same RO without OCR calls, page reassignment or changes to download history.

## Possible matches, different images and missing uploads

Each missing printed slot has its own candidate counts. An unassigned page with a known conflicting identity or printed number appears under Different images, remains inspectable and cannot be linked. An image with no known conflict appears under Possible matches and still needs human review. If all available candidates conflict, the order reports No matching image / Needs upload rather than implying those thumbnails can complete it. The API returns candidate_summary and pages_needing_upload; no_compatible_image distinguishes this case from an unprocessed or unreadable page.

Upload missing pages is available inside the fixer. When the new PDF completes processing, the open order updates in place, preserving the active workflow; completion switches to the ready result. This remains available for truly absent pages in other uploads; current samples have every page and exercise manual review of shifted numbers instead.

## ZIP totals before download

The scan download card shows detected orders, orders ready for the ZIP, orders not ready, and unresolved printed-page slots. Counts come from the same source document and prepared ticket IDs as the ZIP, excluding unrelated workspace history. During processing the card labels pending pages and provisional totals. Manual page approval updates the counts. Unidentified images remain visible as a separate warning when no known printed-page gap represents them. After a restart, the last attempted scan and its existing prepared PDFs are restored without new provider calls.
