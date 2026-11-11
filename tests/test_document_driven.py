"""Order data must originate in uploaded pages, never Excel or fixture metadata."""
import io
import json
import time
import zipfile

import fitz
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from ADK_Agentic import ocr, storage as db
from ADK_Agentic.etl import checksum
from ADK_Agentic.web_api import create_app
from scripts.create_demo_data import generate_dataset


@pytest.mark.parametrize('gap_case', ['missing_page', 'present_but_unidentified'])
def test_empty_workspace_builds_dataframe_orders_and_separates_missing_pages(tmp_path, monkeypatch, gap_case):
    data = tmp_path / 'demo_data'
    manifest = generate_dataset(data, count=2, min_pages=6, max_pages=6, rasterize=False)
    packets = [data / t['pdf'] for t in manifest['tickets']]
    # Interleave the orders and deliberately omit page 6 from the second order.
    sequence = [(0, 5), (1, 3), (0, 0), (1, 0), (0, 3), (1, 2),
                (0, 1), (1, 4), (0, 4), (1, 1), (0, 2)]
    if gap_case == 'present_but_unidentified':
        # The page exists, but its deliberately conflicting header prevents grouping.
        with fitz.open(packets[1]) as packet:
            page = packet[5]
            page.add_redact_annot(fitz.Rect(306, 0, 612, 198), fill=(1, 1, 1))
            page.apply_redactions()
            page.insert_text((334, 47), 'Delivery Ticket / Shipment', fontsize=11)
            page.insert_text((334, 70), 'Shipment No. 88888888', fontsize=16)
            temporary = packets[1].with_suffix('.part')
            packet.save(temporary)
        temporary.replace(packets[1])
        sequence.append((1, 5))
    combined = data / 'scan.pdf'
    with fitz.open() as pdf:
        for index, page in sequence:
            with fitz.open(packets[index]) as packet:
                pdf.insert_pdf(packet, from_page=page, to_page=page)
        pdf.save(combined)
    for ticket in manifest['tickets']:
        ticket.update(pdf='scan.pdf', pdf_sha256=checksum(combined),
                      customer='POISON: fixture metadata must not populate rows', address='Wrong address')
    (data / 'manifest.json').write_text(json.dumps(manifest))
    (data / 'orders.xlsx').unlink()
    (data / 'orders.csv').unlink()
    runtime = tmp_path / 'demo_runtime'
    runtime.mkdir()
    store = db.Store(db.sqlite_url(runtime / 'workspace.sqlite'))
    store.migrate()
    monkeypatch.setenv('AZURE_DOC_INTEL_ENDPOINT', 'https://example.invalid')
    monkeypatch.setenv('AZURE_DOC_INTEL_KEY', 'test-only')
    identifiers = iter('88888888' if gap_case == 'present_but_unidentified' and index == 1 and page == 5
                       else manifest['tickets'][index]['shipment'] for index, page in sequence)
    monkeypatch.setattr(ocr, 'extract_order_identity', lambda *a, **kw: ocr.ParsedIdentifier('shipment', next(identifiers)))
    app = create_app(root=tmp_path)
    with TestClient(app) as client:
        assert client.get('/api/workspaces/workspace/tickets').json()['tickets'] == []
        response = client.post('/api/workspaces/workspace/intake', content=combined.read_bytes(),
            headers={'content-type': 'application/pdf', 'x-file-name': 'scan.pdf'})
        assert response.status_code == 200, response.text
        deadline = time.monotonic() + 5
        while app.state.intake_progress.snapshot()['phase'] != 'needs_attention' and time.monotonic() < deadline:
            time.sleep(.01)
        snapshot = app.state.intake_progress.snapshot()
        assert snapshot['phase'] == 'needs_attention', snapshot
        rows = client.get('/api/workspaces/workspace/tickets').json()['tickets']
        assert len(rows) == 2
        ready = next(r for r in rows if r['download_ready'])
        missing = next(r for r in rows if not r['download_ready'])
        assert ready['customer'] == 'Demo Amber Workshop'
        assert ready['billing_address'] == '100 Simulation Way, Demo City, ZZ 00000'
        assert ready['rental_order'] == ready['parent_rental_number'] == 'RO-700001'
        assert ready['billing_address_source'] == 'document'
        assert missing['missing_pages'] == [6]
        assert missing['verified_pages'] == 5
        assert missing['page_gap_status'] == ('not_in_scan' if gap_case == 'missing_page' else 'unidentified_in_scan')
        assert len(missing['unidentified_scan_pages']) == (0 if gap_case == 'missing_page' else 1)
        if gap_case == 'present_but_unidentified':
            assert missing['unidentified_scan_pages'][0]['identifier'] == '88888888'
            assert missing['unidentified_scan_pages'][0]['source_page'] == 12
            with fitz.open(combined) as original:
                assert 'Page 6/6' in original[-1].get_text()
        assert client.get('/api/workspaces/workspace/tickets?ocr=missing').json()['total'] == 1
        assert client.get(f"/api/workspaces/workspace/tickets/{missing['id']}/download").status_code == 409
        archive = client.get('/api/workspaces/workspace/progress/tickets.zip', params={'revision': snapshot['revision']})
        assert archive.status_code == 200
        with zipfile.ZipFile(io.BytesIO(archive.content)) as z:
            assert len(z.namelist()) == 1
            assert 'RO-700001' in z.namelist()[0]
            with fitz.open(stream=z.read(z.namelist()[0]), filetype='pdf') as output:
                assert len(output) == 6
                for number, page in enumerate(output, 1):
                    assert f'Page {number}/6' in page.get_text()
        assert {r['kind'] for r in store.rows(select(db.sources))} == {'pdf'}
        assert len(store.rows(select(db.raw_rows))) == 11
    store.close()
