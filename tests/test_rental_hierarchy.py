"""RO groups distinct OD orders and SO shipments; cropped OD values require review."""
import io
from pathlib import Path
import fitz
import zipfile

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from ADK_Agentic import ocr, storage as db
from ADK_Agentic.document_data import observe_rental_context
from ADK_Agentic.etl import checksum
from ADK_Agentic.intake_watcher import IntakeWatcher
from ADK_Agentic.processing import register_pdf, process_page
from ADK_Agentic.web_api import create_app
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


def test_ro_groups_multiple_tickets_and_shared_shipments(hierarchy):
    client, store, _, _ = hierarchy
    parents = client.get('/api/workspaces/validation/rental-orders').json()['rental_orders']
    assert len(parents) == 2
    assert len({p['customer'] for p in parents}) == 1  # One customer can own multiple ROs.
    assert {p['rental_number'] for p in parents} == {'RO-810001', 'RO-810002'}
    assert all(p['ticket_count'] == 4 for p in parents)
    assert sorted(p['unassigned_pages'] for p in parents) == [1, 1]
    assert sorted(p['ready_tickets'] for p in parents) == [3, 3]
    for parent in parents:
        assert len({t['shipment'] for t in parent['tickets']}) == 2
        assert len({t['ticket_number'] for t in parent['tickets']}) == 4
        assert all(t['rental_id'] == parent['id'] and t['parent_rental_number'] == parent['rental_number'] for t in parent['tickets'])
    assert store.counts()['orders'] == 8
    assert len(store.rows(select(db.rental_pages))) == 48
    flags = client.get('/api/workspaces/validation/activity?issues_only=true').json()['activity']
    assert len(flags) == 2
    assert {p['error_code'] for p in flags} == {'order_number_not_read'}
    assert sum(bool(p['rental_id']) for p in flags) == 2


def test_document_order_and_due_dates_reach_the_tracker(hierarchy):
    client, _, records, _ = hierarchy
    rows = {t['work_order']: t for t in client.get('/api/workspaces/validation/tickets').json()['tickets']}
    for record in records:
        assert rows[record['order_id']]['order_date'] == record['order_date']
        assert rows[record['order_id']]['due_date'] == record['deadline']


def test_only_ro_is_retained_without_inventing_a_ticket(tmp_path):
    pdf, records, sequence = create(tmp_path, rasterize=False)
    store = db.Store(db.sqlite_url(tmp_path / 'workspace.sqlite'))
    store.migrate()
    document_id = register_pdf(store, pdf, synthetic=True)
    position = next(n for n, (index, page, *_rest) in enumerate(sequence, 1) if index == 2 and page == 0)
    page_id = store.rows(select(db.pages.c.id).where(db.pages.c.document_id == document_id, db.pages.c.page_number == position))[0]['id']
    result = process_page(store, page_id, extractor=lambda *a, **k: ocr.ParsedIdentifier('rental_order', 'RO-810001'), document_driven=True)
    assert result['status'] == 'no_match' and result['error_code'] == 'order_number_not_read'
    assert store.counts()['orders'] == 0
    assert len(store.rows(select(db.rental_orders))) == 1
    assert len(store.rows(select(db.rental_pages))) == 1
    with TestClient(create_app(root=tmp_path, databases={'validation': tmp_path / 'workspace.sqlite'}, allowed_roots=[tmp_path])) as client:
        parent = client.get('/api/workspaces/validation/rental-orders').json()['rental_orders'][0]
        assert parent['rental_number'] == 'RO-810001'
        assert parent['ticket_count'] == 0 and parent['unassigned_pages'] == 1
    store.close()


def test_page_fixer_is_scoped_to_ro_not_just_shared_source_pdf(hierarchy):
    client, store, _, _ = hierarchy
    tickets = client.get('/api/workspaces/validation/tickets').json()['tickets']
    target = next(t for t in tickets if t['ticket_number'] == 'OD-992003')
    other = next(t for t in tickets if t['ticket_number'] == 'OD-992006')
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
    parents = client.get('/api/workspaces/validation/rental-orders').json()['rental_orders']
    parent = next(p for p in parents if p['id'] == target['rental_id'])
    assert parent['ready_tickets'] == 4 and parent['unassigned_pages'] == 0
    archive = client.get(f"/api/workspaces/validation/rental-orders/{parent['id']}/download.zip")
    assert archive.status_code == 200
    with zipfile.ZipFile(io.BytesIO(archive.content)) as z:
        assert len(z.namelist()) == 4
        assert all('RO-810001' in name and 'OD-' in name for name in z.namelist())
    receipts = store.rows(select(db.downloads))
    assert len(receipts) == 4 and all(r['kind'] == 'rental_zip' for r in receipts)
    rows = client.get('/api/workspaces/validation/tickets').json()['tickets']
    assert all(t['downloaded'] for t in rows if t['rental_id'] == target['rental_id'])
    assert not any(t['downloaded'] for t in rows if t['rental_id'] == other['rental_id'])


def test_confirmed_page_cannot_silently_move_to_another_ro(hierarchy):
    _, store, _, _ = hierarchy
    page = store.rows(select(db.rental_pages))[0]
    original_parent = page['rental_id']
    altered = dict(page['fields'], parent_rental_number='RO-999999')
    with pytest.raises(ValueError, match='Conflicting rental order'):
        observe_rental_context(store, {}, page['page_id'], altered, 'RO-999999')
    assert store.rows(select(db.rental_pages.c.rental_id).where(db.rental_pages.c.page_id == page['page_id']))[0]['rental_id'] == original_parent
    assert len(store.rows(select(db.rental_orders))) == 2


def test_conflicting_page_cannot_overwrite_an_existing_ro_billing_address(hierarchy):
    _, store, _, _ = hierarchy
    page = store.rows(select(db.rental_pages))[0]
    before = store.rows(select(db.rental_orders).where(db.rental_orders.c.id == page['rental_id']))[0]
    altered = dict(page['fields'], address='999 Different Billing Address')
    with pytest.raises(ValueError, match='Conflicting billing address'):
        observe_rental_context(store, {}, page['page_id'], altered, altered['parent_rental_number'])
    after = store.rows(select(db.rental_orders).where(db.rental_orders.c.id == page['rental_id']))[0]
    assert before == after


def test_present_shifted_page_is_not_treated_as_absent_and_manual_link_completes_order(hierarchy):
    client, store, records, sequence = hierarchy
    target = next(t for t in client.get('/api/workspaces/validation/tickets').json()['tickets'] if t['ticket_number'] == 'OD-992006')
    assert len(sequence) == 48 and all(len(r['pages']) == 6 for r in records)
    assert target['missing_pages'] == [6]
    assert target['candidate_summary']['6'] == {'possible': 1, 'different': 0}
    assert target['page_gap_status'] == 'unidentified_in_scan'
    assert target['pages_needing_upload'] == []
    image = target['unidentified_scan_pages'][0]
    assert image['fields']['work_order'] == 'OD-992006'
    assert image['fields']['page_number'] == 6
    assert image['fields']['ocr_identifiers'] == {'rental_order': 'RO-810002', 'shipment': '904003'}
    assert not image['review']['6']['blocked']
    response = client.post(f"/api/workspaces/validation/tickets/{target['id']}/page-approvals",
        json={'page_id': image['id'], 'printed_page': 6})
    assert response.status_code == 200
    updated = client.get(f"/api/workspaces/validation/tickets/{target['id']}").json()
    assert updated['download_ready'] and updated['verified_pages'] == 6
    assert store.counts()['orders'] == 8
    response = client.get(f"/api/workspaces/validation/tickets/{target['id']}/download?preview=true")
    with fitz.open(stream=response.content, filetype='pdf') as pdf:
        assert len(pdf) == 6 and 'Page 6/6' in pdf[-1].get_text()


def test_parser_separates_parent_ro_from_child_tk_and_shipment():
    parent = ocr.parse_identifier('Rental Order No. RO-810001 Ticket No. TK-992001 Shipment No. 904001')
    assert parent == ocr.ParsedIdentifier('rental_order', 'RO-810001')
    assert ocr.parse_identifier('Rental Order No. RO-810001 Shipment No. 904001') == parent
    assert ocr.parse_identifier('Delivery Ticket Ticket No. TK-992001') == ocr.ParsedIdentifier('work_order', 'TK-992001')


def test_od_ro_and_so_are_three_distinct_identifiers():
    parsed = ocr.parse_identifier('Rental No. RO-810001 Order No. OD-992001 Shipment No. SO-904001')
    assert parsed.kind == 'work_order' and parsed.value == 'OD-992001'
    assert parsed.identifiers == {'rental_order': 'RO-810001', 'work_order': 'OD-992001', 'shipment': '904001'}
    assert ocr.parse_identifier('Order No. OD-992001').kind == 'work_order'
    assert ocr.parse_identifier('Shipment No. SO-904001').kind == 'shipment'
    without_order = ocr.parse_identifier('Rental No. RO-810001 Shipment No. SO-904001')
    assert 'work_order' not in without_order.identifiers


def test_zip_summary_counts_only_current_scan_and_updates_after_manual_fix(hierarchy, tmp_path):
    from ADK_Agentic.intake_watcher import prepare_ticket_pdfs
    client, store, _, _ = hierarchy
    document = store.rows(select(db.documents))[0]
    unrelated = dict(store.rows(select(db.orders))[0], id=db.uid(), order_number='OD-999999', shipment_number='999999')
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
    target = next(t for t in client.get('/api/workspaces/validation/tickets').json()['tickets'] if t['work_order'] == 'OD-992003')
    result = client.post(f"/api/workspaces/validation/tickets/{target['id']}/page-approvals",
        json={'page_id': target['unidentified_scan_pages'][0]['id'], 'printed_page': 1})
    assert result.status_code == 200
    summary = client.get('/api/workspaces/validation/progress').json()['download_summary']
    assert summary == dict(total_orders=8, ready_orders=7, not_ready_orders=1,
        missing_pages=1, unidentified_pages=1, pending_pages=0)


def test_saved_scan_zip_summary_survives_restart_without_provider_calls(hierarchy, tmp_path, monkeypatch):
    import sqlite3
    from ADK_Agentic.intake_watcher import prepare_ticket_pdfs
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


def test_sample_refresh_creates_64_grouped_work_orders_and_preserves_workspace(tmp_path):
    import json
    import fitz
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
        tickets=[dict(order_id='W-991001', pdf='incomming_scan/batch_01_8_orders.pdf', pdf_sha256='a' * 64)])))
    manifest, backup = create_batches(tmp_path, rasterize=False)
    main = [r for r in manifest['tickets'] if r.get('sample_role') == 'batch']
    assert len(main) == len({r['order_id'] for r in main}) == 64
    assert len({r['parent_rental_number'] for r in main}) == 16
    assert len({r['shipment'] for r in main}) == 32
    assert sum(r['test_case'] == 'good' for r in main) == 48
    assert manifest['count'] == 64 and manifest['total_pages'] == 384
    assert not list((tmp_path / 'Scans/recovery_pages').glob('*.pdf'))
    assert database.read_bytes() == b'existing database stays untouched'
    assert uploaded.read_bytes() == b'uploaded source stays untouched'
    assert (backup / 'incomming_scan/batch_01_8_orders.pdf').read_bytes() == b'previous sample'
    assert 'a' * 64 in manifest['legacy_allowed_hashes']
    first = tmp_path / 'Scans/incomming_scan/batch_01_8_orders.pdf'
    assert first.read_bytes() == (first.parent / 'rental_orders_RO_OD_SO_shuffled.pdf').read_bytes()
    with fitz.open(first) as pdf:
        assert len(pdf) == 48
        header = pdf[0].get_text(clip=fitz.Rect(306, 0, 612, 198))
        assert header.index('Rental No.') < header.index('Order No.') < header.index('Shipment No.')
        assert 'Rental Agreement No.' not in header
        crop_misses = 0
        for record in main[:8]:
            assert {p['source_page'] for p in record['pages']} == set(range(1, 7))
            for page in record['pages']:
                image = pdf[page['page'] - 1]
                full = image.get_text()
                crop = image.get_text(clip=fitz.Rect(306, 0, 612, 198))
                assert record['order_id'] in full and 'TK-' not in full and 'W-' not in full
                parsed = ocr.parse_identifier(crop)
                assert parsed.identifiers['rental_order'] == record['parent_rental_number']
                assert parsed.identifiers['shipment'] == record['shipment']
                if page['expected_order_readable']:
                    assert parsed.identifiers['work_order'] == record['order_id']
                else:
                    crop_misses += 1
                    assert 'work_order' not in parsed.identifiers
        assert crop_misses == 2
