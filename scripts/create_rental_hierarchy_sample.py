"""Create complete OD/RO/SO packets with realistic identifier crop misses."""
from dataclasses import asdict, replace
import argparse
import hashlib
import json
from pathlib import Path
import random
import tempfile
import sys
import shutil

import fitz

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.create_demo_data import build_tickets, write_ticket_pdf


def _canonical_manifest_paths(manifest):
    """Keep portable JSON paths and recognize older Windows-generated records."""
    for record in [*manifest.get('tickets', []), *manifest.get('batches', [])]:
        if isinstance(record.get('pdf'), str):
            record['pdf'] = record['pdf'].replace('\\', '/')
    return manifest


def create(root, rasterize=True, batch_number=1, output_name=None):
    scans = root / 'Scans'
    incoming = scans / 'incomming_scan'
    incoming.mkdir(parents=True, exist_ok=True)
    offset = (batch_number - 1) * 8
    originals = build_tickets(8, seed=915 + batch_number, min_pages=6, max_pages=6, start_index=2001 + offset)
    tickets = [replace(t, order_id=t.order_id.replace('W-', 'OD-'),
        parent_rental_number=f'RO-{810001 + offset // 4 + index // 4}', shipment=str(904001 + offset // 2 + index // 2),
        customer=originals[0].customer.removeprefix('Demo '), address=originals[(index // 4) * 4].address,
        destination=originals[0].destination) for index, t in enumerate(originals)]
    records, sequence = [], []
    with tempfile.TemporaryDirectory(prefix='ocr-ro-sample-') as scratch:
        for index, ticket in enumerate(tickets):
            path = Path(scratch) / f'{ticket.order_id}.pdf'
            # Every page and number exists. Only the OD line moves, so RO/SO
            # cannot silently substitute for an unreadable order in the crop.
            offsets = {1: 64} if index == 2 else {6: 72} if index == 5 else {}
            metadata = write_ticket_pdf(path, ticket, rasterize, order_offsets=offsets)
            case = 'order_number_outside_crop' if offsets else 'good'
            record = json.loads(json.dumps(asdict(ticket), default=str))
            record.update(rental_order=ticket.rental_order, test_case=case, sample_role='batch',
                          shifted_order_pages=list(offsets), pages=[])
            records.append(record)
            sequence.extend((index, n, path, page) for n, page in enumerate(metadata))
        random.Random(915 + batch_number).shuffle(sequence)
        output = incoming / (output_name or 'rental_orders_RO_OD_SO_shuffled.pdf')
        with fitz.open() as combined:
            for number, (index, page_number, path, metadata) in enumerate(sequence, 1):
                with fitz.open(path) as pdf:
                    combined.insert_pdf(pdf, from_page=page_number, to_page=page_number)
                records[index]['pages'].append(dict(metadata, source_page=page_number + 1, page=number,
                    expected_ocr_id=records[index]['order_id'],
                    expected_order_readable=page_number + 1 not in records[index]['shifted_order_pages']))
            combined.save(output, garbage=4, deflate=True)
    digest = hashlib.sha256(output.read_bytes()).hexdigest()
    for record in records:
        record.update(pdf=output.relative_to(scans).as_posix(), pdf_sha256=digest)
    manifest_path = scans / 'manifest.json'
    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else dict(
        generator='ocr-synthetic-demo-v1', synthetic=True, tickets=[])
    _canonical_manifest_paths(manifest)
    manifest['tickets'] = [t for t in manifest['tickets'] if t.get('pdf') != output.relative_to(scans).as_posix()] + records
    manifest['count'] = len(manifest['tickets'])
    sample = output.relative_to(scans).as_posix()
    manifest['batches'] = [b for b in manifest.get('batches', []) if b['pdf'] != sample] + [dict(pdf=sample, pages=len(sequence))]
    manifest['batch_count'] = len(manifest['batches'])
    manifest['total_pages'] = sum(b['pages'] for b in manifest['batches'])
    temporary_manifest = manifest_path.with_suffix('.part')
    temporary_manifest.write_text(json.dumps(manifest, indent=2) + '\n')
    temporary_manifest.replace(manifest_path)
    return output, records, sequence


def create_batches(root, rasterize=True):
    """Replace only selectable sample templates; never reset uploaded documents or SQL."""
    scans = root / 'Scans'
    scans.mkdir(exist_ok=True)
    manifest_path = scans / 'manifest.json'
    old = _canonical_manifest_paths(json.loads(manifest_path.read_text())) if manifest_path.exists() else {}
    backup = Path(tempfile.mkdtemp(prefix='ocr-samples-before-refresh-'))
    if manifest_path.exists():
        shutil.copy2(manifest_path, backup / 'manifest.json')
    with tempfile.TemporaryDirectory(prefix='ocr-sample-build-') as directory:
        stage = Path(directory)
        for batch in range(1, 9):
            create(stage, rasterize=rasterize, batch_number=batch, output_name=f'batch_{batch:02d}_8_orders.pdf')
            print(f'Prepared batch {batch}/8', flush=True)
        data = json.loads((stage / 'Scans/manifest.json').read_text())
        first = stage / 'Scans/incomming_scan/batch_01_8_orders.pdf'
        alias = stage / 'Scans/incomming_scan/rental_orders_RO_OD_SO_shuffled.pdf'
        shutil.copy2(first, alias)
        alias_records = [dict(t, pdf='incomming_scan/rental_orders_RO_OD_SO_shuffled.pdf', sample_role='alias')
                         for t in data['tickets'] if t['pdf'] == 'incomming_scan/batch_01_8_orders.pdf']
        data['tickets'].extend(alias_records)
        replaced = {t['pdf'] for t in data['tickets']}
        retired = {t['pdf'] for t in old.get('tickets', []) if t.get('sample_role') in {'recovery', 'alias'} and t.get('pdf') not in replaced}
        data['tickets'] = [t for t in old.get('tickets', []) if t.get('pdf') not in replaced | retired] + data['tickets']
        data['legacy_allowed_hashes'] = sorted(set(old.get('legacy_allowed_hashes', [])) | {t['pdf_sha256'] for t in old.get('tickets', []) if t.get('pdf_sha256')})
        data.update(count=len({t['order_id'] for t in data['tickets']}), recommended_pdf='incomming_scan/batch_01_8_orders.pdf',
                    recovery_page_count=0, scan_profile='complete-packets-with-order-crop-misses')
        # Retire obsolete generator-owned supplements/aliases after backing them
        # up; never remove uploaded unique-name copies or preserved originals.
        for relative in retired:
            target = scans / relative
            if target.is_file():
                saved = backup / relative
                saved.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(target, saved)
                target.unlink()
        for relative in replaced:
            target = scans / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists():
                saved = backup / relative
                saved.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(target, saved)
            temporary = target.with_suffix('.part')
            shutil.copyfile(stage / 'Scans' / relative, temporary)
            temporary.replace(target)
        temporary = manifest_path.with_suffix('.part')
        temporary.write_text(json.dumps(data, indent=2) + '\n')
        temporary.replace(manifest_path)
    (scans / 'README.md').write_text('# Current scan samples\n\n'
        'Upload batch_01_8_orders.pdf through batch_08_8_orders.pdf from incomming_scan.\n'
        'Each has 2 ROs, 8 OD orders, 4 shared SO shipments and all 48 shuffled pages.\n'
        'Per batch: 6 orders read normally; 2 have one OD line just below the fixed OCR crop.\n'
        'All six pages exist for every order. In Flags, inspect the full-page OD and approve the correct image.\n'
        'The rental_orders_RO_OD_SO_shuffled.pdf file is an identical alias of batch 1.\n'
        'No database rows are preloaded. Existing uploaded originals, results and history are preserved.\n')
    return data, backup


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--all-batches', action='store_true')
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    if args.all_batches:
        _, backup = create_batches(root)
        print(f'8 batches, 64 OD orders, 16 ROs, 32 SO shipments, 384 pages; prior templates backed up in {backup}. Live workspace untouched.')
    else:
        output, records, _ = create(root)
        print(f'{output}: 2 ROs, 8 OD orders, 4 SO shipments, 48 shuffled pages. No rows preloaded.')
