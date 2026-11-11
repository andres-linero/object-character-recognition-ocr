"""Manual page assignment must complete real PDFs without rewriting OCR evidence."""
import io
import zipfile

import fitz
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from ADK_Agentic import ocr, storage as db
from ADK_Agentic.etl import checksum
from ADK_Agentic.intake_watcher import IntakeWatcher
from ADK_Agentic.processing import register_pdf
from ADK_Agentic.web_api import create_app
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
        page.insert_text((334, 47), 'Delivery Ticket / Shipment', fontsize=11)
        page.insert_text((334, 70), 'Shipment No. 88888888', fontsize=16)
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
    values = iter(['900001', '900001', '88888888', '900001', '900001', '900001'])
    calls = []

    def extract(*args, **kwargs):
        calls.append(1)
        return ocr.ParsedIdentifier('shipment', next(values))

    worker = IntakeWatcher(store, incoming, {checksum(scan)}, extract, root=tmp_path)
    worker.tick(submitted=scan)
    assert len(calls) == 6
    app = create_app(root=tmp_path, databases={'validation': database}, allowed_roots=[tmp_path])
    with TestClient(app) as client:
        ticket = client.get('/api/workspaces/validation/tickets').json()['tickets'][0]
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
    assert manual['extracted'] == '88888888' and manual['ocr_status'] == 'no_match'
    pdf = client.get(f"/api/workspaces/validation/tickets/{ticket['id']}/download")
    assert pdf.status_code == 200
    with fitz.open(stream=pdf.content, filetype='pdf') as compiled:
        assert len(compiled) == 6
        assert '88888888' in compiled[-1].get_text()
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
        assert len(z.namelist()) == 1
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


def test_shipment_difference_requires_explicit_acknowledgment(repair_workspace):
    client, store, ticket, candidate, _, _, _ = repair_workspace
    url = f"/api/workspaces/validation/tickets/{ticket['id']}/page-approvals"
    current = client.get(f"/api/workspaces/validation/tickets/{ticket['id']}").json()
    review = current['unidentified_scan_pages'][0]['review']['6']
    assert review['blocked'] is False and review['needs_acknowledgment'] is True
    assert review['differences'] == ['Shipment / SO']
    assert client.post(url, json={'page_id': candidate['id'], 'printed_page': 6}).status_code == 409
    assert store.rows(select(db.page_approvals)) == []
    assert client.post(url, json={'page_id': candidate['id'], 'printed_page': 6, 'acknowledge_differences': True}).status_code == 200
    assert 'differences explicitly acknowledged' in store.rows(select(db.page_approvals))[0]['note']


@pytest.mark.parametrize('field,value', [('customer', 'Another customer'), ('address', '999 Other Street'),
    ('work_order', 'TK-999999'), ('parent_rental_number', 'RO-999999'), ('rental_order', 'RA-999999'),
    ('page_number', 1), ('expected_pages', 12)])
def test_conflicting_identity_or_page_cannot_be_overridden(repair_workspace, field, value):
    client, store, ticket, candidate, _, _, _ = repair_workspace
    fields = dict(store.rows(select(db.page_extractions).where(db.page_extractions.c.page_id == candidate['id']))[0]['fields'])
    fields[field] = value
    # Add a known parent to the target when testing a conflicting RO.
    if field == 'parent_rental_number':
        from ADK_Agentic.etl import upsert
        with store.engine.begin() as connection:
            customer = connection.scalar(select(db.orders.c.customer_id).where(db.orders.c.id == ticket['id']))
            parent = upsert(connection, db.rental_orders, ['source_system', 'customer_id', 'rental_number'], dict(source_system='documents', customer_id=customer, rental_number='RO-810001', address=''))
            upsert(connection, db.rental_tickets, ['order_id'], dict(order_id=ticket['id'], rental_id=parent))
            upsert(connection, db.rental_pages, ['page_id'], dict(page_id=candidate['id'], rental_id=parent,
                attempt_id=store.rows(select(db.attempts.c.id).where(db.attempts.c.page_id == candidate['id']))[0]['id'], fields=fields))
    with store.engine.begin() as connection:
        connection.execute(db.page_extractions.update().where(db.page_extractions.c.page_id == candidate['id']).values(fields=fields))
    detail = client.get(f"/api/workspaces/validation/tickets/{ticket['id']}").json()
    assert detail['unidentified_scan_pages'][0]['review']['6']['blocked'] is True
    response = client.post(f"/api/workspaces/validation/tickets/{ticket['id']}/page-approvals",
        json={'page_id': candidate['id'], 'printed_page': 6, 'acknowledge_differences': True})
    assert response.status_code == 409
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
    assert [r['version'] for r in store.rows(select(db.versions).order_by(db.versions.c.version))] == [1, 2, 3, 4, 5]


def test_legacy_agreement_number_maps_to_one_ro_without_changing_page_history(repair_workspace):
    from scripts.link_existing_rental_numbers import link_existing

    client, store, ticket, candidate, _, _, _ = repair_workspace
    route = f"/api/workspaces/validation/tickets/{ticket['id']}"
    assert client.post(route + '/page-approvals', json={'page_id': candidate['id'], 'printed_page': 6,
        'acknowledge_differences': True}).status_code == 200
    assert client.get(route + '/download').status_code == 200
    before = store.counts()
    history = {table.name: store.rows(select(table)) for table in (db.attempts, db.page_approvals, db.downloads)}
    with store.engine.begin() as connection:
        for table in (db.rental_pages, db.rental_tickets, db.rental_orders):
            connection.execute(table.delete())
    assert link_existing(store) == link_existing(store) == 1
    assert len(store.rows(select(db.rental_orders))) == 1
    detail = client.get(route).json()
    assert detail['rental_order'] == detail['parent_rental_number'] == 'RO-700001'
    assert detail['downloaded'] is True and detail['download_ready'] is True
    assert store.counts() == before
    for table in (db.attempts, db.page_approvals, db.downloads):
        assert store.rows(select(table)) == history[table.name]


def test_ro_migration_preserves_approvals_and_allows_shared_shipments(repair_workspace):
    from sqlalchemy.exc import IntegrityError

    client, store, ticket, candidate, _, _, _ = repair_workspace
    assert client.post(f"/api/workspaces/validation/tickets/{ticket['id']}/page-approvals",
        json={'page_id': candidate['id'], 'printed_page': 6, 'acknowledge_differences': True}).status_code == 200
    before = store.counts()
    approvals = store.rows(select(db.page_approvals))
    attempts = store.rows(select(db.attempts))
    # Recreate the v2 uniqueness rule on a populated, approved workspace.
    with store.engine.begin() as connection:
        for table in (db.downloads, db.page_extractions, db.rental_pages, db.rental_tickets, db.rental_orders):
            table.drop(connection)
        connection.exec_driver_sql('CREATE UNIQUE INDEX legacy_shipment_unique ON orders (source_system, shipment_number)')
        connection.execute(db.versions.delete().where(db.versions.c.version >= 3))
    store.migrate()
    store.migrate()
    assert store.counts() == before
    assert store.rows(select(db.page_approvals)) == approvals
    assert store.rows(select(db.attempts)) == attempts
    with store.engine.connect() as connection:
        assert connection.exec_driver_sql('PRAGMA foreign_keys').scalar() == 1
        assert connection.exec_driver_sql('PRAGMA foreign_key_check').all() == []
    sibling = dict(store.rows(select(db.orders))[0], id=db.uid(), order_number='TK-999999')
    with store.engine.begin() as connection:
        connection.execute(db.orders.insert().values(**sibling))
    assert store.counts()['orders'] == before['orders'] + 1
    with pytest.raises(IntegrityError), store.engine.begin() as connection:
        connection.execute(db.orders.insert().values(**dict(sibling, id=db.uid())))


def test_pdf_preparation_failure_can_retry_without_duplicate_approval(repair_workspace, monkeypatch):
    from ADK_Agentic import intake_watcher
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
