"""Folder intake detects stable PDFs and persists actual matching without repeat calls."""
import shutil
from pathlib import Path

from sqlalchemy import select
from ADK_Agentic import storage as db
from ADK_Agentic.etl import ingest_tracker, checksum
from ADK_Agentic.intake_watcher import IntakeWatcher
from scripts.create_demo_data import generate_dataset


def test_watched_folder_ignores_outside_samples_then_reads_each_page_once(tmp_path):
    outside = tmp_path / 'ready_to_scan'
    manifest = generate_dataset(outside, count=1, min_pages=6, max_pages=6, rasterize=False)
    pdf = outside / manifest['tickets'][0]['pdf']
    folder = tmp_path / 'incoming'
    store = db.Store(db.sqlite_url(tmp_path / 'workspace.sqlite'))
    try:
        store.migrate()
        ingest_tracker(store, outside / 'orders.xlsx', 'demo', synthetic=True)
        calls = []
        def extract(*args, **kwargs):
            calls.append(1)
            return manifest['tickets'][0]['shipment']
        worker = IntakeWatcher(store, folder, {checksum(pdf)}, extract)
        worker.tick()
        assert store.counts()['documents'] == 0
        shutil.copy2(pdf, folder / 'new_scan.PDF')
        worker.tick()
        assert not calls  # file must be observed stable twice
        worker.tick()
        assert len(calls) == 6
        assert store.counts()['documents'] == 1
        assert store.counts()['ocr_attempts'] == store.counts()['order_document_pages'] == 6
        assert all(r['status'] == 'success' for r in store.rows(select(db.attempts)))
        worker.tick()
        restarted = IntakeWatcher(store, folder, {checksum(pdf)}, extract)
        restarted.tick()
        restarted.tick()
        assert len(calls) == 6
        archive = Path(store.rows(select(db.documents))[0]['path'])
        assert archive.is_relative_to(folder.parent / 'processed')
        (folder / 'new_scan.PDF').unlink()
        assert archive.is_file() and checksum(archive) == checksum(pdf)
    finally:
        store.close()


def test_demo_watcher_does_not_submit_unknown_files(tmp_path):
    store = db.Store(db.sqlite_url(tmp_path / 'workspace.sqlite'))
    try:
        store.migrate()
        worker = IntakeWatcher(store, tmp_path / 'incoming', set(), lambda *a, **k: 'never')
        (worker.folder / 'unknown.pdf').write_bytes(b'unrecognized demo input')
        worker.tick()
        worker.tick()
        assert store.counts()['documents'] == store.counts()['ocr_attempts'] == 0
    finally:
        store.close()
