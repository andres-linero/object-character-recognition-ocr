"""Create an opt-in fictional ledger from the currently observed rental orders."""
import argparse
import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sqlalchemy import select
from ocr_workspace import storage as db


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database', type=Path, default=Path('demo_runtime/workspace.sqlite'))
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    output = args.output or args.database.parent / 'rental_billing.csv'
    store = db.Store(db.sqlite_url(args.database))
    try:
        rows = store.rows(select(db.rental_orders.c.rental_number).order_by(db.rental_orders.c.rental_number))
    finally:
        store.close()
    # Exclusive creation protects an existing ledger from being overwritten.
    with output.open('x', newline='') as stream:
        writer = csv.writer(stream)
        writer.writerow(['invoice_id','rental_order','invoice_date','currency','billed_cents','collected_cents','synthetic'])
        for index, row in enumerate(r for r in rows if r['rental_number'].startswith('RO-')):
            billed = 85000 + (index % 9) * 27500
            collected = [billed, billed, billed // 2, 0][index % 4]
            writer.writerow([f'DEMO-INV-{index+1:04}', row['rental_number'], f'2026-{9+index%3:02}-{1+index%27:02}', 'USD', billed, collected, 'true'])
    print(f'Created fictional billing ledger: {output}')


if __name__ == '__main__':
    main()
