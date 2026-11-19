"""Manual page assignment must complete real PDFs without rewriting OCR evidence."""
import io
import zipfile

import pymupdf as fitz
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from ocr_workspace import ocr, storage as db
from ocr_workspace.etl import checksum
from ocr_workspace.intake_watcher import IntakeWatcher
from ocr_workspace.processing import register_pdf
from ocr_workspace.web_api import create_app
from scripts.create_demo_data import generate_dataset


@pytest.fixture
def repair_workspace(tmp_path):
    data = tmp_path / 'demo_data'
    manifest = generate_dataset(data, count=1, min_pages=6, max_pages=6, rasterize=False)
    source = data / manifest['tickets'][0]['pdf']
    with fitz.open(source) as pdf:
        page = pdf[5]
        page.add_redact_annot(fitz.Rect(306, 0, 612, 198), fill=(1, 1, 1))
        page.apply_redactions()
        # The header is illegible: no rental or work order number can be read from this page.
        page.insert_text((334, 47), 'RENTAL ORDER', fontsize=11)
        changed = source.with_suffix('.part')
        pdf.save(changed)
    changed.replace(source)
    incoming = tmp_path / 'Scans/incomming_scan'
    incoming.mkdir(parents=True)
    scan = incoming / 'mixed.pdf'
    with fitz.open() as pdf, fitz.open(source) as original:
        for page in [1, 3, 5, 0, 4, 2]:
            pdf.insert_pdf(original, from_page=page, to_page=page)
        pdf.save(scan)
    database = tmp_path / 'workspace.sqlite'
    store = db.Store(db.sqlite_url(database))
    store.migrate()
    good = 'RENTAL ORDER Rental Order No. RO-0000001 Work Order No. W-0000001'
    # The provider misreads the smudged header of the third scanned image as another work order.
    values = iter([good, good, 'RENTAL ORDER Work Order No. W-88888888', good, good, good])
    calls = []

    def extract(*args, **kwargs):
        calls.append(1)
        return ocr.parse_identifier(next(values))

    worker = IntakeWatcher(store, incoming, {checksum(scan)}, extract, root=tmp_path)
    worker.tick(submitted=scan)
    assert len(calls) == 6
    app = create_app(root=tmp_path, databases={'validation': database}, allowed_roots=[tmp_path])
    with TestClient(app) as client:
        tickets = client.get('/api/workspaces/validation/tickets').json()['tickets']
        assert len(tickets) == 1
        ticket = tickets[0]
        assert (ticket['order_number'], ticket['order_type'], ticket['parent_order_number']) == ('W-0000001', 'RENTAL', 'RO-0000001')
        assert ticket['unaccounted_pages'] == [6]
        candidate = ticket['unidentified_scan_pages'][0]
        assert candidate['source_page'] == 3
        yield client, store, ticket, candidate, app, scan, calls
    store.close()


def test_approval_completes_download_zip_and_preserves_original_ocr(repair_workspace):
    client, store, ticket, candidate, app, scan, calls = repair_workspace
    url = f"/api/workspaces/validation/tickets/{ticket['id']}/page-approvals"
    payload = {'page_id': candidate['id'], 'printed_page': 6, 'acknowledge_differences': True}
    original_checksum = checksum(scan)
    original_attempt = store.rows(select(db.attempts).where(db.attempts.c.page_id == candidate['id']))[0]
    response = client.post(url, json=payload)
    assert response.status_code == 200, response.text
    fixed = response.json()['ticket']
    assert fixed['download_ready'] is True
    assert fixed['verified_pages'] == 6
    assert fixed['ocr_verified_pages'] == 5
    assert fixed['manually_approved_pages'] == 1
    assert fixed['unaccounted_pages'] == []
    approval = store.rows(select(db.page_approvals))[0]
    assert approval['attempt_id'] == original_attempt['id']
    assert approval['approved_by'] == 'local_user'
    assert approval['approved_at'] is not None
    assert store.rows(select(db.attempts).where(db.attempts.c.id == original_attempt['id']))[0] == original_attempt
    assert checksum(scan) == original_checksum
    assert len(calls) == 6  # Approval makes no new provider calls.
    detail = client.get(f"/api/workspaces/validation/tickets/{ticket['id']}").json()
    assert [p['printed_page'] for p in detail['pages']] == [1, 2, 3, 4, 5, 6]
    manual = detail['pages'][-1]
    assert manual['manually_approved'] and manual['accepted']
    assert not manual['matched']
    assert manual['extracted'] == 'W-88888888' and manual['ocr_status'] == 'no_match'
    assert manual['error_code'] == 'document_fields_incomplete_or_conflicting'
    pdf = client.get(f"/api/workspaces/validation/tickets/{ticket['id']}/download")
    assert pdf.status_code == 200
    with fitz.open(stream=pdf.content, filetype='pdf') as compiled:
        assert len(compiled) == 6
        assert 'W-0000001' not in compiled[-1].get_text()  # The approved image is the unreadable one.
        assert all('W-0000001' in page.get_text() for page in list(compiled)[:5])
        assert all(f'Page {n}/6' in page.get_text() for n, page in enumerate(compiled, 1))
    activity = client.get('/api/workspaces/validation/activity?issues_only=true').json()
    assert activity['activity'] == []
    assert activity['counts']['manually_approved'] == 1
    assert activity['current_scan']['completed'] == 6
    snapshot = app.state.intake_progress.snapshot()
    assert snapshot['phase'] == 'ready'
    archive = client.get('/api/workspaces/validation/progress/tickets.zip', params={'revision': snapshot['revision']})
    assert archive.status_code == 200
    with zipfile.ZipFile(io.BytesIO(archive.content)) as z:
        assert z.namelist() == ['RO-0000001/Amber Workshop__RO-0000001__W-0000001__100 Simulation Way, Demo City, ZZ 00000.pdf']
        with fitz.open(stream=z.read(z.namelist()[0]), filetype='pdf') as compiled:
            assert len(compiled) == 6
    assert client.post(url, json=payload).status_code == 200
    assert len(store.rows(select(db.page_approvals))) == 1
    assert len(client.get(f"/api/workspaces/validation/tickets/{ticket['id']}").json()['pages']) == 6
    restarted = create_app(root=scan.parents[2], databases={'validation': store.engine.url.database}, allowed_roots=[scan.parents[2]])
    with TestClient(restarted) as fresh:
        assert fresh.get(f"/api/workspaces/validation/tickets/{ticket['id']}").json()['download_ready']


@pytest.mark.parametrize('failure', ['occupied_slot', 'out_of_range', 'matched_image', 'foreign_scan', 'cross_origin', 'invalid_number', 'processing', 'source_changed'])
def test_invalid_assignments_do_not_mutate_orders(repair_workspace, failure, tmp_path):
    client, store, ticket, candidate, _, _, _ = repair_workspace
    payload = {'page_id': candidate['id'], 'printed_page': 6}
    headers = {}
    if failure == 'occupied_slot':
        payload['printed_page'] = 1
    if failure == 'out_of_range':
        payload['printed_page'] = 7
    if failure == 'invalid_number':
        payload['printed_page'] = 0
    if failure == 'matched_image':
        payload['page_id'] = client.get(f"/api/workspaces/validation/tickets/{ticket['id']}").json()['pages'][0]['id']
    if failure == 'foreign_scan':
        foreign = tmp_path / 'another.pdf'
        with fitz.open() as pdf:
            pdf.new_page().insert_text((40, 40), 'Another source scan')
            pdf.save(foreign)
        document_id = register_pdf(store, foreign, synthetic=True)
        payload['page_id'] = store.rows(select(db.pages.c.id).where(db.pages.c.document_id == document_id))[0]['id']
    if failure == 'cross_origin':
        headers['Origin'] = 'https://untrusted.example'
    if failure == 'processing':
        with store.engine.begin() as connection:
            page_id = connection.scalar(select(db.attempts.c.page_id).where(db.attempts.c.status == 'success').limit(1))
            connection.execute(db.attempts.update().where(db.attempts.c.page_id == page_id).values(status='running'))
    if failure == 'source_changed':
        from pathlib import Path
        path = store.rows(select(db.documents.c.path).select_from(db.pages.join(db.documents)).where(db.pages.c.id == candidate['id']))[0]['path']
        with Path(path).open('ab') as source:
            source.write(b'changed')
    result = client.post(f"/api/workspaces/validation/tickets/{ticket['id']}/page-approvals", json=payload, headers=headers)
    assert result.status_code == (403 if failure == 'cross_origin' else 422 if failure == 'invalid_number' else 409), result.text
    assert store.rows(select(db.page_approvals)) == []
    assert not client.get(f"/api/workspaces/validation/tickets/{ticket['id']}").json()['download_ready']


def test_approved_image_cannot_be_reassigned_to_a_different_page(repair_workspace):
    client, store, ticket, candidate, _, _, _ = repair_workspace
    url = f"/api/workspaces/validation/tickets/{ticket['id']}/page-approvals"
    assert client.post(url, json={'page_id': candidate['id'], 'printed_page': 6, 'acknowledge_differences': True}).status_code == 200
    assert client.post(url, json={'page_id': candidate['id'], 'printed_page': 5}).status_code == 409
    assert store.rows(select(db.page_approvals))[0]['printed_page'] == 6


def test_misread_order_number_requires_explicit_acknowledgment(repair_workspace):
    client, store, ticket, candidate, _, _, _ = repair_workspace
    url = f"/api/workspaces/validation/tickets/{ticket['id']}/page-approvals"
    current = client.get(f"/api/workspaces/validation/tickets/{ticket['id']}").json()
    review = current['unidentified_scan_pages'][0]['review']['6']
    assert review['blocked'] is False and review['needs_acknowledgment'] is True
    assert review['differences'] == ['Work order OCR']
    assert [c['key'] for c in review['checks']] == [
        'customer', 'address', 'parent_order_number', 'order_number', 'page_number', 'expected_pages']
    statuses = {c['key']: c['status'] for c in review['checks']}
    assert statuses == dict(customer='match', address='match', parent_order_number='not_read',
                            order_number='not_read', page_number='match', expected_pages='match')
    assert [c['label'] for c in review['checks']] == ['Customer', 'Address', 'Order', 'Work order', 'Printed page', 'Page total']
    assert review['identified'] is True and review['conflicts'] == []
    order_check = next(c for c in review['checks'] if c['key'] == 'order_number')
    assert (order_check['expected'], order_check['ocr_found'], order_check['ocr_differs']) == ('W-0000001', 'W-88888888', True)
    assert client.post(url, json={'page_id': candidate['id'], 'printed_page': 6}).status_code == 409
    assert store.rows(select(db.page_approvals)) == []
    assert client.post(url, json={'page_id': candidate['id'], 'printed_page': 6, 'acknowledge_differences': True}).status_code == 200
    assert 'differences explicitly acknowledged' in store.rows(select(db.page_approvals))[0]['note']


@pytest.mark.parametrize('field,value', [('customer', 'Another customer'), ('address', '999 Other Street'),
    ('order_number', 'W-9999999'), ('order_number', 'Shipment 00001'), ('order_number', 'WO-990001'),
    ('parent_order_number', 'RO-9999999'), ('parent_order_number', 'SO-0000001'),
    ('page_number', 1), ('expected_pages', 12)])
def test_conflicting_identity_or_page_cannot_be_overridden(repair_workspace, field, value):
    client, store, ticket, candidate, _, _, _ = repair_workspace
    fields = dict(store.rows(select(db.page_extractions).where(db.page_extractions.c.page_id == candidate['id']))[0]['fields'])
    fields[field] = value
    with store.engine.begin() as connection:
        connection.execute(db.page_extractions.update().where(db.page_extractions.c.page_id == candidate['id']).values(fields=fields))
    detail = client.get(f"/api/workspaces/validation/tickets/{ticket['id']}").json()
    review = detail['unidentified_scan_pages'][0]['review']['6']
    assert review['blocked'] is True
    # Every differing check blocks; nothing else on the page does.
    assert [c['key'] for c in review['checks'] if c['blocking']] == [field]
    assert [c['key'] for c in review['checks'] if c['status'] == 'different'] == [field]
    response = client.post(f"/api/workspaces/validation/tickets/{ticket['id']}/page-approvals",
        json={'page_id': candidate['id'], 'printed_page': 6, 'acknowledge_differences': True})
    assert response.status_code == 409
    assert store.rows(select(db.page_approvals)) == []


@pytest.mark.parametrize('printed', [
    dict(order_number='W-0000001', parent_order_number='SO-0000002'),
    dict(order_number='Shipment 00001', parent_order_number='RO-0000001'),
    dict(order_number='W-0000001', parent_order_number='RO-0000001'),
], ids=['work_order_under_a_sales_order', 'shipment_under_the_rental_order', 'matching_numbers_beside_a_sales_number'])
def test_page_printing_rental_and_sales_numbers_together_cannot_be_approved(repair_workspace, printed):
    client, store, ticket, candidate, _, _, _ = repair_workspace
    fields = dict(store.rows(select(db.page_extractions).where(db.page_extractions.c.page_id == candidate['id']))[0]['fields'])
    fields.update(printed, mixed_order_types=True)
    with store.engine.begin() as connection:
        connection.execute(db.page_extractions.update().where(db.page_extractions.c.page_id == candidate['id']).values(fields=fields))
    detail = client.get(f"/api/workspaces/validation/tickets/{ticket['id']}").json()
    review = detail['unidentified_scan_pages'][0]['review']['6']
    assert review['blocked'] is True
    assert review['conflicts'][-1] == 'Rental and sales numbers on one page'
    assert detail['candidate_summary']['6'] == {'possible': 0, 'different': 1}
    response = client.post(f"/api/workspaces/validation/tickets/{ticket['id']}/page-approvals",
        json={'page_id': candidate['id'], 'printed_page': 6, 'acknowledge_differences': True})
    assert response.status_code == 409 and 'Rental and sales numbers on one page' in response.json()['detail']
    assert store.rows(select(db.page_approvals)) == []


def test_migration_adds_approvals_without_changing_existing_scan_data(repair_workspace):
    _, store, _, _, _, _, _ = repair_workspace
    before = store.counts()
    with store.engine.begin() as connection:
        db.page_approvals.drop(connection)
        connection.execute(db.versions.delete().where(db.versions.c.version >= 2))
    store.migrate()
    store.migrate()
    assert store.counts() == before
    assert store.rows(select(db.page_approvals)) == []
    assert [r['version'] for r in store.rows(select(db.versions).order_by(db.versions.c.version))] == [1, 2, 3, 4, 5, 6, 7]


def test_upgrade_from_schema_version_2_preserves_approvals_and_drops_the_shipment_column(repair_workspace):
    from sqlalchemy.exc import IntegrityError

    client, store, ticket, candidate, _, _, _ = repair_workspace
    assert client.post(f"/api/workspaces/validation/tickets/{ticket['id']}/page-approvals",
        json={'page_id': candidate['id'], 'printed_page': 6, 'acknowledge_differences': True}).status_code == 200
    before = store.counts()
    approvals = store.rows(select(db.page_approvals))
    attempts = store.rows(select(db.attempts))
    orders = store.rows(select(db.orders))
    # Recreate the v2 shape on a populated, approved workspace: orders carried a
    # shipment number that had to be unique, and no rental hierarchy existed yet.
    with store.engine.begin() as connection:
        for table in (db.downloads, db.page_extractions, db.rental_pages, db.rental_tickets, db.rental_orders):
            table.drop(connection)
        connection.exec_driver_sql('ALTER TABLE orders ADD COLUMN shipment_number VARCHAR(80)')
        connection.exec_driver_sql("UPDATE orders SET shipment_number = '900001'")
        connection.exec_driver_sql('CREATE UNIQUE INDEX legacy_shipment_unique ON orders (source_system, shipment_number)')
        connection.execute(db.versions.delete().where(db.versions.c.version >= 3))
    store.migrate()
    store.migrate()
    assert [r['version'] for r in store.rows(select(db.versions).order_by(db.versions.c.version))] == [1, 2, 3, 4, 5, 6, 7]
    assert store.counts() == before
    assert store.rows(select(db.page_approvals)) == approvals
    assert store.rows(select(db.attempts)) == attempts
    assert store.rows(select(db.orders)) == orders
    with store.engine.connect() as connection:
        assert connection.exec_driver_sql('PRAGMA foreign_keys').scalar() == 1
        assert connection.exec_driver_sql('PRAGMA foreign_key_check').all() == []
        assert [r[1] for r in connection.exec_driver_sql('PRAGMA table_info(orders)')] == [c.name for c in db.orders.columns]
        assert 'legacy_shipment_unique' not in [r[1] for r in connection.exec_driver_sql('PRAGMA index_list(orders)')]
    # An order is identified by its one number: another work order is accepted, a repeated number is not.
    sibling = dict(orders[0], id=db.uid(), order_number='W-9999999')
    with store.engine.begin() as connection:
        connection.execute(db.orders.insert().values(**sibling))
    assert store.counts()['orders'] == before['orders'] + 1
    with pytest.raises(IntegrityError), store.engine.begin() as connection:
        connection.execute(db.orders.insert().values(**dict(sibling, id=db.uid())))
    assert client.get(f"/api/workspaces/validation/tickets/{ticket['id']}").json()['download_ready'] is True


def test_pdf_preparation_failure_can_retry_without_duplicate_approval(repair_workspace, monkeypatch):
    from ocr_workspace import intake_watcher
    client, store, ticket, candidate, _, _, _ = repair_workspace
    prepare = intake_watcher.prepare_ticket_pdfs
    calls = []

    def fail_once(*args, **kwargs):
        calls.append(1)
        if len(calls) == 1:
            raise OSError('simulated output failure')
        return prepare(*args, **kwargs)

    monkeypatch.setattr(intake_watcher, 'prepare_ticket_pdfs', fail_once)
    url = f"/api/workspaces/validation/tickets/{ticket['id']}/page-approvals"
    payload = {'page_id': candidate['id'], 'printed_page': 6, 'acknowledge_differences': True}
    first = client.post(url, json=payload)
    assert first.status_code == 503
    assert 'approval was saved' in first.json()['detail']
    assert len(store.rows(select(db.page_approvals))) == 1
    assert client.post(url, json=payload).status_code == 200
    assert len(store.rows(select(db.page_approvals))) == 1
