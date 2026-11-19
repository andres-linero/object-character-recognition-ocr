"""Shared-count order samples: RO and SO parents, 3-page work orders and 1-page shipments."""
import csv
import hashlib
import json
import re

import pymupdf as fitz
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from ocr_workspace import ocr, storage as db
from ocr_workspace.etl import checksum, ingest_tracker
from ocr_workspace.intake_watcher import IntakeWatcher, known_demo_hashes
from ocr_workspace.web_api import create_app
from scripts import create_order_samples as samples

COUNT = 80  # Enough pages to need more than one PDF, small enough to render quickly.


@pytest.fixture(scope='module')
def generated(tmp_path_factory):
    output = tmp_path_factory.mktemp('order-samples') / 'order_samples'
    manifest = samples.create(output, count=COUNT, seed=7, rasterize=False)
    return output, manifest


def documents(manifest):
    return [(record, document) for record in manifest['records'] for document in record['documents']]


def test_rental_and_sales_orders_share_one_count_without_gaps_or_duplicates(generated):
    _, manifest = generated
    numbers = [record['order'] for record in manifest['records']]
    assert all(re.fullmatch(r'(?:RO|SO)-\d{7}', number) for number in numbers)
    # One shared sequence: 1..N, each number used by exactly one RO or SO.
    assert [int(number.split('-')[1]) for number in numbers] == list(range(1, COUNT + 1))
    rentals = [number for number in numbers if number.startswith('RO-')]
    sales = [number for number in numbers if number.startswith('SO-')]
    assert (len(rentals), len(sales)) == (COUNT // 2, COUNT - COUNT // 2)
    assert (manifest['orders'], manifest['rental_orders'], manifest['sales_orders']) == (COUNT, len(rentals), len(sales))
    # The two families are shuffled along the count, not issued in blocks or strict alternation.
    kinds = [number[:2] for number in numbers]
    assert kinds != sorted(kinds) and kinds != sorted(kinds, reverse=True)
    assert kinds != ['RO', 'SO'] * (COUNT // 2) and kinds != ['SO', 'RO'] * (COUNT // 2)
    assert manifest['generator'] == 'ocr-order-samples-v1' and manifest['synthetic'] is True


def test_work_orders_and_shipments_each_have_their_own_count(generated):
    _, manifest = generated
    work_orders = [d['label'] for r, d in documents(manifest) if r['order'].startswith('RO-')]
    shipments = [d['label'] for r, d in documents(manifest) if r['order'].startswith('SO-')]
    assert all(re.fullmatch(r'W-\d{7}', label) for label in work_orders)
    assert all(re.fullmatch(r'Shipment \d{5}', label) for label in shipments)
    assert [int(label.split('-')[1]) for label in work_orders] == list(range(1, len(work_orders) + 1))
    assert [int(label.split()[1]) for label in shipments] == list(range(1, len(shipments) + 1))
    assert (manifest['work_orders'], manifest['shipments']) == (len(work_orders), len(shipments))
    assert not any(label.startswith('WO-') for label in work_orders + shipments)
    for record in manifest['records']:
        rental = record['order'].startswith('RO-')
        # A rental order creates 1-3 work orders; a sales order creates 1-4 shipments; never none, never the other kind.
        assert 1 <= len(record['documents']) <= (3 if rental else 4)
        assert all(d['label'].startswith('W-' if rental else 'Shipment ') for d in record['documents'])
    assert max(len(r['documents']) for r in manifest['records']) > 1  # One parent can have several documents.


def test_every_work_order_has_three_pages_and_every_shipment_one(generated):
    _, manifest = generated
    for record, document in documents(manifest):
        expected = 3 if document['label'].startswith('W-') else 1
        assert document['pages'] == expected, document['label']
        assert sorted(page['printed_page'] for page in document['scan_pages']) == list(range(1, expected + 1))
        papers = [page['paper'] for page in sorted(document['scan_pages'], key=lambda page: page['printed_page'])]
        assert papers == (['Delivery Ticket', 'Rental Agreement', 'Delivery Acknowledgement'] if expected == 3
                          else ['Delivery Ticket'])
    assert manifest['total_pages'] == 3 * manifest['work_orders'] + manifest['shipments']


def test_every_pdf_is_under_250_pages_and_matches_the_manifest(generated):
    output, manifest = generated
    assert len(manifest['files']) > 1
    assert sorted(path.name for path in output.iterdir()) == sorted(
        [item['pdf'] for item in manifest['files']] + ['manifest.json', 'orders.csv'])
    assert json.loads((output / 'manifest.json').read_text()) == manifest
    for item in manifest['files']:
        with fitz.open(output / item['pdf']) as pdf:
            assert len(pdf) == item['pages'] < 250
        assert item['pdf'].endswith(f"_{item['pages']}_pages.pdf")
        assert hashlib.sha256((output / item['pdf']).read_bytes()).hexdigest() == item['sha256']
        in_file = [d for _, d in documents(manifest) if d['file'] == item['pdf']]
        assert sum(d['pages'] for d in in_file) == item['pages']
        # Each scan position is used exactly once.
        assert sorted(page['scan_page'] for d in in_file for page in d['scan_pages']) == list(range(1, item['pages'] + 1))
        assert item['orders'] == len({r['order'] for r, d in documents(manifest) if d['file'] == item['pdf']})
    assert sum(item['pages'] for item in manifest['files']) == manifest['total_pages']
    assert sum(item['orders'] for item in manifest['files']) == COUNT


def test_all_documents_of_one_parent_order_are_in_the_same_pdf_and_pages_are_shuffled(generated):
    _, manifest = generated
    names = {item['pdf'] for item in manifest['files']}
    for record in manifest['records']:
        assert len({document['file'] for document in record['documents']}) == 1, record['order']
        assert record['documents'][0]['file'] in names
    # Pages are shuffled inside a PDF: some work order's three pages are not consecutive and in order.
    work_orders = [d for _, d in documents(manifest) if d['pages'] == 3]
    positions = [[page['scan_page'] for page in sorted(d['scan_pages'], key=lambda page: page['printed_page'])] for d in work_orders]
    assert sum(found != list(range(found[0], found[0] + 3)) for found in positions) > len(positions) // 2


def test_orders_csv_starts_with_order_work_order_address_and_lists_every_document(generated):
    output, manifest = generated
    with (output / 'orders.csv').open(newline='', encoding='utf-8') as handle:
        reader = csv.DictReader(handle)
        assert reader.fieldnames[:3] == ['Order', 'Work order', 'Address']
        assert reader.fieldnames == ['Order', 'Work order', 'Address', 'Customer', 'Pages', 'File']
        rows = list(reader)
    assert [(row['Order'], row['Work order'], row['Address'], row['Customer'], int(row['Pages']), row['File']) for row in rows] == [
        (record['order'], document['label'], record['address'], record['customer'], document['pages'], document['file'])
        for record, document in documents(manifest)]
    assert len({row['Work order'] for row in rows}) == len(rows)
    # One billing address per parent order, shared by all of its documents.
    by_order = {}
    for row in rows:
        by_order.setdefault(row['Order'], set()).add((row['Address'], row['Customer']))
    assert all(len(values) == 1 for values in by_order.values())
    assert len({row['Address'] for row in rows}) == COUNT


def test_orders_csv_rows_load_as_tracker_rows_with_every_document_under_its_parent(generated, tmp_path):
    output, manifest = generated
    store = db.Store(db.sqlite_url(tmp_path / 'tracker.sqlite'))
    try:
        store.migrate()
        total = manifest['work_orders'] + manifest['shipments']
        # The sample list carries Order / Work order / Address; a tracker also needs a status per row.
        with (output / 'orders.csv').open(newline='', encoding='utf-8') as handle:
            rows = [dict(row, Status='OPEN', Expected_Pages=row['Pages']) for row in csv.DictReader(handle)]
        tracker = tmp_path / 'orders.csv'
        with tracker.open('w', newline='', encoding='utf-8') as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
        result = ingest_tracker(store, tracker, 'demo', synthetic=True)
        assert (result['rows_loaded'], result['rows_rejected']) == (total, 0)
        parents = {r['id']: r for r in store.rows(select(db.rental_orders))}
        assert sorted(r['rental_number'] for r in parents.values()) == sorted(r['order'] for r in manifest['records'])
        orders = {o['id']: o for o in store.rows(select(db.orders))}
        links = {orders[link['order_id']]['order_number']: parents[link['rental_id']]['rental_number']
                 for link in store.rows(select(db.rental_tickets))}
        assert links == {document['label']: record['order'] for record, document in documents(manifest)}
        assert {o['order_number']: (o['order_type'], o['expected_pages']) for o in orders.values()} == {
            document['label']: ('RENTAL', 3) if document['label'].startswith('W-') else ('SALE', 1)
            for _, document in documents(manifest)}
    finally:
        store.close()


def test_every_header_inside_the_ocr_crop_parses_to_its_document_and_parent(generated):
    output, manifest = generated
    assert (ocr.HEADER_CROP_WIDTH, ocr.HEADER_CROP_HEIGHT) == (0.50, 0.25)
    checked = 0
    for item in manifest['files']:
        with fitz.open(output / item['pdf']) as pdf:
            for record, document in documents(manifest):
                if document['file'] != item['pdf']:
                    continue
                rental = record['order'].startswith('RO-')
                for scan in document['scan_pages']:
                    page = pdf[scan['scan_page'] - 1]
                    # Right half, top quarter: exactly what the provider receives.
                    crop = fitz.Rect(page.rect.width / 2, 0, page.rect.width, page.rect.height / 4)
                    header = page.get_text(clip=crop)
                    parsed = ocr.parse_identifier(header)
                    assert parsed is not None, (item['pdf'], scan['scan_page'])
                    assert (parsed.kind, parsed.value) == ('work_order' if rental else 'shipment', document['label'])
                    assert parsed.identifiers == (
                        {'rental_order': record['order'], 'work_order': document['label']} if rental else
                        {'sales_order': record['order'], 'shipment': document['label']})
                    assert not ocr.mixed_families(parsed.identifiers)
                    assert f"Page {scan['printed_page']}/{document['pages']}" in header
                    assert ('RENTAL ORDER' if rental else 'SALES ORDER') in header
                    if not rental:
                        assert f"Shipment No. {document['label'].split()[1]}" in header
                    # Customer details stay outside the crop that leaves the machine.
                    assert record['customer'] not in header and record['address'] not in header
                    full = page.get_text()
                    assert record['customer'] in full and record['address'] in full
                    assert not ocr.mixed_families(ocr.parse_document_identifiers(full))
                    assert 'WO-' not in full
                    checked += 1
    assert checked == manifest['total_pages']


def test_refuses_to_overwrite_a_directory_it_did_not_create(tmp_path):
    target = tmp_path / 'real-scans'
    target.mkdir()
    (target / 'important.pdf').write_bytes(b'untouched')
    with pytest.raises(ValueError, match='not empty'):
        samples.create(target, count=4, rasterize=False)
    assert [path.name for path in target.iterdir()] == ['important.pdf']
    assert (target / 'important.pdf').read_bytes() == b'untouched'
    # Another generator's manifest is not ownership either.
    (target / 'manifest.json').write_text(json.dumps(dict(generator='ocr-synthetic-demo-v1', synthetic=True, tickets=[])))
    with pytest.raises(ValueError, match='not empty'):
        samples.create(target, count=4, rasterize=False)
    assert sorted(path.name for path in target.iterdir()) == ['important.pdf', 'manifest.json']
    assert (target / 'important.pdf').read_bytes() == b'untouched'


def test_its_own_output_is_replaced_and_an_empty_directory_is_accepted(tmp_path):
    target = tmp_path / 'order_samples'
    target.mkdir()
    first = samples.create(target, count=6, seed=3, rasterize=False)
    again = samples.create(target, count=6, seed=3, rasterize=False)

    def strip(manifest):
        return [(r['order'], r['customer'], r['address'], [(d['label'], d['pages'], d['scan_pages']) for d in r['documents']])
                for r in manifest['records']]

    assert strip(first) == strip(again)  # The same seed reproduces the same orders and page order.
    smaller = samples.create(target, count=4, seed=3, rasterize=False)
    assert smaller['orders'] == 4
    assert sorted(path.name for path in target.iterdir()) == sorted(
        [item['pdf'] for item in smaller['files']] + ['manifest.json', 'orders.csv'])
    assert strip(samples.create(tmp_path / 'other', count=6, seed=4, rasterize=False)) != strip(first)


def test_default_scan_like_pages_are_images_at_the_same_positions(tmp_path):
    manifest = samples.create(tmp_path / 'raster', count=2, seed=5)
    with fitz.open(tmp_path / 'raster' / manifest['files'][0]['pdf']) as pdf:
        assert len(pdf) == manifest['total_pages']
        assert all(page.get_text() == '' and len(page.get_images()) == 1 for page in pdf)


def test_register_adds_the_files_to_the_scan_manifest_so_they_can_be_uploaded(generated, tmp_path):
    output, manifest = generated
    root = tmp_path / 'workspace'
    scans = root / 'Scans'
    scans.mkdir(parents=True)
    existing = dict(generator='ocr-synthetic-demo-v1', synthetic=True,
        tickets=[dict(order_id='W-0009001', pdf='incomming_scan/earlier.pdf', pdf_sha256='a' * 64)],
        batches=[dict(pdf='incomming_scan/earlier.pdf', pages=6)])
    (scans / 'manifest.json').write_text(json.dumps(existing))
    assert known_demo_hashes(root) == {'a' * 64}
    assert samples.register(root, manifest, output) == len(manifest['files'])
    hashes = known_demo_hashes(root)
    for item in manifest['files']:
        copied = scans / 'incomming_scan' / item['pdf']
        assert copied.read_bytes() == (output / item['pdf']).read_bytes()
        assert checksum(copied) == item['sha256']
        assert item['sha256'] in hashes
    assert 'a' * 64 in hashes  # Earlier samples stay uploadable.
    data = json.loads((scans / 'manifest.json').read_text())
    assert data['generator'] == 'ocr-synthetic-demo-v1' and data['synthetic'] is True
    assert data['tickets'][0] == existing['tickets'][0]
    added = [t for t in data['tickets'] if t.get('sample_role') == 'order_samples']
    assert [(t['order_id'], t['parent_order_number'], t['page_count']) for t in added] == [
        (document['label'], record['order'], document['pages']) for record, document in documents(manifest)]
    assert all(t['pdf'] == f"incomming_scan/{t['pdf'].split('/')[-1]}" and len(t['pages']) == t['page_count'] for t in added)
    assert [b for b in data['batches'] if b['pdf'] != 'incomming_scan/earlier.pdf'] == [
        dict(pdf=f"incomming_scan/{item['pdf']}", pages=item['pages']) for item in manifest['files']]
    # Registering again replaces its own records instead of duplicating them.
    samples.register(root, manifest, output)
    again = json.loads((scans / 'manifest.json').read_text())
    assert again == data
    assert not list(scans.glob('*.part'))


def test_register_creates_the_scan_manifest_when_none_exists_and_the_upload_endpoint_accepts_the_pdf(tmp_path):
    output = tmp_path / 'order_samples'
    manifest = samples.create(output, count=4, seed=11, rasterize=False)
    root = tmp_path / 'workspace'
    assert known_demo_hashes(root) == set()
    assert samples.register(root, manifest, output) == 1
    assert known_demo_hashes(root) == {manifest['files'][0]['sha256']}
    database = root / 'workspace.sqlite'
    store = db.Store(db.sqlite_url(database))
    store.migrate()
    store.close()
    sample = output / manifest['files'][0]['pdf']
    with TestClient(create_app(root=root, databases={'validation': database}, allowed_roots=[root])) as client:
        response = client.post('/api/workspaces/validation/intake', content=sample.read_bytes(),
                               headers={'content-type': 'application/pdf', 'x-file-name': sample.name})
        assert response.status_code == 200, response.text
        assert response.json()['page_count'] == manifest['total_pages']
        # Without preloaded rows the registered samples add no orders by themselves.
        assert client.get('/api/workspaces/validation/tickets').json()['tickets'] == []


def test_a_sample_scan_becomes_complete_documents_grouped_under_their_parent_orders(tmp_path):
    output = tmp_path / 'order_samples'
    manifest = samples.create(output, count=12, seed=21, rasterize=False)
    assert len(manifest['files']) == 1
    pdf = output / manifest['files'][0]['pdf']
    database = tmp_path / 'workspace.sqlite'
    store = db.Store(db.sqlite_url(database))
    store.migrate()
    with fitz.open(pdf) as source:
        crops = iter([page.get_text(clip=fitz.Rect(page.rect.width / 2, 0, page.rect.width, page.rect.height / 4))
                      for page in source])
    worker = IntakeWatcher(store, pdf.parent, {checksum(pdf)}, lambda *a, **k: ocr.parse_identifier(next(crops)), root=tmp_path)
    worker.tick(submitted=pdf)
    attempts = store.rows(select(db.attempts))
    assert len(attempts) == manifest['total_pages']
    assert {(a['status'], a['error_code']) for a in attempts} == {('success', None)}
    expected = {document['label']: (record['order'], document['pages']) for record, document in documents(manifest)}
    with TestClient(create_app(root=tmp_path, databases={'validation': database}, allowed_roots=[tmp_path])) as client:
        tickets = client.get('/api/workspaces/validation/tickets').json()['tickets']
        assert {t['order_number']: (t['parent_order_number'], t['expected_pages']) for t in tickets} == expected
        assert all(t['download_ready'] and t['verified_pages'] == t['expected_pages'] and not t['flagged'] for t in tickets)
        assert all(t['order_type'] == ('RENTAL' if t['order_number'].startswith('W-') else 'SALE') for t in tickets)
        listing = client.get('/api/workspaces/validation/parent-orders').json()
        assert listing['total'] == 12
        for parent in listing['parent_orders']:
            record = next(r for r in manifest['records'] if r['order'] == parent['parent_number'])
            assert parent['order_type'] == ('RENTAL' if record['order'].startswith('RO-') else 'SALE')
            assert sorted(t['order_number'] for t in parent['tickets']) == sorted(d['label'] for d in record['documents'])
            assert (parent['ticket_count'], parent['ready_tickets'], parent['unassigned_pages']) == (
                len(record['documents']), len(record['documents']), 0)
            assert (parent['customer'], parent['address']) == (record['customer'], record['address'])
        shipment = next(t for t in tickets if t['order_type'] == 'SALE')
        download = client.get(f"/api/workspaces/validation/tickets/{shipment['id']}/download")
        assert download.status_code == 200
        with fitz.open(stream=download.content, filetype='pdf') as single:
            assert len(single) == 1 and 'Page 1/1' in single[0].get_text()
        work_order = next(t for t in tickets if t['order_type'] == 'RENTAL')
        download = client.get(f"/api/workspaces/validation/tickets/{work_order['id']}/download")
        assert download.status_code == 200
        with fitz.open(stream=download.content, filetype='pdf') as packet:
            assert [f'Page {n}/3' in page.get_text() for n, page in enumerate(packet, 1)] == [True] * 3
    store.close()


def test_default_build_is_300_orders_split_across_6_files_under_250_pages():
    orders = samples.build_orders()
    assert len(orders) == 300
    assert [int(order['order'].split('-')[1]) for order in orders] == list(range(1, 301))
    assert sum(order['kind'] == 'RO' for order in orders) == sum(order['kind'] == 'SO' for order in orders) == 150
    assert all(order['order'].startswith(order['kind'] + '-') for order in orders)
    for order in orders:
        rental = order['kind'] == 'RO'
        assert 1 <= len(order['documents']) <= (3 if rental else 4)
        assert all(d['pages'] == (3 if rental else 1) and d['label'].startswith('W-' if rental else 'Shipment ')
                   for d in order['documents'])
    work_orders = [d['label'] for o in orders if o['kind'] == 'RO' for d in o['documents']]
    shipments = [d['label'] for o in orders if o['kind'] == 'SO' for d in o['documents']]
    assert [int(label.split('-')[1]) for label in work_orders] == list(range(1, len(work_orders) + 1))
    assert [int(label.split()[1]) for label in shipments] == list(range(1, len(shipments) + 1))
    files = samples.split_into_files(orders)
    assert len(files) == 6
    sizes = [sum(d['pages'] for order in group for d in order['documents']) for group in files]
    assert all(0 < size < 250 for size in sizes), sizes
    # Every order is in exactly one file, whole.
    assert [order['order'] for group in files for order in group] == [order['order'] for order in orders]
    assert sum(sizes) == 3 * len(work_orders) + len(shipments)
    again = samples.build_orders()
    assert [(o['order'], [d['label'] for d in o['documents']]) for o in again] == [
        (o['order'], [d['label'] for d in o['documents']]) for o in orders]
    assert [o['order'] for o in samples.build_orders(seed=2027)] != [o['order'] for o in orders]
