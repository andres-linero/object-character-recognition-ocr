"""Exercise product API against real SQL and generated multi-ticket source PDFs."""

import fitz
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from ADK_Agentic import etl, storage as db
from ADK_Agentic.processing import register_pdf
from ADK_Agentic.web_api import create_app
from scripts import create_demo_data as demo


@pytest.fixture
def api_workspace(tmp_path):
    dataset = tmp_path / "demo_data"
    manifest = demo.generate_dataset(dataset, count=2, min_pages=6, max_pages=6, rasterize=False)
    path = tmp_path / "workspace.sqlite"
    store = db.Store(db.sqlite_url(path))
    store.migrate()
    etl.ingest_tracker(store, dataset / "orders.xlsx", "demo", synthetic=True)
    source = dataset / "combined.pdf"
    with fitz.open() as pdf:
        for ticket in manifest["tickets"]:
            with fitz.open(dataset / ticket["pdf"]) as packet:
                pdf.insert_pdf(packet)
        pdf.save(source)
    document_id = register_pdf(store, source, synthetic=True)
    with store.engine.begin() as connection:
        number = 0
        for ticket in manifest["tickets"]:
            order_id = connection.scalar(select(db.orders.c.id).where(db.orders.c.shipment_number == ticket["shipment"]))
            for _ in ticket["pages"]:
                number += 1
                page_id = connection.scalar(select(db.pages.c.id).where(db.pages.c.document_id == document_id, db.pages.c.page_number == number))
                etl.upsert(connection, db.associations, ["order_id", "page_id", "method"],
                    dict(order_id=order_id, page_id=page_id, method="synthetic_manifest"))
                if number <= 6:
                    etl.upsert(connection, db.associations, ["order_id", "page_id", "method"],
                        dict(order_id=order_id, page_id=page_id, method="azure_ocr"))
                    connection.execute(db.attempts.insert().values(page_id=page_id, started_at=db.utcnow(),
                        finished_at=db.utcnow(), provider="azure_document_intelligence", status="success", identifier=ticket["shipment"]))
    app = create_app(root=tmp_path, databases={"validation": path}, allowed_roots=[dataset])
    with TestClient(app) as client:
        yield client, store, dataset
    store.close()


def test_tracker_filters_real_rows_and_returns_source_addresses(api_workspace):
    client, store, dataset = api_workspace
    rows = client.get('/api/workspaces/validation/tickets').json()['tickets']
    assert len(rows) == 2
    assert rows[0]['work_order'] == 'W-990002'
    assert rows[0]['billing_address'] == '101 Simulation Way, Demo City, ZZ 00000'
    assert rows[0]['billing_address_source'] == 'synthetic_manifest'
    assert rows[0]['rental_order'] == rows[0]['parent_rental_number'] == 'RO-700002'
    assert len(client.get('/api/workspaces/validation/tickets?q=900001').json()['tickets']) == 1
    assert len(client.get('/api/workspaces/validation/tickets?ocr=verified').json()['tickets']) == 1
    assert client.get('/api/workspaces/validation/tickets?q=no-match').json()['tickets'] == []
    assert 'path' not in rows[0]


def test_ticket_preview_and_download_extract_only_its_own_pages(api_workspace):
    client, store, dataset = api_workspace
    ticket_id = client.get('/api/workspaces/validation/tickets').json()['tickets'][0]['id']
    detail = client.get(f'/api/workspaces/validation/tickets/{ticket_id}').json()
    assert len(detail['pages']) == 6
    assert detail['pages'][0]['source_page'] == 7
    assert detail['pages'][0]['paper'] == 'Delivery Ticket'
    preview = client.get(f"/api/workspaces/validation/pages/{detail['pages'][0]['id']}/preview")
    assert preview.status_code == 200 and preview.content.startswith(b'\x89PNG')
    download = client.get(f'/api/workspaces/validation/tickets/{ticket_id}/download')
    assert download.status_code == 409
    ready = next(t for t in client.get('/api/workspaces/validation/tickets').json()['tickets'] if t['download_ready'])
    download = client.get(f"/api/workspaces/validation/tickets/{ready['id']}/download")
    assert download.status_code == 200
    assert 'RO-700001' in download.headers['content-disposition']
    inline = client.get(f"/api/workspaces/validation/tickets/{ready['id']}/download?preview=true")
    assert inline.status_code == 200
    assert inline.headers['content-disposition'].startswith('inline;')
    with fitz.open(stream=inline.content, filetype='pdf') as compiled:
        assert len(compiled) == 6
    with fitz.open(stream=download.content, filetype='pdf') as pdf:
        assert len(pdf) == 6
        assert all('900001' in page.get_text() and '900002' not in page.get_text() for page in pdf)


def test_review_is_persisted_with_origin_check(api_workspace):
    client, store, dataset = api_workspace
    ticket_id = client.get('/api/workspaces/validation/tickets').json()['tickets'][0]['id']
    route = f'/api/workspaces/validation/tickets/{ticket_id}/review'
    assert client.post(route, json={'reviewed': True}, headers={'Origin': 'https://untrusted.example'}).status_code == 403
    assert client.post(route, json={'reviewed': True}).json() == {'reviewed': True}
    assert client.get(f'/api/workspaces/validation/tickets/{ticket_id}').json()['reviewed'] is True
    assert len(client.get('/api/workspaces/validation/tickets?review=pending').json()['tickets']) == 1


def test_download_marks_persist_but_inline_previews_do_not_mark(api_workspace):
    client, store, _ = api_workspace
    ready = next(t for t in client.get('/api/workspaces/validation/tickets').json()['tickets'] if t['download_ready'])
    route = f"/api/workspaces/validation/tickets/{ready['id']}"
    assert ready['downloaded'] is False and ready['downloaded_at'] is None
    assert client.get(route + '/download?preview=true').status_code == 200
    assert store.rows(select(db.downloads)) == []
    assert client.get(route + '/download').status_code == 200
    saved = client.get(route).json()
    assert saved['downloaded'] is True and saved['downloaded_at']
    assert saved['download_count'] == 1
    assert saved['download_version'] == ready['download_version']
    store.migrate()
    assert client.get(route).json()['downloaded'] is True
    assert client.get(route + '/download').status_code == 200
    assert client.get(route).json()['download_count'] == 2
    receipts = store.rows(select(db.downloads))
    assert all(r['kind'] == 'pdf' and r['version'] == ready['download_version'] for r in receipts)
    assert client.get('/api/workspaces/validation/tickets').json()['tickets'][0]['downloaded'] is False


def test_incomplete_or_unavailable_pdf_does_not_get_a_download_mark(api_workspace):
    client, store, dataset = api_workspace
    rows = client.get('/api/workspaces/validation/tickets').json()['tickets']
    incomplete = next(t for t in rows if not t['download_ready'])
    assert client.get(f"/api/workspaces/validation/tickets/{incomplete['id']}/download").status_code == 409
    ready = next(t for t in rows if t['download_ready'])
    (dataset / 'combined.pdf').unlink()
    assert client.get(f"/api/workspaces/validation/tickets/{ready['id']}/download").status_code == 404
    assert store.rows(select(db.downloads)) == []


def test_changed_pdf_version_is_available_as_a_new_download(api_workspace):
    from ADK_Agentic.etl import checksum
    client, store, dataset = api_workspace
    ready = next(t for t in client.get('/api/workspaces/validation/tickets').json()['tickets'] if t['download_ready'])
    route = f"/api/workspaces/validation/tickets/{ready['id']}"
    assert client.get(route + '/download').status_code == 200
    source = dataset / 'combined.pdf'
    changed = source.with_suffix('.part')
    with fitz.open(source) as pdf:
        pdf[0].insert_text((40, 780), 'Updated document version')
        pdf.save(changed)
    changed.replace(source)
    with store.engine.begin() as connection:
        connection.execute(db.documents.update().values(sha256=checksum(source)))
    current = client.get(route).json()
    assert current['download_ready'] is True
    assert current['download_version'] != ready['download_version']
    assert current['downloaded'] is False and current['download_count'] == 0
    assert len(store.rows(select(db.downloads))) == 1  # Earlier version stays recorded.


def test_download_readiness_requires_current_successful_attempts(api_workspace):
    client, store, _ = api_workspace
    ready = next(t for t in client.get('/api/workspaces/validation/tickets').json()['tickets'] if t['download_ready'])
    assert ready['verified_pages'] == ready['expected_pages'] == 6
    with store.engine.begin() as connection:
        attempt_id = connection.scalar(select(db.attempts.c.id).limit(1))
        connection.execute(db.attempts.update().where(db.attempts.c.id == attempt_id).values(status='error'))
    changed = client.get(f"/api/workspaces/validation/tickets/{ready['id']}").json()
    assert changed['verified_pages'] == 5
    assert changed['download_ready'] is False
    assert client.get(f"/api/workspaces/validation/tickets/{ready['id']}/download").status_code == 409


def test_document_filters_use_database_associations(api_workspace):
    client, store, dataset = api_workspace
    docs = client.get('/api/workspaces/validation/documents').json()['documents']
    assert len(docs) == 1 and docs[0]['pages'] == 12 and docs[0]['first_page_id']
    assert len(client.get('/api/workspaces/validation/tickets?document_id='+docs[0]['id']).json()['tickets']) == 2
    assert client.get('/api/workspaces/validation/tickets?document_id=unknown').json()['tickets'] == []


def test_private_sources_and_unknown_ids_are_not_exposed(api_workspace):
    client, store, dataset = api_workspace
    assert client.get('/api/workspaces/unknown/tickets').status_code == 404
    assert client.get('/api/workspaces/validation/pages/unknown/preview').status_code == 404
    with store.engine.begin() as connection:
        connection.execute(db.sources.update().values(synthetic=False))
    assert client.get('/api/workspaces/validation/tickets').status_code == 403


def test_outside_document_paths_are_not_served(api_workspace, tmp_path):
    client, store, dataset = api_workspace
    page_id = store.rows(select(db.pages))[0]['id']
    outside = tmp_path / 'private.pdf'
    outside.write_bytes(b'not-to-be-served')
    with store.engine.begin() as connection:
        connection.execute(db.documents.update().values(path=str(outside)))
    assert client.get(f'/api/workspaces/validation/pages/{page_id}/preview').status_code == 404


def test_wrong_order_associations_do_not_inflate_verified_page_counts(api_workspace):
    client, store, dataset = api_workspace
    with store.engine.begin() as connection:
        first = connection.scalar(select(db.orders.c.id).where(db.orders.c.shipment_number == '900001'))
        second_pages = connection.execute(select(db.associations.c.page_id).where(
            db.associations.c.order_id != first, db.associations.c.method == 'synthetic_manifest')).scalars().all()
        for page_id in second_pages:
            etl.upsert(connection, db.associations, ['order_id', 'page_id', 'method'],
                       dict(order_id=first, page_id=page_id, method='azure_ocr'))
    summary = client.get('/api/workspaces/validation').json()
    assert summary['verified_pages'] == 6
    # Extra, unverified associations must not be included in a downloadable PDF.
    assert summary['verified_tickets'] == 0
    assert client.get(f'/api/workspaces/validation/tickets/{first}/download').status_code == 409


def test_scan_results_include_pending_pages_and_only_actual_ocr_matches(api_workspace):
    client, store, dataset = api_workspace
    response = client.get('/api/workspaces/validation/activity').json()
    assert response['total'] == 12
    assert response['files'] == 1
    assert response['files_read'] == 0
    assert response['current_scan']['total'] == 12
    assert response['current_scan']['completed'] == 6
    assert response['counts']['success'] == response['counts']['pending'] == 6
    read = [p for p in response['activity'] if p['status'] == 'success']
    pending = [p for p in response['activity'] if p['status'] == 'pending']
    assert all(p['matched_order']['work_order'] == 'W-990001' for p in read)
    assert all(p['matched_order'] is None and p['identifier'] is None for p in pending)
    assert all('path' not in p and p['page_id'] for p in response['activity'])
    assert client.get('/api/workspaces/validation').json()['flagged_tickets'] == 0
    page_id = pending[0]['page_id']
    with store.engine.begin() as connection:
        connection.execute(db.attempts.insert().values(page_id=page_id, started_at=db.utcnow(),
            finished_at=db.utcnow(), provider='azure_document_intelligence', status='no_match', identifier='999999'))
    assert client.get('/api/workspaces/validation').json()['flagged_tickets'] == 1
    response = client.get('/api/workspaces/validation/activity').json()
    flagged = next(p for p in response['activity'] if p['page_id'] == page_id)
    assert response['current_scan']['total'] == 12
    assert response['current_scan']['completed'] == 7
    assert flagged['status'] == 'no_match' and flagged['matched_order'] is None
    issues = client.get('/api/workspaces/validation/activity?issues_only=true').json()
    assert [row['page_id'] for row in issues['activity']] == [page_id]
    assert issues['current_scan']['total'] == 12
    with store.engine.begin() as connection:
        connection.execute(db.attempts.insert().values(page_id=page_id, started_at=db.utcnow(),
            finished_at=db.utcnow(), provider='azure_document_intelligence', status='success', identifier='900002'))
    assert client.get('/api/workspaces/validation').json()['flagged_tickets'] == 0


def test_progress_snapshot_reports_worker_state_and_respects_workspace_boundary(api_workspace):
    client, store, dataset = api_workspace
    assert client.get('/api/workspaces/validation/progress').json()['phase'] == 'waiting'
    client.app.state.intake_progress.update('reading', file='demo.pdf', total=6, completed=2, matched=2)
    response = client.get('/api/workspaces/validation/progress').json()
    assert response['phase'] == 'reading' and response['completed'] == 2
    assert response['ready_tickets'] == []
    assert client.get('/api/workspaces/missing/progress').status_code == 404


def test_pdf_drop_queues_a_valid_demo_file_in_the_existing_watch_folder(api_workspace):
    client, store, dataset = api_workspace
    sample = next((dataset / 'incoming_scans').glob('*.pdf'))
    response = client.post('/api/workspaces/validation/intake', content=sample.read_bytes(),
                           headers={'content-type': 'application/pdf', 'x-file-name': 'my_scan.pdf'})
    assert response.status_code == 200
    assert response.json()['status'] == 'queued'
    uploaded = dataset.parent / 'Scans/incomming_scan' / response.json()['file']
    assert uploaded.read_bytes() == sample.read_bytes()
    assert response.json()['page_count'] == 6
    assert sample.is_file()
    assert not list((dataset.parent / 'Scans/.uploads').glob('*.part'))


def test_pdf_drop_rejects_invalid_input_and_cross_origin_requests(api_workspace, monkeypatch):
    client, store, dataset = api_workspace
    route = '/api/workspaces/validation/intake'
    headers = {'content-type': 'application/pdf', 'x-file-name': 'scan.pdf'}
    assert client.post(route, content=b'not PDF', headers=headers).status_code == 422
    assert client.post(route, content=b'%PDF-1.7\ntruncated document', headers=headers).status_code == 422
    assert client.post(route, content=b'not PDF', headers={**headers, 'x-file-name': '../scan.pdf'}).status_code == 400
    assert client.post(route, content=b'not PDF', headers={**headers, 'origin': 'https://outside.invalid'}).status_code == 403
    assert client.post(route, content=b'not PDF', headers={**headers, 'content-type': 'text/plain'}).status_code == 415
    from ADK_Agentic import web_api
    monkeypatch.setattr(web_api, 'MAX_UPLOAD_BYTES', 2)
    assert client.post(route, content=b'123', headers=headers).status_code == 413
    assert not list((dataset.parent / 'Scans/.uploads').glob('*.part'))


def test_scan_zip_contains_only_ready_ticket_pdfs(api_workspace):
    import io
    import zipfile
    from ADK_Agentic.intake_watcher import prepare_ticket_pdfs

    client, store, dataset = api_workspace
    progress = client.app.state.intake_progress
    url = '/api/workspaces/validation/progress/tickets.zip'
    assert client.get(url, params={'revision': 0}).status_code == 409
    assert store.rows(select(db.downloads)) == []
    document_id = store.rows(select(db.documents.c.id))[0]['id']
    tickets = prepare_ticket_pdfs(store, document_id, dataset.parent / 'Scans/output')
    progress.update('ready', ready_tickets=tickets)
    revision = progress.snapshot()['revision']
    response = client.get(url, params={'revision': revision})
    assert response.status_code == 200
    assert response.headers['content-type'] == 'application/zip'
    receipts = store.rows(select(db.downloads))
    assert len(receipts) == 1 and receipts[0]['kind'] == 'scan_zip'
    rows = client.get('/api/workspaces/validation/tickets').json()['tickets']
    assert sum(t['downloaded'] for t in rows) == 1
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        assert archive.namelist() == ['RO-700001/Amber Workshop__W-990001__RO-700001__100 Simulation Way, Demo City, ZZ 00000.pdf']
        with fitz.open(stream=archive.read(archive.namelist()[0]), filetype='pdf') as pdf:
            assert len(pdf) == 6
            assert all('900001' in page.get_text() and '900002' not in page.get_text() for page in pdf)
    assert client.get(url, params={'revision': revision - 1}).status_code == 409
    (dataset.parent / 'Scans/output' / f'ticket-{tickets[0]["id"]}.pdf').unlink()
    assert client.get(url, params={'revision': revision}).status_code == 409
    progress.update('reading', ready_tickets=[])
    assert client.get(url, params={'revision': progress.snapshot()['revision']}).status_code == 409
    assert store.rows(select(db.downloads)) == receipts


def test_changed_registered_source_blocks_preview_download_and_receipts(api_workspace):
    from ADK_Agentic.intake_watcher import prepare_ticket_pdfs
    client, store, dataset = api_workspace
    ready = next(t for t in client.get('/api/workspaces/validation/tickets').json()['tickets'] if t['download_ready'])
    document = store.rows(select(db.documents))[0]
    compiled = prepare_ticket_pdfs(store, document['id'], dataset.parent / 'Scans/output')
    progress = client.app.state.intake_progress
    progress.update('ready', document_id=document['id'], ready_tickets=compiled)
    page = client.get(f"/api/workspaces/validation/tickets/{ready['id']}").json()['pages'][0]
    with Path(document['path']).open('ab') as source:
        source.write(b'\n% modified after registration\n')
    for endpoint in [f"pages/{page['id']}/preview", f"tickets/{ready['id']}/download",
                     f"progress/tickets.zip?revision={progress.snapshot()['revision']}"]:
        assert client.get('/api/workspaces/validation/' + endpoint).status_code == 409
    assert store.rows(select(db.downloads)) == []


def test_scan_zip_cannot_export_a_stale_or_replaced_prepared_pdf(api_workspace):
    import io
    import zipfile
    from ADK_Agentic.intake_watcher import prepare_ticket_pdfs
    client, store, dataset = api_workspace
    document = store.rows(select(db.documents))[0]
    ready = prepare_ticket_pdfs(store, document['id'], dataset.parent / 'Scans/output')
    artifact = dataset.parent / 'Scans/output' / f"ticket-{ready[0]['id']}.pdf"
    with fitz.open() as replacement:
        replacement.new_page().insert_text((36, 40), 'Unrelated document - must never be exported')
        replacement.save(artifact, garbage=4)
    progress = client.app.state.intake_progress
    progress.update('ready', document_id=document['id'], ready_tickets=ready)
    response = client.get('/api/workspaces/validation/progress/tickets.zip', params={'revision': progress.snapshot()['revision']})
    assert response.status_code == 200
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        with fitz.open(stream=archive.read(archive.namelist()[0]), filetype='pdf') as pdf:
            assert len(pdf) == 6
            assert all('900001' in page.get_text() for page in pdf)
