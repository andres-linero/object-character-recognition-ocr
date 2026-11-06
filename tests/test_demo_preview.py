from pathlib import Path

from streamlit.testing.v1 import AppTest
from ADK_Agentic import storage as db, etl

ROOT = Path(__file__).resolve().parents[1]


def setup_store(tmp_path, synthetic):
    path = tmp_path / "preview.sqlite"
    store = db.Store(db.sqlite_url(path))
    store.migrate()
    tracker = tmp_path / "orders.csv"
    tracker.write_text("Order_ID,SO,Customer_name,Status\nW-900001,800001,Demo Customer,OPEN\n")
    etl.ingest_tracker(store, tracker, synthetic=synthetic)
    store.close()
    return path


def test_preview_reads_synthetic_sql_data_without_signin_or_azure(tmp_path, monkeypatch):
    monkeypatch.setenv("DEMO_DATABASE_PATH", str(setup_store(tmp_path, True)))
    monkeypatch.setenv("AZURE_DOC_INTEL_ENDPOINT", "must-not-be-used")
    app = AppTest.from_file(str(ROOT / "ADK_Agentic/demo_app.py"), default_timeout=20).run()
    assert not app.exception and not app.error
    assert app.metric[0].value == "1"
    assert app.metric[2].value == "0"
    app.text_input[0].set_value("no matching customer").run()
    assert app.dataframe[0].value.empty
    assert not app.exception


def test_preview_refuses_non_synthetic_sources(tmp_path, monkeypatch):
    monkeypatch.setenv("DEMO_DATABASE_PATH", str(setup_store(tmp_path, False)))
    app = AppTest.from_file(str(ROOT / "ADK_Agentic/demo_app.py"), default_timeout=20).run()
    assert not app.exception
    assert "synthetic data only" in app.error[0].value


def test_live_app_still_requires_sso(monkeypatch):
    for key in ("AZURE_TENANT_ID", "AZURE_CLIENT_ID", "AZURE_CLIENT_SECRET"):
        monkeypatch.delenv(key, raising=False)
    app = AppTest.from_file(str(ROOT / "ADK_Agentic/streamlit_app.py"), default_timeout=20).run()
    assert not app.exception
    assert "Microsoft SSO is not configured" in app.error[0].value
