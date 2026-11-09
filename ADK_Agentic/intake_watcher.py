"""One folder, one worker: stable demo PDFs are registered and read once per page."""
from pathlib import Path
import json
import logging
import os
import shutil
import errno
import threading
from copy import deepcopy

import fitz

from sqlalchemy import select
from . import storage as db
from .etl import checksum
from .processing import process_page, register_pdf

LOG = logging.getLogger(__name__)


class ProgressState:
    """Thread-safe worker evidence for the live UI; never includes provider text."""
    def __init__(self):
        self.lock = threading.Lock()
        self.value = dict(phase='waiting', file=None, total=0, completed=0, matched=0,
                          ready_tickets=[], message='Waiting for a PDF in Scans/incoming.', revision=0)

    def update(self, phase, **values):
        with self.lock:
            self.value.update(values, phase=phase, revision=self.value['revision'] + 1)

    def snapshot(self):
        with self.lock:
            return deepcopy(self.value)


def prepare_ticket_pdfs(store, document_id, output):
    """Create and open real ticket PDFs before announcing readiness."""
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    links = store.rows(select(db.associations.c.order_id).select_from(db.associations.join(db.pages))
                       .where(db.pages.c.document_id == document_id, db.associations.c.method == 'azure_ocr'))
    order_ids = {row['order_id'] for row in links}
    if not order_ids:
        raise ValueError('No matched orders')
    ready = []
    for order_id in sorted(order_ids):
        order = store.rows(select(db.orders).where(db.orders.c.id == order_id))[0]
        pages = store.rows(select(db.pages.c.id, db.pages.c.page_number, db.documents.c.path)
            .select_from(db.associations.join(db.pages).join(db.documents))
            .where(db.associations.c.order_id == order_id, db.associations.c.method == 'azure_ocr')
            .order_by(db.documents.c.path, db.pages.c.page_number))
        ids = {page['id'] for page in pages}
        memberships = store.rows(select(db.associations).where(db.associations.c.page_id.in_(ids), db.associations.c.method == 'azure_ocr'))
        if any(len({link['order_id'] for link in memberships if link['page_id'] == page_id}) != 1 for page_id in ids):
            raise ValueError('Ambiguous page association')
        latest = {}
        for attempt in store.rows(select(db.attempts).where(db.attempts.c.page_id.in_(ids)).order_by(db.attempts.c.started_at)):
            latest[attempt['page_id']] = attempt['status']
        if any(latest.get(page_id) != 'success' for page_id in ids):
            raise ValueError('Some associated pages are not verified')
        if len(pages) < (order['expected_pages'] or 1):
            raise ValueError('Order still has missing pages')
        target = output / f'ticket-{order_id}.pdf'
        temporary = target.with_suffix('.part')
        with fitz.open() as pdf:
            for page in pages:
                with fitz.open(page['path']) as source:
                    pdf.insert_pdf(source, from_page=page['page_number'] - 1, to_page=page['page_number'] - 1)
            pdf.save(temporary, garbage=4, deflate=True)
        with fitz.open(temporary) as verified:
            if len(verified) != len(pages):
                raise ValueError('Ticket PDF page count differs')
        temporary.replace(target)
        ready.append(dict(id=order_id, work_order=order['order_number'], shipment=order['shipment_number']))
    return ready


class IntakeWatcher:
    def __init__(self, store, folder, allowed_hashes, extractor=None, stop=None, progress=None, root=None):
        self.store = store
        self.folder = Path(folder).resolve()
        self.folder.mkdir(parents=True, exist_ok=True)
        self.allowed_hashes = set(allowed_hashes)
        self.root = Path(root) if root is not None else None
        self.extractor = extractor
        self.stop = stop
        self.progress = progress or ProgressState()
        self.observed = {}
        self.finished = {}

    def tick(self):
        """Wait for two identical file observations before reading a completed copy."""
        for path in sorted(self.folder.iterdir(), key=lambda p: p.name):
            if path.suffix.lower() != '.pdf' or path.is_symlink() or not path.is_file():
                continue
            signature = (path.stat().st_size, path.stat().st_mtime_ns)
            if self.finished.get(path.name) == signature:
                continue
            if self.observed.get(path.name) != signature:
                self.progress.update('receiving', file=path.name, total=0, completed=0, matched=0,
                                     ready_tickets=[], message='Waiting for the PDF copy to finish.')
                self.observed[path.name] = signature
                continue
            try:
                digest = checksum(path)
                if digest not in self.allowed_hashes and self.root is not None:
                    self.allowed_hashes.update(known_demo_hashes(self.root))
                if digest not in self.allowed_hashes:
                    self.progress.update('error', failed_at='receiving', message='This file is not a recognized demo PDF.')
                    LOG.warning('Intake skipped an unrecognized file; this workspace accepts generated demo PDFs.')
                    self.finished[path.name] = signature
                    continue
                archive = self.folder.parent / 'processed' / digest / path.name
                archive.parent.mkdir(parents=True, exist_ok=True)
                if not archive.exists():
                    temporary = archive.with_suffix('.part')
                    shutil.copyfile(path, temporary)
                    if checksum(temporary) != digest:
                        temporary.unlink()
                        continue
                    temporary.replace(archive)
                if checksum(archive) != digest:
                    raise ValueError('Archived source checksum changed')
                document_id = register_pdf(self.store, archive, synthetic=True)
                attempted = {r['page_id'] for r in self.store.rows(select(db.attempts.c.page_id))}
                pages = self.store.rows(select(db.pages).where(db.pages.c.document_id == document_id)
                                        .order_by(db.pages.c.page_number))
                statuses = {row['page_id']: row['status'] for row in self.store.rows(select(db.attempts).order_by(db.attempts.c.started_at))}
                def report(phase):
                    completed = sum(statuses.get(p['id']) in {'success', 'no_match', 'error'} for p in pages)
                    matched = sum(statuses.get(p['id']) == 'success' for p in pages)
                    self.progress.update(phase, total=len(pages), completed=completed, matched=matched,
                                         message=f'{matched} of {len(pages)} pages matched.')
                report('reading')
                for page in pages:
                    if self.stop and self.stop.is_set():
                        return
                    if page['id'] in attempted:
                        continue
                    report('reading')
                    result = process_page(self.store, page['id'], 'demo', self.extractor,
                                          on_stage=lambda phase: report(phase))
                    statuses[page['id']] = result['status']
                    report('matching')
                    LOG.info('Intake OCR page %s: %s', page['page_number'], result['status'])
                    if result.get('error_code') in {'HTTP401', 'HTTP403', 'HTTP404'}:
                        raise RuntimeError('Provider configuration rejected')
                if all(statuses.get(p['id']) == 'success' for p in pages):
                    report('preparing_pdf')
                    tickets = prepare_ticket_pdfs(self.store, document_id, self.folder.parent / 'output')
                    self.progress.update('ready', ready_tickets=tickets, message='OCR matched and ticket PDFs are ready.')
                else:
                    self.progress.update('needs_attention', message='Some pages are unreadable, unmatched, or incomplete. PDF not ready.')
                self.finished[path.name] = signature
            except Exception as exc:
                # Never log provider text, credentials, or ticket contents.
                self.progress.update('error', failed_at=self.progress.snapshot()['phase'], message=f'Processing stopped ({type(exc).__name__}). PDF not ready.')
                LOG.warning('Intake stopped a file attempt: %s', type(exc).__name__)
                self.finished[path.name] = signature


def known_demo_hashes(root):
    hashes = set()
    paths = [Path(root) / 'demo_data/manifest.json', *Path(root).glob('demo_batches/*/manifest.json')]
    for manifest in paths:
        data = json.loads(manifest.read_text()) if manifest.exists() else {}
        if data.get('synthetic') is not True or data.get('generator') != 'ocr-synthetic-demo-v1':
            continue
        for ticket in data['tickets']:
            pdf = (manifest.parent / ticket['pdf']).resolve()
            if pdf.is_relative_to(manifest.parent.resolve()):
                if pdf.is_file():
                    hashes.add(checksum(pdf))
                elif isinstance(ticket.get('pdf_sha256'), str) and len(ticket['pdf_sha256']) == 64:
                    hashes.add(ticket['pdf_sha256'])
    return hashes


def _try_worker_lock(lock):
    if os.name == 'nt':
        import msvcrt
        lock.seek(0)
        lock.write(b'0')
        lock.flush()
        lock.seek(0)
        msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
    else:
        import fcntl
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)


def _acquire_worker_lock(lock, stop, progress):
    while not stop.is_set():
        try:
            _try_worker_lock(lock)
            return True
        except OSError as exc:
            if exc.errno not in {errno.EACCES, errno.EAGAIN}:
                raise
            progress.update('waiting', message='Waiting for the previous intake worker to stop.')
            stop.wait(1)
    return False


def watch(root, database, folder, stop, progress=None):
    """Hold an OS lock for the worker lifetime, including all provider calls."""
    progress = progress or ProgressState()
    root, database = Path(root), Path(database)
    database.parent.mkdir(parents=True, exist_ok=True)
    lock = (database.parent / 'intake-worker.lock').open('a+b')
    try:
        if not _acquire_worker_lock(lock, stop, progress):
            return
        progress.update('waiting', message='Waiting for a PDF in Scans/incoming.')
        from dotenv import dotenv_values
        values = dotenv_values(root / '.env')
        for key in ('AZURE_DOC_INTEL_ENDPOINT', 'AZURE_DOC_INTEL_KEY'):
            value = values.get(key) or os.getenv(key)
            if not value:
                progress.update('error', failed_at='receiving', message='Configure Azure credentials before OCR can start.')
                LOG.warning('Intake OCR is not configured: missing %s', key)
                return
            os.environ[key] = value
        store = db.Store(db.sqlite_url(database))
        try:
            allowed = known_demo_hashes(root) | {row['sha256'] for row in store.rows(select(db.documents).where(db.documents.c.synthetic.is_(True)))}
            worker = IntakeWatcher(store, folder, allowed, stop=stop, progress=progress, root=root)
            while not stop.is_set():
                worker.tick()
                stop.wait(2)
        finally:
            store.close()
    except OSError:
        progress.update('error', failed_at='receiving', message='Intake worker is unavailable; another worker may hold the lock.')
        LOG.warning('Intake worker unavailable: another worker may hold the lock.')
    finally:
        lock.close()
