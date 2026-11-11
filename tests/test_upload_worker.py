"""Exercise real upload-to-worker delivery without making Azure calls."""
import time

from fastapi.testclient import TestClient

from ADK_Agentic import ocr, storage as db
from ADK_Agentic.web_api import create_app
from scripts.create_demo_data import generate_dataset


def test_upload_starts_ocr_and_recovers_queued_upload_on_restart(tmp_path, monkeypatch):
    data = tmp_path / 'demo_data'
    manifest = generate_dataset(data, count=1, min_pages=6, max_pages=6, rasterize=False)
    runtime = tmp_path / 'demo_runtime'
    runtime.mkdir()
    store = db.Store(db.sqlite_url(runtime / 'workspace.sqlite'))
    store.migrate()
    assert store.counts()['orders'] == 0
    calls = []

    def extract(*args, **kwargs):
        calls.append(1)
        return ocr.ParsedIdentifier('shipment', manifest['tickets'][0]['shipment'])

    monkeypatch.setattr(ocr, 'extract_order_identity', extract)
    monkeypatch.setenv('AZURE_DOC_INTEL_ENDPOINT', 'https://example.invalid')
    monkeypatch.setenv('AZURE_DOC_INTEL_KEY', 'test-only')
    source = data / manifest['tickets'][0]['pdf']
    app = create_app(root=tmp_path)
    with TestClient(app) as client:
        response = client.post('/api/workspaces/workspace/intake', content=source.read_bytes(),
                               headers={'content-type': 'application/pdf', 'x-file-name': 'mixed.pdf'})
        assert response.status_code == 200, response.text
        deadline = time.monotonic() + 5
        while app.state.intake_progress.snapshot()['phase'] != 'ready' and time.monotonic() < deadline:
            time.sleep(.01)
        assert app.state.intake_progress.snapshot()['phase'] == 'ready'
        assert len(calls) == 6
        assert not list((tmp_path / 'Scans/incomming_scan').glob('*.queued'))
    # Simulate an accepted submission surviving a server stop before delivery.
    path = tmp_path / 'Scans/incomming_scan/recovered.pdf'
    path.write_bytes(source.read_bytes())
    path.with_suffix('.pdf.queued').write_text('queued\n')
    app = create_app(root=tmp_path)
    with TestClient(app):
        deadline = time.monotonic() + 5
        while app.state.intake_progress.snapshot()['phase'] != 'ready' and time.monotonic() < deadline:
            time.sleep(.01)
        assert app.state.intake_progress.snapshot()['phase'] == 'ready'
        assert len(calls) == 6  # Previously processed content does not incur more OCR calls.
        assert not path.with_suffix('.pdf.queued').exists()
    store.close()
