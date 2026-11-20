# Demo workflow and sample data

This guide describes the current document-driven workspace and generated test cases. Start with the [README](../README.md) for setup and an overview.

## Order numbering

```text
Shared count for orders: 1, 2, 3, ...

RENTAL                                 SALE
RO-0000002  (rental order)             SO-0000001  (sales order)
 ├─ W-0000001   work order, 3 pages     ├─ Shipment 00001   1 page
 └─ W-0000002   work order, 3 pages     ├─ Shipment 00002   1 page
                                        └─ Shipment 00003   1 page
```

| Number | What it is | Where its number comes from |
| --- | --- | --- |
| `RO-0000002` | Rental order. A parent order. It creates one or more work orders. | The shared order count |
| `SO-0000001` | Sales order. A parent order. It creates one or more shipments. | The shared order count |
| `W-0000001` | Work order. Created from a rental order; belongs to exactly one. | The work-order count |
| `Shipment 00001` | Shipment. Created from a sales order; belongs to exactly one. | The shipment count |

The rules:

- Rental orders and sales orders share **one** count, so an order number is used once: if order 1 is `SO-0000001`, there is no `RO-0000001`.
- The pages belong to the work order or the shipment. In the owner's forms a work order is three pages and a shipment is one page; the [300-order samples](demo-data.md#300-order-sample-scans) follow that. The eight demo batches below use six-page packets for both. The app takes the page total from the page itself ("Page 2/3").
- A page prints its order and its own document:
  - rental page: `Rental Order No. RO-0000002` and `Work Order No. W-0000001`
  - sales page: `Sales Order No. SO-0000001` and `Shipment No. 00001`
- Digits are kept exactly as printed, including leading zeros.
- A page that mixes the two families (an RO or W number together with an SO or Shipment number) is rejected and flagged.
- If only the order (RO or SO) can be read in the OCR crop, the page is kept under that order and flagged (`work_order_not_read` or `shipment_not_read`). The order number never stands in for the work order or shipment.
- Nothing else is a number the app recognises. A number without one of these four labels is ignored.

The tracker table and its CSV export lead with three columns:

| Order | Work order | Address |
| --- | --- | --- |
| `RO-0000002` | `W-0000001` | billing address |
| `SO-0000001` | `Shipment 00001` | billing address |

The **Work order** column holds the work order for a rental and the shipment for a sale. There is one row per work order or shipment, and that row is what becomes ready, is flagged, and is downloaded.

Each page also carries the customer, the address and delivery location, the document type, the copy and the printed page X/Y.

## Try the current dataset

Choose a PDF from `Scans/incomming_scan/` and drop it onto Overview or OCR activity, or use **Choose PDF**. The spelling `incomming_scan` is intentional for workspace compatibility.

| Files | Contents |
| --- | --- |
| `batch_01_8_orders.pdf` through `batch_08_8_orders.pdf` | Eight PDFs. Each contains 8 six-page documents, 48 shuffled pages: 2 rental orders with 3 work orders each, and 2 sales orders with one shipment each. Batch 1 holds `RO-0001001` (`W-0001501` to `W-0001503`), `SO-0001002` (`Shipment 00501`), `RO-0001003` (`W-0001504` to `W-0001506`) and `SO-0001004` (`Shipment 00502`). |
| `rental_and_sales_orders_shuffled.pdf` | An identical alias of batch 1. Uploading both does not duplicate its pages. |
| `sample_scan_01_155_pages.pdf` through `sample_scan_06_229_pages.pdf` | Optional and large: 300 orders, 1,261 pages in six PDFs. Present only after `scripts/create_order_samples.py --register`. Every uploaded page is one billable Azure read; see [300-order sample scans](demo-data.md#300-order-sample-scans) before uploading. |

Across the eight batches there are **64 documents: 48 work orders under 16 rental orders, and 16 shipments under 16 sales orders**. Each work order or shipment expects six printed pages. The file names say "8 orders" because the tracker shows one row per work order or shipment. Every batch includes:

| Case | Expected result | Action |
| --- | --- | --- |
| Four work orders and two shipments with normally positioned numbers | Approved and ready for download | Download their compiled PDFs or scan ZIP. |
| One work order with the `Work Order No.` line on printed page 1 below the OCR zone | All six images exist, but page 1 needs review | Inspect the visible work order, RO and customer/address in Flags and link the image. |
| One work order with the `Work Order No.` line on printed page 6 below the OCR zone | All six images exist, but page 6 needs review | Inspect and approve the correct original image. |

No page or identifier is deleted or replaced with a fake number. The fixed crop cannot read the shifted work-order line, while local full-page extraction retains it for review. A readable RO alone never verifies a work-order page: the page is kept under its RO and flagged (`work_order_not_read`). Across eight batches, 384 pages are present. By construction, 48 documents (32 work orders and 16 shipments) have every number inside the crop and 16 work orders have one page to review. These are expected results, not preloaded statuses or measured outcomes; actual provider readings determine the result.

Generating samples does not submit them or preload rows. Previously uploaded legacy batches retain their original identifiers and test cases; refreshing templates does not rewrite that history.

To create a separate, fully correct control sample with all identifiers inside the crop:

```sh
uv run --locked python scripts/create_rental_hierarchy_sample.py --clean --batch-number 10
```

This adds `batch_10_ALL_CORRECT_8_orders.pdf`: eight documents (2 rental orders with 3 work orders each, and 2 sales orders with one shipment each) with all 48 pages and no intentional scan defects. It preserves the other sample PDFs and makes Batch 10 the recommended sample. Generating it does not preload orders or call Azure.

## Use the workspace

| Tab | Purpose |
| --- | --- |
| **Overview** | Upload PDFs and see flat Approved / In review order rows, with downloads for approved orders. |
| **Dataset** | Search the document-derived tracker by order (RO or SO), work order or shipment, customer or address. The table leads with **Order**, **Work order** and **Address**. Check completeness and download marks. |
| **Rental analytics** | View explicit rental billing, collections, customer and monthly charts; see [billing setup](rental-analytics.md). |
| **OCR activity** | Follow the current PDF's actual page total and processing progress. Download its completed orders together. |
| **Flags** | Inspect incomplete orders, unmatched images and field conflicts; repair assignments or upload missing pages. |
| **Ingestion history** | See document-processing runs. |

### Review and repair

Flags groups incomplete work orders and shipments under their rental or sales order, lists documents whose order number was not read in a separate section, and shows unidentified pages. Open an incomplete row and choose **Fix pages**. The target's order (RO or SO), its work order or shipment, customer and address identify what you are completing.

- **Possible matches** are unassigned images without a known conflicting order or page field. They still require your review.
- **Different images** have conflicting customer, address, order, work-order (or shipment) or printed-page details. They remain available for inspection and for their correct order; they are not deleted or marked complete.
- **No matching image** means available images cannot fill the selected printed slot. Upload the missing page instead of linking an unrelated image.

Selecting an image changes its preview and comparison only, preserving the tab, scroll and keyboard focus. The comparison separates target values from image values. The compared fields are customer, address, order, work order (the shipment on a sales page), printed page and page total. Any known difference blocks linking on the server and in the UI. A page whose order differs from the target's, for example an RO page offered to a shipment, cannot be linked, and neither can a page that mixes rental and sales numbers. An image whose identity could not be read, or whose Azure reading differs from the target, requires explicit acknowledgment after inspection.

The link action names both source image and destination order/page. A separate approval record preserves the decision without changing the source PDF or original OCR result. An order becomes ready only when every expected printed page is accounted for without duplicates. One complete order can be downloaded while others still need attention.

### Download once

Before downloading the scan ZIP, its card shows orders detected in this scan, ready orders, orders not ready, and printed pages still unresolved. Only ready orders enter the ZIP. Counts update after repairs and exclude older scans; saved scan results remain available after restarting the app.

A download is named `Customer__<order>__<work order or shipment>__Address.pdf`, for example `Amber Workshop__RO-0000002__W-0000001__101 Simulation Way, Demo City, ZZ 00000.pdf` or `Amber Workshop__SO-0000001__Shipment 00001__100 Simulation Way, Demo City, ZZ 00000.pdf`. The scan ZIP puts each document in a folder named after its order, so `RO-0000002/` holds its work orders and `SO-0000001/` holds its shipments.

PDF and ZIP downloads mark included orders **Downloaded**. The mark persists after refresh or restart, with a separate **Download again** action. Inline previews do not count. Changed source pages create a new downloadable version; earlier receipts remain in history. A receipt records a file served by the app, not confirmation that a browser saved it to disk.

## Files and persistence

| Path | Purpose |
| --- | --- |
| `Scans/incomming_scan/` | Selectable samples and incoming uploads. |
| `demo_data/order_samples/` | The optional 300-order sample scans with their `orders.csv` and `manifest.json`. |
| `Scans/processed/<sha256>/` | Preserved original uploads referenced by database pages. |
| `Scans/flag_order/` | Copies and page-status reports for scans needing attention. |
| `Scans/output/` | Checked, compiled ticket PDFs. |
| `Scans/manifest.json` | Synthetic-file allowlist and sample case descriptions; not the source of tracker rows. |
| `demo_runtime/workspace.sqlite` | Work orders and shipments, their parent orders (RO and SO), pages, attempts, manual approvals and versioned download receipts. |

`ocr_workspace/storage.py` owns the schema and startup migrations. PostgreSQL migration references are in `database/`; the local app uses SQLite. Generated data, source documents, runtime databases and credentials are excluded from Git.

For older registered scans, `scripts/extract_page_details.py` adds local details. It makes no Azure calls and does not reassign pages. `scripts/rebuild_scan_dataset.py` requires `--confirm-reset` and deletes local scans, uploads, databases and workflow history. It is not part of normal startup or sample refresh.
