"""Replace generated demo inputs with eight shuffled, multi-order scan batches.

Run only with the web server stopped. No Azure calls are made.
"""
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import random
import shutil
import sys
import tempfile

import fitz

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.create_demo_data import build_tickets, write_ticket_pdf
from ADK_Agentic import storage as db

CASES = ('good', 'missing_identifier', 'good', 'unknown_shipment',
         'missing_identifier', 'missing_page', 'unknown_shipment', 'good')


def build(destination, batch_count=8):
    destination.mkdir(parents=True)
    incoming = destination / 'incomming_scan'
    incoming.mkdir()
    (destination / 'flag_order').mkdir()
    tickets = build_tickets(batch_count * 8, seed=811, min_pages=6, max_pages=6, start_index=1001)
    manifest = dict(generator='ocr-synthetic-demo-v1', synthetic=True,
                    count=len(tickets), batch_count=batch_count, tickets=[], batches=[])
    with tempfile.TemporaryDirectory(prefix='ocr-source-pages-') as scratch:
        for batch in range(batch_count):
            source_pages = []
            records = []
            for index, ticket in enumerate(tickets[batch * 8:(batch + 1) * 8]):
                path = Path(scratch) / f'{ticket.order_id}.pdf'
                pages = write_ticket_pdf(path, ticket, rasterize=True)
                case = CASES[index]
                with fitz.open(path) as original:
                    if case == 'missing_page':
                        original.delete_page(len(original) - 1)
                        pages = pages[:-1]
                    elif case in {'missing_identifier', 'unknown_shipment'}:
                        page = original[0]
                        page.add_redact_annot(fitz.Rect(306, 0, 612, 198), fill=(1, 1, 1))
                        page.apply_redactions()
                        if case == 'unknown_shipment':
                            page.insert_text((334, 47), 'Delivery Ticket / Shipment', fontsize=11)
                            page.insert_text((334, 70), 'Shipment No. 88888888', fontsize=16)
                    temporary = path.with_suffix('.part')
                    original.save(temporary, garbage=4, deflate=True)
                temporary.replace(path)
                record = json.loads(json.dumps(asdict(ticket), default=str))
                record.update(rental_order=ticket.rental_order, test_case=case, pages=[])
                records.append(record)
                source_pages.extend((path, n, index, metadata) for n, metadata in enumerate(pages))
            random.Random(811 + batch).shuffle(source_pages)
            target = incoming / f'batch_{batch + 1:02d}_8_orders.pdf'
            with fitz.open() as combined:
                for position, (path, number, index, metadata) in enumerate(source_pages, 1):
                    with fitz.open(path) as original:
                        combined.insert_pdf(original, from_page=number, to_page=number)
                    records[index]['pages'].append(dict(metadata, source_page=number + 1, page=position))
                combined.save(target, garbage=4, deflate=True)
            digest = hashlib.sha256(target.read_bytes()).hexdigest()
            for record in records:
                record.update(pdf=str(target.relative_to(destination)), pdf_sha256=digest)
            manifest['tickets'].extend(records)
            manifest['batches'].append(dict(pdf=str(target.relative_to(destination)), pages=len(source_pages)))
    manifest['total_pages'] = sum(b['pages'] for b in manifest['batches'])
    (destination / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    (destination / 'README.md').write_text(
        '# Shuffled multi-order scans\n\n'
        'Upload PDFs from incomming_scan through the app. Files are not watched.\n'
        '8 batches, 8 orders per batch, 47 pages per batch. Each batch contains '
        '3 good orders, 2 blank identifier cases, 2 unknown shipment cases, and 1 missing-page case.\n'
        'flag_order receives copies and reports for scans needing attention.\n'
        'manifest.json maps every scan page to its original order and intended test case.\n')
    return manifest


def replace(root):
    with tempfile.TemporaryDirectory(prefix='ocr-rebuild-', dir=root) as scratch:
        staged = Path(scratch) / 'Scans'
        manifest = build(staged)
        for batch in manifest['batches']:
            with fitz.open(staged / batch['pdf']) as pdf:
                assert len(pdf) == 47
        # Only generated data directories are replaced; source and tests stay intact.
        for name in ('Scans', 'demo_data', 'demo_batches', 'demo_runtime'):
            folder = root / name
            if folder.exists():
                shutil.rmtree(folder)
        staged.rename(root / 'Scans')
    runtime = root / 'demo_runtime'
    runtime.mkdir()
    store = db.Store(db.sqlite_url(runtime / 'workspace.sqlite'))
    try:
        store.migrate()
        print(json.dumps(dict(orders=64, batches=8, pages=manifest['total_pages'], database=store.counts(), orders_preloaded=0)))
    finally:
        store.close()


if __name__ == '__main__':
    replace(Path(__file__).resolve().parents[1])
