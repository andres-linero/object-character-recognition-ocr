import csv

import pytest
from ocr_workspace.analytics import rental_analytics


def ledger(tmp_path, rows):
    path = tmp_path / 'billing.csv'
    with path.open('w', newline='') as source:
        writer = csv.writer(source)
        writer.writerow(['invoice_id','rental_order','invoice_date','currency','billed_cents','collected_cents','synthetic'])
        writer.writerows(rows)
    return path


def test_revenue_counts_invoices_once_despite_multiple_work_orders(tmp_path):
    tickets = [dict(parent_order_number='RO-0001', order_type='RENTAL', customer='Amber', download_ready=True)] * 3
    tickets += [dict(parent_order_number='SO-0002', order_type='SALE', customer='Amber', download_ready=True)]
    path = ledger(tmp_path, [['A','RO-0001','2026-11-01','USD',10001,5000,'true'], ['B','SO-0002','2026-11-01','USD',99999,99999,'true']])
    result = rental_analytics(tickets, path)
    assert result['totals'] == dict(billed_cents=10001, collected_cents=5000, outstanding_cents=5001, rentals=1, invoices=1)
    assert result['rows'][0]['work_orders'] == 3
    assert result['customers'][0]['collected_cents'] == 5000
    assert rental_analytics(tickets, path, month='2026-10')['totals']['billed_cents'] == 0
    assert rental_analytics(tickets, path, customer='other')['rows'] == []


def test_missing_ledger_never_invents_revenue(tmp_path):
    result = rental_analytics([], tmp_path/'missing.csv')
    assert result['totals']['collected_cents'] == 0
    assert not result['ledger_available']


@pytest.mark.parametrize('amount,paid', [(-1,0),(100,101),(100,-1)])
def test_invalid_amounts_fail(tmp_path, amount, paid):
    with pytest.raises(ValueError):
        rental_analytics([], ledger(tmp_path, [['A','RO-1','2026-11-01','USD',amount,paid,'true']]))


def test_duplicate_invoices_fail(tmp_path):
    row = ['A','RO-1','2026-11-01','USD',100,50,'true']
    with pytest.raises(ValueError):
        rental_analytics([], ledger(tmp_path, [row,row]))
