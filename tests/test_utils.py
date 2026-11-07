import utils


def test_pdf_name_for_work_order():
    name = utils.pdf_name(
        {
            "Order_ID": "W-108624",
            "Order_Type": "RO",
            "SO": "5425.0",
            "Customer_name": "Demo Construction",
            "Ship_to": "100 Example Way",
        }
    )
    assert name == "W-108624_RO.5425_Demo Construction_100 Example Way"


def test_pdf_name_for_shipment_order():
    name = utils.pdf_name(
        {
            "Order_ID": "3501",
            "Order_Type": "SO",
            "SO": 3501.0,
            "Customer_name": "ExampleCo",
            "Ship_to": "Bronx",
        }
    )
    assert name == "Shipment 3501_SO.3501_ExampleCo_Bronx"


def test_compiled_lookup_matches_full_tokens_and_distinct_id_spaces(tmp_path):
    names = ["1001.pdf", "Shipment 1001_SO.1001_Demo.pdf", "10010.pdf", "W-11001.pdf", "W-1001_RO.8001_Demo.pdf"]
    for name in names:
        (tmp_path / name).write_bytes(b"synthetic")
    assert {p.name for p in utils.find_compiled_pdfs(tmp_path, "1001")} == set(names[:2])
    assert [p.name for p in utils.find_compiled_pdfs(tmp_path, "W-1001")] == [names[-1]]
    assert utils.find_compiled_pdfs(tmp_path, "../1001") == []


def test_download_names_remove_windows_path_separators():
    name = utils.pdf_name(dict(Order_ID="W-1001", Order_Type="RO", SO="8001", Customer_name='Demo/Build:Team?', Ship_to='Bay\\West*'))
    assert not any(char in name for char in '<>:"/\\|?*')
