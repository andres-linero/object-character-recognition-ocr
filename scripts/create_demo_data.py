"""Generate fictional, OCR-compatible multi-paper demo tickets without Azure calls.

The default is 100 tickets with 6, 9, or 12 pages each: two to four complete
copies of each of three document types. No source PDF is loaded or copied by this script.
Run ``python scripts/create_demo_data.py --help`` for options.
"""
from __future__ import annotations

import argparse
import csv
from dataclasses import asdict, dataclass
from datetime import date, timedelta
from decimal import Decimal
import json
from pathlib import Path
import random
import shutil
import tempfile
from typing import Sequence

import fitz
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill

GENERATOR_ID = "ocr-synthetic-demo-v1"
ROOT = Path(__file__).resolve().parents[1]
DOCUMENT_TYPES = ("Delivery Ticket", "Rental Agreement", "Delivery Acknowledgement")
COPY_NAMES = ("White", "Yellow", "Blue", "Pink")
COPY_COLORS = ((1, 1, 1), (1, 0.98, 0.80), (0.88, 0.95, 1), (1, 0.91, 0.94))
PAGE_WIDTH, PAGE_HEIGHT = 612, 792
TRACKER_COLUMNS = (
    "Order_ID", "SO", "Customer_name", "Ship_to", "Status", "Today",
    "Deadline", "Deadline Status", "Requested by", "Expected_Pages", "Order_Type",
)
INK = (0.12, 0.17, 0.24)
MUTED = (0.35, 0.39, 0.45)
BLUE = (0.15, 0.30, 0.48)
PALE = (0.94, 0.96, 0.98)


@dataclass(frozen=True)
class Item:
    code: str
    description: str
    quantity: int
    daily_rate: str

    @property
    def amount(self) -> Decimal:
        return Decimal(self.daily_rate) * self.quantity


@dataclass(frozen=True)
class Ticket:
    order_id: str
    shipment: str
    customer: str
    destination: str
    address: str
    contact_email: str
    contact_phone: str
    dispatcher: str
    order_date: date
    deadline: date
    status: str
    page_count: int
    items: tuple[Item, ...]

    def tracker_row(self) -> dict:
        return dict(zip(TRACKER_COLUMNS, (
            self.order_id, self.shipment, self.customer, self.destination,
            self.status, self.order_date, self.deadline,
            "Complete" if self.status == "COMPLETE" else "On schedule",
            self.dispatcher, self.page_count, "RENTAL",
        )))


def validate_options(count: int, min_pages: int, max_pages: int) -> tuple[int, ...]:
    if not 1 <= count <= 1000:
        raise ValueError("count must be between 1 and 1000")
    if min_pages < 3 or max_pages > 12 or min_pages > max_pages:
        raise ValueError("page bounds must satisfy 3 <= min-pages <= max-pages <= 12")
    choices = tuple(n for n in range(min_pages, max_pages + 1) if n % 3 == 0)
    if not choices:
        raise ValueError("page range must contain a multiple of three for complete paper sets")
    return choices


def build_tickets(count: int = 100, seed: int = 42, min_pages: int = 6,
                  max_pages: int = 12, start_date: date = date(2030, 4, 1)) -> list[Ticket]:
    """Create deterministic fictional records; dates do not depend on today's date."""
    choices = validate_options(count, min_pages, max_pages)
    rng = random.Random(seed)
    adjectives = ("Amber", "Cobalt", "Cedar", "Copper", "Indigo", "Maple", "Quartz", "Silver", "Willow", "Zephyr")
    nouns = ("Workshop", "Fabrication", "Assembly", "Structures", "Projects", "Buildworks", "Logistics", "Engineering", "Installations", "Contracting")
    equipment = ("Deck panel", "Support frame", "Adjustable brace", "Base plate", "Safety rail", "Access ladder", "Connector set", "Storage rack")
    tickets = []
    for i in range(count):
        when = start_date + timedelta(days=i % 45)
        customer = f"Demo {adjectives[(i // 10) % 10]} {nouns[i % 10]}"
        items = tuple(Item(f"DEMO-{i + 1:04d}-{j + 1:02d}", description,
                           rng.randint(2, 30), str(Decimal(rng.randint(250, 2400)) / 100))
                      for j, description in enumerate(rng.sample(equipment, rng.randint(3, 6))))
        tickets.append(Ticket(
            order_id=f"W-{990001 + i}", shipment=str(900001 + i), customer=customer,
            destination=f"Demo Depot {i % 12 + 1:02d}",
            address=f"{100 + i} Simulation Way, Demo City, ZZ 00000",
            contact_email=f"dispatch.{i + 1:03d}@example.test",
            contact_phone=f"202-555-{100 + i % 100:04d}",
            dispatcher=f"Dispatch Desk {i % 5 + 1:02d}", order_date=when,
            deadline=when + timedelta(days=rng.randint(3, 14)),
            status="COMPLETE" if i % 5 == 0 else "OPEN", page_count=rng.choice(choices),
            items=items,
        ))
    return tickets


def _text(page, x: float, y: float, value: str, size: float = 10,
          bold: bool = False, color=INK):
    page.insert_text((x, y), str(value), fontsize=size,
                     fontname="hebo" if bold else "helv", color=color)


def _box(page, rect, title: str, lines: Sequence[str]):
    box = fitz.Rect(rect)
    page.draw_rect(box, color=(0.72, 0.77, 0.82), width=0.65)
    _text(page, box.x0 + 10, box.y0 + 17, title, 8, True, MUTED)
    for i, line in enumerate(lines):
        _text(page, box.x0 + 10, box.y0 + 36 + i * 15, line, 9)


def _draw_page(page, ticket: Ticket, kind: str, copy_number: int, copy_count: int,
               page_number: int):
    page.draw_rect(page.rect, fill=COPY_COLORS[copy_number - 1], color=None)
    # Only identifiers and document labels occupy the application's OCR crop.
    _text(page, 36, 39, "NORTHSTAR DEMO EQUIPMENT", 15, True, BLUE)
    _text(page, 36, 58, "Fictional rental and delivery operations", 9, color=MUTED)
    page.draw_rect(fitz.Rect(322, 24, 576, 166), fill=PALE, color=None)
    _text(page, 334, 47, "Delivery Ticket / Shipment", 11, True)
    _text(page, 334, 70, f"Shipment No. {ticket.shipment}", 16, True, BLUE)
    _text(page, 334, 91, f"Work Order No. {ticket.order_id}", 10)
    _text(page, 334, 111, kind, 10, True)
    _text(page, 334, 131, f"{COPY_NAMES[copy_number - 1]} copy {copy_number}/{copy_count} | Page {page_number}/{ticket.page_count}", 9)
    _text(page, 334, 150, "SYNTHETIC DEMO - NOT A REAL ORDER", 8, True, MUTED)
    page.draw_line((36, 185), (576, 185), color=BLUE, width=1.2)
    _text(page, 36, 212, kind.upper(), 18, True, BLUE)
    _text(page, 36, 232, f"{COPY_NAMES[copy_number - 1]} copy - fictional training packet", 9, color=MUTED)
    _box(page, (36, 249, 300, 351), "CUSTOMER / BILL TO", [ticket.customer,
         ticket.address, ticket.contact_email, ticket.contact_phone])
    _box(page, (312, 249, 576, 351), "SHIP TO / DISPATCH", [ticket.destination,
         f"Demo loading bay {int(ticket.shipment) % 12 + 1:02d}", f"Order date: {ticket.order_date.isoformat()}",
         f"Due date: {ticket.deadline.isoformat()}"])
    _text(page, 36, 371, f"Transport: Demo Fleet | Dispatch: {ticket.dispatcher} | Mode: simulated delivery", 9, color=MUTED)
    if kind == "Delivery Ticket":
        page.draw_rect(fitz.Rect(36, 389, 576, 413), fill=BLUE, color=None)
        for x, label in [(44, "ITEM"), (160, "DESCRIPTION"), (379, "QTY"), (431, "RATE"), (507, "AMOUNT")]:
            _text(page, x, 405, label, 8, True, (1, 1, 1))
        for i, item in enumerate(ticket.items):
            top = 413 + i * 28
            if i % 2 == 0:
                page.draw_rect(fitz.Rect(36, top, 576, top + 28), fill=PALE, color=None)
            for x, value in [(44, item.code), (160, item.description), (383, str(item.quantity)),
                             (431, f"${Decimal(item.daily_rate):.2f}"), (507, f"${item.amount:.2f}")]:
                _text(page, x, top + 18, value, 9)
        y = 413 + len(ticket.items) * 28 + 25
        total = sum((item.amount for item in ticket.items), Decimal("0"))
        _text(page, 359, y, "DEMO DAILY TOTAL", 9, True)
        _text(page, 497, y, f"${total:.2f}", 11, True, BLUE)
        _box(page, (36, 635, 576, 696), "DELIVERY NOTES", [
            "Quantities staged for the fictional depot; no actual equipment movement.",
            "All item codes, rates and quantities were generated for training."])
    elif kind == "Rental Agreement":
        _text(page, 36, 406, "DEMO TERMS - NOT A CONTRACT OR LEGAL FORM", 11, True, BLUE)
        paragraphs = (
            ("Purpose", "This page is an original fictional training document for an OCR demonstration."),
            ("Equipment", "The simulated items are listed on the matching delivery ticket in this packet."),
            ("Schedule", "Dates describe an invented workflow and create no delivery or return obligation."),
            ("Charges", "Displayed rates and amounts are sample numbers. No payment is due."),
            ("Condition", "Equipment condition and handling checks are simulated, not actual inspections."),
            ("Acceptance", "No agreement is created. All copies belong to the same synthetic shipment."),
        )
        for i, (title, text) in enumerate(paragraphs):
            y = 438 + i * 38
            _text(page, 36, y, title.upper(), 9, True)
            _text(page, 36, y + 16, text, 9)
        _text(page, 36, 692, "No payment obligation, rental commitment, or legal acceptance is created.", 9, color=MUTED)
    else:
        _text(page, 36, 406, "RECEIVING CHECK - SIMULATED EVIDENCE ONLY", 11, True, BLUE)
        for i, text in enumerate((
            "[X] Ticket number and shipment identifier match the packet.",
            "[X] Listed quantities checked by Demo Receiving Desk.",
            "[X] Packaging condition recorded as demo acceptable.",
            "[X] No missing items reported in this fictional scenario.",
        )):
            _text(page, 44, 440 + i * 29, text, 10)
        _box(page, (36, 565, 576, 641), "ACKNOWLEDGEMENT ROLES", [
            "Receiving: Demo Receiving Desk | Transport: Demo Fleet Desk",
            "NOT SIGNED - DEMO. No handwritten or personal signature is included."])
        _box(page, (36, 655, 576, 710), "DELIVERY RESULT", ["SIMULATED ACCEPTANCE ONLY - NOT PROOF OF DELIVERY"])
    _text(page, 36, 720, "Acknowledgment: DEMO ONLY - no handwriting, signature, or personal identity.", 9)
    page.draw_line((36, 742), (576, 742), color=(0.72, 0.77, 0.82), width=0.6)
    _text(page, 36, 760, "SYNTHETIC DEMO DATA | All entities and transactions are fictional", 8, color=MUTED)
    _text(page, 496, 760, f"Page {page_number}/{ticket.page_count}", 8, color=MUTED)


def write_ticket_pdf(path: Path, ticket: Ticket, rasterize: bool = True) -> list[dict]:
    pages = []
    copy_count = ticket.page_count // 3
    with fitz.open() as pdf:
        for index in range(ticket.page_count):
            kind = DOCUMENT_TYPES[index // copy_count]
            copy_number = index % copy_count + 1
            with fitz.open() as source:
                page = source.new_page(width=PAGE_WIDTH, height=PAGE_HEIGHT)
                _draw_page(page, ticket, kind, copy_number, copy_count, index + 1)
                if rasterize:
                    pixmap = page.get_pixmap(dpi=120, alpha=False)
                    target = pdf.new_page(width=PAGE_WIDTH, height=PAGE_HEIGHT)
                    target.insert_image(target.rect, stream=pixmap.tobytes("jpeg", jpg_quality=85))
                else:
                    pdf.insert_pdf(source)
            pages.append({"page": index + 1, "document_type": kind,
                          "copy": COPY_NAMES[copy_number - 1], "copy_number": copy_number,
                          "expected_ocr_id": ticket.shipment})
        pdf.set_metadata({"title": f"Synthetic demo shipment {ticket.shipment}",
                          "author": "OCR Demo Generator", "subject": "Entirely fictional demo data",
                          "creator": GENERATOR_ID})
        pdf.save(path, garbage=4, deflate=True, no_new_id=True)
    return pages


def _write_tracker(path: Path, tickets: Sequence[Ticket]):
    rows = [ticket.tracker_row() for ticket in tickets]
    with path.with_suffix(".csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=TRACKER_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    wb = Workbook()
    wb.remove(wb.active)
    months = dict.fromkeys(row["Today"].strftime("%b").upper() for row in rows)
    widths = (18, 15, 34, 22, 15, 15, 15, 20, 24, 18, 18)
    for month in months:
        ws = wb.create_sheet(month)
        ws.append(TRACKER_COLUMNS)
        for row in rows:
            if row["Today"].strftime("%b").upper() == month:
                ws.append([row[key] for key in TRACKER_COLUMNS])
        ws.freeze_panes = "A2"
        ws.auto_filter.ref = ws.dimensions
        for col, width in zip(ws.iter_cols(), widths):
            ws.column_dimensions[col[0].column_letter].width = width
        for cell in ws[1]:
            cell.fill = PatternFill("solid", fgColor="264D7B")
            cell.font = Font(bold=True, color="FFFFFF")
            cell.alignment = Alignment(vertical="center")
        ws.row_dimensions[1].height = 25
        for row in ws.iter_rows(min_row=2):
            row[5].number_format = row[6].number_format = "yyyy-mm-dd"
    wb.save(path)


def _check_destination(output: Path, overwrite: bool):
    if output.is_symlink():
        raise ValueError("output must not be a symlink")
    if not output.exists():
        return
    if not output.is_dir():
        raise ValueError("output must be a directory")
    if not any(output.iterdir()):
        return
    if not overwrite:
        raise FileExistsError(f"{output} is not empty; choose a new output or use --overwrite")
    marker = output / "manifest.json"
    try:
        data = json.loads(marker.read_text())
    except (OSError, ValueError) as exc:
        raise ValueError("overwrite requires an existing generator-owned dataset") from exc
    if data.get("generator") != GENERATOR_ID:
        raise ValueError("overwrite requires an existing generator-owned dataset")
    expected = {"manifest.json", "orders.xlsx", "orders.csv", "incoming_scans"}
    if {path.name for path in output.iterdir()} != expected:
        raise ValueError("output contains unexpected files; refusing to overwrite")
    expected_pdfs = {row["pdf"].split("/")[-1] for row in data.get("tickets", [])}
    scans = output / "incoming_scans"
    if (scans.is_symlink() or not scans.is_dir()
            or {p.name for p in scans.iterdir()} != expected_pdfs
            or any(not p.is_file() for p in scans.iterdir())):
        raise ValueError("incoming_scans contains unexpected files; refusing to overwrite")
    if any(p.is_symlink() for p in output.rglob("*")):
        raise ValueError("dataset contains symlinks; refusing to overwrite")


def generate_dataset(output: Path, count: int = 100, seed: int = 42,
                     min_pages: int = 6, max_pages: int = 12,
                     start_date: date = date(2030, 4, 1), overwrite: bool = False,
                     rasterize: bool = True) -> dict:
    """Build an isolated dataset, replacing only a recognized dataset when requested."""
    tickets = build_tickets(count, seed, min_pages, max_pages, start_date)
    output = Path(output).absolute()
    _check_destination(output, overwrite)
    output.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".ocr-demo-build-", dir=output.parent))
    try:
        incoming = staging / "incoming_scans"
        incoming.mkdir()
        manifest_tickets = []
        for ticket in tickets:
            pdf_name = f"demo_ticket_{ticket.shipment}.pdf"
            pages = write_ticket_pdf(incoming / pdf_name, ticket, rasterize)
            record = asdict(ticket)
            record["items"] = list(record["items"])
            record["order_date"] = ticket.order_date.isoformat()
            record["deadline"] = ticket.deadline.isoformat()
            record.update({"pdf": f"incoming_scans/{pdf_name}", "pages": pages})
            manifest_tickets.append(record)
        _write_tracker(staging / "orders.xlsx", tickets)
        manifest = {"generator": GENERATOR_ID, "seed": seed, "count": count,
                    "start_date": start_date.isoformat(), "min_pages": min_pages,
                    "max_pages": max_pages, "document_types": list(DOCUMENT_TYPES),
                    "page_count_rule": "Two to four colored copies of each of three papers by default; total pages are multiples of three.",
                    "rasterized": rasterize, "render_dpi": 120 if rasterize else None,
                    "total_pages": sum(t.page_count for t in tickets), "synthetic": True,
                    "tracker": "orders.xlsx", "tracker_csv": "orders.csv",
                    "tickets": manifest_tickets}
        (staging / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
        if output.exists():
            # Existing nonempty outputs were checked as generator-owned above.
            backup = Path(tempfile.mkdtemp(prefix=".ocr-demo-old-", dir=output.parent))
            backup.rmdir()
            output.rename(backup)
            try:
                staging.rename(output)
            except BaseException:
                backup.rename(output)
                raise
            shutil.rmtree(backup)
        else:
            staging.rename(output)
        return manifest
    finally:
        if staging.exists():
            shutil.rmtree(staging)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--output", type=Path, default=ROOT / "demo_data", help="Isolated output directory (default: repository/demo_data)")
    parser.add_argument("--count", type=int, default=100, help="Number of tickets, 1-1000 (default: 100)")
    parser.add_argument("--seed", type=int, default=42, help="Seed for repeatable fictional records (default: 42)")
    parser.add_argument("--min-pages", type=int, default=6, help="Minimum total pages per ticket (default: 6)")
    parser.add_argument("--max-pages", type=int, default=12, help="Maximum total pages per ticket (default: 12)")
    parser.add_argument("--start-date", type=date.fromisoformat, default=date(2030, 4, 1), help="Fixed starting order date, YYYY-MM-DD")
    parser.add_argument("--overwrite", action="store_true", help="Replace only a recognized generator-owned output dataset")
    parser.add_argument("--vector", action="store_true", help="Keep selectable text instead of default image-only 120dpi pages")
    args = parser.parse_args(argv)
    try:
        result = generate_dataset(args.output, args.count, args.seed, args.min_pages,
                                  args.max_pages, args.start_date, args.overwrite, not args.vector)
    except (ValueError, FileExistsError) as exc:
        parser.error(str(exc))
    print(f"Created {result['count']} synthetic tickets / {result['total_pages']} pages in {args.output.absolute()}")
    print("Each ticket has colored copies of three papers; no real data or reference PDF content was copied.")
    print(f"EXCEL_PATH={args.output.absolute() / 'orders.xlsx'}")
    print(f"SCAN_PDF_PATH={args.output.absolute() / 'incoming_scans'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
