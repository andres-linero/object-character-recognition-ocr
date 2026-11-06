"""Local synthetic-data preview. Separate from authenticated/live Azure execution."""
from pathlib import Path
import os
import json
import sys

import fitz
import pandas as pd
import streamlit as st
from sqlalchemy import func, select

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from ADK_Agentic import storage as db

DATABASE = Path(os.getenv("DEMO_DATABASE_PATH", str(ROOT / "demo_runtime/demo.sqlite")))
ALLOWED_ROOTS = [ROOT / "demo_data", ROOT / "demo_batches"]

st.set_page_config(page_title="OCR Document Processing | Demo", page_icon="📄", layout="wide")
st.title("OCR Document Processing")
st.info("Synthetic documents • local SQL database • this viewer makes no Azure calls or Microsoft sign-in requests. Manifest pages are expected associations; OCR verified pages are completed provider matches.")
if not os.getenv("DEMO_DATABASE_PATH"):
    datasets = {"Full synthetic dataset": ROOT / "demo_runtime/demo.sqlite"}
    validation_database = ROOT / "demo_runtime/ocr_validation.sqlite"
    if validation_database.exists():
        datasets["Azure OCR validation — new batches"] = validation_database
    selected_dataset = st.sidebar.selectbox("Dataset", list(datasets), index=len(datasets) - 1)
    DATABASE = datasets[selected_dataset]
if st.sidebar.button("Refresh results"):
    st.rerun()
if not DATABASE.exists():
    st.error("Prepare the demo first: python3 scripts/prepare_demo.py")
    st.stop()
store = db.Store(db.sqlite_url(DATABASE))
# This entrypoint never loads .env, calls Azure, or initializes live-app state.
with store.engine.connect() as connection:
    private_sources = connection.scalar(select(func.count()).select_from(db.sources).where(db.sources.c.synthetic.is_(False)))
    private_documents = connection.scalar(select(func.count()).select_from(db.documents).where(db.documents.c.synthetic.is_(False)))
if private_sources or private_documents:
    store.close()
    st.error("This preview accepts synthetic data only.")
    st.stop()
counts = store.counts()
metrics = st.columns(4)
for column, label, value in zip(metrics, ["Orders", "Registered pages", "OCR attempts", "Rejected rows"],
                                 [counts["orders"], counts["document_pages"], counts["ocr_attempts"], counts["rejected_rows"]]):
    column.metric(label, value)
st.caption("Excel/CSV → validation and staging → normalized SQL tables → dashboard. SQLite runs this preview; PostgreSQL is the shared-storage target.")

report_path = ROOT / "demo_runtime/ocr_validation_report.json"
if DATABASE.resolve() == (ROOT / "demo_runtime/ocr_validation.sqlite").resolve() and report_path.exists():
    report = json.loads(report_path.read_text())
    total = report["total_pages"]
    processed = total - report["pending"]
    st.progress(processed / total if total else 0,
                text=f"Azure validation: {report['passed']}/{total} passed · {report['mismatch']} mismatches · {report['error']} errors · {report['pending']} pending")
    csv_path = report_path.with_suffix(".csv")
    if csv_path.exists():
        st.download_button("Download page-by-page validation report", csv_path.read_bytes(), "ocr_validation.csv", "text/csv")

orders_tab, documents_tab, quality_tab, history_tab = st.tabs(["Order Reconciliation", "Document Preview", "Data Quality", "Ingestion History"])
with orders_tab:
    frame = pd.DataFrame(store.order_rows())
    if not frame.empty:
        frame = frame.merge(pd.DataFrame(store.reconciliation_rows()), on="database_id", how="left")
    else:
        st.warning("No orders have been imported. Run scripts/prepare_demo.py.")
        store.close()
        st.stop()
    query = st.text_input("Search orders, shipments, customers, or destinations")
    status = st.selectbox("Order status", ["All", "OPEN", "COMPLETE"])
    if query:
        frame = frame[frame[["Order_ID", "SO", "Customer_name", "Ship_to"]].astype(str).apply(
            lambda row: any(query.casefold() in value.casefold() for value in row), axis=1)]
    if status != "All":
        frame = frame[frame["Status"] == status]
    st.dataframe(frame.drop(columns=["database_id"], errors="ignore"), hide_index=True, width="stretch")
    st.download_button("Export displayed orders (CSV)", frame.drop(columns=["database_id"], errors="ignore").to_csv(index=False),
                       "demo_orders.csv", "text/csv")
with documents_tab:
    docs = store.rows(select(db.documents).order_by(db.documents.c.path))
    if docs:
        choices = {record["id"]: record for record in docs}
        selected = st.selectbox("Ticket PDF", list(choices), format_func=lambda key: Path(choices[key]["path"]).name)
        record = choices[selected]
        path = Path(record["path"]).resolve()
        if not any(path.is_relative_to(root.resolve()) for root in ALLOWED_ROOTS):
            st.error("Document is outside the synthetic dataset directories.")
        elif not path.is_file():
            st.error("The registered document is missing from local storage.")
        else:
            page = st.number_input("Page", min_value=1, max_value=record["page_count"], value=1, step=1)
            with fitz.open(path) as pdf:
                st.image(pdf[int(page) - 1].get_pixmap(dpi=100).tobytes("png"), width=650)
            st.caption(f"{record['page_count']} pages • image-only synthetic packet • stored file checksum recorded at registration")
            st.download_button("Download ticket PDF", path.read_bytes(), path.name, "application/pdf")
with quality_tab:
    st.subheader("Validation results")
    failures = store.rows(select(db.rejected.c.reason, db.raw_rows.c.sheet, db.raw_rows.c.row_number,
                                 db.runs.c.started_at).select_from(db.rejected.join(db.raw_rows).join(db.runs)))
    if failures:
        st.dataframe(pd.DataFrame(failures), hide_index=True, width="stretch")
    else:
        st.success("No rejected tracker rows in this demo database.")
    st.write("Checks include identifier format, required customer, supported status, valid dates, positive page counts, duplicate order IDs, and relational constraints.")
    st.warning("Registered pages and manifest associations are not OCR accuracy measurements. Live Azure verification remains separate.")
with history_tab:
    history = store.rows(select(db.runs).order_by(db.runs.c.started_at.desc()))
    st.dataframe(pd.DataFrame(history), hide_index=True, width="stretch")
    st.caption("Rerunning preparation records another ingestion run while upserting the same business keys. It does not duplicate orders or pages.")
store.close()
