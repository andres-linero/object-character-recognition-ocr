# Synthetic demo dataset

Three generators create fictional documents. None of them calls Azure.

| Script | Creates | Use it for |
| --- | --- | --- |
| `scripts/create_demo_data.py` | 100 separate packets with a matching tracker, in `demo_data/` | Tracker ingestion and the CLI tools (this page, below) |
| `scripts/create_rental_hierarchy_sample.py` | Eight 48-page shuffled batches in `Scans/incomming_scan/` | The browser demo; see [demo workflow](demo-workflow.md) |
| `scripts/create_order_samples.py` | 300 orders in six large shuffled PDFs, in `demo_data/order_samples/` | Larger scans in the owner's page counts; see [300-order sample scans](#300-order-sample-scans) |

All three use the same numbering:

```text
Shared count for orders: 1, 2, 3, ...

RENTAL                                 SALE
RO-0000002  (rental order)             SO-0000001  (sales order)
 ├─ W-0000001   work order              ├─ Shipment 00001
 └─ W-0000002   work order              ├─ Shipment 00002
                                        └─ Shipment 00003
```

Rental orders and sales orders are the parent orders and share one count. A rental order creates work orders; a sales order creates shipments. Work orders and shipments each have their own count. The full rules are in [order numbering](demo-workflow.md#order-numbering).

## The 100-packet dataset

`scripts/create_demo_data.py` creates 100 fictional packets by default. Records come in groups of four: three work orders (`W-`) under one rental order (`RO-`), then one shipment under one sales order (`SO-`). All four share a customer and billing address. The default 100 packets are 75 work orders under 25 rental orders, and 25 shipments under 25 sales orders. The first group is:

| Order | Work order | Kind |
| --- | --- | --- |
| `RO-0000001` | `W-0000001` | Rental |
| `RO-0000001` | `W-0000002` | Rental |
| `RO-0000001` | `W-0000003` | Rental |
| `SO-0000002` | `Shipment 00001` | Sale |

The generator follows the reference packet structure without copying its scanned pages, logos, handwriting, customer records, addresses, or document text. The original reference is not required at generation time and is not included in the repository.

### Packet structure

Each packet is one work order or one shipment and has three distinct papers:

1. Delivery Ticket: bill-to and ship-to blocks, order metadata, and equipment rows.
2. Demo terms, with no legal effect: titled "Rental Agreement" in a rental packet and "Sales Order" in a sales packet.
3. Delivery Acknowledgement: role-based receipt fields and an explicit unsigned demo marker.

Each paper has two, three, or four copies, giving **6, 9, or 12 total pages per packet**, including all three papers. Copy colors distinguish the copies. All pages are marked as synthetic demo material. No real people, signatures, or identity documents are generated.

Every page in a packet prints the same two numbers inside the application's top-right OCR crop, including on terms and acknowledgement copies:

- A rental page prints `Rental Order No. RO-0000001` and `Work Order No. W-0000001`.
- A sales page prints `Sales Order No. SO-0000002` and `Shipment No. 00001`.

The companion tracker has one row per work order or shipment. Its `Order` column holds the `RO-…` or `SO-…` number and its `Work order` column holds the `W-…` number or `Shipment 00001`. `Address` holds the billing address.

### Generate the dataset

```sh
python scripts/create_demo_data.py --count 100 --seed 42 --output demo_data
```

The default uses 6, 9, or 12 pages per packet and a fixed start date of `2030-04-01`. To customize the range or create a smaller smoke-test set:

```sh
python scripts/create_demo_data.py --count 3 --seed 42 --output /tmp/ocr-demo-smoke --min-pages 6 --max-pages 6 --vector
```

The default range is 6–12 pages. Custom bounds may range from 3 to 12 and must include a multiple of three; every paper has the same number of copies. Default output is image-only at 120 dpi to exercise OCR like a scan. Use `--vector` to keep searchable text for diagnostics. `--start-date YYYY-MM-DD` controls the date sequence. Existing generated outputs are protected unless `--overwrite` is supplied; use a new output directory when preserving a previous dataset.

| Output | Purpose |
| --- | --- |
| `incoming_scans/demo_order_<number>.pdf` | One complete packet per work order or shipment, for example `demo_order_W-0000001.pdf` or `demo_order_Shipment_00001.pdf` |
| `orders.xlsx` | Matching tracker with monthly worksheets |
| `orders.csv` | Portable tracker data |
| `manifest.json` | Seed/configuration and ticket/page/document mappings |

### Running safely

Use the repository Python environment with its existing runtime dependencies installed. Generation is local and makes no Azure calls. The generated dataset is kept under `demo_data/`, which Git ignores. Do not point output at private source-data directories.

### Using the dataset

Load the generated tracker and manifest with the ingestion CLI described in [the data-pipeline guide](data-pipeline.md), or run `scripts/prepare_demo.py` to build an isolated `demo_runtime/demo.sqlite`. The browser workspace itself derives orders from uploaded documents and accepts only its own generated samples.

Generation does not call Azure, but OCR processing of generated pages does. A full 100-packet dataset contains 600–1,200 pages; process a small batch first (`scripts/process_documents.py --limit 10`) and set `OCR_MAX_PAGES_PER_FILE` when uploading through the app to cap spend.

### Reproducibility and verification

Keep the generator seed and configuration with the dataset manifest. Generated PDFs and the tracker must agree on identifiers, dates, customer labels, page counts, and document copies. PDF metadata and rendering internals need not be byte-identical across library versions.

Structural checks and offline crop verification do not prove live Azure OCR accuracy. Confirm a representative sample through your configured Azure resource before recording a full walkthrough.

### Verified default run

Seed `42` with 100 packets produces 930 image-only pages: 26 packets of 6 pages, 38 of 9 pages, and 36 of 12 pages. The tracker has 100 matching rows across APR/MAY worksheets, with 80 OPEN and 20 COMPLETE records. The uncompressed dataset is approximately 123 MB.

All generated packets were checked for expected page counts, image-only pages, unique identifiers, and tracker/manifest consistency. Representative pages from the three paper layouts were rendered for visual review.

An earlier offline text-recognition check on 27 rendered header crops (one 6-page, one 9-page, and one 12-page packet) was made on an older numbering and has not been repeated on the current headers. Azure itself was not called.

### Additional batches

Use `--start-index` to avoid reusing numbers across datasets. Changing only the seed changes the fictional details but does not change the default number range. For two 60-page batches after the initial 100 packets:

```sh
python3 scripts/create_demo_data.py --count 10 --seed 43 --start-index 101 --min-pages 6 --max-pages 6 --output demo_batches/batch_02
python3 scripts/create_demo_data.py --count 10 --seed 44 --start-index 111 --min-pages 6 --max-pages 6 --output demo_batches/batch_03
```

Activate your virtual environment first. If `python` is unavailable, use `python3` or the environment's full Python path. Each batch has its own matching tracker.

## 300-order sample scans

`scripts/create_order_samples.py` creates large shuffled scans in the owner's page counts: a work order is three pages and a shipment is one page.

```sh
uv run --locked python scripts/create_order_samples.py
```

With the defaults (`--count 300 --seed 2026`) it writes to `demo_data/order_samples/`:

| What | Count |
| --- | --- |
| Orders, numbered 1–300 on one shared count | 300 |
| Rental orders (`RO-`), mixed in among the sales orders | 150 |
| Sales orders (`SO-`) | 150 |
| Work orders (`W-0000001` to `W-0000301`), 3 pages each | 301 |
| Shipments (`Shipment 00001` to `Shipment 00358`), 1 page each | 358 |
| Pages (301 × 3 + 358 × 1) | 1,261 |

A rental order has one to three work orders; a sales order has one to four shipments. Because the count is shared, a number is used once: the first two orders are `SO-0000001` (three shipments) and `RO-0000002` (two work orders), and there is no `RO-0000001`. Each order has its own billing address, shared by all of its work orders or shipments.

The pages are written to six PDFs, each under 250 pages. An order's pages are all in one PDF, shuffled with the other orders in that file:

| File | Pages | Orders |
| --- | --- | --- |
| `sample_scan_01_155_pages.pdf` | 155 | 40 |
| `sample_scan_02_228_pages.pdf` | 228 | 52 |
| `sample_scan_03_202_pages.pdf` | 202 | 52 |
| `sample_scan_04_240_pages.pdf` | 240 | 53 |
| `sample_scan_05_207_pages.pdf` | 207 | 46 |
| `sample_scan_06_229_pages.pdf` | 229 | 57 |

Two more files describe what the scans contain:

| File | Contents |
| --- | --- |
| `orders.csv` | One row per work order or shipment: `Order`, `Work order`, `Address`, `Customer`, `Pages`, `File` |
| `manifest.json` | Seed, the counts above, each PDF's page count and SHA-256, and every order with its documents and scan page positions |

Pages are scan-like images by default, and the six default PDFs are roughly 20–32 MB each, inside the app's 50 MB upload limit; `--vector` keeps selectable text. `--output`, `--count` and `--seed` change the destination, the number of orders and the fictional details; the counts and file sizes above apply to the defaults only. Re-running replaces the previous output of this script and refuses to write into a non-empty folder it did not create.

### Uploading them costs money

Generating the samples is free. The app accepts only PDFs on its checksum allowlist, and `demo_data/order_samples/` is not on it, so the samples cannot be uploaded until you register them:

```sh
uv run --locked python scripts/create_order_samples.py --register
```

`--register` copies the six PDFs into `Scans/incomming_scan/` and adds them to `Scans/manifest.json`. Existing uploads, results and history are not touched, and nothing is submitted: you still upload each PDF in the browser.

**Every uploaded page is one billable Azure read.** The six files hold 1,261 pages in total, and the largest single file holds 240. Upload one file, check the result, and only then continue. To cap a file, set `OCR_MAX_PAGES_PER_FILE` in `.env` (see [configuration](configuration.md)); the scan stops once that many pages have been sent to Azure. Pages already read are served from the result cache and are not billed again.

Live Azure reading has not been validated on these samples; see [validation results](ocr-validation-results.md).
