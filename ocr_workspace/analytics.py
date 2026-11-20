"""Explicit billing-ledger analytics; document counts never imply revenue."""
import csv
from collections import defaultdict
from datetime import date
from pathlib import Path


def rental_analytics(tickets, ledger, customer='', month=''):
    parents = {}
    for ticket in tickets:
        number = ticket.get('parent_order_number')
        if ticket.get('order_type') == 'RENTAL' and number:
            parents.setdefault(number, []).append(ticket)
    rows = []
    seen = set()
    path = Path(ledger)
    if path.is_file():
        with path.open(newline='') as source:
            for record in csv.DictReader(source):
                invoice = record['invoice_id'].strip()
                if not invoice or invoice in seen:
                    raise ValueError('Billing ledger requires unique invoice IDs.')
                seen.add(invoice)
                issued = date.fromisoformat(record['invoice_date']).isoformat()
                billed, collected = int(record['billed_cents']), int(record['collected_cents'])
                if billed < 0 or not 0 <= collected <= billed:
                    raise ValueError('Billing amounts must satisfy 0 <= collected <= billed.')
                if record['currency'] != 'USD':
                    raise ValueError('This dashboard supports USD billing records only.')
                number = record['rental_order']
                if number not in parents:
                    continue
                children = parents[number]
                name = children[0]['customer']
                if customer and customer.casefold() not in name.casefold():
                    continue
                if month and issued[:7] != month:
                    continue
                rows.append(dict(invoice_id=invoice, invoice_date=issued, rental_order=number,
                    customer=name, billed_cents=billed, collected_cents=collected,
                    outstanding_cents=billed-collected, work_orders=len(children),
                    ready_work_orders=sum(t['download_ready'] for t in children),
                    synthetic=record.get('synthetic', '').lower() == 'true'))
    def totals(items):
        return {key: sum(r[key] for r in items) for key in
                ('billed_cents', 'collected_cents', 'outstanding_cents')}
    def group(key):
        groups = defaultdict(list)
        for row in rows:
            groups[row[key][:7] if key == 'invoice_date' else row[key]].append(row)
        return [dict(label=label, **totals(items), rentals=len({r['rental_order'] for r in items}))
                for label, items in sorted(groups.items())]
    return dict(currency='USD', source='rental_billing.csv', ledger_available=path.is_file(),
        synthetic=any(r['synthetic'] for r in rows), rows=sorted(rows, key=lambda r: (r['invoice_date'], r['invoice_id']), reverse=True),
        totals=dict(**totals(rows), rentals=len({r['rental_order'] for r in rows}), invoices=len(rows)),
        customers=group('customer'), months=group('invoice_date'),
        unbilled_rentals=len(set(parents)-{r['rental_order'] for r in rows}) if not customer and not month else None)
