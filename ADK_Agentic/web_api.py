"""Read-only synthetic workspace API with a local review action; no Azure calls."""
from __future__ import annotations

from contextlib import contextmanager, asynccontextmanager
from pathlib import Path
import json
import threading
import asyncio

import fitz
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sqlalchemy import func, select
from starlette.middleware.trustedhost import TrustedHostMiddleware

from . import storage as db
from .intake_watcher import ProgressState

ROOT = Path(__file__).resolve().parents[1]


class ReviewChange(BaseModel):
    reviewed: bool


def create_app(root=ROOT, databases=None, allowed_roots=None):
    root = Path(root)
    live = databases is None
    databases = databases or {"workspace": root / "demo_runtime/workspace.sqlite"}
    allowed_roots = allowed_roots or [root / "demo_data", root / "demo_batches", root / "Scans"]

    progress = ProgressState()

    @asynccontextmanager
    async def lifespan(app):
        stop = threading.Event()
        worker = None
        if live and Path(databases["workspace"]).is_file():
            from .intake_watcher import watch
            worker = threading.Thread(target=watch, args=(root, databases["workspace"], root / "Scans/incoming", stop, progress), daemon=True)
            worker.start()
        app.state.intake_worker = worker
        yield
        stop.set()
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
        return path

    def enrichments():
        result = {}
        for relative in ("demo_data/manifest.json", "demo_batches/batch_02/manifest.json", "demo_batches/batch_03/manifest.json", "demo_batches/intake_test_03/manifest.json"):
            path = root / relative
            if path.exists():
                data = json.loads(path.read_text())
                if data.get("synthetic") is True and data.get("generator") == "ocr-synthetic-demo-v1":
                    for ticket in data["tickets"]:
                        result[(ticket["order_id"], ticket["shipment"])] = ticket
        return result

    def all_tickets(store):
        extras = enrichments()
        reconciled = {r["database_id"]: r for r in store.reconciliation_rows()}
        review_state = {}
        for event in store.rows(select(db.reviews).order_by(db.reviews.c.created_at)):
            review_state[event["order_id"]] = event["status"] == "reviewed"
        latest_attempts = {}
        for attempt in store.rows(select(db.attempts).order_by(db.attempts.c.started_at, db.attempts.c.id)):
            latest_attempts[attempt["page_id"]] = attempt
        memberships = {}
        for association in store.rows(select(db.associations)):
            entry = memberships.setdefault(association["order_id"], {"synthetic_manifest": set(), "azure_ocr": set()})
            entry[association["method"]].add(association["page_id"])
        tickets = []
        for row in store.order_rows():
            extra = extras.get((row["Order_ID"], row["SO"]), {})
            state = reconciled.get(row["database_id"], {})
            total = row["Expected_Pages"] or state.get("Manifest_Pages", 0)
            membership = memberships.get(row["database_id"], {"synthetic_manifest": set(), "azure_ocr": set()})
            expected_ids, actual_ids = membership["synthetic_manifest"], membership["azure_ocr"]
            verified = len(expected_ids & actual_ids) if expected_ids else len(actual_ids)
            tickets.append(dict(id=row["database_id"], work_order=row["Order_ID"], shipment=row["SO"],
                customer=row["Customer_name"], delivery_location=row["Ship_to"],
                billing_address=extra.get("address"), billing_address_source="synthetic_manifest" if extra.get("address") else None,
                status=row["Status"], order_date=row["Today"], due_date=row["Deadline"],
                assigned_to=row["Requested by"], order_type=row["Order_Type"],
                expected_pages=total, verified_pages=verified,
                ocr_status="verified" if total and verified >= total else "pending" if not verified else "partial",
                flagged=any(latest_attempts.get(page_id, {}).get("status") in {"error", "no_match"}
                            for page_id in expected_ids | actual_ids),
                reviewed=review_state.get(row["database_id"], False)))
        return sorted(tickets, key=lambda r: r["shipment"], reverse=True)

    def find_ticket(store, ticket_id):
        row = next((r for r in all_tickets(store) if r["id"] == ticket_id), None)
        if not row:
            raise HTTPException(404, "Work order not found")
        return row

    def ticket_pages(store, ticket_id):
        rows = store.rows(select(db.pages.c.id, db.pages.c.page_number, db.documents.c.id.label("document_id"),
                                 db.documents.c.path, db.associations.c.method)
            .select_from(db.associations.join(db.pages).join(db.documents))
            .where(db.associations.c.order_id == ticket_id)
            .order_by(db.documents.c.path, db.pages.c.page_number))
        # Expected membership is independent from the provider's returned association.
        expected = [r for r in rows if r["method"] == "synthetic_manifest"]
        chosen = expected or rows
        unique = {r["id"]: r for r in chosen}
        latest = {}
        if unique:
            for attempt in store.rows(select(db.attempts).where(db.attempts.c.page_id.in_(list(unique))).order_by(db.attempts.c.started_at)):
                latest[attempt["page_id"]] = attempt
        return unique, latest

    @app.get("/api/health")
    def health():
        return {"status": "ok", "mode": "local_synthetic_workspace",
                "watching": bool(getattr(app.state, "intake_worker", None) and app.state.intake_worker.is_alive()),
                "scan_directory": "Scans/incoming"}

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
                        for k in ("work_order", "shipment", "customer", "delivery_location", "billing_address"))]
            if status != "all":
                rows = [r for r in rows if r["status"] == status.upper()]
            if ocr != "all":
                rows = [r for r in rows if r["ocr_status"] == ocr]
            if review == "pending":
                rows = [r for r in rows if not r["reviewed"]]
            return {"tickets": rows, "total": len(rows)}

    @app.get("/api/workspaces/{dataset}/tickets/{ticket_id}")
    def ticket(dataset, ticket_id):
        with workspace(dataset) as store:
            row = find_ticket(store, ticket_id)
            extra = enrichments().get((row["work_order"], row["shipment"]), {})
            selected, latest = ticket_pages(store, ticket_id)
            metadata = extra.get("pages", [])
            result = []
            for index, page in enumerate(selected.values()):
                attempt = latest.get(page["id"])
                source = metadata[index] if index < len(metadata) else {}
                result.append(dict(id=page["id"], number=index + 1, source_page=page["page_number"],
                    document_id=page["document_id"], document=Path(page["path"]).name,
                    paper=source.get("document_type", "Ticket page"), copy=source.get("copy"),
                    expected=row["shipment"], extracted=attempt["identifier"] if attempt else None,
                    ocr_status=attempt["status"] if attempt else "pending",
                    matched=bool(attempt and attempt["status"] == "success" and attempt["identifier"] == row["shipment"]),
                    processed_at=attempt["finished_at"] if attempt else None,
                    error_code=attempt["error_code"] if attempt else None))
            return dict(**row, pages=result, contact_email=extra.get("contact_email"),
                        contact_phone=extra.get("contact_phone"), items=extra.get("items", []))

    @app.get("/api/workspaces/{dataset}/pages/{page_id}/preview")
    def preview(dataset, page_id):
        with workspace(dataset) as store:
            rows = store.rows(select(db.pages.c.page_number, db.documents.c.path)
                .select_from(db.pages.join(db.documents)).where(db.pages.c.id == page_id))
            if not rows:
                raise HTTPException(404, "Page not found")
            path = safe_file(rows[0])
            with fitz.open(path) as pdf:
                image = pdf[rows[0]["page_number"] - 1].get_pixmap(dpi=110).tobytes("png")
            return Response(image, media_type="image/png", headers={"Cache-Control": "private, max-age=60"})

    @app.get("/api/workspaces/{dataset}/tickets/{ticket_id}/download")
    def download(dataset, ticket_id):
        with workspace(dataset) as store:
            row = find_ticket(store, ticket_id)
            selected, _ = ticket_pages(store, ticket_id)
            if not selected:
                raise HTTPException(404, "No ticket pages registered")
            with fitz.open() as result:
                for page in selected.values():
                    with fitz.open(safe_file(page)) as source:
                        result.insert_pdf(source, from_page=page["page_number"] - 1, to_page=page["page_number"] - 1)
                content = result.tobytes(garbage=4, deflate=True)
            return Response(content, media_type="application/pdf",
                headers={"Content-Disposition": f'attachment; filename="ticket-{row["shipment"]}.pdf"'})

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

    @app.get("/api/workspaces/{dataset}/progress")
    def progress_snapshot(dataset):
        with workspace(dataset):
            return progress.snapshot()

    @app.get("/api/workspaces/{dataset}/progress/stream")
    async def progress_stream(dataset, request: Request):
        with workspace(dataset):
            pass
        async def events():
            while not await request.is_disconnected():
                yield "data: " + json.dumps(progress.snapshot()) + "\n\n"
                await asyncio.sleep(1)
        return StreamingResponse(events(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    @app.get("/api/workspaces/{dataset}/activity")
    def activity(dataset):
        with workspace(dataset) as store:
            latest = {}
            for attempt in store.rows(select(db.attempts).order_by(db.attempts.c.started_at, db.attempts.c.id)):
                latest[attempt["page_id"]] = attempt
            orders = {row["id"]: row for row in all_tickets(store)}
            matched = {}
            for link in store.rows(select(db.associations).where(db.associations.c.method == "azure_ocr")):
                matched.setdefault(link["page_id"], []).append(link["order_id"])
            rows = []
            for page in store.rows(select(db.pages, db.documents.c.path).select_from(db.pages.join(db.documents))):
                attempt = latest.get(page["id"], {})
                links = matched.get(page["id"], [])
                order = orders.get(links[0]) if len(links) == 1 and attempt.get("status") == "success" else None
                try:
                    modified = safe_file(page).stat().st_mtime
                except HTTPException:
                    modified = 0
                rows.append(dict(id=attempt.get("id", page["id"]), page_id=page["id"],
                    identifier=attempt.get("identifier"), status=attempt.get("status", "pending"),
                    page=page["page_number"], document_id=page["document_id"], document=Path(page["path"]).name,
                    at=attempt.get("finished_at") or attempt.get("started_at"),
                    error_code=attempt.get("error_code"), matched_order=order, modified=modified))
            rows.sort(key=lambda r: (r["modified"], r["document"], -r["page"]), reverse=True)
            counts = {status: sum(r["status"] == status for r in rows)
                      for status in ("pending", "running", "success", "no_match", "error")}
            document_states = {}
            for row in rows:
                document_states.setdefault(row["document_id"], []).append(row["status"])
            files_read = sum(all(status == "success" for status in statuses) for statuses in document_states.values())
            for row in rows:
                row.pop("modified")
            return {"activity": rows[:200], "total": len(rows), "counts": counts,
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
