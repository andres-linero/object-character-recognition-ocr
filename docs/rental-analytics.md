# Rental analytics

Open **Rental analytics** in the browser workspace. This view joins explicit billing records to rental orders observed in uploaded documents. It never derives financial amounts from document counts or OCR completeness.

## Prepare interview demo billing

After uploading and processing synthetic sample orders:

```sh
uv run --locked python scripts/create_demo_billing.py
```

This creates `demo_runtime/rental_billing.csv` beside the workspace database. It refuses to overwrite an existing ledger, makes no Azure calls, and changes no order or document records. The generated amounts are fictional, carry `synthetic=true`, and appear under a synthetic billing notice. Reload the analytics view after changing the ledger.

A different workspace can use `--database /path/to/workspace.sqlite`. For the dashboard to discover the output, keep the filename `rental_billing.csv` beside that database.

## Ledger format

One row per invoice; amounts use integer USD cents:

```csv
invoice_id,rental_order,invoice_date,currency,billed_cents,collected_cents,synthetic
DEMO-INV-0001,RO-0000002,2026-11-01,USD,125000,75000,true
```

| Field | Meaning |
| --- | --- |
| `invoice_id` | Unique, nonempty invoice identifier. Duplicate IDs reject the ledger. |
| `rental_order` | Exact parent RO number already observed in this workspace. |
| `invoice_date` | ISO date (`YYYY-MM-DD`). |
| `currency` | `USD`; other currencies reject the ledger to prevent mixing totals. |
| `billed_cents` | Nonnegative integer invoice amount. |
| `collected_cents` | Recorded collection total, between zero and the billed amount. |
| `synthetic` | `true` for fictional demo billing. |

Missing ledgers show an empty state and zero totals. Unknown rental orders and sales orders are excluded. Invalid IDs, dates or amounts return a validation error. A rental with several work orders contributes its invoice amount once. Multiple distinct invoices for the same rental are added; the rental count remains distinct.

## Meaning and limits

- **Billed** is the sum of included invoice amounts.
- **Collected** is the sum of recorded collections against those invoices.
- **Outstanding** is billed minus collected.
- **Documents ready** shows ready work orders over known work orders; it does not indicate payment.
- Monthly collections are grouped by **invoice date**, not the dates payments arrived.
- Customer search and invoice-month filters update totals, charts, the table and CSV export together. Customer charts show the top five; totals include every matching customer.

This is a read-only billing snapshot, not an accounting system. It has no payment event history, credit notes, refunds, tax calculation, cost/profit calculation or recognized-revenue rules. Billing values are not extracted from scanned pages. Runtime ledgers stay excluded from Git.

## Interview walkthrough

1. Show the tracker: rental orders create work orders; sales orders create shipments.
2. Open Rental analytics and explain the separate billed, collected and outstanding amounts.
3. Search for a customer; show that totals, charts and invoice rows update together.
4. Show a rental’s invoice beside its document readiness and explain why document completion and payment are independent.
5. Export the filtered CSV for follow-up analysis.

Current media: [dashboard](media/order-scanner/rental-analytics.jpg), [filtered customer](media/order-scanner/rental-analytics-filtered.jpg), [ledger](media/order-scanner/rental-billing-ledger.jpg), [analytics recording](media/order-scanner/rental-analytics-live.mp4), and [document viewer recording](media/order-scanner/document-tracker-live.mp4). Both videos are continuous browser-content captures of real interactions, sampled at approximately 7–8 frames per second, with idle endings removed. The GIF previews use the same live footage at four frames per second. Audio and other applications are excluded.
