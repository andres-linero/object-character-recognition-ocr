import time

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
