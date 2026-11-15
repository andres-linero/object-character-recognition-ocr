"""Combine eight synthetic orders into a shuffled, multi-order intake PDF."""
from collections import Counter
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import random
import shutil

import fitz


def combine(source, output):
    data = deepcopy(json.loads((source / "manifest.json").read_text()))
    output.mkdir(parents=True, exist_ok=False)
    target = output / "mixed_orders_shuffled.pdf"
    sequence = [(i, n) for i, ticket in enumerate(data["tickets"])
                for n in range(len(ticket["pages"]))]
    random.Random(811).shuffle(sequence)
    mapping = []
    with fitz.open() as combined:
        for position, (index, number) in enumerate(sequence, 1):
            ticket = data["tickets"][index]
            with fitz.open(source / ticket["pdf"]) as original:
                combined.insert_pdf(original, from_page=number, to_page=number)
            mapping.append(dict(scan_page=position, order=ticket["order_id"],
                                original_page=number + 1, case=ticket["test_case"]))
        combined.save(target, garbage=4, deflate=True)
    digest = hashlib.sha256(target.read_bytes()).hexdigest()
    for ticket in data["tickets"]:
        ticket["source_pdf"] = ticket["pdf"]
        ticket["pdf"] = target.name
        ticket["pdf_sha256"] = digest
        for page, position in zip(ticket["pages"], sorted(
                (r for r in mapping if r["order"] == ticket["order_id"]),
                key=lambda r: r["original_page"])):
            page["scan_page"] = position["scan_page"]
    data["scan_page_map"] = mapping
    (output / "manifest.json").write_text(json.dumps(data, indent=2) + "\n")
    shutil.copyfile(source / "orders.xlsx", output / "orders.xlsx")
    shutil.copyfile(source / "orders.csv", output / "orders.csv")
    with fitz.open(target) as check:
        assert len(check) == 47
        check[0].get_pixmap(matrix=fitz.Matrix(0.8, 0.8)).save("/tmp/mixed-scan-preview.png")
    assert len(Counter(r["order"] for r in mapping)) == 8
    print(f"Verified {target}: 47 shuffled pages, 8 orders, {target.stat().st_size} bytes")


if __name__ == "__main__":
    root = Path(__file__).resolve().parents[1]
    combine(root / "demo_batches/mixed_flags_08", root / "demo_batches/mixed_orders_shuffled_08")
