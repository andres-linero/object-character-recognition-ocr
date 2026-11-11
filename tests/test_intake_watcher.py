"""Folder intake detects stable PDFs and persists actual matching without repeat calls."""
import shutil
import fitz
import pytest
from pathlib import Path

from sqlalchemy import select
from ADK_Agentic import storage as db
from ADK_Agentic.etl import ingest_tracker, checksum
from ADK_Agentic.intake_watcher import IntakeWatcher
from scripts.create_demo_data import generate_dataset


@pytest.mark.parametrize('upload_triggered', [False, True])
def test_watched_folder_ignores_outside_samples_then_reads_each_page_once(tmp_path, upload_triggered):
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
            if upload_triggered:
                assert worker.progress.snapshot()['total'] == 6
                assert worker.progress.snapshot()['completed'] == len(calls)
            calls.append(1)
            return manifest['tickets'][0]['shipment']
        worker = IntakeWatcher(store, folder, {checksum(pdf)}, extract)
        worker.tick()
        assert store.counts()['documents'] == 0
        shutil.copy2(pdf, folder / 'new_scan.PDF')
        if upload_triggered:
            worker.tick(submitted=folder / 'new_scan.PDF')
        else:
            worker.tick()
            assert not calls  # file must be observed stable twice
            worker.tick()
        assert len(calls) == 6
        assert worker.progress.snapshot()['phase'] == 'ready'
        assert worker.progress.snapshot()['matched'] == worker.progress.snapshot()['total'] == 6
        output = next((folder.parent / 'output').glob('*.pdf'))
        with fitz.open(output) as result:
            assert len(result) == 6
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


@pytest.mark.parametrize('failure', ['no_match', 'pdf_error'])
def test_progress_cannot_announce_ready_for_unmatched_pages_or_failed_pdf(tmp_path, monkeypatch, failure):
    from ADK_Agentic import intake_watcher
    outside = tmp_path / 'samples'
    manifest = generate_dataset(outside, count=1, min_pages=6, max_pages=6, rasterize=False)
    pdf = outside / manifest['tickets'][0]['pdf']
    store = db.Store(db.sqlite_url(tmp_path / 'workspace.sqlite'))
    try:
        store.migrate()
        ingest_tracker(store, outside / 'orders.xlsx', 'demo', synthetic=True)
        def extractor(*args, **kwargs):
            return None if failure == 'no_match' else manifest['tickets'][0]['shipment']
        if failure == 'pdf_error':
            def fail_pdf(*args):
                raise OSError('simulated PDF write failure')
            monkeypatch.setattr(intake_watcher, 'prepare_ticket_pdfs', fail_pdf)
        worker = IntakeWatcher(store, tmp_path / 'incoming', {checksum(pdf)}, extractor)
        shutil.copy2(pdf, worker.folder / 'new.pdf')
        worker.tick()
        assert worker.progress.snapshot()['phase'] == 'receiving'
        worker.tick()
        result = worker.progress.snapshot()
        assert result['phase'] == ('needs_attention' if failure == 'no_match' else 'error')
        assert result['ready_tickets'] == []
        assert (tmp_path / 'flag_order/new.pdf').is_file()
        assert (tmp_path / 'flag_order/new.json').is_file()
        if failure == 'pdf_error':
            assert result['failed_at'] == 'preparing_pdf'
    finally:
        store.close()


def test_generated_manifest_recognizes_sample_moved_before_app_starts(tmp_path):
    from ADK_Agentic.intake_watcher import known_demo_hashes
    dataset = tmp_path / 'demo_data'
    manifest = generate_dataset(dataset, count=1, min_pages=6, max_pages=6, rasterize=False)
    sample = dataset / manifest['tickets'][0]['pdf']
    digest = checksum(sample)
    incoming = tmp_path / 'Scans/incoming'
    incoming.mkdir(parents=True)
    shutil.move(sample, incoming / sample.name)
    assert digest in known_demo_hashes(tmp_path)


def test_replacing_sample_file_does_not_expand_the_recorded_allowlist(tmp_path):
    from ADK_Agentic.intake_watcher import known_demo_hashes
    dataset = tmp_path / 'demo_data'
    manifest = generate_dataset(dataset, count=1, min_pages=6, max_pages=6, rasterize=False)
    sample = dataset / manifest['tickets'][0]['pdf']
    original = checksum(sample)
    with sample.open('ab') as modified:
        modified.write(b'\n% changed after generation\n')
    hashes = known_demo_hashes(tmp_path)
    assert checksum(sample) not in hashes
    assert original in hashes


def test_worker_waits_for_old_live_connection_to_release_lock(tmp_path, monkeypatch):
    import errno
    import threading
    from ADK_Agentic import intake_watcher
    attempts = []
    def lock_after_restart(lock):
        attempts.append(1)
        if len(attempts) == 1:
            raise BlockingIOError(errno.EAGAIN, 'previous worker still shutting down')
    monkeypatch.setattr(intake_watcher, '_try_worker_lock', lock_after_restart)
    stop = threading.Event()
    monkeypatch.setattr(stop, 'wait', lambda seconds: False)
    progress = intake_watcher.ProgressState()
    with (tmp_path / 'worker.lock').open('a+b') as lock:
        assert intake_watcher._acquire_worker_lock(lock, stop, progress)
    assert len(attempts) == 2
    assert progress.snapshot()['phase'] == 'waiting'
