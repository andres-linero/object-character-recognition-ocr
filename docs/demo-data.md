# Synthetic demo dataset

The demo generator creates 100 fictional ticket packets by default. It follows the reference packet structure without copying its scanned pages, logos, handwriting, customer records, addresses, or document text. The original reference is not required at generation time and is not included in the repository.

## Packet structure

Each ticket has three distinct papers:

1. Equipment delivery: bill-to and ship-to blocks, order metadata, and equipment rows.
2. Demo rental terms: original demonstration text, with no legal effect.
3. Delivery acknowledgement: role-based receipt fields and an explicit unsigned demo marker.

Each paper has two, three, or four copies, giving **6, 9, or 12 total pages per ticket**, including all three papers. Copy colors distinguish the copies. All pages are marked as synthetic demo material. No real people, signatures, or identity documents are generated.

Every page in a packet uses the same fictional work-order/shipment identifiers. The shipment label is inside the application's top-right OCR crop, including on terms and acknowledgement copies. The companion tracker links that shipment number to the ticket's work-order number and fictional customer.

## Generate the dataset

```sh
python scripts/create_demo_data.py --count 100 --seed 42 --output demo_data
```

The default uses 6, 9, or 12 pages per ticket and a fixed start date of `2030-04-01`. To customize the range or create a smaller smoke-test set:

```sh
python scripts/create_demo_data.py --count 3 --seed 42 --output /tmp/ocr-demo-smoke --min-pages 6 --max-pages 6 --vector
```

The default range is 6–12 pages. Custom bounds may range from 3 to 12 and must include a multiple of three; every paper has the same number of copies. Default output is image-only at 120 dpi to exercise OCR like a scan. Use `--vector` to keep searchable text for diagnostics. `--start-date YYYY-MM-DD` controls the date sequence. Existing generated outputs are protected unless `--overwrite` is supplied; use a new output directory when preserving a previous dataset.

| Output | Purpose |
| --- | --- |
| `incoming_scans/demo_ticket_<SO>.pdf` | One complete packet per ticket |
| `orders.xlsx` | Matching dashboard tracker with monthly worksheets |
| `orders.csv` | Portable tracker data |
| `manifest.json` | Seed/configuration and ticket/page/document mappings |

## Running safely

Use the repository Python environment with its existing runtime dependencies installed. Generation is local and makes no Azure calls. The generated dataset is kept under `demo_data/`, which Git ignores. Do not point output at private source-data directories.

The existing `scripts/create_sample_data.py` remains available for the one-page quick-start fixture. The larger generator creates separate files so it does not replace that fixture or change application credentials.

## Using the dataset in the dashboard

Stop the dashboard before switching data sources. Configure the generated inputs in your local `.env`:

```dotenv
EXCEL_PATH=demo_data/orders.xlsx
SCAN_PDF_PATH=demo_data/incoming_scans
```

Launch from the repository root when using those relative paths; absolute paths also work. Keep Microsoft sign-in and your own Azure OCR credentials configured normally. Restart the app and verify matching with a few synthetic tickets first.

Generation does not call Azure, but indexing generated pages in the app does. A full 100-ticket dataset contains 600–1,200 pages. The current application performs OCR synchronously during dashboard reruns; use a smaller generated dataset when demonstrating setup or diagnosing crop behavior.

Use a fresh app checkout or preserve existing local state before indexing demo data. The index retains historical associations when source PDFs are removed, so changing the input directory alone does not establish a clean demo state. Do not delete private indexes or outputs to prepare a demonstration.

## Reproducibility and verification

Keep the generator seed and configuration with the dataset manifest. Generated PDFs and the tracker must agree on identifiers, dates, customer labels, page counts, and document copies. PDF metadata and rendering internals need not be byte-identical across library versions.

Structural checks and offline crop verification do not prove live Azure OCR accuracy. Confirm a representative sample through your configured Azure resource before recording a full dashboard walkthrough.

## Verified default run

Seed `42` with 100 tickets produces 930 image-only pages: 26 packets of 6 pages, 38 of 9 pages, and 36 of 12 pages. The tracker has 100 matching rows across APR/MAY worksheets, with 80 OPEN and 20 COMPLETE records. The uncompressed dataset is approximately 123 MB.

The generator and application suite pass 25 tests. All generated packets were checked for expected page counts, image-only pages, unique identifiers, and tracker/manifest consistency. Representative pages from the three paper layouts were rendered for visual review.

Offline text recognition on 27 rendered header crops (one 6-page, one 9-page, and one 12-page packet) recovered every expected shipment number. The existing OCR extraction parser returned the correct identifier for all 27 recognized headers. Azure itself was not called.
