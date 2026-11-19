"""Page evidence survives failed identification and never fabricates a signature."""
import pymupdf as fitz
import json
import pytest
from types import SimpleNamespace
from fastapi.testclient import TestClient
from sqlalchemy import select

from ocr_workspace import storage as db, ocr
from ocr_workspace.document_data import extract_fields
from ocr_workspace import document_data
from ocr_workspace.processing import process_page, register_pdf
from ocr_workspace.web_api import create_app
from scripts.create_demo_data import generate_dataset
from scripts.extract_page_details import extract_existing


@pytest.fixture
def packet(tmp_path):
    manifest = generate_dataset(tmp_path, count=1, min_pages=6, max_pages=6, rasterize=False)
    return tmp_path / manifest['tickets'][0]['pdf']


def test_page_fields_remain_available_when_identifier_is_missing(packet, tmp_path):
    with fitz.open(packet) as pdf:
        pdf[0].add_redact_annot(fitz.Rect(306, 0, 612, 198), fill=(1, 1, 1))
        pdf[0].apply_redactions()
        changed = packet.with_suffix('.part')
        pdf.save(changed)
    changed.replace(packet)
    database = tmp_path / 'workspace.sqlite'
    store = db.Store(db.sqlite_url(database))
    store.migrate()
    doc = register_pdf(store, packet, synthetic=True)
    page = store.rows(select(db.pages).where(db.pages.c.document_id == doc, db.pages.c.page_number == 1))[0]
    result = process_page(store, page['id'], extractor=lambda *a, **kw: None, document_driven=True)
    assert result['status'] == 'no_match' and result['error_code'] == 'identifier_not_found'
    assert store.counts()['orders'] == 0
    fields = store.rows(select(db.page_extractions))[0]['fields']
    assert fields['customer'] == 'Demo Amber Workshop'
    assert fields['address'] == '100 Simulation Way, Demo City, ZZ 00000'
    assert fields['order_number'] is None and fields['parent_order_number'] is None
    assert fields['mixed_order_types'] is False
    assert not {'work_order', 'shipment', 'customer_order_number', 'rental_order', 'parent_rental_number',
                'rental_number_printed', 'rental_number_conflict'} & set(fields)
    assert fields['page_number'] == 1 and fields['expected_pages'] == 6
    assert fields['document_type'] == 'Delivery Ticket'
    assert fields['signature_status'] == 'explicitly_unsigned'
    assert fields['extraction_method'] == 'pdf_text'
    with TestClient(create_app(root=tmp_path, databases={'test': database}, allowed_roots=[tmp_path])) as client:
        row = client.get('/api/workspaces/test/activity?issues_only=true').json()['activity'][0]
        assert row['identifier'] is None and row['fields'] == fields
        assert row['matched_order'] is None
    store.close()


def test_fields_are_saved_before_provider_failure(packet, tmp_path):
    store = db.Store(db.sqlite_url(tmp_path / 'workspace.sqlite'))
    store.migrate()
    register_pdf(store, packet, synthetic=True)
    page = store.rows(select(db.pages))[0]

    def fail(*a, **kw):
        raise RuntimeError('Provider unavailable')

    assert process_page(store, page['id'], extractor=fail, document_driven=True)['status'] == 'error'
    fields = store.rows(select(db.page_extractions))[0]['fields']
    assert (fields['order_number'], fields['parent_order_number']) == ('W-0000001', 'RO-0000001')
    assert store.counts()['orders'] == 0
    store.close()


def test_rental_order_alone_does_not_become_a_work_order(packet, tmp_path):
    # The work order line is unreadable: only the parent rental order remains on the page.
    with fitz.open(packet) as pdf:
        pdf[0].add_redact_annot(fitz.Rect(322, 138, 590, 162), fill=(1, 1, 1))
        pdf[0].apply_redactions()
        changed = packet.with_suffix('.part')
        pdf.save(changed)
    changed.replace(packet)
    store = db.Store(db.sqlite_url(tmp_path / 'workspace.sqlite'))
    store.migrate()
    register_pdf(store, packet, synthetic=True)
    page = store.rows(select(db.pages).where(db.pages.c.page_number == 1))[0]
    calls = []

    def identify(*args, **kwargs):
        calls.append(1)
        return ocr.parse_identifier('RENTAL ORDER Delivery Ticket Rental Order No. RO-0000001')

    result = process_page(store, page['id'], extractor=identify, document_driven=True)
    assert result['status'] == 'no_match' and result['error_code'] == 'work_order_not_read'
    assert result['identifier'] == 'RO-0000001'
    assert store.counts()['orders'] == 0
    fields = store.rows(select(db.page_extractions))[0]['fields']
    assert fields['address'] and fields['order_number'] is None
    assert fields['parent_order_number'] == 'RO-0000001'
    assert fields['ocr_identifiers'] == {'rental_order': 'RO-0000001'}
    assert fields['ocr_identifier_kind'] == 'rental_order'
    # The rental context is kept so the page can be reviewed under its rental order.
    assert [r['rental_number'] for r in store.rows(select(db.rental_orders))] == ['RO-0000001']
    assert [r['page_id'] for r in store.rows(select(db.rental_pages))] == [page['id']]
    assert store.rows(select(db.rental_tickets)) == []
    assert len(calls) == 1
    store.close()


def test_independent_header_conflict_is_not_hidden_by_a_matching_rental_order(packet, tmp_path):
    store = db.Store(db.sqlite_url(tmp_path / 'workspace.sqlite'))
    store.migrate()
    register_pdf(store, packet, synthetic=True)
    page = store.rows(select(db.pages))[0]
    result = process_page(store, page['id'], extractor=lambda *a, **k: ocr.parse_identifier(
        'Delivery Ticket Rental Order No. RO-0000001 Work Order No. W-9999999'), document_driven=True)
    assert result['status'] == 'no_match' and result['error_code'] == 'identifier_fields_disagree'
    assert store.counts()['orders'] == 0
    fields = store.rows(select(db.page_extractions))[0]['fields']
    assert fields['order_number'] == 'W-0000001'
    assert fields['ocr_identifiers']['work_order'] == 'W-9999999'
    store.close()


def test_sales_order_alone_does_not_become_a_shipment(tmp_path):
    manifest = generate_dataset(tmp_path, count=4, min_pages=6, max_pages=6, rasterize=False)
    sale = tmp_path / manifest['tickets'][3]['pdf']
    # The shipment line is unreadable: only the parent sales order remains on the page.
    with fitz.open(sale) as pdf:
        pdf[0].add_redact_annot(fitz.Rect(322, 138, 590, 162), fill=(1, 1, 1))
        pdf[0].apply_redactions()
        changed = sale.with_suffix('.part')
        pdf.save(changed)
    changed.replace(sale)
    store = db.Store(db.sqlite_url(tmp_path / 'workspace.sqlite'))
    store.migrate()
    register_pdf(store, sale, synthetic=True)
    page = store.rows(select(db.pages).where(db.pages.c.page_number == 1))[0]
    result = process_page(store, page['id'], extractor=lambda *a, **k: ocr.parse_identifier(
        'SALES ORDER Delivery Ticket Sales Order No. SO-0000002'), document_driven=True)
    assert result['status'] == 'no_match' and result['error_code'] == 'shipment_not_read'
    assert result['identifier'] == 'SO-0000002'
    assert store.counts()['orders'] == 0
    fields = store.rows(select(db.page_extractions))[0]['fields']
    assert fields['address'] and fields['order_number'] is None
    assert fields['parent_order_number'] == 'SO-0000002'
    assert fields['ocr_identifiers'] == {'sales_order': 'SO-0000002'}
    assert fields['ocr_identifier_kind'] == 'sales_order'
    # The sales order is kept as parent context so the page can be reviewed under it.
    assert [r['rental_number'] for r in store.rows(select(db.rental_orders))] == ['SO-0000002']
    assert [r['page_id'] for r in store.rows(select(db.rental_pages))] == [page['id']]
    assert store.rows(select(db.rental_tickets)) == []
    store.close()


@pytest.mark.parametrize('position,parent,error', [
    (0, 'RO-0000001', 'work_order_not_read'), (3, 'SO-0000002', 'shipment_not_read')])
@pytest.mark.parametrize('as_string', [False, True])
def test_local_full_page_read_does_not_stand_in_for_a_number_the_provider_missed(tmp_path, position, parent, error, as_string):
    """The page prints both numbers, but the provider crop returned only the parent order."""
    manifest = generate_dataset(tmp_path, count=4, min_pages=6, max_pages=6, rasterize=False)
    ticket = manifest['tickets'][position]
    store = db.Store(db.sqlite_url(tmp_path / 'workspace.sqlite'))
    store.migrate()
    register_pdf(store, tmp_path / ticket['pdf'], synthetic=True)
    page = store.rows(select(db.pages).where(db.pages.c.page_number == 1))[0]
    response = parent if as_string else ocr.parse_identifier(f'Order No. {parent}')
    result = process_page(store, page['id'], extractor=lambda *a, **k: response, document_driven=True)
    assert (result['status'], result['identifier'], result['error_code']) == ('no_match', parent, error)
    assert store.counts()['orders'] == 0 and store.rows(select(db.associations)) == []
    fields = store.rows(select(db.page_extractions))[0]['fields']
    # The local read still holds the document number as evidence for the reviewer.
    assert (fields['order_number'], fields['parent_order_number']) == (ticket['order_id'], parent)
    assert [r['rental_number'] for r in store.rows(select(db.rental_orders))] == [parent]
    assert len(store.rows(select(db.rental_pages))) == 1 and store.rows(select(db.rental_tickets)) == []
    store.close()


MIXED_CASES = {
    # case: (packet position, provider text, text printed on the page for the local read only)
    'rental_page_provider_reads_a_sales_order': (0, 'Rental Order No. RO-0000001 Work Order No. W-0000001 Sales Order No. SO-0000009', None),
    'rental_page_provider_reads_a_shipment': (0, 'Rental Order No. RO-0000001 Work Order No. W-0000001 Shipment No. 00009', None),
    'rental_page_prints_a_sales_order': (0, 'Rental Order No. RO-0000001 Work Order No. W-0000001', 'Sales Order No. SO-0000009'),
    'rental_page_prints_a_shipment': (0, 'Rental Order No. RO-0000001 Work Order No. W-0000001', 'Shipment No. 00009'),
    'sales_page_provider_reads_a_rental_order': (3, 'Sales Order No. SO-0000002 Shipment No. 00001 Rental Order No. RO-0000009', None),
    'sales_page_provider_reads_a_work_order': (3, 'Sales Order No. SO-0000002 Shipment No. 00001 Work Order No. W-0000009', None),
    'sales_page_prints_a_rental_order': (3, 'Sales Order No. SO-0000002 Shipment No. 00001', 'Rental Order No. RO-0000009'),
    'sales_page_prints_a_work_order': (3, 'Sales Order No. SO-0000002 Shipment No. 00001', 'Work Order No. W-0000009'),
    'provider_reads_both_parents_only': (0, 'Rental Order No. RO-0000001 Sales Order No. SO-0000002', None),
}


@pytest.mark.parametrize('case', MIXED_CASES)
def test_page_with_a_rental_number_and_a_sales_number_is_rejected(tmp_path, case):
    position, response, printed = MIXED_CASES[case]
    manifest = generate_dataset(tmp_path, count=4, min_pages=6, max_pages=6, rasterize=False)
    packet = tmp_path / manifest['tickets'][position]['pdf']
    if printed:
        # Printed on the page but absent from the provider's answer: only the local full-page pass sees it.
        with fitz.open(packet) as pdf:
            pdf[0].insert_text((334, 104), printed, fontsize=9)
            changed = packet.with_suffix('.part')
            pdf.save(changed)
        changed.replace(packet)
    store = db.Store(db.sqlite_url(tmp_path / 'workspace.sqlite'))
    store.migrate()
    register_pdf(store, packet, synthetic=True)
    page = store.rows(select(db.pages).where(db.pages.c.page_number == 1))[0]
    result = process_page(store, page['id'], extractor=lambda *a, **k: ocr.parse_identifier(response), document_driven=True)
    assert result['status'] == 'no_match'
    assert result['error_code'] == 'rental_and_sales_numbers_on_one_page'
    assert store.counts()['orders'] == 0
    assert store.rows(select(db.associations)) == []
    assert store.rows(select(db.rental_orders)) == [] and store.rows(select(db.rental_pages)) == []
    fields = store.rows(select(db.page_extractions))[0]['fields']
    assert fields['mixed_order_types'] is bool(printed)
    assert fields['customer'] == 'Demo Amber Workshop'  # Evidence stays available for review.
    store.close()


def _replace_parent_line(packet, text):
    """Reprint the parent-order line of every page with another order number."""
    with fitz.open(packet) as pdf:
        for page in pdf:
            page.add_redact_annot(fitz.Rect(322, 112, 590, 134), fill=(1, 1, 1))
            page.apply_redactions()
            if text:
                page.insert_text((334, 126), text, fontsize=13)
        changed = packet.with_suffix('.part')
        pdf.save(changed)
    changed.replace(packet)


@pytest.mark.parametrize('position,document,wrong_parent', [
    (0, 'W-0000001', 'Sales Order No. SO-0000002'), (3, 'Shipment 00001', 'Rental Order No. RO-0000001')])
@pytest.mark.parametrize('provider_reads', ['document_only', 'document_and_parent'])
def test_document_printed_under_a_parent_of_the_other_family_does_not_create_an_order(
        tmp_path, position, document, wrong_parent, provider_reads):
    """A W- under an SO, or a shipment under an RO, is never accepted."""
    manifest = generate_dataset(tmp_path, count=4, min_pages=6, max_pages=6, rasterize=False)
    packet = tmp_path / manifest['tickets'][position]['pdf']
    _replace_parent_line(packet, wrong_parent)
    with fitz.open(packet) as pdf:
        fields = extract_fields(pdf[0])
    assert (fields['order_number'], fields['parent_order_number']) == (document, wrong_parent.split()[-1])
    assert fields['mixed_order_types'] is True
    store = db.Store(db.sqlite_url(tmp_path / 'workspace.sqlite'))
    store.migrate()
    register_pdf(store, packet, synthetic=True)
    label = document if document.startswith('W-') else 'Shipment No. ' + document.split()[-1]
    response = label if provider_reads == 'document_only' else f'{wrong_parent} {label}'
    pages = store.rows(select(db.pages).order_by(db.pages.c.page_number))
    results = [process_page(store, page['id'], extractor=lambda *a, **k: ocr.parse_identifier(response),
                            document_driven=True) for page in pages]
    assert {(r['status'], r['error_code']) for r in results} == {('no_match', 'rental_and_sales_numbers_on_one_page')}
    assert store.counts()['orders'] == 0 and store.rows(select(db.associations)) == []
    assert store.rows(select(db.rental_orders)) == [] and store.rows(select(db.rental_tickets)) == []
    store.close()


@pytest.mark.parametrize('position,document', [(0, 'W-0000001'), (3, 'Shipment 00001')])
def test_document_without_any_parent_order_does_not_create_an_order(tmp_path, position, document):
    manifest = generate_dataset(tmp_path, count=4, min_pages=6, max_pages=6, rasterize=False)
    packet = tmp_path / manifest['tickets'][position]['pdf']
    _replace_parent_line(packet, None)
    store = db.Store(db.sqlite_url(tmp_path / 'workspace.sqlite'))
    store.migrate()
    register_pdf(store, packet, synthetic=True)
    page = store.rows(select(db.pages).where(db.pages.c.page_number == 1))[0]
    result = process_page(store, page['id'], extractor=lambda *a, **k: document, document_driven=True)
    assert (result['status'], result['identifier']) == ('no_match', document)
    assert result['error_code'] == 'document_fields_incomplete_or_conflicting'
    fields = store.rows(select(db.page_extractions))[0]['fields']
    assert (fields['order_number'], fields['parent_order_number']) == (document, None)
    assert store.counts()['orders'] == 0 and store.rows(select(db.rental_orders)) == []
    store.close()


def test_sales_page_reads_its_shipment_and_its_sales_order(tmp_path):
    manifest = generate_dataset(tmp_path, count=4, min_pages=6, max_pages=6, rasterize=False)
    sale = manifest['tickets'][3]
    assert (sale['order_id'], sale['order_type'], sale['parent_order_number']) == ('Shipment 00001', 'SALE', 'SO-0000002')
    store = db.Store(db.sqlite_url(tmp_path / 'workspace.sqlite'))
    store.migrate()
    document = register_pdf(store, tmp_path / sale['pdf'], synthetic=True)
    pages = store.rows(select(db.pages).where(db.pages.c.document_id == document).order_by(db.pages.c.page_number))
    with fitz.open(tmp_path / sale['pdf']) as pdf:
        fields = extract_fields(pdf[2])
    assert (fields['order_number'], fields['parent_order_number']) == ('Shipment 00001', 'SO-0000002')
    assert fields['mixed_order_types'] is False and fields['document_type'] == 'Sales Order'
    results = [process_page(store, page['id'], extractor=lambda *a, **k: 'Shipment 00001', document_driven=True) for page in pages]
    assert {(r['status'], r['identifier'], r['error_code']) for r in results} == {('success', 'Shipment 00001', None)}
    order = store.rows(select(db.orders))
    assert len(order) == 1
    assert (order[0]['order_number'], order[0]['order_type'], order[0]['expected_pages']) == ('Shipment 00001', 'SALE', 6)
    # The sales order is the parent: one parent row, linked to the shipment and to all six pages.
    parents = store.rows(select(db.rental_orders))
    assert [r['rental_number'] for r in parents] == ['SO-0000002']
    assert [(r['order_id'], r['rental_id']) for r in store.rows(select(db.rental_tickets))] == [(order[0]['id'], parents[0]['id'])]
    assert {r['rental_id'] for r in store.rows(select(db.rental_pages))} == {parents[0]['id']}
    assert len(store.rows(select(db.rental_pages))) == 6
    saved = store.rows(select(db.page_extractions))[0]['fields']
    assert saved['ocr_identifiers'] == {'shipment': 'Shipment 00001'} and saved['ocr_identifier_kind'] == 'shipment'
    store.close()


@pytest.mark.parametrize('answer', ['900004', '00001', 'WO-990001', 'OD-992003', 'Work Order No. 0000001', 'ALSO-1234'])
def test_number_outside_the_four_namespaces_is_not_an_identifier_for_a_document_page(tmp_path, answer):
    manifest = generate_dataset(tmp_path, count=4, min_pages=6, max_pages=6, rasterize=False)
    store = db.Store(db.sqlite_url(tmp_path / 'workspace.sqlite'))
    store.migrate()
    register_pdf(store, tmp_path / manifest['tickets'][3]['pdf'], synthetic=True)
    page = store.rows(select(db.pages).where(db.pages.c.page_number == 1))[0]
    result = process_page(store, page['id'], extractor=lambda *a, **k: answer, document_driven=True)
    assert (result['status'], result['identifier'], result['error_code']) == ('no_match', None, 'identifier_not_found')
    assert store.counts()['orders'] == 0
    store.close()


def test_details_distinguish_unsigned_acknowledgment_from_signature_text(packet):
    with fitz.open(packet) as pdf:
        acknowledgment = extract_fields(pdf[4])
        assert acknowledgment['signature_document'] is True
        assert acknowledgment['signature_status'] == 'explicitly_unsigned'
        assert acknowledgment['signature_evidence'] == 'NOT SIGNED - DEMO'
        assert acknowledgment['parent_order_number'] == 'RO-0000001'
        assert acknowledgment['order_number'] == 'W-0000001'
        assert acknowledgment['mixed_order_types'] is False
        assert acknowledgment['contact_email'] == 'dispatch.001@example.test'
    with fitz.open() as pdf:
        page = pdf.new_page()
        page.insert_text((40, 50), 'Signature: __________________')
        page.insert_text((40, 70), 'Customer Order No. CO-134560')
        fields = extract_fields(page)
        # Customer-order numbers are not part of the model and are never read as an order.
        assert 'customer_order_number' not in fields
        assert fields['order_number'] is None and fields['parent_order_number'] is None
        assert fields['signature_status'] == 'field_present'
        assert fields['signature_evidence'] == 'Signature: __________________'


def test_vector_header_does_not_hide_scanned_body_fields(packet, monkeypatch):
    with fitz.open(packet) as original, fitz.open() as hybrid:
        source = original[0]
        lines = [dict(text=' '.join(s['text'] for s in line['spans']),
                      x=line['bbox'][0] / source.rect.width, y=line['bbox'][1] / source.rect.height)
                 for block in source.get_text('dict')['blocks'] for line in block.get('lines', [])]
        page = hybrid.new_page(width=source.rect.width, height=source.rect.height)
        page.insert_image(page.rect, stream=source.get_pixmap().tobytes('png'))
        page.insert_text((334, 70), 'Work Order No. W-0000001')
        calls = []

        def local_read(args, **kwargs):
            calls.append(args)
            return SimpleNamespace(stdout=json.dumps(lines).encode())

        monkeypatch.setattr(document_data.subprocess, 'run', local_read)
        fields = extract_fields(page)
        assert fields['extraction_method'] == 'local_vision'
        assert fields['customer'] == 'Demo Amber Workshop'
        assert fields['address'] == '100 Simulation Way, Demo City, ZZ 00000'
        assert fields['page_number'] == 1
        assert calls[-1][0].endswith('read-scan')


def test_existing_scan_extraction_preserves_attempts_and_is_idempotent(packet, tmp_path):
    store = db.Store(db.sqlite_url(tmp_path / 'workspace.sqlite'))
    store.migrate()
    register_pdf(store, packet, synthetic=True)
    page = store.rows(select(db.pages))[0]
    process_page(store, page['id'], extractor=lambda *a, **k: None, document_driven=True)
    attempts = store.rows(select(db.attempts))
    counts = store.counts()
    # Upgrade a pre-detail workspace with an existing unsuccessful OCR attempt.
    with store.engine.begin() as connection:
        db.page_extractions.drop(connection)
        connection.execute(db.versions.delete().where(db.versions.c.version >= 4))
    store.migrate()
    assert extract_existing(store, [tmp_path]) == 6
    assert extract_existing(store, [tmp_path]) == 0
    assert store.counts() == counts
    assert store.rows(select(db.attempts)) == attempts
    assert len(store.rows(select(db.page_extractions))) == 6
    with packet.open('ab') as out:
        out.write(b'changed')
    with pytest.raises(ValueError, match='changed after registration'):
        extract_existing(store, [tmp_path], refresh=True)
    store.close()
