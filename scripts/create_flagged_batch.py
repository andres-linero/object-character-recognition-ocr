"""Create eight synthetic intake PDFs with documented success and failure cases."""
import hashlib
import json
from pathlib import Path

import fitz

from create_demo_data import generate_dataset


def create(output):
    manifest = generate_dataset(output, count=8, seed=811, min_pages=6,
                                max_pages=6, start_index=801)
    cases = ["good", "missing_identifier", "good", "unknown_shipment",
             "missing_identifier", "missing_page", "unknown_shipment", "good"]
    rows = []
    for record, case in zip(manifest["tickets"], cases):
        path = output / record["pdf"]
        if case != "good":
            with fitz.open(path) as pdf:
                if case == "missing_page":
                    pdf.delete_page(len(pdf) - 1)
                    record["pages"] = record["pages"][:-1]
                else:
                    # A single failed page prevents this scan becoming ready.
                    page = pdf[0]
                    page.add_redact_annot(fitz.Rect(306, 0, 612, 198), fill=(1, 1, 1))
                    page.apply_redactions()
                    if case == "unknown_shipment":
                        page.insert_text((334, 47), "Delivery Ticket / Shipment", fontsize=11)
                        page.insert_text((334, 70), "Shipment No. 88888888", fontsize=16)
                temporary = path.with_suffix(".part")
                pdf.save(temporary, garbage=4, deflate=True)
            temporary.replace(path)
        record["pdf_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
        record["test_case"] = case
        rows.append(f"| {path.name} | {record['order_id']} | {case} |")
    manifest["total_pages"] = sum(len(t["pages"]) for t in manifest["tickets"])
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    (output / "TEST_CASES.md").write_text(
        "# Mixed OCR batch\n\n8 PDFs, 47 pages: 3 expected ready and 5 expected flagged.\n\n"
        "| PDF | Work order | Expected case |\n| --- | --- | --- |\n"
        + "\n".join(rows)
        + "\n\nMissing identifier: first page has a blank OCR crop. Unknown shipment: first page reads 88888888, absent from this tracker. Missing page: 5 supplied, 6 expected. OCR outcomes still depend on Azure recognition.\n"
        "\nFiles are staged here, not in watched intake. Upload individually to inspect each outcome; the current progress display tracks the latest file only.\n")
    return manifest


if __name__ == "__main__":
    output = Path(__file__).resolve().parents[1] / "demo_batches/mixed_flags_08"
    result = create(output)
    print(f"Created {result['count']} PDFs / {result['total_pages']} pages in {output}")
