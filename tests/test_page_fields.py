"""Page evidence survives failed identification and never fabricates a signature."""
import fitz
import json
import pytest
from types import SimpleNamespace
from fastapi.testclient import TestClient
from sqlalchemy import select

from ADK_Agentic import storage as db, ocr
from ADK_Agentic.document_data import extract_fields
from ADK_Agentic import document_data
from ADK_Agentic.processing import process_page, register_pdf
from ADK_Agentic.web_api import create_app
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
    assert result['status'] == 'no_match'
    assert store.counts()['orders'] == 0
    fields = store.rows(select(db.page_extractions))[0]['fields']
    assert fields['customer'] == 'Demo Amber Workshop'
    assert fields['address'] == '100 Simulation Way, Demo City, ZZ 00000'
    assert fields['work_order'] is None and fields['shipment'] is None
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
    assert store.rows(select(db.page_extractions))[0]['fields']['shipment'] == '900001'
    assert store.counts()['orders'] == 0
    store.close()


def test_shipment_alone_does_not_become_a_work_order(packet, tmp_path):
    with fitz.open(packet) as pdf:
        pdf[0].add_redact_annot(fitz.Rect(322, 78, 590, 100), fill=(1, 1, 1))
        pdf[0].apply_redactions()
        changed = packet.with_suffix('.part')
        pdf.save(changed)
    changed.replace(packet)
    store = db.Store(db.sqlite_url(tmp_path / 'workspace.sqlite'))
    store.migrate()
    register_pdf(store, packet, synthetic=True)
    page = store.rows(select(db.pages))[0]
    calls = []

    def identify(*args, **kwargs):
        calls.append(1)
        return ocr.parse_identifier('Delivery Ticket Shipment No. 900001')

    result = process_page(store, page['id'], extractor=identify, document_driven=True)
    assert result['status'] == 'no_match'
    assert store.counts()['orders'] == 0
    fields = store.rows(select(db.page_extractions))[0]['fields']
    assert fields['address'] and fields['work_order'] is None
    assert fields['shipment'] == '900001'
    assert fields['ocr_identifiers'] == {'shipment': '900001'}
    assert len(calls) == 1
    store.close()


def test_independent_header_conflict_is_not_hidden_by_a_matching_shipment(packet, tmp_path):
    store = db.Store(db.sqlite_url(tmp_path / 'workspace.sqlite'))
    store.migrate()
    register_pdf(store, packet, synthetic=True)
    page = store.rows(select(db.pages))[0]
    result = process_page(store, page['id'], extractor=lambda *a, **k: ocr.parse_identifier(
        'Delivery Ticket Shipment No. 900001 Work Order No. W-999999'), document_driven=True)
    assert result['status'] == 'no_match' and result['error_code'] == 'identifier_fields_disagree'
    assert store.counts()['orders'] == 0
    fields = store.rows(select(db.page_extractions))[0]['fields']
    assert fields['work_order'] == 'W-990001'
    assert fields['ocr_identifiers']['work_order'] == 'W-999999'
    store.close()


def test_details_distinguish_unsigned_acknowledgment_from_signature_text(packet):
    with fitz.open(packet) as pdf:
        acknowledgment = extract_fields(pdf[4])
        assert acknowledgment['signature_document'] is True
        assert acknowledgment['signature_status'] == 'explicitly_unsigned'
        assert acknowledgment['signature_evidence'] == 'NOT SIGNED - DEMO'
        assert acknowledgment['rental_order'] == acknowledgment['parent_rental_number'] == 'RO-700001'
        assert acknowledgment['rental_number_printed'] == 'RA-700001'
        assert acknowledgment['shipment'] == '900001'
        assert acknowledgment['work_order'] == 'W-990001'
        assert acknowledgment['contact_email'] == 'dispatch.001@example.test'
    with fitz.open() as pdf:
        page = pdf.new_page()
        page.insert_text((40, 50), 'Signature: __________________')
        page.insert_text((40, 70), 'Customer Order No. CO-134560')
        fields = extract_fields(page)
        assert fields['customer_order_number'] == 'CO-134560'
        assert fields['signature_status'] == 'field_present'
        assert fields['signature_evidence'] == 'Signature: __________________'
        assert fields['shipment'] is None


def test_vector_header_does_not_hide_scanned_body_fields(packet, monkeypatch):
    with fitz.open(packet) as original, fitz.open() as hybrid:
        source = original[0]
        lines = [dict(text=' '.join(s['text'] for s in line['spans']),
                      x=line['bbox'][0] / source.rect.width, y=line['bbox'][1] / source.rect.height)
                 for block in source.get_text('dict')['blocks'] for line in block.get('lines', [])]
        page = hybrid.new_page(width=source.rect.width, height=source.rect.height)
        page.insert_image(page.rect, stream=source.get_pixmap().tobytes('png'))
        page.insert_text((334, 70), 'Shipment No. 900001')
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
