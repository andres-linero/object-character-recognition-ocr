from ocr_workspace.ticket_names import ticket_filename


def test_rental_filename_is_customer_rental_order_work_order_address_without_demo_prefix():
    assert ticket_filename(dict(customer='Demo Amber Projects', order_number='W-0000005',
        parent_order_number='RO-0000003', billing_address='1104 Simulation Way')) == (
        'Amber Projects__RO-0000003__W-0000005__1104 Simulation Way.pdf')


def test_sales_filename_is_customer_sales_order_shipment_address():
    name = ticket_filename(dict(customer='Demo Amber Projects', order_number='Shipment 00001',
        parent_order_number='SO-0000002', billing_address='1104 Simulation Way'))
    assert name == 'Amber Projects__SO-0000002__Shipment 00001__1104 Simulation Way.pdf'
    assert 'RO-' not in name and 'W-' not in name and 'Rental' not in name


def test_filename_cannot_create_paths_or_headers_and_missing_values_are_explicit():
    name = ticket_filename(dict(customer='A/B\r\n"C', order_number='W:12',
        parent_order_number='RO:34', billing_address='../Main\\Street'))
    assert not any(c in name for c in '/\\\r\n:"')
    assert ticket_filename({}) == (
        'Customer-not-recorded__Order-not-recorded__Work-order-not-recorded__Address-not-recorded.pdf')
    # A document whose parent was never recorded still says so explicitly.
    assert ticket_filename(dict(customer='Amber', order_number='Shipment 00001', billing_address='1 Way')) == (
        'Amber__Order-not-recorded__Shipment 00001__1 Way.pdf')
