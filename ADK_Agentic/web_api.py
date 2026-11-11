"""Document workspace API with upload-triggered OCR and auditable manual page assignment."""
from __future__ import annotations

from contextlib import contextmanager, asynccontextmanager
from pathlib import Path
import json
import io
import zipfile
import threading
import queue
import asyncio
import re
import hashlib
from urllib.parse import unquote

import fitz
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.concurrency import run_in_threadpool

from . import storage as db
from .intake_watcher import ProgressState
from .ticket_names import ticket_filename
from .document_data import page_field_records
from .page_review import compare_page, unify_rental_fields, rental_number

ROOT = Path(__file__).resolve().parents[1]
MAX_UPLOAD_BYTES = 50 * 1024 * 1024


class ReviewChange(BaseModel):
    reviewed: bool


class PageApproval(BaseModel):
    page_id: str
    printed_page: int = Field(ge=1)
    note: str = Field(default="Approved after visual comparison", max_length=500)
    acknowledge_differences: bool = False


def record_downloads(store, tickets, kind):
    """Record only artifacts that have been successfully prepared for download."""
    when = db.utcnow()
    with store.engine.begin() as connection:
        for ticket in tickets:
            connection.execute(db.downloads.insert().values(order_id=ticket['id'], version=ticket['download_version'],
                downloaded_at=when, kind=kind, filename=ticket_filename(ticket)))


def create_app(root=ROOT, databases=None, allowed_roots=None):
    root = Path(root)
    live = databases is None
    databases = databases or {"workspace": root / "demo_runtime/workspace.sqlite"}
    allowed_roots = allowed_roots or [root / "demo_data", root / "demo_batches", root / "Scans"]

    progress = ProgressState()
    submissions = queue.Queue()
    approval_lock = threading.Lock()
    progress_cache = {}
    progress_cache_lock = threading.Lock()

    @asynccontextmanager
    async def lifespan(app):
        stop = threading.Event()
        worker = None
        if live and Path(databases["workspace"]).is_file():
            migration = db.Store(db.sqlite_url(Path(databases["workspace"])))
            try:
                migration.migrate()
            finally:
                migration.close()
            from .intake_watcher import watch
            worker = threading.Thread(target=watch, args=(root, databases["workspace"], root / "Scans/incomming_scan", stop, progress, submissions), daemon=True)
            worker.start()
        app.state.intake_worker = worker
        # Recover only durable upload jobs once at startup; no folder polling.
        for marker in sorted((root / "Scans/incomming_scan").glob("*.queued")):
            target = marker.with_suffix("")
            if target.is_file():
                submissions.put(target)
        yield
        stop.set()
        submissions.put(None)
        if worker:
            worker.join(timeout=1)

    app = FastAPI(title="OCR Workspace API", version="1.0.0", docs_url="/api/docs", redoc_url=None, lifespan=lifespan)
    app.state.intake_progress = progress
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost", "testserver"])

    @contextmanager
    def workspace(dataset):
        if dataset not in databases or not Path(databases[dataset]).is_file():
            raise HTTPException(404, "Dataset not available. Prepare the synthetic demo first.")
        store = db.Store(db.sqlite_url(Path(databases[dataset])))
        try:
            with store.engine.connect() as connection:
                private = sum(connection.scalar(select(func.count()).select_from(table).where(table.c.synthetic.is_(False)))
                              for table in (db.sources, db.documents))
            if private:
                raise HTTPException(403, "This local workspace accepts synthetic data only.")
            yield store
        finally:
            store.close()

    def safe_file(record):
        path = Path(record["path"]).resolve()
        if not any(path.is_relative_to(Path(base).resolve()) for base in allowed_roots) or not path.is_file():
            raise HTTPException(404, "Document not available in this workspace")
        if record.get('sha256'):
            from .etl import checksum
            if checksum(path) != record['sha256']:
                raise HTTPException(409, 'The source PDF has changed since processing')
        return path

    def enrichments():
        result = {}
        paths = [root / "Scans/manifest.json", root / "demo_data/manifest.json",
                 *sorted(root.glob("demo_batches/*/manifest.json"))]
        for path in paths:
            if path.exists():
                data = json.loads(path.read_text())
                if data.get("synthetic") is True and data.get("generator") == "ocr-synthetic-demo-v1":
                    for ticket in data["tickets"]:
                        result[(ticket["order_id"], ticket["shipment"])] = ticket
        return result

    def all_tickets(store):
        extras = {} if live else enrichments()
        extracted_fields = page_field_records(store)
        page_fields = {r['id']: unify_rental_fields(r['payload']) for r in store.rows(select(db.raw_rows).where(db.raw_rows.c.sheet == 'document_fields'))}
        detected_extras = {(r['work_order'], r['shipment']): r for r in page_fields.values()}
        reconciled = {r["database_id"]: r for r in store.reconciliation_rows()}
        review_state = {}
        download_records = {}
        for receipt in store.rows(select(db.downloads).order_by(db.downloads.c.downloaded_at, db.downloads.c.id)):
            download_records.setdefault((receipt['order_id'], receipt['version']), []).append(receipt)
        for event in store.rows(select(db.reviews).order_by(db.reviews.c.created_at)):
            review_state[event["order_id"]] = event["status"] == "reviewed"
        latest_attempts = {}
        for attempt in store.rows(select(db.attempts).order_by(db.attempts.c.started_at, db.attempts.c.id)):
            latest_attempts[attempt["page_id"]] = attempt
        memberships = {}
        page_orders = {}
        for association in store.rows(select(db.associations)):
            entry = memberships.setdefault(association["order_id"], {"synthetic_manifest": set(), "azure_ocr": set()})
            entry[association["method"]].add(association["page_id"])
            if association['method'] == 'azure_ocr':
                page_orders.setdefault(association['page_id'], set()).add(association['order_id'])
        rental_map = {r['order_id']: r['rental_id'] for r in store.rows(select(db.rental_tickets))}
        rentals = {r['id']: r for r in store.rows(select(db.rental_orders))}
        rental_pages = {r['page_id']: r for r in store.rows(select(db.rental_pages))}
        approvals = {r['page_id']: r for r in store.rows(select(db.page_approvals))}
        for approval in approvals.values():
            page_orders.setdefault(approval['page_id'], set()).add(approval['order_id'])
            memberships.setdefault(approval['order_id'], {"synthetic_manifest": set(), "azure_ocr": set()})
        registered_pages = store.rows(select(db.pages.c.id, db.pages.c.document_id, db.pages.c.page_number, db.documents.c.sha256)
            .select_from(db.pages.join(db.documents)))
        sources = {p['id']: p for p in registered_pages}
        page_documents = {p['id']: p['document_id'] for p in registered_pages}
        unidentified_by_document = {}
        for page in registered_pages:
            attempt = latest_attempts.get(page['id'], {})
            if attempt.get('status') in {'no_match', 'error'} and page['id'] not in approvals:
                unidentified_by_document.setdefault(page['document_id'], []).append(dict(
                    id=page['id'], source_page=page['page_number'], identifier=attempt.get('identifier'), status=attempt['status'],
                    fields=extracted_fields.get(page['id'], {})))
        unidentified_by_rental = {}
        for pages in unidentified_by_document.values():
            for page in pages:
                context = rental_pages.get(page['id'])
                if context:
                    unidentified_by_rental.setdefault(context['rental_id'], []).append(page)
        active_documents = {document for page_id, document in page_documents.items()
                            if latest_attempts.get(page_id, {}).get('status') not in {'success', 'no_match', 'error'}}
        tickets = []
        for row in store.order_rows():
            document_driven = row['Source_Sheet'] == 'document_fields'
            extra = unify_rental_fields((detected_extras if document_driven else extras).get((row["Order_ID"], row["SO"]), {}))
            state = reconciled.get(row["database_id"], {})
            total = row["Expected_Pages"] or state.get("Manifest_Pages", 0)
            membership = memberships.get(row["database_id"], {"synthetic_manifest": set(), "azure_ocr": set()})
            expected_ids, actual_ids = membership["synthetic_manifest"], membership["azure_ocr"]
            verified_ids = {page_id for page_id in actual_ids
                            if latest_attempts.get(page_id, {}).get('status') == 'success'
                            and len(page_orders.get(page_id, set())) == 1}
            ocr_verified = len(expected_ids & verified_ids) if expected_ids else len(verified_ids)
            approved = {p: a for p, a in approvals.items() if a['order_id'] == row['database_id']}
            ocr_verified = len((expected_ids & verified_ids if expected_ids else verified_ids) - set(approved))
            accounted_ids = verified_ids | set(approved)
            verified = len(expected_ids & accounted_ids) if expected_ids else len(accounted_ids)
            if document_driven:
                sequence = {page_fields[p].get('page_number') for p in verified_ids if p in page_fields}
                sequence.update(a['printed_page'] for a in approved.values())
                verified = len(sequence)
            flagged = any(latest_attempts.get(page_id, {}).get('status') in {'error', 'no_match'}
                          or len(page_orders.get(page_id, set())) > 1 for page_id in (expected_ids | actual_ids) - set(approved))
            ready = bool(total and verified >= total and not flagged
                         and actual_ids <= verified_ids and expected_ids <= accounted_ids)
            if document_driven:
                ready = ready and sequence == set(range(1, total + 1)) and len(actual_ids | set(approved)) == total
            if document_driven and len(actual_ids | set(approved)) > len(sequence):
                flagged = True
                ready = False
            processing = any(page_documents.get(p) in active_documents for p in actual_ids | set(approved))
            missing_pages = sorted(set(range(1, total + 1)) - sequence) if document_driven and total else []
            related_documents = {page_documents[p] for p in actual_ids | set(approved) if p in page_documents}
            rental_id = rental_map.get(row['database_id'])
            rental = rentals.get(rental_id, {})
            unknown_parent = [p for doc in related_documents for p in unidentified_by_document.get(doc, []) if p['id'] not in rental_pages]
            candidates = list({p['id']: p for p in [*unidentified_by_rental.get(rental_id, []), *unknown_parent]}.values()) if rental_id else unknown_parent
            unidentified = sorted(candidates, key=lambda p: p['source_page']) if missing_pages else []
            gap_status = ('processing' if processing else 'unidentified_in_scan' if unidentified else 'not_in_scan') if missing_pages else None
            selected_ids = (expected_ids or actual_ids) | set(approved)
            content_pages = sorted((sources[p]['sha256'], sources[p]['page_number'],
                approved[p]['printed_page'] if p in approved else page_fields.get(p, {}).get('page_number') or sources[p]['page_number'])
                for p in selected_ids)
            version = hashlib.sha256(json.dumps(content_pages, separators=(',', ':')).encode()).hexdigest()
            receipts = download_records.get((row['database_id'], version), []) if ready else []
            tickets.append(dict(id=row["database_id"], work_order=row["Order_ID"], shipment=row["SO"],
                customer=row["Customer_name"], delivery_location=row["Ship_to"],
                data_source="document" if document_driven else "tracker",
                rental_id=rental_id, parent_rental_number=rental.get('rental_number') or rental_number(extra), ticket_number=row['Order_ID'] if row['Order_ID'].startswith(('TK-', 'OD-')) else None,
                rental_order=rental.get('rental_number') or rental_number(extra),
                customer_order_number=extra.get('customer_order_number'),
                billing_address=extra.get("address"), billing_address_source=("document" if document_driven else "synthetic_manifest") if extra.get("address") else None,
                status=row["Status"], order_date=row["Today"], due_date=row["Deadline"],
                assigned_to=row["Requested by"], order_type=row["Order_Type"],
                expected_pages=total, verified_pages=verified, ocr_verified_pages=ocr_verified, manually_approved_pages=len(approved),
                ocr_status="verified" if ready else "pending" if not verified else "partial",
                download_ready=ready, flagged=flagged, processing=processing, missing_pages=missing_pages,
                unaccounted_pages=missing_pages, page_gap_status=gap_status, unidentified_scan_pages=unidentified,
                download_version=version, downloaded=bool(receipts), downloaded_at=receipts[-1]['downloaded_at'] if receipts else None,
                download_count=len(receipts),
                reviewed=review_state.get(row["database_id"], False)))
        for ticket in tickets:
            ticket['unidentified_scan_pages'] = [dict(page, review={str(number): compare_page(ticket, page.get('fields', {}), number)
                for number in ticket['unaccounted_pages']}) for page in ticket['unidentified_scan_pages']]
            ticket['candidate_summary'] = {str(number): dict(
                possible=sum(not p['review'][str(number)]['blocked'] for p in ticket['unidentified_scan_pages']),
                different=sum(p['review'][str(number)]['blocked'] for p in ticket['unidentified_scan_pages']))
                for number in ticket['unaccounted_pages']}
            ticket['pages_needing_upload'] = [number for number in ticket['unaccounted_pages']
                if ticket['candidate_summary'][str(number)]['possible'] == 0 and not ticket['processing']]
            if ticket['pages_needing_upload'] and len(ticket['pages_needing_upload']) == len(ticket['unaccounted_pages']) and ticket['unidentified_scan_pages']:
                ticket['page_gap_status'] = 'no_compatible_image'
        return sorted(tickets, key=lambda r: (r["shipment"] or "", r["work_order"]), reverse=True)

    def find_ticket(store, ticket_id):
        row = next((r for r in all_tickets(store) if r["id"] == ticket_id), None)
        if not row:
            raise HTTPException(404, "Work order not found")
        return row

    def ticket_pages(store, ticket_id):
        rows = store.rows(select(db.pages.c.id, db.pages.c.page_number, db.documents.c.id.label("document_id"),
                                 db.documents.c.path, db.documents.c.sha256, db.associations.c.method)
            .select_from(db.associations.join(db.pages).join(db.documents))
            .where(db.associations.c.order_id == ticket_id)
            .order_by(db.documents.c.path, db.pages.c.page_number))
        # Expected membership is independent from the provider's returned association.
        expected = [r for r in rows if r["method"] == "synthetic_manifest"]
        chosen = expected or rows
        unique = {r["id"]: r for r in chosen}
        manual = store.rows(select(db.pages.c.id, db.pages.c.page_number,
            db.documents.c.id.label('document_id'), db.documents.c.path, db.documents.c.sha256,
            db.page_approvals.c.printed_page, db.page_approvals.c.approved_at, db.page_approvals.c.approved_by)
            .select_from(db.page_approvals.join(db.pages).join(db.documents))
            .where(db.page_approvals.c.order_id == ticket_id))
        for page in manual:
            unique[page['id']] = dict(page, method='manual_approval')
        latest = {}
        if unique:
            for attempt in store.rows(select(db.attempts).where(db.attempts.c.page_id.in_(list(unique))).order_by(db.attempts.c.started_at)):
                latest[attempt["page_id"]] = attempt
        extracted = {r['id']: r['payload'] for r in store.rows(select(db.raw_rows).where(db.raw_rows.c.id.in_(list(unique))))} if unique else {}
        if unique and all(p in extracted or unique[p].get('printed_page') for p in unique):
            unique = dict(sorted(unique.items(), key=lambda item: item[1].get('printed_page') or extracted.get(item[0], {}).get('page_number') or 0))
        return unique, latest

    @app.get("/api/health")
    def health():
        return {"status": "ok", "mode": "local_synthetic_workspace",
                "watching": bool(getattr(app.state, "intake_worker", None) and app.state.intake_worker.is_alive()),
                "scan_directory": "Scans/incomming_scan"}

    @app.get("/api/datasets")
    def datasets():
        available = [dict(id=key, label="Dataset") for key, path in databases.items() if Path(path).is_file()]
        return {"datasets": available, "default": available[0]["id"] if available else None}


    @app.get("/api/workspaces/{dataset}")
    def overview(dataset):
        with workspace(dataset) as store:
            tickets = all_tickets(store)
            counts = store.counts()
            recent = store.rows(select(db.attempts.c.finished_at).where(db.attempts.c.status == "success")
                                .order_by(db.attempts.c.finished_at.desc()).limit(1))
            return dict(tickets=len(tickets), pages=counts["document_pages"], documents=counts["documents"],
                rental_orders=len(store.rows(select(db.rental_orders.c.id))),
                missing_tickets=sum(bool(t["missing_pages"]) and not t["processing"] for t in tickets),
                flagged_tickets=sum(t["flagged"] for t in tickets),
                verified_tickets=sum(t["ocr_status"] == "verified" for t in tickets),
                verified_pages=sum(t["verified_pages"] for t in tickets),
                review_queue=sum(not t["reviewed"] for t in tickets),
                rejected_rows=counts["rejected_rows"], last_verified_at=recent[0]["finished_at"] if recent else None,
                synthetic=True)

    @app.get("/api/workspaces/{dataset}/tickets")
    def tickets(dataset, q: str = "", status: str = "all", ocr: str = "all", review: str = "all", document_id: str = ""):
        with workspace(dataset) as store:
            rows = all_tickets(store)
            if document_id:
                linked = {r["order_id"] for r in store.rows(select(db.associations.c.order_id)
                    .select_from(db.associations.join(db.pages)).where(db.pages.c.document_id == document_id))}
                rows = [r for r in rows if r["id"] in linked]
            if q:
                query = q.casefold()
                rows = [r for r in rows if any(query in str(r[k] or "").casefold()
                        for k in ("work_order", "shipment", "customer", "delivery_location", "billing_address", "parent_rental_number"))]
            if status != "all":
                rows = [r for r in rows if r["status"] == status.upper()]
            if ocr == "missing":
                rows = [r for r in rows if r["missing_pages"] and not r["processing"]]
            elif ocr != "all":
                rows = [r for r in rows if (r["ocr_status"] != "verified" if ocr == "pending" else r["ocr_status"] == ocr)]
            if review == "pending":
                rows = [r for r in rows if not r["reviewed"]]
            return {"tickets": rows, "total": len(rows)}

    @app.get("/api/workspaces/{dataset}/rental-orders")
    def rental_order_list(dataset):
        with workspace(dataset) as store:
            tickets = all_tickets(store)
            actual = {r['page_id'] for r in store.rows(select(db.associations.c.page_id).where(db.associations.c.method == 'azure_ocr'))}
            actual.update(r['page_id'] for r in store.rows(select(db.page_approvals.c.page_id)))
            pages = store.rows(select(db.rental_pages))
            rows = store.rows(select(db.rental_orders, db.customers.c.name.label('customer'))
                .select_from(db.rental_orders.join(db.customers)))
            result = []
            for row in rows:
                children = [t for t in tickets if t['rental_id'] == row['id']]
                unassigned = [p['page_id'] for p in pages if p['rental_id'] == row['id'] and p['page_id'] not in actual]
                result.append(dict(id=row['id'], rental_number=row['rental_number'], customer=row['customer'],
                    address=row['address'], tickets=children, ticket_count=len(children),
                    ready_tickets=sum(t['download_ready'] for t in children), unassigned_pages=len(unassigned)))
            return {'rental_orders': result, 'total': len(result)}

    @app.get("/api/workspaces/{dataset}/rental-orders/{rental_id}/download.zip")
    def rental_download(dataset, rental_id):
        with workspace(dataset) as store:
            rental = store.rows(select(db.rental_orders).where(db.rental_orders.c.id == rental_id))
            if not rental:
                raise HTTPException(404, 'Rental order not found')
            ready = [row for row in all_tickets(store) if row['rental_id'] == rental_id and row['download_ready']]
        if not ready:
            raise HTTPException(409, 'No complete tickets are ready for this rental order')
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
            for row in ready:
                response = download(dataset, row['id'], preview=True)
                archive.writestr(ticket_filename(row), response.body)
        with workspace(dataset) as store:
            record_downloads(store, ready, 'rental_zip')
        return Response(buffer.getvalue(), media_type='application/zip', headers={
            'Content-Disposition': f'attachment; filename="{rental[0]["rental_number"]}-ready-tickets.zip"', 'Cache-Control': 'no-store'})

    @app.get("/api/workspaces/{dataset}/tickets/{ticket_id}")
    def ticket(dataset, ticket_id):
        with workspace(dataset) as store:
            row = find_ticket(store, ticket_id)
            extra = {} if row['data_source'] == 'document' else enrichments().get((row["work_order"], row["shipment"]), {})
            extracted = page_field_records(store)
            selected, latest = ticket_pages(store, ticket_id)
            metadata = extra.get("pages", [])
            result = []
            for index, page in enumerate(selected.values()):
                attempt = latest.get(page["id"])
                source = extracted.get(page["id"], {}) if row["data_source"] == "document" else metadata[index] if index < len(metadata) else {}
                manually_approved = page.get('method') == 'manual_approval'
                printed = page.get('printed_page') or source.get('page_number')
                result.append(dict(id=page["id"], number=printed or index + 1, printed_page=printed, source_page=page["page_number"],
                    document_id=page["document_id"], document=Path(page["path"]).name,
                    paper=source.get("document_type", "Ticket page"), copy=source.get("copy"),
                    fields=source if row['data_source'] == 'document' else {},
                    comparison=compare_page(row, source, printed or index + 1) if row['data_source'] == 'document' else None,
                    expected=row['parent_rental_number'] if attempt and str(attempt['identifier'] or '').startswith('RO-') else row["shipment"], extracted=attempt["identifier"] if attempt else None,
                    ocr_status=attempt["status"] if attempt else "pending",
                    matched=bool(attempt and attempt["status"] == "success" and attempt["identifier"] in {row["shipment"], row["work_order"], row["parent_rental_number"]}),
                    manually_approved=manually_approved, accepted=manually_approved or bool(attempt and attempt['status'] == 'success'),
                    approved_at=page.get('approved_at'), approved_by=page.get('approved_by'),
                    processed_at=attempt["finished_at"] if attempt else None,
                    error_code=attempt["error_code"] if attempt else None))
            details = next((p['fields'] for p in result if p.get('fields')), {})
            return dict(**row, pages=result, contact_email=details.get('contact_email') or extra.get("contact_email"),
                        contact_phone=details.get('contact_phone') or extra.get("contact_phone"), items=extra.get("items", []))

    @app.get("/api/workspaces/{dataset}/pages/{page_id}/preview")
    def preview(dataset, page_id):
        with workspace(dataset) as store:
            rows = store.rows(select(db.pages.c.page_number, db.documents.c.path, db.documents.c.sha256)
                .select_from(db.pages.join(db.documents)).where(db.pages.c.id == page_id))
            if not rows:
                raise HTTPException(404, "Page not found")
            path = safe_file(rows[0])
            with fitz.open(path) as pdf:
                image = pdf[rows[0]["page_number"] - 1].get_pixmap(dpi=110).tobytes("png")
            return Response(image, media_type="image/png", headers={"Cache-Control": "private, max-age=60"})

    @app.get("/api/workspaces/{dataset}/tickets/{ticket_id}/download")
    def download(dataset, ticket_id, preview: bool = False):
        with workspace(dataset) as store:
            row = find_ticket(store, ticket_id)
            if not row['download_ready']:
                raise HTTPException(409, "This order is not ready: all expected pages must be matched and verified")
            selected, _ = ticket_pages(store, ticket_id)
            if not selected:
                raise HTTPException(404, "No ticket pages registered")
            with fitz.open() as result:
                ordered = list(selected.values())
                checked_paths = {}
                for page in ordered:
                    if page['path'] not in checked_paths:
                        checked_paths[page['path']] = safe_file(page)
                    with fitz.open(checked_paths[page['path']]) as source:
                        result.insert_pdf(source, from_page=page["page_number"] - 1, to_page=page["page_number"] - 1)
                content = result.tobytes(garbage=4, deflate=True)
            if not preview:
                record_downloads(store, [row], 'pdf')
            return Response(content, media_type="application/pdf",
                headers={"Content-Disposition": f'{"inline" if preview else "attachment"}; filename="{ticket_filename(row)}"', 'Cache-Control': 'no-store'})

    @app.post("/api/workspaces/{dataset}/tickets/{ticket_id}/page-approvals")
    def approve_page(dataset, ticket_id, change: PageApproval, request: Request):
        origin = request.headers.get('origin')
        if origin and origin.rstrip('/') != str(request.base_url).rstrip('/'):
            raise HTTPException(403, 'Cross-origin changes are not allowed')
        with approval_lock, workspace(dataset) as store:
            row = find_ticket(store, ticket_id)
            previous = store.rows(select(db.page_approvals).where(db.page_approvals.c.page_id == change.page_id))
            if previous:
                if previous[0]['order_id'] != ticket_id or previous[0]['printed_page'] != change.printed_page:
                    raise HTTPException(409, 'This image is already assigned to another page or order')
            else:
                if row['processing']:
                    raise HTTPException(409, 'Wait for this scan to finish before assigning pages')
                if change.printed_page not in row['unaccounted_pages']:
                    raise HTTPException(409, 'This printed page is already accounted for or outside the expected page count')
                if change.page_id not in {p['id'] for p in row['unidentified_scan_pages']}:
                    raise HTTPException(409, 'Choose an unidentified page from this rental order or its original source scan')
            candidates = store.rows(select(db.pages, db.documents.c.path, db.documents.c.sha256)
                .select_from(db.pages.join(db.documents)).where(db.pages.c.id == change.page_id))
            if not candidates:
                raise HTTPException(404, 'Source page not found')
            candidate = candidates[0]
            from .etl import checksum
            if checksum(safe_file(candidate)) != candidate['sha256']:
                raise HTTPException(409, 'The source PDF has changed since processing')
            if not previous:
                fields = page_field_records(store).get(change.page_id, {})
                comparison = compare_page(row, fields, change.printed_page)
                if comparison['blocked']:
                    raise HTTPException(409, 'This image conflicts with the target: ' + ', '.join(comparison['conflicts']))
                if comparison['needs_acknowledgment'] and not change.acknowledge_differences:
                    raise HTTPException(409, 'Confirm the shipment difference or unreadable identity after inspecting this image')
                try:
                    with store.engine.begin() as connection:
                        # Recheck ownership inside the write transaction; constraints also protect page/slot uniqueness.
                        owned = connection.scalar(select(db.associations.c.id).where(db.associations.c.page_id == change.page_id,
                            db.associations.c.method == 'azure_ocr').limit(1))
                        if owned:
                            raise HTTPException(409, 'This page already belongs to a detected order')
                        attempt = connection.execute(select(db.attempts).where(db.attempts.c.page_id == change.page_id)
                            .order_by(db.attempts.c.started_at.desc(), db.attempts.c.id.desc()).limit(1)).mappings().first()
                        if not attempt or attempt['status'] not in {'no_match', 'error'}:
                            raise HTTPException(409, 'This page is not waiting for manual identification')
                        connection.execute(db.page_approvals.insert().values(order_id=ticket_id, page_id=change.page_id,
                            printed_page=change.printed_page, attempt_id=attempt['id'], approved_at=db.utcnow(),
                            approved_by='local_user', note=change.note + ('; differences explicitly acknowledged' if change.acknowledge_differences else '')))
                except IntegrityError:
                    raise HTTPException(409, 'This image or printed page was assigned by another request') from None
            from .intake_watcher import prepare_ticket_pdfs
            try:
                ready = prepare_ticket_pdfs(store, candidate['document_id'], root / 'Scans/output', allow_partial=True)
            except (OSError, ValueError, RuntimeError):
                raise HTTPException(503, 'Page approval was saved, but PDF preparation failed. Retry this approval to rebuild the PDF.') from None
            updated = find_ticket(store, ticket_id)
            snapshot = progress.snapshot()
            if snapshot.get('file') in {None, Path(candidate['path']).name} and snapshot['phase'] in {'waiting', 'ready', 'needs_attention', 'error'}:
                doc_pages = {p['id'] for p in store.rows(select(db.pages.c.id).where(db.pages.c.document_id == candidate['document_id']))}
                approved_ids = {a['page_id'] for a in store.rows(select(db.page_approvals))}
                latest = {}
                for attempt in store.rows(select(db.attempts).where(db.attempts.c.page_id.in_(doc_pages)).order_by(db.attempts.c.started_at, db.attempts.c.id)):
                    latest[attempt['page_id']] = attempt['status']
                unresolved = any(status in {'no_match', 'error'} and page_id not in approved_ids for page_id, status in latest.items())
                affected = {a['order_id'] for a in store.rows(select(db.associations.c.order_id).select_from(db.associations.join(db.pages))
                    .where(db.pages.c.document_id == candidate['document_id']))} | {a['order_id'] for a in store.rows(select(db.page_approvals).where(db.page_approvals.c.page_id.in_(doc_pages)))}
                incomplete = unresolved or len(ready) < len(affected)
                progress.update('needs_attention' if incomplete else 'ready', file=Path(candidate['path']).name, document_id=candidate['document_id'],
                    total=len(doc_pages), completed=sum(status in {'success', 'no_match', 'error'} for status in latest.values()),
                    matched=sum(status == 'success' or page_id in approved_ids for page_id, status in latest.items()),
                    ready_tickets=ready, message=f'{len(ready)} complete orders ready. Manual page assignments recorded.')
            else:
                progress.update(snapshot['phase'])
            return {'approved': True, 'ticket': updated}

    @app.post("/api/workspaces/{dataset}/tickets/{ticket_id}/review")
    def review(dataset, ticket_id, change: ReviewChange, request: Request):
        origin = request.headers.get("origin")
        if origin and origin.rstrip("/") != str(request.base_url).rstrip("/"):
            raise HTTPException(403, "Cross-origin review requests are not allowed")
        with workspace(dataset) as store:
            find_ticket(store, ticket_id)
            with store.engine.begin() as connection:
                connection.execute(db.reviews.insert().values(order_id=ticket_id, created_at=db.utcnow(),
                    status="reviewed" if change.reviewed else "pending"))
        return {"reviewed": change.reviewed}

    @app.get("/api/workspaces/{dataset}/documents")
    def documents(dataset):
        with workspace(dataset) as store:
            rows = store.rows(select(db.documents, db.pages.c.id.label("first_page_id"))
                .select_from(db.documents.join(db.pages)).where(db.pages.c.page_number == 1).order_by(db.documents.c.path))
            return {"documents": [dict(id=r["id"], name=Path(r["path"]).name, pages=r["page_count"],
                                        synthetic=r["synthetic"], first_page_id=r["first_page_id"]) for r in rows]}

    @app.post("/api/workspaces/{dataset}/intake")
    async def upload_pdf(dataset, request: Request):
        origin = request.headers.get('origin')
        if origin and origin.rstrip('/') != str(request.base_url).rstrip('/'):
            raise HTTPException(403, 'Cross-origin uploads are not allowed')
        with workspace(dataset):
            pass
        worker = getattr(app.state, 'intake_worker', None)
        if live and (worker is None or not worker.is_alive()):
            raise HTTPException(503, progress.snapshot().get('message') or 'OCR worker is unavailable')
        name = unquote(request.headers.get('x-file-name', 'scan.pdf'))
        if Path(name).name != name or '\\' in name or Path(name).suffix.lower() != '.pdf':
            raise HTTPException(400, 'Choose a PDF file with a plain filename')
        if request.headers.get('content-type', '').split(';')[0] != 'application/pdf':
            raise HTTPException(415, 'Only PDF uploads are accepted')
        maximum = MAX_UPLOAD_BYTES
        incoming = root / 'Scans/incomming_scan'
        staging = root / 'Scans/.uploads'
        incoming.mkdir(parents=True, exist_ok=True)
        staging.mkdir(parents=True, exist_ok=True)
        temporary = staging / f'{db.uid()}.part'
        try:
            total = 0
            with temporary.open('wb') as output:
                async for chunk in request.stream():
                    total += len(chunk)
                    if total > maximum:
                        raise HTTPException(413, 'PDF files must be 50 MB or smaller')
                    output.write(chunk)
            try:
                # Validate bounded bytes so a failed MuPDF open cannot retain
                # a Windows file handle and prevent temporary-file cleanup.
                with fitz.open(stream=temporary.read_bytes(), filetype='pdf') as pdf:
                    if pdf.is_encrypted or len(pdf) < 1:
                        raise ValueError('Unreadable PDF')
                    page_count = len(pdf)
            except Exception:
                raise HTTPException(422, 'This file is not a readable, unencrypted PDF') from None
            from .etl import checksum
            from .intake_watcher import known_demo_hashes
            if checksum(temporary) not in known_demo_hashes(root):
                raise HTTPException(422, 'Use a generated demo PDF from the sample folder')
            safe_name = re.sub(r'[^A-Za-z0-9._-]', '_', Path(name).stem)[:80] or 'scan'
            target = incoming / f'{safe_name}-{db.uid()[:8]}.pdf'
            temporary.replace(target)
            target.with_suffix('.pdf.queued').write_text('queued\n')
            submissions.put(target)
            return {"status": "queued", "file": target.name, "page_count": page_count}
        finally:
            temporary.unlink(missing_ok=True)

    def progress_snapshot(dataset):
        """Scope ZIP counts to the same scan and prepared files as the download."""
        snapshot = progress.snapshot()
        with workspace(dataset) as store, progress_cache_lock:
            cached = progress_cache.get(dataset)
            if cached and cached['revision'] == snapshot['revision']:
                return cached
            documents = store.rows(select(db.documents))
            document = next((d for d in documents if d['id'] == snapshot.get('document_id')), None)
            document = document or next((d for d in documents if Path(d['path']).name == snapshot.get('file')), None)
            restored = live and not snapshot.get('file') and snapshot['phase'] == 'waiting'
            if restored:
                recent = store.rows(select(db.pages.c.document_id).select_from(db.attempts.join(db.pages))
                    .order_by(db.attempts.c.started_at.desc(), db.attempts.c.id.desc()).limit(1))
                document = next((d for d in documents if recent and d['id'] == recent[0]['document_id']), None)
            snapshot['download_summary'] = None
            if document:
                page_ids = {p['id'] for p in store.rows(select(db.pages.c.id).where(db.pages.c.document_id == document['id']))}
                links = store.rows(select(db.associations).where(db.associations.c.page_id.in_(page_ids)))
                approvals = store.rows(select(db.page_approvals).where(db.page_approvals.c.page_id.in_(page_ids)))
                affected = {a['order_id'] for a in [*links, *approvals]}
                fields = page_field_records(store)
                observed_orders = {fields[p].get('work_order') for p in page_ids if p in fields}
                rows = [t for t in all_tickets(store) if t['id'] in affected or t['work_order'] in observed_orders]
                latest = {}
                for attempt in store.rows(select(db.attempts).where(db.attempts.c.page_id.in_(page_ids))
                    .order_by(db.attempts.c.started_at, db.attempts.c.id)):
                    latest[attempt['page_id']] = attempt['status']
                approved = {a['page_id'] for a in approvals}
                unresolved = sum(status in {'no_match', 'error'} and page not in approved for page, status in latest.items())
                completed = sum(status in {'success', 'no_match', 'error'} for status in latest.values())
                if restored:
                    ready = [dict(id=t['id'], work_order=t['work_order'], shipment=t['shipment']) for t in rows
                        if t['download_ready'] and (root / 'Scans/output' / f"ticket-{t['id']}.pdf").is_file()]
                    snapshot.update(file=Path(document['path']).name, document_id=document['id'], total=len(page_ids),
                        completed=completed, matched=sum(status == 'success' or page in approved for page, status in latest.items()),
                        ready_tickets=ready, phase='error' if completed < len(page_ids) else
                            'needs_attention' if unresolved or len(ready) < len(rows) else 'ready',
                        message='Saved scan results restored.')
                prepared = {t['id'] for t in snapshot.get('ready_tickets', [])}
                ready_count = sum(t['id'] in prepared and t['download_ready'] for t in rows)
                snapshot['download_summary'] = dict(total_orders=len(rows), ready_orders=ready_count,
                    not_ready_orders=len(rows) - ready_count,
                    missing_pages=sum(len(t['unaccounted_pages']) if t['data_source'] == 'document'
                        else max(0, t['expected_pages'] - t['verified_pages']) for t in rows),
                    unidentified_pages=unresolved, pending_pages=len(page_ids) - completed)
            progress_cache[dataset] = snapshot
            return snapshot

    app.get("/api/workspaces/{dataset}/progress")(progress_snapshot)

    @app.get("/api/workspaces/{dataset}/progress/tickets.zip")
    def scanned_tickets_zip(dataset, revision: int):
        snapshot = progress_snapshot(dataset)
        with workspace(dataset) as store:
            if snapshot['phase'] not in {'ready', 'needs_attention'} or not snapshot.get('ready_tickets'):
                raise HTTPException(409, "Ticket PDFs are not ready yet")
            if snapshot['revision'] != revision:
                raise HTTPException(409, "The scan has changed. Refresh before downloading")
            output = (root / 'Scans/output').resolve()
            buffer = io.BytesIO()
            downloaded_rows = []
            with zipfile.ZipFile(buffer, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
                for ticket in snapshot['ready_tickets']:
                    row = find_ticket(store, ticket['id'])
                    if not row['download_ready']:
                        raise HTTPException(409, 'A ticket in this scan is no longer ready for download')
                    path = (output / f"ticket-{ticket['id']}.pdf").resolve()
                    if not path.is_relative_to(output) or not path.is_file():
                        raise HTTPException(409, "A completed ticket PDF is unavailable")
                    content = path.read_bytes()
                    try:
                        with fitz.open(stream=content, filetype='pdf') as pdf:
                            if pdf.is_encrypted or len(pdf) < 1:
                                raise ValueError('Invalid ticket PDF')
                    except Exception:
                        raise HTTPException(409, "A completed ticket PDF is unreadable") from None
                    # Prepared files establish readiness, but source originals
                    # remain authoritative. Rebuild through the checksum-checked
                    # individual download path so stale artifacts cannot leak
                    # another ticket's pages into a valid-looking ZIP.
                    content = download(dataset, ticket['id'], preview=True).body
                    name = ticket_filename(row)
                    archive.writestr(f"{row['parent_rental_number']}/{name}" if row.get('parent_rental_number') else name, content)
                    downloaded_rows.append(row)
            if progress.snapshot()['revision'] != revision:
                raise HTTPException(409, "The scan has changed. Refresh before downloading")
            record_downloads(store, downloaded_rows, 'scan_zip')
            return Response(buffer.getvalue(), media_type='application/zip', headers={
                'Content-Disposition': 'attachment; filename="scanned-tickets.zip"',
                'Cache-Control': 'no-store',
            })

    @app.get("/api/workspaces/{dataset}/progress/stream")
    async def progress_stream(dataset, request: Request):
        with workspace(dataset):
            pass
        async def events():
            while not await request.is_disconnected():
                snapshot = await run_in_threadpool(progress_snapshot, dataset)
                yield "data: " + json.dumps(snapshot) + "\n\n"
                await asyncio.sleep(1)
        return StreamingResponse(events(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    @app.get("/api/workspaces/{dataset}/activity")
    def activity(dataset, issues_only: bool = False):
        with workspace(dataset) as store:
            extracted_fields = page_field_records(store)
            latest = {}
            for attempt in store.rows(select(db.attempts).order_by(db.attempts.c.started_at, db.attempts.c.id)):
                latest[attempt["page_id"]] = attempt
            orders = {row["id"]: row for row in all_tickets(store)}
            manual = {r['page_id']: r for r in store.rows(select(db.page_approvals))}
            parent_pages = {r['page_id']: r['rental_id'] for r in store.rows(select(db.rental_pages))}
            parents = {r['id']: r['rental_number'] for r in store.rows(select(db.rental_orders))}
            matched = {}
            for link in store.rows(select(db.associations).where(db.associations.c.method == "azure_ocr")):
                matched.setdefault(link["page_id"], []).append(link["order_id"])
            rows = []
            for page in store.rows(select(db.pages, db.documents.c.path).select_from(db.pages.join(db.documents))):
                attempt = latest.get(page["id"], {})
                links = matched.get(page["id"], [])
                approval = manual.get(page['id'])
                order = orders.get(approval['order_id']) if approval else orders.get(links[0]) if len(links) == 1 and attempt.get("status") == "success" else None
                try:
                    modified = safe_file(page).stat().st_mtime
                except HTTPException:
                    modified = 0
                rows.append(dict(id=attempt.get("id", page["id"]), page_id=page["id"],
                    identifier=attempt.get("identifier"), status="manually_approved" if approval else attempt.get("status", "pending"),
                    original_ocr_status=attempt.get('status'), rental_id=parent_pages.get(page['id']), parent_rental_number=parents.get(parent_pages.get(page['id'])),
                    page=page["page_number"], document_id=page["document_id"], document=Path(page["path"]).name,
                    at=attempt.get("finished_at") or attempt.get("started_at"),
                    error_code=attempt.get("error_code"), matched_order=order, modified=modified,
                    fields=extracted_fields.get(page['id'], {})))
            rows.sort(key=lambda r: (r["modified"], r["document"], -r["page"]), reverse=True)
            counts = {status: sum(r["status"] == status for r in rows)
                      for status in ("pending", "running", "success", "no_match", "error", "manually_approved")}
            document_states = {}
            for row in rows:
                document_states.setdefault(row["document_id"], []).append(row["status"])
            files_read = sum(all(status in {"success", "manually_approved"} for status in statuses) for statuses in document_states.values())
            for row in rows:
                row.pop("modified")
            current_scan = None
            if rows:
                document_id = rows[0]['document_id']
                statuses = document_states[document_id]
                current_scan = dict(file=rows[0]['document'], total=len(statuses),
                    completed=sum(status in {'success', 'no_match', 'error', 'manually_approved'} for status in statuses))
            visible = [row for row in rows if row['status'] in {'no_match', 'error'}] if issues_only else rows
            return {"activity": visible[:200], "total": len(rows), "counts": counts, "current_scan": current_scan,
                    "files": len(document_states), "files_read": files_read}

    @app.get("/api/workspaces/{dataset}/imports")
    def imports(dataset):
        with workspace(dataset) as store:
            return {"imports": store.rows(select(db.runs).order_by(db.runs.c.started_at.desc()).limit(100))}

    static = root / "web"
    if static.exists():
        app.mount("/", StaticFiles(directory=static, html=True), name="workspace")
    return app


app = create_app()
