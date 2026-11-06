import os
from pathlib import Path

import fitz

import scan_index


def _make_source_pdf(path: Path, pages: int = 3) -> None:
    doc = fitz.open()
    for page_num in range(pages):
        page = doc.new_page()
        page.insert_text((72, 72), f"Source page {page_num + 1}")
    doc.save(path)
    doc.close()


def test_build_index_folder_groups_pages_and_writes_outputs(tmp_path, monkeypatch):
    scans_dir = tmp_path / "upload_ready"
    cache_dir = tmp_path / "cache"
    incoming_dir = tmp_path / "incoming"
    incoming_dir.mkdir()
    pdf_path = incoming_dir / "batch1.pdf"
    _make_source_pdf(pdf_path, pages=3)

    monkeypatch.setattr(scan_index, "SCANS_DIR", scans_dir)
    monkeypatch.setattr(scan_index, "CACHE_DIR", cache_dir)
    monkeypatch.setattr(scan_index, "INDEX_FILE", cache_dir / "scan_index.json")

    results = iter(["W-1001", "W-1001", None])
    monkeypatch.setattr(scan_index, "extract_order_number", lambda *_args, **_kwargs: next(results))

    index = scan_index.ScanIndex()
    built = index.build_index_folder(str(incoming_dir), force=True)

    assert built["W-1001"] == [(str(pdf_path), 0), (str(pdf_path), 1)]
    unmatched_key = f"UNMATCHED_{pdf_path.name}_p3"
    assert built[unmatched_key] == [(str(pdf_path), 2)]

    order_pdf = scans_dir / "W-1001.pdf"
    preview_png = scans_dir / "W-1001.png"
    unmatched_pdf = scans_dir / f"{unmatched_key}.pdf"

    assert order_pdf.exists()
    assert preview_png.exists()
    assert unmatched_pdf.exists()

    compiled_order = fitz.open(order_pdf)
    compiled_unmatched = fitz.open(unmatched_pdf)
    assert compiled_order.page_count == 2
    assert compiled_unmatched.page_count == 1
    compiled_order.close()
    compiled_unmatched.close()

    assert index.find_pages("W-1001") == [0, 1]
    assert index.find_pages("1001") == [0, 1]
    assert index.get_scan_pdf("W-1001") == str(order_pdf)
    assert index.get_scan_preview("1001") == str(preview_png)


def test_pdf_signature_uses_size_and_mtime(tmp_path):
    pdf_path = tmp_path / "same-size.pdf"
    pdf_path.write_bytes(b"abc")

    first = scan_index.ScanIndex._pdf_signature(pdf_path)
    pdf_path.write_bytes(b"xyz")
    os.utime(
        pdf_path,
        ns=(first["mtime_ns"] + 1_000_000, first["mtime_ns"] + 1_000_000),
    )
    second = scan_index.ScanIndex._pdf_signature(pdf_path)

    assert first["size"] == second["size"]
    assert scan_index.ScanIndex._signature_matches(first, second) is False
    assert scan_index.ScanIndex._signature_matches(first["size"], second) is False
