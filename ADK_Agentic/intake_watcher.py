"""One folder, one worker: stable demo PDFs are registered and read once per page."""
from pathlib import Path
import json
import logging
import os
import shutil

from sqlalchemy import select
from . import storage as db
from .etl import checksum
from .processing import process_page, register_pdf

LOG = logging.getLogger(__name__)


class IntakeWatcher:
    def __init__(self, store, folder, allowed_hashes, extractor=None, stop=None):
        self.store = store
        self.folder = Path(folder).resolve()
        self.folder.mkdir(parents=True, exist_ok=True)
        self.allowed_hashes = allowed_hashes
        self.extractor = extractor
        self.stop = stop
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
                self.observed[path.name] = signature
                continue
            try:
                digest = checksum(path)
                if digest not in self.allowed_hashes:
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
                for page in pages:
                    if self.stop and self.stop.is_set():
                        return
                    if page['id'] in attempted:
                        continue
                    result = process_page(self.store, page['id'], 'demo', self.extractor)
                    LOG.info('Intake OCR page %s: %s', page['page_number'], result['status'])
                    if result.get('error_code') in {'HTTP401', 'HTTP403', 'HTTP404'}:
                        raise RuntimeError('Provider configuration rejected')
                self.finished[path.name] = signature
            except Exception as exc:
                # Never log provider text, credentials, or ticket contents.
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
            if pdf.is_relative_to(manifest.parent.resolve()) and pdf.is_file():
                hashes.add(checksum(pdf))
    return hashes


def watch(root, database, folder, stop):
    """Hold an OS lock for the worker lifetime, including all provider calls."""
    root, database = Path(root), Path(database)
    database.parent.mkdir(parents=True, exist_ok=True)
    lock = (database.parent / 'intake-worker.lock').open('a+b')
    try:
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
        from dotenv import dotenv_values
        values = dotenv_values(root / '.env')
        for key in ('AZURE_DOC_INTEL_ENDPOINT', 'AZURE_DOC_INTEL_KEY'):
            value = values.get(key) or os.getenv(key)
            if not value:
                LOG.warning('Intake OCR is not configured: missing %s', key)
                return
            os.environ[key] = value
        store = db.Store(db.sqlite_url(database))
        try:
            worker = IntakeWatcher(store, folder, known_demo_hashes(root), stop=stop)
            while not stop.is_set():
                worker.tick()
                stop.wait(2)
        finally:
            store.close()
    except OSError:
        LOG.warning('Intake worker unavailable: another worker may hold the lock.')
    finally:
        lock.close()
