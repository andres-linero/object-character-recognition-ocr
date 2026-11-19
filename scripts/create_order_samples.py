"""Create shuffled sample scans for the shared-count order numbering.

Rental orders (RO-) and sales orders (SO-) draw their numbers from one shared
count. A rental order creates one or more work orders (W-), three pages each.
A sales order creates one or more shipments, one page each. Work orders and
shipments have their own counts.

Output (default ``demo_data/order_samples``): several shuffled PDFs, each under
250 pages, ``orders.csv`` (Order, Work order, Address, ...) and ``manifest.json``.
Everything is fictional. No Azure calls are made.
"""
import argparse
import csv
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import random
import sys

import pymupdf as fitz

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import create_demo_data as demo

# Page targets per PDF; the last file takes whatever remains.
TARGET_PAGES = (156, 230, 204, 244, 212)
MAX_PAGES = 250
WORK_ORDER_PAGES = 3
SHIPMENT_PAGES = 1


def build_orders(count=300, seed=2026):
    """Return orders with their work orders or shipments, numbered from one shared count."""
    rng = random.Random(seed)
    people = demo.build_tickets(count, seed=seed, min_pages=3, max_pages=3)
    kinds = ["RO"] * (count // 2) + ["SO"] * (count - count // 2)
    rng.shuffle(kinds)
    orders, work_orders, shipments = [], 0, 0
    for number, (kind, person) in enumerate(zip(kinds, people), 1):
        # One billing address per order, shared by all of its work orders or shipments.
        person = replace(person, address=f"{100 + number} Simulation Way, Demo City, ZZ 00000")
        order = dict(order=f"{kind}-{number:07d}", kind=kind, customer=person.customer,
                     address=person.address, documents=[], person=person)
        children = rng.choice((1, 2, 2, 3)) if kind == "RO" else rng.choice((1, 2, 3, 4))
        for _ in range(children):
            if kind == "RO":
                work_orders += 1
                order["documents"].append(dict(label=f"W-{work_orders:07d}", pages=WORK_ORDER_PAGES))
            else:
                shipments += 1
                order["documents"].append(dict(label=f"Shipment {shipments:05d}", pages=SHIPMENT_PAGES))
        orders.append(order)
    return orders


def _pages(order):
    return sum(document["pages"] for document in order["documents"])


def split_into_files(orders):
    """Keep every order inside one PDF; fill each file up to its target."""
    files, current, target = [], [], 0
    for order in orders:
        limit = TARGET_PAGES[len(files)] if len(files) < len(TARGET_PAGES) else MAX_PAGES - 1
        if current and target + _pages(order) > limit and len(files) < len(TARGET_PAGES):
            files.append(current)
            current, target = [], 0
        current.append(order)
        target += _pages(order)
    files.append(current)
    sizes = [sum(_pages(o) for o in group) for group in files]
    if any(size >= MAX_PAGES for size in sizes):
        raise ValueError(f"A PDF would reach {MAX_PAGES} pages: {sizes}")
    return files


def _draw(order, document, page_number, rasterize, target_pdf):
    person = order["person"]
    if order["kind"] == "RO":
        ticket = replace(person, order_id=document["label"], parent_order_number=order["order"],
                         page_count=WORK_ORDER_PAGES)
    else:
        ticket = replace(person, order_id=document["label"], parent_order_number=order["order"],
                         page_count=SHIPMENT_PAGES)
    kind = ticket.document_types[page_number - 1]
    with fitz.open() as source:
        page = source.new_page(width=demo.PAGE_WIDTH, height=demo.PAGE_HEIGHT)
        demo._draw_page(page, ticket, kind, 1, 1, page_number)
        if rasterize:
            pixmap = page.get_pixmap(dpi=120, alpha=False)
            target = target_pdf.new_page(width=demo.PAGE_WIDTH, height=demo.PAGE_HEIGHT)
            target.insert_image(target.rect, stream=pixmap.tobytes("jpeg", jpg_quality=85))
        else:
            target_pdf.insert_pdf(source)
    return kind


def create(output, count=300, seed=2026, rasterize=True):
    output = Path(output)
    if output.exists() and any(output.iterdir()):
        marker = output / "manifest.json"
        if not marker.exists() or json.loads(marker.read_text()).get("generator") != "ocr-order-samples-v1":
            raise ValueError(f"{output} is not empty and was not created by this script")
        for old in output.iterdir():
            old.unlink()
    output.mkdir(parents=True, exist_ok=True)
    orders = build_orders(count, seed)
    rows, files = [], []
    for index, group in enumerate(split_into_files(orders), 1):
        sequence = [(order, document, number) for order in group for document in order["documents"]
                    for number in range(1, document["pages"] + 1)]
        random.Random(seed + index).shuffle(sequence)
        name = f"sample_scan_{index:02d}_{len(sequence)}_pages.pdf"
        with fitz.open() as pdf:
            for position, (order, document, number) in enumerate(sequence, 1):
                paper = _draw(order, document, number, rasterize, pdf)
                document["file"] = name
                document.setdefault("scan_pages", []).append(dict(scan_page=position, printed_page=number, paper=paper))
            pdf.save(output / name, garbage=4, deflate=True)
        files.append(dict(pdf=name, pages=len(sequence), orders=len(group),
                          sha256=hashlib.sha256((output / name).read_bytes()).hexdigest()))
        for order in group:
            for document in order["documents"]:
                rows.append({"Order": order["order"], "Work order": document["label"], "Address": order["address"],
                             "Customer": order["customer"], "Pages": document["pages"], "File": name})
    with (output / "orders.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    manifest = dict(generator="ocr-order-samples-v1", synthetic=True, seed=seed,
        orders=len(orders), rental_orders=sum(o["kind"] == "RO" for o in orders),
        sales_orders=sum(o["kind"] == "SO" for o in orders),
        work_orders=sum(len(o["documents"]) for o in orders if o["kind"] == "RO"),
        shipments=sum(len(o["documents"]) for o in orders if o["kind"] == "SO"),
        total_pages=sum(f["pages"] for f in files), files=files,
        records=[dict(order=o["order"], customer=o["customer"], address=o["address"], documents=o["documents"])
                 for o in orders])
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest


def register(root, manifest, source):
    """Copy the sample PDFs into the workspace and allow them to be uploaded.

    Adds records to ``Scans/manifest.json``; existing uploads, results and
    history are not touched.
    """
    import shutil
    scans = Path(root) / "Scans"
    incoming = scans / "incomming_scan"
    incoming.mkdir(parents=True, exist_ok=True)
    path = scans / "manifest.json"
    data = json.loads(path.read_text()) if path.exists() else dict(
        generator="ocr-synthetic-demo-v1", synthetic=True, tickets=[], batches=[])
    files = {item["pdf"]: item for item in manifest["files"]}
    names = {f"incomming_scan/{name}" for name in files}
    data["tickets"] = [t for t in data.get("tickets", []) if t.get("pdf") not in names]
    data["batches"] = [b for b in data.get("batches", []) if b.get("pdf") not in names]
    for name, item in files.items():
        shutil.copyfile(Path(source) / name, incoming / name)
        data["batches"].append(dict(pdf=f"incomming_scan/{name}", pages=item["pages"]))
    for record in manifest["records"]:
        for document in record["documents"]:
            name = document["file"]
            data["tickets"].append(dict(order_id=document["label"], parent_order_number=record["order"],
                customer=record["customer"], address=record["address"], page_count=document["pages"],
                pdf=f"incomming_scan/{name}", pdf_sha256=files[name]["sha256"], sample_role="order_samples",
                pages=document["scan_pages"]))
    temporary = path.with_suffix(".part")
    temporary.write_text(json.dumps(data, indent=2) + "\n")
    temporary.replace(path)
    return len(files)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--output", type=Path, default=ROOT / "demo_data/order_samples")
    parser.add_argument("--count", type=int, default=300, help="Number of orders (RO and SO together)")
    parser.add_argument("--seed", type=int, default=2026)
    parser.add_argument("--vector", action="store_true", help="Keep selectable text instead of scan-like images")
    parser.add_argument("--register", action="store_true",
                        help="Also copy the PDFs into Scans/incomming_scan and allow them to be uploaded in the app")
    args = parser.parse_args()
    result = create(args.output, args.count, args.seed, not args.vector)
    if args.register:
        print(f"Registered {register(ROOT, result, args.output)} PDFs for upload in Scans/incomming_scan")
    print(json.dumps({key: result[key] for key in ("orders", "rental_orders", "sales_orders", "work_orders",
                                                   "shipments", "total_pages")}))
    for item in result["files"]:
        print(f"{item['pdf']}: {item['pages']} pages, {item['orders']} orders")
