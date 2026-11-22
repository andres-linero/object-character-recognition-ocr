"""Order data must originate in uploaded pages, never Excel or fixture metadata."""
import io
import json
import zipfile

import pymupdf as fitz
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from ocr_workspace import ocr, storage as db
from ocr_workspace.etl import checksum
from ocr_workspace.web_api import create_app
from scripts.create_demo_data import generate_dataset


def header(ticket):
    """Provider text for one clean page of this order's header crop."""
    if ticket['order_type'] == 'SALE':
        return f"SALES ORDER Sales Order No. {ticket['parent_order_number']} Shipment No. {ticket['order_id'].split()[-1]}"
    return f"RENTAL ORDER Rental Order No. {ticket['parent_order_number']} Work Order No. {ticket['order_id']}"


def empty_workspace(tmp_path, manifest, combined, monkeypatch, responses):
    """An empty live workspace whose only inputs are one uploaded scan and provider text."""
    data = combined.parent
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
    texts = iter(responses)
    monkeypatch.setattr(ocr, 'extract_order_identity', lambda *a, **kw: ocr.parse_identifier(next(texts)))
    return store, create_app(root=tmp_path)


def upload_and_wait(app, client, combined, phase, wait_for_intake):
    response = client.post('/api/workspaces/workspace/intake', content=combined.read_bytes(),
        headers={'content-type': 'application/pdf', 'x-file-name': 'scan.pdf'})
    assert response.status_code == 200, response.text
    return wait_for_intake(app, phase)


@pytest.mark.parametrize('gap_case', ['missing_page', 'present_but_unidentified'])
def test_empty_workspace_builds_dataframe_orders_and_separates_missing_pages(tmp_path, monkeypatch, gap_case, wait_for_intake):
    data = tmp_path / 'demo_data'
    manifest = generate_dataset(data, count=2, min_pages=6, max_pages=6, rasterize=False)
    assert [t['order_id'] for t in manifest['tickets']] == ['W-0000001', 'W-0000002']
    packets = [data / t['pdf'] for t in manifest['tickets']]
    # Interleave the orders and deliberately omit page 6 from the second order.
    sequence = [(0, 5), (1, 3), (0, 0), (1, 0), (0, 3), (1, 2),
                (0, 1), (1, 4), (0, 4), (1, 1), (0, 2)]
    if gap_case == 'present_but_unidentified':
        # The page exists, but only its rental order is readable: it cannot be grouped on its own.
        with fitz.open(packets[1]) as packet:
            page = packet[5]
            page.add_redact_annot(fitz.Rect(306, 0, 612, 198), fill=(1, 1, 1))
            page.apply_redactions()
            page.insert_text((334, 47), 'RENTAL ORDER', fontsize=11)
            page.insert_text((334, 70), 'Rental Order No. RO-0000001', fontsize=16)
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
    responses = ['RENTAL ORDER Rental Order No. RO-0000001' if gap_case == 'present_but_unidentified' and (index, page) == (1, 5)
                 else header(manifest['tickets'][index]) for index, page in sequence]
    store, app = empty_workspace(tmp_path, manifest, combined, monkeypatch, responses)
    with TestClient(app) as client:
        assert client.get('/api/workspaces/workspace/tickets').json()['tickets'] == []
        snapshot = upload_and_wait(app, client, combined, 'needs_attention', wait_for_intake)
        rows = client.get('/api/workspaces/workspace/tickets').json()['tickets']
        assert len(rows) == 2
        ready = next(r for r in rows if r['download_ready'])
        missing = next(r for r in rows if not r['download_ready'])
        assert ready['customer'] == 'Demo Amber Workshop'
        assert ready['billing_address'] == '100 Simulation Way, Demo City, ZZ 00000'
        assert (ready['order_number'], ready['order_type'], ready['parent_order_number']) == ('W-0000001', 'RENTAL', 'RO-0000001')
        assert not {'work_order', 'shipment', 'ticket_number', 'customer_order_number', 'rental_order',
                    'parent_rental_number', 'rental_id'} & set(ready)
        assert ready['parent_id'] == missing['parent_id'] is not None
        assert ready['billing_address_source'] == 'document'
        assert (missing['order_number'], missing['parent_order_number']) == ('W-0000002', 'RO-0000001')
        assert missing['missing_pages'] == [6]
        assert missing['verified_pages'] == 5
        assert missing['page_gap_status'] == ('not_in_scan' if gap_case == 'missing_page' else 'unidentified_in_scan')
        assert len(missing['unidentified_scan_pages']) == (0 if gap_case == 'missing_page' else 1)
        if gap_case == 'present_but_unidentified':
            assert missing['unidentified_scan_pages'][0]['identifier'] == 'RO-0000001'
            assert missing['unidentified_scan_pages'][0]['source_page'] == 12
            flagged = client.get('/api/workspaces/workspace/activity?issues_only=true').json()['activity']
            assert [(p['error_code'], p['parent_order_number']) for p in flagged] == [('work_order_not_read', 'RO-0000001')]
            assert flagged[0]['parent_id'] == missing['parent_id'] and 'rental_id' not in flagged[0]
            with fitz.open(combined) as original:
                assert 'Page 6/6' in original[-1].get_text()
        assert client.get('/api/workspaces/workspace/tickets?ocr=missing').json()['total'] == 1
        assert client.get(f"/api/workspaces/workspace/tickets/{missing['id']}/download").status_code == 409
        assert snapshot['ready_tickets'] == [dict(id=ready['id'], order_number='W-0000001', order_type='RENTAL')]
        archive = client.get('/api/workspaces/workspace/progress/tickets.zip', params={'revision': snapshot['revision']})
        assert archive.status_code == 200
        with zipfile.ZipFile(io.BytesIO(archive.content)) as z:
            assert z.namelist() == ['RO-0000001/Amber Workshop__RO-0000001__W-0000001__100 Simulation Way, Demo City, ZZ 00000.pdf']
            with fitz.open(stream=z.read(z.namelist()[0]), filetype='pdf') as output:
                assert len(output) == 6
                for number, page in enumerate(output, 1):
                    assert f'Page {number}/6' in page.get_text()
        assert {r['kind'] for r in store.rows(select(db.sources))} == {'pdf'}
        assert len(store.rows(select(db.raw_rows))) == 11
    store.close()


def test_sales_order_pages_become_a_shipment_document_under_its_sales_order(tmp_path, monkeypatch, wait_for_intake):
    data = tmp_path / 'demo_data'
    manifest = generate_dataset(data, count=4, min_pages=6, max_pages=6, rasterize=False)
    rental, sale = manifest['tickets'][0], manifest['tickets'][3]
    assert (rental['order_id'], rental['parent_order_number']) == ('W-0000001', 'RO-0000001')
    assert (sale['order_id'], sale['parent_order_number'], sale['order_type']) == ('Shipment 00001', 'SO-0000002', 'SALE')
    chosen = [rental, sale]
    # One shuffled scan: a complete rental work order and a complete shipment of a sales order.
    sequence = [(1, 4), (0, 5), (1, 0), (0, 3), (0, 0), (1, 5), (0, 1), (1, 2), (0, 4), (1, 3), (1, 1), (0, 2)]
    combined = data / 'scan.pdf'
    with fitz.open() as pdf:
        for index, page in sequence:
            with fitz.open(data / chosen[index]['pdf']) as packet:
                pdf.insert_pdf(packet, from_page=page, to_page=page)
        pdf.save(combined)
    with fitz.open(combined) as scan:
        for (index, _), page in zip(sequence, scan):
            crop = page.get_text(clip=fitz.Rect(306, 0, 612, 198))
            # A rental page prints RO + W; a sales page prints SO + Shipment; never a mix.
            assert ('SO-' in crop, 'Shipment No.' in crop, 'RO-' in crop, 'W-' in crop) == (
                (True, True, False, False) if index else (False, False, True, True))
    address = '100 Simulation Way, Demo City, ZZ 00000'
    rental_file = f'Amber Workshop__RO-0000001__W-0000001__{address}.pdf'
    sale_file = f'Amber Workshop__SO-0000002__Shipment 00001__{address}.pdf'
    responses = [header(chosen[index]) for index, _ in sequence]
    store, app = empty_workspace(tmp_path, manifest, combined, monkeypatch, responses)
    with TestClient(app) as client:
        snapshot = upload_and_wait(app, client, combined, 'ready', wait_for_intake)
        listing = client.get('/api/workspaces/workspace/tickets').json()['tickets']
        rows = {r['order_number']: r for r in listing}
        assert set(rows) == {'W-0000001', 'Shipment 00001'}
        sold = rows['Shipment 00001']
        assert sold['order_type'] == 'SALE'
        assert sold['parent_order_number'] == 'SO-0000002' and sold['parent_id']
        assert 'parent_rental_number' not in sold and 'rental_id' not in sold
        assert sold['customer'] == 'Demo Amber Workshop'
        assert sold['billing_address'] == address
        assert sold['data_source'] == 'document'
        assert (sold['expected_pages'], sold['verified_pages'], sold['download_ready']) == (6, 6, True)
        assert sold['missing_pages'] == [] and sold['flagged'] is False
        assert rows['W-0000001']['order_type'] == 'RENTAL' and rows['W-0000001']['download_ready']
        assert rows['W-0000001']['parent_order_number'] == 'RO-0000001'
        assert rows['W-0000001']['parent_id'] != sold['parent_id']
        # Tickets sort by (parent order, document number), descending.
        assert [r['order_number'] for r in listing] == ['Shipment 00001', 'W-0000001']
        assert client.get('/api/workspaces/workspace/tickets?q=SO-0000002').json()['total'] == 1
        assert client.get('/api/workspaces/workspace/tickets?q=Shipment 00001').json()['total'] == 1

        # The sale is never standalone: it is grouped under its SO next to the rental order.
        parents = client.get('/api/workspaces/workspace/parent-orders').json()
        assert parents['total'] == 2 and 'rental_orders' not in parents
        by_number = {parent['parent_number']: parent for parent in parents['parent_orders']}
        assert set(by_number) == {'RO-0000001', 'SO-0000002'}
        sales_parent = by_number['SO-0000002']
        assert sales_parent['id'] == sold['parent_id'] and sales_parent['order_type'] == 'SALE'
        assert (sales_parent['ticket_count'], sales_parent['ready_tickets'], sales_parent['unassigned_pages']) == (1, 1, 0)
        assert [t['order_number'] for t in sales_parent['tickets']] == ['Shipment 00001']
        assert (sales_parent['customer'], sales_parent['address']) == ('Demo Amber Workshop', address)
        rental_parent = by_number['RO-0000001']
        assert rental_parent['order_type'] == 'RENTAL'
        assert [t['order_number'] for t in rental_parent['tickets']] == ['W-0000001']
        assert client.get('/api/workspaces/workspace').json()['parent_orders'] == 2
        assert client.get('/api/workspaces/workspace/rental-orders').status_code == 404

        orders = {o['order_number']: o for o in store.rows(select(db.orders))}
        assert orders['Shipment 00001']['order_type'] == 'SALE' and orders['Shipment 00001']['expected_pages'] == 6
        stored_parents = {r['id']: r['rental_number'] for r in store.rows(select(db.rental_orders))}
        links = {r['order_id']: stored_parents[r['rental_id']] for r in store.rows(select(db.rental_tickets))}
        assert links == {orders['Shipment 00001']['id']: 'SO-0000002', orders['W-0000001']['id']: 'RO-0000001'}
        # Every page carries its parent context, sales pages included.
        contexts = [stored_parents[r['rental_id']] for r in store.rows(select(db.rental_pages))]
        assert sorted(contexts) == ['RO-0000001'] * 6 + ['SO-0000002'] * 6
        assert {a['error_code'] for a in store.rows(select(db.attempts))} == {None}
        assert {a['identifier'] for a in store.rows(select(db.attempts))} == {'W-0000001', 'Shipment 00001'}

        detail = client.get(f"/api/workspaces/workspace/tickets/{sold['id']}").json()
        assert [p['printed_page'] for p in detail['pages']] == [1, 2, 3, 4, 5, 6]
        assert {p['paper'] for p in detail['pages']} == {'Delivery Ticket', 'Sales Order', 'Delivery Acknowledgement'}
        assert all(p['matched'] and p['expected'] == p['extracted'] == 'Shipment 00001' for p in detail['pages'])
        assert all(not p['comparison']['blocked'] for p in detail['pages'])
        assert all((p['fields']['order_number'], p['fields']['parent_order_number']) == ('Shipment 00001', 'SO-0000002')
                   for p in detail['pages'])
        assert all(p['fields']['ocr_identifiers'] == {'sales_order': 'SO-0000002', 'shipment': 'Shipment 00001'}
                   for p in detail['pages'])
        download = client.get(f"/api/workspaces/workspace/tickets/{sold['id']}/download")
        assert download.status_code == 200
        assert f'filename="{sale_file}"' in download.headers['content-disposition']
        with fitz.open(stream=download.content, filetype='pdf') as output:
            assert len(output) == 6
            for page in output:
                text = page.get_text()
                assert 'Sales Order No. SO-0000002' in text and 'Shipment No. 00001' in text
                assert 'RO-' not in text and 'Work Order No.' not in text

        assert sorted(t['order_number'] for t in snapshot['ready_tickets']) == ['Shipment 00001', 'W-0000001']
        assert {t['order_number']: t['order_type'] for t in snapshot['ready_tickets']} == {
            'Shipment 00001': 'SALE', 'W-0000001': 'RENTAL'}
        revision = client.get('/api/workspaces/workspace/progress').json()['revision']
        archive = client.get('/api/workspaces/workspace/progress/tickets.zip', params={'revision': revision})
        assert archive.status_code == 200
        with zipfile.ZipFile(io.BytesIO(archive.content)) as z:
            # Each document is filed in the folder of its parent order: RO for the work order, SO for the shipment.
            assert sorted(z.namelist()) == [f'RO-0000001/{rental_file}', f'SO-0000002/{sale_file}']
        bundle = client.get(f"/api/workspaces/workspace/parent-orders/{sales_parent['id']}/download.zip")
        assert bundle.status_code == 200
        assert 'filename="SO-0000002-ready-tickets.zip"' in bundle.headers['content-disposition']
        with zipfile.ZipFile(io.BytesIO(bundle.content)) as z:
            assert z.namelist() == [sale_file]
        bundle = client.get(f"/api/workspaces/workspace/parent-orders/{rental_parent['id']}/download.zip")
        assert bundle.status_code == 200
        with zipfile.ZipFile(io.BytesIO(bundle.content)) as z:
            assert z.namelist() == [rental_file]
        assert client.get('/api/workspaces/workspace/parent-orders/unknown/download.zip').status_code == 404
        assert client.get('/api/workspaces/workspace/tickets/unknown').json() == {'detail': 'Order not found'}
    store.close()


def test_sales_page_showing_only_its_sales_order_is_kept_under_that_order_for_review(tmp_path, monkeypatch, wait_for_intake):
    data = tmp_path / 'demo_data'
    manifest = generate_dataset(data, count=4, min_pages=6, max_pages=6, rasterize=False)
    sale = manifest['tickets'][3]
    packet_path = data / sale['pdf']
    # Page 6 exists, but its shipment line is unreadable everywhere: only the SO remains.
    with fitz.open(packet_path) as packet:
        page = packet[5]
        page.add_redact_annot(fitz.Rect(306, 0, 612, 198), fill=(1, 1, 1))
        page.apply_redactions()
        page.insert_text((334, 47), 'SALES ORDER', fontsize=11)
        page.insert_text((334, 70), 'Sales Order No. SO-0000002', fontsize=16)
        temporary = packet_path.with_suffix('.part')
        packet.save(temporary)
    temporary.replace(packet_path)
    sequence = [3, 0, 5, 2, 4, 1]
    combined = data / 'scan.pdf'
    with fitz.open() as pdf, fitz.open(packet_path) as packet:
        for page in sequence:
            pdf.insert_pdf(packet, from_page=page, to_page=page)
        pdf.save(combined)
    responses = ['SALES ORDER Sales Order No. SO-0000002' if page == 5 else header(sale) for page in sequence]
    store, app = empty_workspace(tmp_path, manifest, combined, monkeypatch, responses)
    with TestClient(app) as client:
        upload_and_wait(app, client, combined, 'needs_attention', wait_for_intake)
        rows = client.get('/api/workspaces/workspace/tickets').json()['tickets']
        assert [(r['order_number'], r['order_type'], r['parent_order_number']) for r in rows] == [
            ('Shipment 00001', 'SALE', 'SO-0000002')]
        shipment = rows[0]
        assert shipment['missing_pages'] == [6] and shipment['verified_pages'] == 5 and not shipment['download_ready']
        assert shipment['page_gap_status'] == 'unidentified_in_scan'
        assert [(p['identifier'], p['source_page']) for p in shipment['unidentified_scan_pages']] == [('SO-0000002', 3)]
        review = shipment['unidentified_scan_pages'][0]['review']['6']
        checks = {check['key']: check for check in review['checks']}
        assert checks['parent_order_number']['status'] == 'match' and checks['order_number']['status'] == 'not_read'
        assert not review['blocked']
        flagged = client.get('/api/workspaces/workspace/activity?issues_only=true').json()['activity']
        assert [(p['error_code'], p['identifier'], p['parent_order_number']) for p in flagged] == [
            ('shipment_not_read', 'SO-0000002', 'SO-0000002')]
        assert flagged[0]['parent_id'] == shipment['parent_id']
        parents = client.get('/api/workspaces/workspace/parent-orders').json()['parent_orders']
        assert [(p['parent_number'], p['order_type'], p['ticket_count'], p['ready_tickets'], p['unassigned_pages'])
                for p in parents] == [('SO-0000002', 'SALE', 1, 0, 1)]
        assert client.get(f"/api/workspaces/workspace/parent-orders/{parents[0]['id']}/download.zip").status_code == 409
        # The reviewer approves the image as page 6 of the shipment; the document completes under its SO.
        approved = client.post(f"/api/workspaces/workspace/tickets/{shipment['id']}/page-approvals",
            json=dict(page_id=shipment['unidentified_scan_pages'][0]['id'], printed_page=6))
        assert approved.status_code == 200, approved.text
        assert approved.json()['ticket']['download_ready'] is True
        bundle = client.get(f"/api/workspaces/workspace/parent-orders/{parents[0]['id']}/download.zip")
        assert bundle.status_code == 200
        with zipfile.ZipFile(io.BytesIO(bundle.content)) as z:
            assert z.namelist() == ['Amber Workshop__SO-0000002__Shipment 00001__100 Simulation Way, Demo City, ZZ 00000.pdf']
    store.close()
