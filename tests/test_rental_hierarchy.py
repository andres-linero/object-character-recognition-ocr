"""A rental order (RO) groups its work orders (W); a sales order (SO) groups its shipments.

A work order or shipment number below the OCR crop requires review; its parent order never stands in for it.
"""
import io
from pathlib import Path
import re
import pymupdf as fitz
import zipfile

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from ocr_workspace import ocr, storage as db
from ocr_workspace.document_data import observe_rental_context
from ocr_workspace.etl import checksum
from ocr_workspace.intake_watcher import IntakeWatcher
from ocr_workspace.processing import register_pdf, process_page
from ocr_workspace.web_api import create_app
from scripts.create_rental_hierarchy_sample import create


@pytest.fixture
def hierarchy(tmp_path):
    pdf, records, sequence = create(tmp_path, rasterize=False)
    store = db.Store(db.sqlite_url(tmp_path / 'workspace.sqlite'))
    store.migrate()
    assert store.counts()['orders'] == 0
    with fitz.open(pdf) as source:
        crop_responses = iter([page.get_text(clip=fitz.Rect(306, 0, 612, 198)) for page in source])
    def extract(*args, **kwargs):
        return ocr.parse_identifier(next(crop_responses))
    worker = IntakeWatcher(store, pdf.parent, {checksum(pdf)},
        extract, root=tmp_path)
    worker.tick(submitted=pdf)
    app = create_app(root=tmp_path, databases={'validation': tmp_path / 'workspace.sqlite'}, allowed_roots=[tmp_path])
    with TestClient(app) as client:
        yield client, store, records, sequence
    store.close()


def test_sample_has_two_rental_orders_with_three_work_orders_each_and_two_sales_orders_with_one_shipment_each(tmp_path):
    pdf, records, sequence = create(tmp_path, rasterize=False)
    assert pdf.name == 'rental_and_sales_orders_shuffled.pdf'
    assert len(sequence) == 48
    assert [(r['order_id'], r['parent_order_number'], r['order_type']) for r in records] == [
        ('W-0001501', 'RO-0001001', 'RENTAL'), ('W-0001502', 'RO-0001001', 'RENTAL'), ('W-0001503', 'RO-0001001', 'RENTAL'),
        ('Shipment 00501', 'SO-0001002', 'SALE'),
        ('W-0001504', 'RO-0001003', 'RENTAL'), ('W-0001505', 'RO-0001003', 'RENTAL'), ('W-0001506', 'RO-0001003', 'RENTAL'),
        ('Shipment 00502', 'SO-0001004', 'SALE')]
    assert all('shipment' not in r and 'rental_order' not in r and 'parent_rental_number' not in r for r in records)
    assert all(len(r['pages']) == 6 and {p['expected_ocr_id'] for p in r['pages']} == {r['order_id']} for r in records)
    # Every document of one parent order shares that order's billing address.
    assert [r['address'].split()[0] for r in records] == ['600'] * 4 + ['601'] * 4
    # The crop-miss profile moves one work order line below the crop in the third and sixth document.
    assert [r['shifted_order_pages'] for r in records] == [[], [], [1], [], [], [6], [], []]
    assert [r['test_case'] for r in records] == ['good', 'good', 'order_number_outside_crop', 'good',
                                                 'good', 'order_number_outside_crop', 'good', 'good']


def test_each_parent_order_groups_its_own_documents_and_no_sale_stands_alone(hierarchy):
    client, store, _, _ = hierarchy
    listing = client.get('/api/workspaces/validation/parent-orders').json()
    parents = listing['parent_orders']
    assert listing['total'] == len(parents) == 4 and 'rental_orders' not in listing
    assert len({p['customer'] for p in parents}) == 1  # One customer can own multiple orders.
    assert {p['parent_number']: p['order_type'] for p in parents} == {
        'RO-0001001': 'RENTAL', 'RO-0001003': 'RENTAL', 'SO-0001002': 'SALE', 'SO-0001004': 'SALE'}
    rentals = [p for p in parents if p['order_type'] == 'RENTAL']
    sales = [p for p in parents if p['order_type'] == 'SALE']
    assert all(p['ticket_count'] == 3 for p in rentals)
    assert sorted(p['unassigned_pages'] for p in rentals) == [1, 1]
    assert sorted(p['ready_tickets'] for p in rentals) == [2, 2]
    assert all((p['ticket_count'], p['ready_tickets'], p['unassigned_pages']) == (1, 1, 0) for p in sales)
    for parent in parents:
        assert len({t['order_number'] for t in parent['tickets']}) == parent['ticket_count']
        prefix = 'W-' if parent['order_type'] == 'RENTAL' else 'Shipment '
        assert all(t['order_number'].startswith(prefix) and t['order_type'] == parent['order_type'] for t in parent['tickets'])
        assert all(t['parent_id'] == parent['id'] and t['parent_order_number'] == parent['parent_number'] for t in parent['tickets'])
        assert not {'rental_number', 'rental_id'} & set(parent)
    assert {p['parent_number']: sorted(t['order_number'] for t in p['tickets']) for p in parents} == {
        'RO-0001001': ['W-0001501', 'W-0001502', 'W-0001503'], 'SO-0001002': ['Shipment 00501'],
        'RO-0001003': ['W-0001504', 'W-0001505', 'W-0001506'], 'SO-0001004': ['Shipment 00502']}
    tickets = client.get('/api/workspaces/validation/tickets').json()['tickets']
    sold = [t for t in tickets if t['order_type'] == 'SALE']
    assert sorted((t['order_number'], t['parent_order_number']) for t in sold) == [
        ('Shipment 00501', 'SO-0001002'), ('Shipment 00502', 'SO-0001004')]
    assert all(t['parent_id'] for t in tickets)
    assert all(t['download_ready'] and t['verified_pages'] == 6 for t in sold)
    # Every document appears under exactly one parent order.
    grouped = [t['id'] for p in parents for t in p['tickets']]
    assert sorted(grouped) == sorted(t['id'] for t in tickets) and len(set(grouped)) == 8
    # Tickets sort by (parent order, document number), descending.
    assert [(t['parent_order_number'], t['order_number']) for t in tickets] == sorted(
        ((t['parent_order_number'], t['order_number']) for t in tickets), reverse=True)
    assert not {'shipment', 'ticket_number', 'work_order', 'rental_order', 'customer_order_number',
                'parent_rental_number', 'rental_id'} & set(tickets[0])
    assert store.counts()['orders'] == 8
    overview = client.get('/api/workspaces/validation').json()
    assert overview['parent_orders'] == 4 and 'rental_orders' not in overview
    # Every page carries its parent context: 8 documents x 6 pages.
    assert len(store.rows(select(db.rental_pages))) == 48
    assert len(store.rows(select(db.rental_tickets))) == 8
    flags = client.get('/api/workspaces/validation/activity?issues_only=true').json()['activity']
    assert len(flags) == 2
    assert {p['error_code'] for p in flags} == {'work_order_not_read'}
    assert {p['identifier'] for p in flags} == {'RO-0001001', 'RO-0001003'}
    assert {p['parent_order_number'] for p in flags} == {'RO-0001001', 'RO-0001003'}
    assert sum(bool(p['parent_id']) for p in flags) == 2 and not any('rental_id' in p for p in flags)


def test_document_order_and_due_dates_reach_the_tracker(hierarchy):
    client, _, records, _ = hierarchy
    rows = {t['order_number']: t for t in client.get('/api/workspaces/validation/tickets').json()['tickets']}
    assert len(rows) == len(records) == 8
    for record in records:
        assert rows[record['order_id']]['order_date'] == record['order_date']
        assert rows[record['order_id']]['due_date'] == record['deadline']
        assert rows[record['order_id']]['order_type'] == record['order_type']
        assert rows[record['order_id']]['parent_order_number'] == record['parent_order_number']


@pytest.mark.parametrize('index,kind,parent,family,error', [
    (2, 'rental_order', 'RO-0001001', 'RENTAL', 'work_order_not_read'),
    (3, 'sales_order', 'SO-0001002', 'SALE', 'shipment_not_read')])
def test_only_the_parent_order_is_retained_without_inventing_a_document(tmp_path, index, kind, parent, family, error):
    pdf, records, sequence = create(tmp_path, rasterize=False)
    store = db.Store(db.sqlite_url(tmp_path / 'workspace.sqlite'))
    store.migrate()
    document_id = register_pdf(store, pdf, synthetic=True)
    position = next(n for n, (record, page, *_rest) in enumerate(sequence, 1) if record == index and page == 0)
    page_id = store.rows(select(db.pages.c.id).where(db.pages.c.document_id == document_id, db.pages.c.page_number == position))[0]['id']
    result = process_page(store, page_id, extractor=lambda *a, **k: ocr.ParsedIdentifier(kind, parent), document_driven=True)
    assert result['status'] == 'no_match' and result['error_code'] == error
    assert store.counts()['orders'] == 0
    assert len(store.rows(select(db.rental_orders))) == 1
    assert len(store.rows(select(db.rental_pages))) == 1
    with TestClient(create_app(root=tmp_path, databases={'validation': tmp_path / 'workspace.sqlite'}, allowed_roots=[tmp_path])) as client:
        listed = client.get('/api/workspaces/validation/parent-orders').json()['parent_orders']
        assert [(p['parent_number'], p['order_type']) for p in listed] == [(parent, family)]
        assert listed[0]['ticket_count'] == 0 and listed[0]['unassigned_pages'] == 1 and listed[0]['tickets'] == []
        assert client.get(f"/api/workspaces/validation/parent-orders/{listed[0]['id']}/download.zip").status_code == 409
    store.close()


def test_page_fixer_is_scoped_to_ro_not_just_shared_source_pdf(hierarchy):
    client, store, _, _ = hierarchy
    tickets = client.get('/api/workspaces/validation/tickets').json()['tickets']
    target = next(t for t in tickets if t['order_number'] == 'W-0001503')
    other = next(t for t in tickets if t['order_number'] == 'W-0001505')
    assert (target['parent_order_number'], other['parent_order_number']) == ('RO-0001001', 'RO-0001003')
    assert target['unaccounted_pages'] == [1] and other['unaccounted_pages'] == [6]
    assert len(target['unidentified_scan_pages']) == 1
    assert len(other['unidentified_scan_pages']) == 1
    possible = next(p for p in target['unidentified_scan_pages'] if not p['review']['1']['blocked'])
    assert possible['id'] != other['unidentified_scan_pages'][0]['id']
    assert target['candidate_summary']['1'] == {'possible': 1, 'different': 0}
    route = f"/api/workspaces/validation/tickets/{target['id']}/page-approvals"
    denied = client.post(route, json={'page_id': other['unidentified_scan_pages'][0]['id'], 'printed_page': 1})
    assert denied.status_code == 409
    assert client.post(route, json={'page_id': possible['id'], 'printed_page': 1}).status_code == 200
    parents = client.get('/api/workspaces/validation/parent-orders').json()['parent_orders']
    parent = next(p for p in parents if p['id'] == target['parent_id'])
    assert parent['ready_tickets'] == 3 and parent['unassigned_pages'] == 0
    archive = client.get(f"/api/workspaces/validation/parent-orders/{parent['id']}/download.zip")
    assert archive.status_code == 200
    with zipfile.ZipFile(io.BytesIO(archive.content)) as z:
        assert sorted(z.namelist()) == [
            f'Amber Workshop__RO-0001001__W-000150{n}__600 Simulation Way, Demo City, ZZ 00000.pdf' for n in (1, 2, 3)]
    assert 'RO-0001001-ready-tickets.zip' in archive.headers['content-disposition']
    receipts = store.rows(select(db.downloads))
    assert len(receipts) == 3 and all(r['kind'] == 'rental_zip' for r in receipts)
    rows = client.get('/api/workspaces/validation/tickets').json()['tickets']
    assert all(t['downloaded'] for t in rows if t['parent_id'] == target['parent_id'])
    # Neither the other rental order nor any sales order was part of this download.
    assert not any(t['downloaded'] for t in rows if t['parent_id'] != target['parent_id'])
    assert sum(t['order_type'] == 'SALE' and not t['downloaded'] for t in rows) == 2
    # A sales order downloads its own shipments the same way.
    sales_parent = next(p for p in parents if p['parent_number'] == 'SO-0001002')
    archive = client.get(f"/api/workspaces/validation/parent-orders/{sales_parent['id']}/download.zip")
    assert archive.status_code == 200 and 'SO-0001002-ready-tickets.zip' in archive.headers['content-disposition']
    with zipfile.ZipFile(io.BytesIO(archive.content)) as z:
        assert z.namelist() == ['Amber Workshop__SO-0001002__Shipment 00501__600 Simulation Way, Demo City, ZZ 00000.pdf']
    assert client.get('/api/workspaces/validation/parent-orders/unknown/download.zip').status_code == 404


@pytest.mark.parametrize('prefix,elsewhere', [('RO-', 'RO-9999999'), ('SO-', 'SO-9999999')])
def test_confirmed_page_cannot_silently_move_to_another_parent_order(hierarchy, prefix, elsewhere):
    _, store, _, _ = hierarchy
    page = next(p for p in store.rows(select(db.rental_pages)) if p['fields']['parent_order_number'].startswith(prefix))
    original_parent = page['rental_id']
    altered = dict(page['fields'], parent_order_number=elsewhere)
    with pytest.raises(ValueError, match='Conflicting parent order'):
        observe_rental_context(store, {}, page['page_id'], altered, elsewhere,
                               'rental_order' if prefix == 'RO-' else 'sales_order')
    assert store.rows(select(db.rental_pages.c.rental_id).where(db.rental_pages.c.page_id == page['page_id']))[0]['rental_id'] == original_parent
    assert len(store.rows(select(db.rental_orders))) == 4


def test_conflicting_page_cannot_overwrite_an_existing_parent_order_billing_address(hierarchy):
    _, store, _, _ = hierarchy
    page = store.rows(select(db.rental_pages))[0]
    before = store.rows(select(db.rental_orders).where(db.rental_orders.c.id == page['rental_id']))[0]
    altered = dict(page['fields'], address='999 Different Billing Address')
    with pytest.raises(ValueError, match='Conflicting billing address'):
        observe_rental_context(store, {}, page['page_id'], altered, altered['parent_order_number'])
    after = store.rows(select(db.rental_orders).where(db.rental_orders.c.id == page['rental_id']))[0]
    assert before == after


def test_present_shifted_page_is_not_treated_as_absent_and_manual_link_completes_order(hierarchy):
    client, store, records, sequence = hierarchy
    target = next(t for t in client.get('/api/workspaces/validation/tickets').json()['tickets'] if t['order_number'] == 'W-0001505')
    assert len(sequence) == 48 and all(len(r['pages']) == 6 for r in records)
    assert target['missing_pages'] == [6]
    assert target['candidate_summary']['6'] == {'possible': 1, 'different': 0}
    assert target['page_gap_status'] == 'unidentified_in_scan'
    assert target['pages_needing_upload'] == []
    image = target['unidentified_scan_pages'][0]
    assert image['fields']['order_number'] == 'W-0001505'
    assert image['fields']['parent_order_number'] == 'RO-0001003'
    assert image['fields']['page_number'] == 6
    # The provider saw only the rental order inside its crop; the work order is local evidence.
    assert image['identifier'] == 'RO-0001003'
    assert image['fields']['ocr_identifiers'] == {'rental_order': 'RO-0001003'}
    assert not image['review']['6']['blocked'] and not image['review']['6']['needs_acknowledgment']
    assert {c['key']: c['status'] for c in image['review']['6']['checks']} == dict.fromkeys(
        ['customer', 'address', 'parent_order_number', 'order_number', 'page_number', 'expected_pages'], 'match')
    response = client.post(f"/api/workspaces/validation/tickets/{target['id']}/page-approvals",
        json={'page_id': image['id'], 'printed_page': 6})
    assert response.status_code == 200
    updated = client.get(f"/api/workspaces/validation/tickets/{target['id']}").json()
    assert updated['download_ready'] and updated['verified_pages'] == 6
    assert store.counts()['orders'] == 8
    response = client.get(f"/api/workspaces/validation/tickets/{target['id']}/download?preview=true")
    with fitz.open(stream=response.content, filetype='pdf') as pdf:
        assert len(pdf) == 6 and 'Page 6/6' in pdf[-1].get_text()


def test_clean_batch_10_has_all_orders_and_all_identifiers_inside_the_crop(tmp_path):
    from ocr_workspace.intake_watcher import ProgressState
    pdf, records, sequence = create(tmp_path, rasterize=False, batch_number=10, clean=True)
    assert pdf.name == 'batch_10_ALL_CORRECT_8_orders.pdf'
    assert len(records) == 8 and len(sequence) == 48
    assert [r['order_id'] for r in records] == ['W-0001555', 'W-0001556', 'W-0001557', 'Shipment 00519',
                                                'W-0001558', 'W-0001559', 'W-0001560', 'Shipment 00520']
    assert [r['parent_order_number'] for r in records] == ['RO-0001037'] * 3 + ['SO-0001038'] + ['RO-0001039'] * 3 + ['SO-0001040']
    assert all(r['test_case'] == 'good' and not r['shifted_order_pages'] for r in records)
    with fitz.open(pdf) as source:
        responses = [ocr.parse_identifier(page.get_text(clip=fitz.Rect(306, 0, 612, 198))) for page in source]
    for record in records:
        assert {p['source_page'] for p in record['pages']} == set(range(1, 7))
        for page in record['pages']:
            assert page['expected_order_readable']
            parsed = responses[page['page'] - 1]
            assert parsed.value == record['order_id']
            assert parsed.identifiers == (
                dict(shipment=record['order_id'], sales_order=record['parent_order_number']) if record['order_type'] == 'SALE' else
                dict(work_order=record['order_id'], rental_order=record['parent_order_number']))
    response_iterator = iter(responses)
    store = db.Store(db.sqlite_url(tmp_path / 'clean.sqlite'))
    store.migrate()
    progress = ProgressState()
    worker = IntakeWatcher(store, pdf.parent, {checksum(pdf)}, lambda *a, **kw: next(response_iterator), root=tmp_path, progress=progress)
    worker.tick(submitted=pdf)
    assert progress.snapshot()['phase'] == 'ready'
    assert len(progress.snapshot()['ready_tickets']) == 8
    assert sorted(t['order_type'] for t in progress.snapshot()['ready_tickets']) == ['RENTAL'] * 6 + ['SALE'] * 2
    assert store.counts()['orders'] == 8
    assert sorted(r['rental_number'] for r in store.rows(select(db.rental_orders))) == [
        'RO-0001037', 'RO-0001039', 'SO-0001038', 'SO-0001040']
    assert len(store.rows(select(db.rental_tickets))) == 8
    assert all(row['status'] == 'success' for row in store.rows(select(db.attempts)))
    store.close()


def test_zip_summary_counts_only_current_scan_and_updates_after_manual_fix(hierarchy, tmp_path):
    from ocr_workspace.intake_watcher import prepare_ticket_pdfs
    client, store, _, _ = hierarchy
    document = store.rows(select(db.documents))[0]
    unrelated = dict(store.rows(select(db.orders))[0], id=db.uid(), order_number='W-9999999')
    with store.engine.begin() as connection:
        connection.execute(db.orders.insert().values(**unrelated))
    ready = prepare_ticket_pdfs(store, document['id'], tmp_path / 'Scans/output', allow_partial=True)
    assert len(ready) == 6
    progress = client.app.state.intake_progress
    progress.update('needs_attention', document_id=document['id'], file=Path(document['path']).name,
        total=48, completed=48, matched=46, ready_tickets=ready)
    snapshot = client.get('/api/workspaces/validation/progress').json()
    assert snapshot['download_summary'] == dict(total_orders=8, ready_orders=6, not_ready_orders=2,
        missing_pages=2, unidentified_pages=2, pending_pages=0)
    archive = client.get('/api/workspaces/validation/progress/tickets.zip', params={'revision': snapshot['revision']})
    with zipfile.ZipFile(io.BytesIO(archive.content)) as contents:
        assert len(contents.namelist()) == snapshot['download_summary']['ready_orders']
        # Every document is filed under its parent order: work orders under the RO, shipments under the SO.
        assert sorted(name.split('/')[0] for name in contents.namelist()) == [
            'RO-0001001', 'RO-0001001', 'RO-0001003', 'RO-0001003', 'SO-0001002', 'SO-0001004']
        assert all(name.split('/')[0] == name.split('__')[1] for name in contents.namelist())
        assert sorted(name.split('__')[2] for name in contents.namelist() if name.startswith('SO-')) == [
            'Shipment 00501', 'Shipment 00502']
    target = next(t for t in client.get('/api/workspaces/validation/tickets').json()['tickets'] if t['order_number'] == 'W-0001503')
    result = client.post(f"/api/workspaces/validation/tickets/{target['id']}/page-approvals",
        json={'page_id': target['unidentified_scan_pages'][0]['id'], 'printed_page': 1})
    assert result.status_code == 200
    summary = client.get('/api/workspaces/validation/progress').json()['download_summary']
    assert summary == dict(total_orders=8, ready_orders=7, not_ready_orders=1,
        missing_pages=1, unidentified_pages=1, pending_pages=0)


def test_saved_scan_zip_summary_survives_restart_without_provider_calls(hierarchy, tmp_path, monkeypatch):
    import sqlite3
    from ocr_workspace.intake_watcher import prepare_ticket_pdfs
    _, store, _, _ = hierarchy
    document = store.rows(select(db.documents))[0]
    prepare_ticket_pdfs(store, document['id'], tmp_path / 'Scans/output', allow_partial=True)
    runtime = tmp_path / 'demo_runtime'
    runtime.mkdir()
    with sqlite3.connect(tmp_path / 'workspace.sqlite') as source, sqlite3.connect(runtime / 'workspace.sqlite') as target:
        source.backup(target)
    monkeypatch.setenv('AZURE_DOC_INTEL_ENDPOINT', 'https://example.test')
    monkeypatch.setenv('AZURE_DOC_INTEL_KEY', 'fake-key')
    def unexpected_call(*args, **kwargs):
        raise AssertionError('Restoring existing results must not call OCR')
    monkeypatch.setattr(ocr, 'extract_order_identity', unexpected_call)
    with TestClient(create_app(root=tmp_path)) as client:
        snapshot = client.get('/api/workspaces/workspace/progress').json()
        assert snapshot['phase'] == 'needs_attention'
        assert snapshot['document_id'] == document['id']
        assert snapshot['download_summary']['ready_orders'] == len(snapshot['ready_tickets']) == 6
        assert snapshot['download_summary']['not_ready_orders'] == 2
        response = client.get('/api/workspaces/workspace/progress/tickets.zip', params={'revision': snapshot['revision']})
        assert response.status_code == 200
        with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
            assert len(archive.namelist()) == 6
    with sqlite3.connect(runtime / 'workspace.sqlite') as restored:
        assert restored.execute('select count(*) from ocr_attempts').fetchone()[0] == 48


def test_sample_refresh_creates_64_orders_across_rentals_and_sales_and_preserves_workspace(tmp_path):
    import json
    import pymupdf as fitz
    from scripts.create_rental_hierarchy_sample import create_batches

    database = tmp_path / 'demo_runtime/workspace.sqlite'
    database.parent.mkdir()
    database.write_bytes(b'existing database stays untouched')
    uploaded = tmp_path / 'Scans/incomming_scan/batch_01_uploaded-uuid.pdf'
    uploaded.parent.mkdir(parents=True)
    uploaded.write_bytes(b'uploaded source stays untouched')
    old = uploaded.parent / 'batch_01_8_orders.pdf'
    old.write_bytes(b'previous sample')
    manifest_path = tmp_path / 'Scans/manifest.json'
    manifest_path.write_text(json.dumps(dict(generator='ocr-synthetic-demo-v1', synthetic=True,
        tickets=[dict(order_id='W-991001', pdf='incomming_scan/batch_01_8_orders.pdf', pdf_sha256='a' * 64),
                 dict(order_id='W-991002', pdf='incomming_scan\\batch_01_8_orders.pdf', pdf_sha256='b' * 64)])))
    manifest, backup = create_batches(tmp_path, rasterize=False)
    main = [r for r in manifest['tickets'] if r.get('sample_role') == 'batch']
    assert len(main) == len({r['order_id'] for r in main}) == 64
    work_orders = [r for r in main if r['order_type'] == 'RENTAL']
    sales = [r for r in main if r['order_type'] == 'SALE']
    assert (len(work_orders), len(sales)) == (48, 16)
    assert all(re.fullmatch(r'W-\d{7}', r['order_id']) and re.fullmatch(r'RO-\d{7}', r['parent_order_number']) for r in work_orders)
    assert all(re.fullmatch(r'Shipment \d{5}', r['order_id']) and re.fullmatch(r'SO-\d{7}', r['parent_order_number']) for r in sales)
    parents = {}
    for record in main:
        parents.setdefault(record['parent_order_number'], []).append(record['order_id'])
    assert sum(number.startswith('RO-') for number in parents) == sum(number.startswith('SO-') for number in parents) == 16
    assert all(len(children) == (3 if number.startswith('RO-') else 1) for number, children in parents.items())
    # RO and SO numbers come from one shared count; work orders and shipments each have their own.
    assert sorted(int(number.split('-')[1]) for number in parents) == list(range(1001, 1033))
    assert sorted(int(r['order_id'].split('-')[1]) for r in work_orders) == list(range(1501, 1549))
    assert sorted(int(r['order_id'].split()[1]) for r in sales) == list(range(501, 517))
    assert all('shipment' not in r and 'parent_rental_number' not in r for r in main)
    assert sum(r['test_case'] == 'good' for r in main) == 48
    assert manifest['count'] == 64 and manifest['total_pages'] == 384
    assert not list((tmp_path / 'Scans/recovery_pages').glob('*.pdf'))
    assert database.read_bytes() == b'existing database stays untouched'
    assert uploaded.read_bytes() == b'uploaded source stays untouched'
    assert (backup / 'incomming_scan/batch_01_8_orders.pdf').read_bytes() == b'previous sample'
    assert 'a' * 64 in manifest['legacy_allowed_hashes']
    assert 'b' * 64 in manifest['legacy_allowed_hashes']
    assert all('\\' not in t['pdf'] for t in manifest['tickets'])
    assert sum(t.get('sample_role') == 'alias' for t in manifest['tickets']) == 8
    first = tmp_path / 'Scans/incomming_scan/batch_01_8_orders.pdf'
    assert first.read_bytes() == (first.parent / 'rental_and_sales_orders_shuffled.pdf').read_bytes()
    assert not (first.parent / 'rental_orders_RO_OD_SO_shuffled.pdf').exists()
    with fitz.open(first) as pdf:
        assert len(pdf) == 48
        crop_misses = 0
        for record in main[:8]:
            sale = record['order_type'] == 'SALE'
            assert {p['source_page'] for p in record['pages']} == set(range(1, 7))
            for page in record['pages']:
                image = pdf[page['page'] - 1]
                full = image.get_text()
                crop = image.get_text(clip=fitz.Rect(306, 0, 612, 198))
                assert not re.search(r'\b(?:OD|TK|RA|CO|PO|WO)-\d', full)
                assert ('SALES ORDER' if sale else 'RENTAL ORDER') in crop
                parsed = ocr.parse_identifier(crop)
                assert not ocr.mixed_families(ocr.parse_document_identifiers(full))
                if sale:
                    # A sales page prints its sales order and its shipment, never a rental or work order number.
                    assert page['expected_order_readable']
                    assert f"Shipment No. {record['order_id'].split()[1]}" in full
                    assert (parsed.kind, parsed.value) == ('shipment', record['order_id'])
                    assert parsed.identifiers == {'sales_order': record['parent_order_number'], 'shipment': record['order_id']}
                    assert 'RO-' not in full and not re.search(r'\bW-\d', full)
                    continue
                assert record['order_id'] in full
                assert 'SO-' not in full and 'Shipment' not in full
                assert parsed.identifiers['rental_order'] == record['parent_order_number']
                assert crop.index('Rental Order No.') < full.index('Work Order No.')
                if page['expected_order_readable']:
                    assert parsed.identifiers == {'rental_order': record['parent_order_number'], 'work_order': record['order_id']}
                else:
                    crop_misses += 1
                    assert parsed.kind == 'rental_order' and 'work_order' not in parsed.identifiers
        assert crop_misses == 2
