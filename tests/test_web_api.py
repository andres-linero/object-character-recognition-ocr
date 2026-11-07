"""Exercise product API against real SQL and generated multi-ticket source PDFs."""

import fitz
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
    assert download.status_code == 200
    with fitz.open(stream=download.content, filetype='pdf') as pdf:
        assert len(pdf) == 6
        assert all('900002' in page.get_text() and '900001' not in page.get_text() for page in pdf)


def test_review_is_persisted_with_origin_check(api_workspace):
    client, store, dataset = api_workspace
    ticket_id = client.get('/api/workspaces/validation/tickets').json()['tickets'][0]['id']
    route = f'/api/workspaces/validation/tickets/{ticket_id}/review'
    assert client.post(route, json={'reviewed': True}, headers={'Origin': 'https://untrusted.example'}).status_code == 403
    assert client.post(route, json={'reviewed': True}).json() == {'reviewed': True}
    assert client.get(f'/api/workspaces/validation/tickets/{ticket_id}').json()['reviewed'] is True
    assert len(client.get('/api/workspaces/validation/tickets?review=pending').json()['tickets']) == 1


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
    assert summary['verified_tickets'] == 1
