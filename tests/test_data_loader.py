import time
import sys

import pytest

import pandas as pd

import data_loader


def _write_excel(path, rows):
    pd.DataFrame(rows).to_excel(path, index=False)


def test_loads_excel_and_normalizes_ids(tmp_path, monkeypatch):
    excel_path = tmp_path / "orders.xlsx"
    _write_excel(
        excel_path,
        [
            {
                "Order_ID": " W-108624 ",
                "SO": 19542.0,
                "Customer_name": " ACME ",
                "Ship_to": " Queens ",
            }
        ],
    )
    monkeypatch.setenv("EXCEL_PATH", f' "{excel_path}" ')

    loader = data_loader.DataLoader()

    assert loader.excel_path == str(excel_path)
    assert loader.excel_df.iloc[0]["Order_ID"] == "W-108624"
    assert loader.excel_df.iloc[0]["SO"] == "19542"
    assert loader.excel_df.iloc[0]["Customer_name"] == "ACME"
    assert loader.get_order_by_id("W-108624")["Ship_to"] == "Queens"
    assert loader.get_order_by_id("19542")["Order_ID"] == "W-108624"


def test_missing_excel_path_returns_empty_loader(monkeypatch):
    monkeypatch.delenv("EXCEL_PATH", raising=False)
    loader = data_loader.DataLoader()
    assert loader.excel_df.empty
    assert loader.get_all_orders() == []
    assert loader.get_order_by_id("anything") is None


def test_maybe_reload_detects_file_changes(tmp_path, monkeypatch):
    excel_path = tmp_path / "orders.xlsx"
    _write_excel(excel_path, [{"Order_ID": "1001", "SO": 1111}])
    monkeypatch.setenv("EXCEL_PATH", str(excel_path))

    loader = data_loader.DataLoader()
    initial_mtime = loader.excel_mtime

    time.sleep(0.02)
    _write_excel(excel_path, [{"Order_ID": "1002", "SO": 2222}])

    assert loader.maybe_reload() is True
    assert loader.excel_mtime >= initial_mtime
    assert loader.get_order_by_id("1002")["SO"] == "2222"


def test_search_orders_filters_rows(tmp_path, monkeypatch):
    excel_path = tmp_path / "orders.xlsx"
    _write_excel(
        excel_path,
        [
            {"Order_ID": "1001", "SO": 1111, "Customer_name": "Alpha"},
            {"Order_ID": "1002", "SO": 2222, "Customer_name": "Beta"},
        ],
    )
    monkeypatch.setenv("EXCEL_PATH", str(excel_path))

    loader = data_loader.DataLoader()
    results = loader.search_orders("Alpha")

    assert len(results) == 1
    assert results[0]["Order_ID"] == "1001"


def test_quoted_tracker_path_reloads_and_path_changes_are_detected(tmp_path, monkeypatch):
    excel_path = tmp_path / "quoted orders.xlsx"
    _write_excel(excel_path, [{"Order_ID": "1001", "SO": "2001"}])
    monkeypatch.setenv("EXCEL_PATH", f' "{excel_path}" ')
    monkeypatch.setattr(data_loader, "CACHE_DIR", tmp_path / "cache")
    monkeypatch.setattr(data_loader, "EXCEL_CACHE_FILE", tmp_path / "cache/excel.pkl")
    loader = data_loader.DataLoader()
    _write_excel(excel_path, [{"Order_ID": "1002", "SO": "2002"}])
    assert loader.maybe_reload()
    assert loader.get_order_by_id("1002")["SO"] == "2002"
    assert not loader.maybe_reload()


def test_cache_schema_version_invalidates_legacy_and_stale_normalization(tmp_path, monkeypatch):
    path = tmp_path / "cache.pkl"
    monkeypatch.setattr(data_loader, "EXCEL_CACHE_FILE", path)
    monkeypatch.setattr(data_loader, "CACHE_DIR", tmp_path)
    signature = {"path": "fixture", "size": 1, "mtime_ns": 1}
    frame = pd.DataFrame([{"Order_ID": "1001"}])
    pd.to_pickle({"signature": signature, "data": frame}, path)
    assert data_loader._load_cached_excel(signature) is None
    data_loader._save_cached_excel(signature, frame)
    assert data_loader._load_cached_excel(signature).equals(frame)
    monkeypatch.setattr(data_loader, "EXCEL_CACHE_SCHEMA_VERSION", 2)
    assert data_loader._load_cached_excel(signature) is None


def test_windows_lock_fallback_invokes_shared_read(tmp_path, monkeypatch):
    import io
    payload = io.BytesIO()
    pd.DataFrame([{"Order_ID": "1001"}]).to_excel(payload, index=False)
    original = pd.read_excel
    monkeypatch.setattr(data_loader.sys, "platform", "win32")
    def locked(source, **kwargs):
        if isinstance(source, (str, type(tmp_path))):
            raise PermissionError("simulated spreadsheet lock")
        return original(source, **kwargs)
    monkeypatch.setattr(pd, "read_excel", locked)
    monkeypatch.setattr(data_loader, "_read_file_bytes_windows_shared", lambda path: payload.getvalue())
    assert data_loader._read_excel_resilient("locked.xlsx").iloc[0]["Order_ID"] == 1001


@pytest.mark.skipif(sys.platform != "win32", reason="requires real Win32 APIs")
def test_real_windows_shared_read_returns_file_bytes(tmp_path):
    path = tmp_path / "shared.xlsx"
    path.write_bytes(b"synthetic shared-read fixture")
    with path.open("rb"):
        assert data_loader._read_file_bytes_windows_shared(str(path)) == path.read_bytes()
