from ADK_Agentic.ticket_names import ticket_filename


def test_customer_facing_filename_contains_all_four_fields_and_no_batch_or_demo_prefix():
    assert ticket_filename(dict(customer='Demo Amber Projects', work_order='W-991005',
        rental_order='RA-701005', billing_address='1104 Simulation Way')) == (
        'Amber Projects__W-991005__RA-701005__1104 Simulation Way.pdf')


def test_filename_cannot_create_paths_or_headers_and_missing_values_are_explicit():
    name = ticket_filename(dict(customer='A/B\r\n"C', work_order='W-12',
        rental_order='RA:34', billing_address='../Main\\Street'))
    assert not any(c in name for c in '/\\\r\n:"')
    assert ticket_filename({}) == 'Customer-not-recorded__Order-not-recorded__Rental-not-recorded__Address-not-recorded.pdf'
