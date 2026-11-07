"""
Optical Character Recognition (OCR) — Streamlit HTML View
Manage work orders, view tickets, and track downloaded PDFs.
Run: streamlit run ADK_Agentic/streamlit_app.py
"""

import html
import os
import re
import secrets
import sys
from pathlib import Path

import pandas as pd
import altair as alt

# Ensure ADK_Agentic is on the path
sys.path.insert(0, os.path.dirname(__file__))

from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

# Try Azure Key Vault — overrides .env values if available
from config import load_secrets
load_secrets()

import streamlit as st

from scan_index import get_scan_index, cleanup_old_files
from data_loader import get_data_loader
from utils import pdf_name as pdf_name_fn, find_compiled_pdfs

OUTPUT_DIR = Path(__file__).parent / "output"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

MONO = "'JetBrains Mono', 'Fira Code', 'SF Mono', 'Cascadia Code', 'Consolas', monospace"


def _html_text(value) -> str:
    """Escape user/workbook text before inserting it into custom HTML."""
    text = str(value or "—").strip() or "—"
    return html.escape(text)


def _safe_order_token(value) -> str | None:
    """Return a filesystem-safe order identifier, or None if it is invalid."""
    token = str(value or "").strip()
    return token if re.fullmatch(r"(?:W-\d+|\d+)", token, re.IGNORECASE) else None

# --- Download tracking ---
# Two parallel registries: compiled (final per-order PDF) and ticket (raw scan).
# the operator can pull either one — we track them independently because pulling the
# scan doesn't mean the compiled file was sent.
DOWNLOADS_FILE = Path(__file__).parent / "cache" / "downloads.json"
DOWNLOADS_TICKETS_FILE = Path(__file__).parent / "cache" / "downloads_tickets.json"
REVIEW_STATUS_FILE = Path(__file__).parent / "cache" / "scan_review_status.json"


def _load_downloaded():
    """Load set of order IDs whose compiled PDF has been downloaded."""
    if DOWNLOADS_FILE.exists():
        try:
            import json
            return set(json.loads(DOWNLOADS_FILE.read_text()))
        except Exception:
            return set()
    return set()


def _mark_downloaded(order_id: str):
    """Mark a compiled PDF as downloaded."""
    import json
    downloaded = _load_downloaded()
    downloaded.add(order_id)
    DOWNLOADS_FILE.parent.mkdir(parents=True, exist_ok=True)
    DOWNLOADS_FILE.write_text(json.dumps(sorted(downloaded)))


def _load_downloaded_tickets():
    """Load set of order IDs whose raw ticket scan has been downloaded."""
    if DOWNLOADS_TICKETS_FILE.exists():
        try:
            import json
            return set(json.loads(DOWNLOADS_TICKETS_FILE.read_text()))
        except Exception:
            return set()
    return set()


def _mark_ticket_downloaded(order_id: str):
    """Mark a ticket scan as downloaded."""
    import json
    downloaded = _load_downloaded_tickets()
    downloaded.add(order_id)
    DOWNLOADS_TICKETS_FILE.parent.mkdir(parents=True, exist_ok=True)
    DOWNLOADS_TICKETS_FILE.write_text(json.dumps(sorted(downloaded)))


def _load_review_statuses():
    """Load manual review statuses for Scan Bucket."""
    if REVIEW_STATUS_FILE.exists():
        try:
            import json
            return json.loads(REVIEW_STATUS_FILE.read_text())
        except Exception:
            return {}
    return {}


def _save_review_status(order_key: str, status: str):
    """Persist one manual review status for Scan Bucket."""
    import json

    statuses = _load_review_statuses()
    statuses[order_key] = status
    REVIEW_STATUS_FILE.parent.mkdir(parents=True, exist_ok=True)
    REVIEW_STATUS_FILE.write_text(json.dumps(statuses, indent=2))

# --- Page Config ---
st.set_page_config(
    page_title="Optical Character Recognition (OCR)",
    page_icon="🏗️",
    layout="wide",
)

# --- Authentication via Microsoft Entra ID (Azure AD) SSO ---
# This runs before Excel loading and OCR. Missing configuration or an
# unauthenticated session fails closed.
import msal

AZURE_TENANT_ID = os.getenv("AZURE_TENANT_ID", "").strip()
AZURE_CLIENT_ID = os.getenv("AZURE_CLIENT_ID", "").strip()
AZURE_CLIENT_SECRET = os.getenv("AZURE_CLIENT_SECRET", "").strip()
AZURE_REDIRECT_URI = os.getenv("AZURE_REDIRECT_URI", "http://localhost:8501").strip()
_MSAL_AUTHORITY = f"https://login.microsoftonline.com/{AZURE_TENANT_ID}"
_MSAL_SCOPES = ["User.Read"]


def _build_msal_app():
    """Build the confidential-client MSAL app, or None if SSO is incomplete."""
    if not (AZURE_TENANT_ID and AZURE_CLIENT_ID and AZURE_CLIENT_SECRET):
        return None
    return msal.ConfidentialClientApplication(
        AZURE_CLIENT_ID,
        authority=_MSAL_AUTHORITY,
        client_credential=AZURE_CLIENT_SECRET,
    )


_msal_app = _build_msal_app()

if _msal_app is None:
    st.error(
        "Microsoft SSO is not configured — AZURE_TENANT_ID, AZURE_CLIENT_ID, "
        "and AZURE_CLIENT_SECRET are required."
    )
    st.stop()
elif "user" not in st.session_state:
    _query_code = st.query_params.get("code")
    if _query_code:
        _query_state = st.query_params.get("state")
        _expected_state = st.session_state.get("sso_oauth_state")
        if not _expected_state or not secrets.compare_digest(str(_query_state or ""), _expected_state):
            st.error("Sign-in failed: invalid OAuth state. Please start the sign-in again.")
            st.query_params.clear()
            st.session_state.pop("sso_oauth_state", None)
            st.stop()
        _result = _msal_app.acquire_token_by_authorization_code(
            _query_code,
            scopes=_MSAL_SCOPES,
            redirect_uri=AZURE_REDIRECT_URI,
        )
        if "id_token_claims" in _result:
            claims = _result["id_token_claims"]
            st.session_state["user"] = {
                "name": claims.get("name", "Unknown"),
                "email": claims.get("preferred_username", claims.get("email", "")),
            }
            st.session_state.pop("sso_oauth_state", None)
            st.query_params.clear()
            st.rerun()
        else:
            st.error(f"Sign-in failed: {_result.get('error_description', 'unknown error')}")
            st.query_params.clear()
            st.stop()
    else:
        _oauth_state = st.session_state.setdefault("sso_oauth_state", secrets.token_urlsafe(32))
        _auth_url = _msal_app.get_authorization_request_url(
            _MSAL_SCOPES,
            redirect_uri=AZURE_REDIRECT_URI,
            state=_oauth_state,
        )
        st.title("Optical Character Recognition (OCR)")
        st.link_button("Sign in with Microsoft →", _auth_url)
        st.stop()
# Authenticated below — carry on.

# --- Auto-cleanup old files (7 days) ---
cleanup_old_files()

# --- Initialize shared resources (cached) ---
@st.cache_resource
def init_data_loader():
    return get_data_loader()


def _clean_env_path(raw: str | None, fallback: str) -> str:
    """Strip whitespace and stray quotes from a .env path value."""
    if not raw:
        return fallback
    return raw.strip().strip('"').strip("'").strip() or fallback


SCANS_FOLDER = Path(_clean_env_path(
    os.getenv("SCAN_PDF_PATH"),
    str(Path(__file__).parent.parent / "Scans" / "incoming_scans"),
))

@st.cache_resource
def init_scan_index():
    """Return the ScanIndex singleton (cached for process lifetime).

    We deliberately do NOT call build_index_folder() here — that runs on
    every rerun below, where it auto-skips unchanged PDFs via file-size
    signatures. This way, newly dropped PDFs get picked up without the
    user clicking "Refresh Orders".
    """
    return get_scan_index()


startup_slot = st.empty()
startup_slot.caption("Loading Excel tracker...")
data_loader = init_data_loader()
scan_index = init_scan_index()

# Hot-reload Excel if the file changed on disk since last read.
# Runs on every Streamlit rerun — cheap when the file is unchanged.
_reload = getattr(data_loader, "maybe_reload", None)
if _reload is not None:
    _reload()
else:
    data_loader._load_excel()

# Auto-index the scans folder on every rerun. build_index_folder() compares
# each PDF's size and modified timestamp against the cached signature and
# only re-OCRs files that are new or changed.
if SCANS_FOLDER.exists():
    startup_slot.caption("Checking scanned PDFs for new or changed tickets...")
    scan_index.build_index_folder(str(SCANS_FOLDER))

startup_slot.empty()


# --- Sidebar Navigation ---
st.sidebar.title("Optical Character Recognition (OCR)")

_current_user = st.session_state["user"]
st.sidebar.caption(f"👤 **{_current_user['name']}**")
st.sidebar.caption(_current_user["email"])
if st.sidebar.button("Sign out", key="sso_signout", use_container_width=True):
    st.session_state.pop("user", None)
    st.session_state.pop("sso_oauth_state", None)
    _logout_url = (
        f"{_MSAL_AUTHORITY}/oauth2/v2.0/logout"
        f"?post_logout_redirect_uri={AZURE_REDIRECT_URI}"
    )
    st.query_params.clear()
    st.markdown(
        f'<meta http-equiv="refresh" content="0; url={html.escape(_logout_url, quote=True)}">',
        unsafe_allow_html=True,
    )
    st.stop()

_nav_options = ["Order Index", "Analysis Table", "Scan Bucket"]
if st.session_state.get("page") not in _nav_options:
    st.session_state.page = _nav_options[0]

st.sidebar.markdown("**Navigation**")
for nav_item in _nav_options:
    if st.sidebar.button(
        nav_item,
        key=f"nav_{nav_item.lower().replace(' ', '_')}",
        type="primary" if st.session_state.page == nav_item else "secondary",
        use_container_width=True,
    ):
        st.session_state.page = nav_item
        st.rerun()

page = st.session_state.page

st.sidebar.markdown("---")

# ─────────────────────────────────────────────
# VIEW 1: Order Index
# ─────────────────────────────────────────────
def view_order_index():
    st.header("Order Index")
    st.caption(
        "Every row from the Excel tracker is listed here. Each card shows whether "
        "we have the Excel row and scanned delivery ticket needed to move forward. "
        "Use the search bar to filter by order number, SO, customer, or assignee."
    )

    order_data = []

    # Excel is the source of truth — every row is one delivery ticket.
    # We do NOT dedupe by Order_ID: a single W-order can have 2 or 3 rows
    # for separate shipments with different SO numbers, and the user needs
    # to see each one.
    all_excel_orders = data_loader.excel_df if not data_loader.excel_df.empty else pd.DataFrame()

    # Track every identifier we've emitted so the scan-index fallback below
    # doesn't duplicate a row that's already represented by an Excel entry.
    # Both Order_ID and SO are tracked because shipment OCR returns the SO
    # number, not the W-order number.
    seen_identifiers = set()

    for idx, row in all_excel_orders.iterrows():
        order_id = str(row.get("Order_ID", "")).strip()
        so = str(row.get("SO", "")).strip()

        # Skip blank or placeholder rows
        if (not order_id or order_id.lower() == "nan") and (not so or so.lower() == "nan"):
            continue

        # Mark both identifiers as seen so the scan-only loop below won't
        # re-add this row under its SO number
        if order_id and order_id.lower() != "nan":
            seen_identifiers.add(order_id)
        if so and so.lower() != "nan":
            seen_identifiers.add(so)

        # Check scan index under BOTH Order_ID and SO — OCR stores shipments
        # under the SO number but work orders under the W-number
        scan_pages = scan_index.find_pages(order_id) if order_id else []
        if not scan_pages and so:
            scan_pages = scan_index.find_pages(so)

        # has_ticket reflects whether the OCR ever indexed pages for this
        # order. We use the in-memory index (find_pages) rather than the
        # disk file from get_scan_pdf — the upload_ready/ per-order PDF can be
        # missing even though the cached index still proves the scan existed.
        has_ticket = bool(scan_pages)

        lookup_id = order_id if order_id and order_id.lower() != "nan" else so
        compiled_files = find_compiled_pdfs(OUTPUT_DIR, lookup_id)
        has_compiled = len(compiled_files) > 0
        has_id = False
        page_count = len(scan_pages)

        # Completion now needs only the two active gates: Excel + Ticket.
        # Compiled PDFs are handled later/manual and do not block this.
        if not has_ticket and page_count == 0:
            flag = "missing_ticket"
        elif has_ticket:
            flag = "complete"
        else:
            flag = "ready"

        order = row.to_dict()
        # Empty cells normalize to "" upstream in data_loader; render as
        # the em-dash placeholder so the UI stays consistent.
        order_data.append({
            # Unique key per row — duplicates of the same Order_ID get
            # different row_keys so Streamlit widget keys don't collide
            "row_key": f"xl_{idx}_{lookup_id}",
            "order_id": lookup_id,
            "pages": page_count,
            "customer": order.get("Customer_name") or "—",
            "ship_to": order.get("Ship_to") or "—",
            "so": so if so and so.lower() != "nan" else "—",
            "status": order.get("Status") or "—",
            "deadline": order.get("Deadline", "—"),
            "requested_by": order.get("Requested by") or "—",
            "has_ticket": has_ticket,
            "has_compiled": has_compiled,
            "has_id": has_id,
            "compiled_files": compiled_files,
            "in_excel": True,
            "flag": flag,
            "month": str(order.get("Source_Sheet", "")).strip() or None,
        })

    # Also include scanned orders not in Excel (e.g. returns, old tickets).
    # These are PDFs the OCR matched to a number that we can't find in Excel
    # under either Order_ID or SO.
    matched_items = {k: v for k, v in scan_index.index.items() if not k.startswith("UNMATCHED_")}
    for scan_id, pages in matched_items.items():
        if scan_id in seen_identifiers:
            continue
        seen_identifiers.add(scan_id)

        # In-memory check — see comment in the Excel loop above
        has_ticket = bool(pages)
        compiled_files = find_compiled_pdfs(OUTPUT_DIR, scan_id)
        has_id = False

        order_data.append({
            "row_key": f"scan_{scan_id}",
            "order_id": scan_id,
            "pages": len(pages),
            "customer": "—",
            "ship_to": "—",
            "so": "—",
            "status": "—",
            "deadline": "—",
            "requested_by": "—",
            "has_ticket": has_ticket,
            "has_compiled": len(compiled_files) > 0,
            "has_id": has_id,
            "compiled_files": compiled_files,
            "in_excel": False,
            "flag": "not_in_excel",
            "month": None,
        })

    if not order_data:
        st.info("No orders are loaded. Check EXCEL_PATH and the incoming scans folder, then rerun the page.")
        return

    # ── Month scope: applied BEFORE metrics, bulk download, and buckets ──
    # We read st.session_state directly because Streamlit populates widget
    # values into session_state before this script reruns. That lets us use
    # the user's current selection here, even though the selectbox itself
    # is rendered further down. On first render session_state is empty, so
    # we fall back to the latest month present in the data.
    month_options_seen = []
    for o in order_data:
        m = o.get("month")
        if m and m not in month_options_seen:
            month_options_seen.append(m)
    has_no_month = any(o.get("month") is None for o in order_data)
    default_month = month_options_seen[-1] if month_options_seen else "All"
    month_options = ["All"] + month_options_seen + (["Other (no month)"] if has_no_month else [])
    selected_month = st.session_state.get("order_month_filter", default_month)
    if selected_month not in month_options:
        selected_month = default_month

    def _passes_month(o, m):
        if m == "All":
            return True
        if m == "Other (no month)":
            return o.get("month") is None
        return o.get("month") == m

    month_orders = [o for o in order_data if _passes_month(o, selected_month)]

    # Summary metrics — scoped to the selected month so the KPIs match
    # what's shown in the buckets and lists below.
    total = len(month_orders)
    complete_count = sum(1 for o in month_orders if o["flag"] == "complete")
    flagged_count = sum(1 for o in month_orders if o["flag"] in ("not_in_excel", "low_pages", "no_scan", "missing_ticket"))

    def _metric_card(label, value, color):
        st.markdown(f"""
        <div style="
            background: linear-gradient(135deg, {color}22, {color}11);
            border: 1px solid {color}33;
            border-top: 4px solid {color};
            border-radius: 16px;
            padding: 24px 16px;
            text-align: center;
            box-shadow: 0 2px 8px {color}15;
            font-family: 'JetBrains Mono', 'Fira Code', 'SF Mono', 'Consolas', monospace;
        ">
            <div style="font-size: 0.7rem; opacity: 0.5; text-transform: uppercase; letter-spacing: 2px; color: inherit;">{label}</div>
            <div style="font-size: 2.5rem; font-weight: 800; color: {color}; margin-top: 4px;">{value}</div>
        </div>
        """, unsafe_allow_html=True)

    col1, col2, col3 = st.columns(3)
    with col1:
        _metric_card("Total Orders", total, "#3B82F6")
    with col2:
        _metric_card("Complete", complete_count, "#22C55E")
    with col3:
        _metric_card("Flagged", flagged_count, "#EF4444")

    st.markdown("<br>", unsafe_allow_html=True)

    # ── Pipeline: classify orders into workflow buckets ──
    # Scoped to the selected month so Action Needed / Complete tabs only
    # show orders from that month, not all months mixed together.
    action_needed = []
    ready_to_send = []
    complete_orders = []

    for o in month_orders:
        if o["flag"] == "complete":
            complete_orders.append(o)
        elif o["flag"] == "ready":
            ready_to_send.append(o)
        else:
            action_needed.append(o)

    # MONO is module-level so the Scan Bucket view can reuse it.
    GRID_COLS = "120px 70px 1fr 1fr 100px 90px 60px 165px"
    GRID_COLS_COMPLETE = "120px 70px 1fr 1fr 90px 60px 80px 165px"

    FLAG_LABELS = {
        "missing_ticket": "No Ticket",
        "no_scan": "No Scan",
        "not_in_excel": "Not in Excel",
        "low_pages": "Low Pages",
    }

    def _section_header(title, count, color):
        st.markdown(f"""
        <div style="
            display: flex; align-items: center; gap: 12px;
            margin: 28px 0 8px 0;
            font-family: {MONO};
        ">
            <span style="font-size: 1.1rem; font-weight: 700; color: {color};">{title}</span>
            <span style="
                background: {color}22; color: {color}; border: 1px solid {color}44;
                border-radius: 12px; padding: 2px 10px; font-size: 0.75rem; font-weight: 600;
            ">{count}</span>
        </div>
        <div style="border-top: 1px solid {color}33; margin: 0 0 4px 0;"></div>
        """, unsafe_allow_html=True)

    def _column_headers(has_download=False, has_ticket_dl=False):
        # `has_download` = Complete tab variant with the Expires column.
        # `has_ticket_dl` = section that may show a ticket-download icon
        #    on individual cards; layout uses normal GRID_COLS but reserves
        #    the icon column so cards line up with the header.
        if has_download:
            grid = GRID_COLS_COMPLETE
            cols = "<div>Order</div><div>SO</div><div>Customer</div><div>Ship To</div><div>Assigned</div><div>Pg</div><div>Expires</div><div>Status</div>"
        else:
            grid = GRID_COLS
            cols = "<div>Order</div><div>SO</div><div>Customer</div><div>Ship To</div><div>Deadline</div><div>Assigned</div><div>Pg</div><div>Status</div>"

        header_html = f"""
        <div style="
            padding: 4px 16px; padding-left: 19px; margin-bottom: 2px;
            font-family: {MONO};
            font-size: 0.65rem; font-weight: 700; text-transform: uppercase;
            letter-spacing: 1.5px; opacity: 0.35;
            display: grid;
            grid-template-columns: {grid};
            gap: 8px;
        ">
            {cols}
        </div>
        """
        if has_download or has_ticket_dl:
            # Wide ratio (30:1) so the card content keeps ~97% of the row
            # width — anything tighter than this visibly squeezes the
            # Customer / Ship-to columns. The popover icon is small and
            # still fits comfortably in the remaining sliver.
            col_card, _ = st.columns([30, 1])
            with col_card:
                st.markdown(header_html, unsafe_allow_html=True)
        else:
            st.markdown(header_html, unsafe_allow_html=True)

    def _indicator(val, label):
        color = "#22C55E" if val else "#EF4444"
        sym = "&#10003;" if val else "&#10007;"
        return f'<span style="color:{color};font-weight:700;">{sym}</span><span style="opacity:0.5;font-size:0.65rem;margin-left:2px;">{label}</span>'

    downloaded_set = _load_downloaded()
    downloaded_tickets_set = _load_downloaded_tickets()

    def _render_order_card(o, section_color, show_download=False, show_ticket_dl=False, key_prefix="main"):
        # Deadline check
        deadline_str = "—"
        is_overdue = False
        dl_parsed = None
        raw = str(o["deadline"])
        if raw not in ("—", "nan", "NaT", ""):
            try:
                dl_parsed = pd.to_datetime(o["deadline"])
                if pd.notna(dl_parsed):
                    deadline_str = dl_parsed.strftime("%m/%d")
                    if dl_parsed < pd.Timestamp.now():
                        is_overdue = True
            except Exception:
                deadline_str = raw

        # Excel Status == COMPLETE → show "COMPLETED" in green instead of
        # the date / OVERDUE flag. Pure visual override: doesn't change the
        # bucket, flag, or download tracking — the operator's tracker is the
        # source of truth for whether the order is closed in Acumatica.
        excel_complete = str(o.get("status", "")).strip().upper() == "COMPLETE"

        # For complete orders, calculate days until auto-deletion (7-day cleanup)
        days_until_deletion = None
        if o["flag"] == "complete" and o["compiled_files"]:
            try:
                from scan_index import CLEANUP_DAYS
                mtime = os.path.getmtime(o["compiled_files"][0])
                age_days = (pd.Timestamp.now() - pd.Timestamp.fromtimestamp(mtime)).days
                days_until_deletion = max(0, CLEANUP_DAYS - age_days)
            except Exception:
                pass
            is_overdue = False  # don't flag overdue on complete

        if excel_complete:
            deadline_str = "COMPLETED"
            is_overdue = False
            dl_color = "#22C55E"
            overdue_tag = ""
        else:
            dl_color = "#EF4444" if is_overdue else "inherit"
            overdue_tag = '<span style="color:#EF4444;font-size:0.6rem;margin-left:4px;">OVERDUE</span>' if is_overdue else ""

        # Flag label for action needed items
        flag_text = FLAG_LABELS.get(o["flag"], "")
        flag_html = f'<span style="color:#F59E0B;font-size:0.7rem;margin-left:6px;">{flag_text}</span>' if flag_text else ""

        # Duplicate badge — tells the user at a glance that this Order_ID
        # appears N times in the Excel so they can clean up the source
        dup_html = ""
        if o.get("is_duplicate"):
            dup_html = (
                f'<span style="background:#8B5CF6;color:white;font-weight:700;'
                f'font-size:0.65rem;padding:2px 6px;border-radius:4px;'
                f'margin-left:6px;">{o["dup_count"]}x</span>'
            )

        indicators = (
            f'<span style="display:flex;align-items:center;justify-content:center;gap:8px;flex-wrap:wrap;">'
            f'{_indicator(o["in_excel"], "Excel")}'
            f'{_indicator(o["has_ticket"], "Ticket")}'
            f'{flag_html}'
            f'{dup_html}'
            f'</span>'
        )

        # Left border colors: green once we've pulled whichever file this
        # card actually offers. The Complete section prefers the compiled
        # PDF but falls back to the ticket scan when no compiled exists
        # yet — the border has to follow the same fallback so a ticket
        # already pulled doesn't leave the row stuck on red.
        is_compiled_downloaded = o["order_id"] in downloaded_set
        is_ticket_downloaded = o["order_id"] in downloaded_tickets_set
        if show_download:
            if o.get("compiled_files"):
                border_color = "#22C55E" if is_compiled_downloaded else "#EF4444"
            elif o.get("in_excel") and o.get("has_ticket"):
                border_color = "#22C55E" if is_ticket_downloaded else "#EF4444"
            else:
                border_color = "#EF4444"
        elif show_ticket_dl and is_ticket_downloaded:
            border_color = "#22C55E"
        elif is_overdue:
            border_color = "#EF4444"
        else:
            border_color = f"{section_color}44"

        assigned = o["requested_by"] if o["requested_by"] != "—" else ""
        order_id_html = _html_text(o["order_id"])
        so_html = _html_text(o["so"])
        customer_html = _html_text(o["customer"])
        ship_to_html = _html_text(o["ship_to"])
        assigned_html = _html_text(assigned) if assigned else ""
        pages_html = _html_text(o["pages"])
        deadline_html = _html_text(deadline_str) + overdue_tag

        # Complete orders: no deadline column
        if show_download:
            grid = GRID_COLS_COMPLETE
            card_html = f"""
            <div style="
                background: rgba(128,128,128,0.04);
                border: 1px solid rgba(128,128,128,0.12);
                border-left: 3px solid {border_color};
                border-radius: 6px;
                padding: 10px 16px;
                margin-bottom: 4px;
                font-family: {MONO};
                font-size: 0.8rem;
                display: grid;
                grid-template-columns: {grid};
                align-items: center;
                gap: 8px;
            ">
                <div style="font-weight:700;">{order_id_html}</div>
                <div style="opacity:0.6;">{so_html}</div>
                <div style="white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">{customer_html}</div>
                <div style="opacity:0.7;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">{ship_to_html}</div>
                <div style="opacity:0.6;font-size:0.75rem;">{assigned_html}</div>
                <div style="opacity:0.6;">{pages_html}</div>
                <div style="font-size:0.75rem;font-weight:600;color:{'#EF4444' if days_until_deletion is not None and days_until_deletion <= 2 else '#F59E0B' if days_until_deletion is not None and days_until_deletion <= 4 else '#22C55E'};">{f'{days_until_deletion}d' if days_until_deletion is not None else '—'}</div>
                <div>{indicators}</div>
            </div>
            """
        else:
            card_html = f"""
            <div style="
                background: rgba(128,128,128,0.04);
                border: 1px solid rgba(128,128,128,0.12);
                border-left: 3px solid {border_color};
                border-radius: 6px;
                padding: 10px 16px;
                margin-bottom: 4px;
                font-family: {MONO};
                font-size: 0.8rem;
                display: grid;
                grid-template-columns: {GRID_COLS};
                align-items: center;
                gap: 8px;
            ">
                <div style="font-weight:700;">{order_id_html}</div>
                <div style="opacity:0.6;">{so_html}</div>
                <div style="white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">{customer_html}</div>
                <div style="opacity:0.7;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">{ship_to_html}</div>
                <div style="color:{dl_color};font-size:0.75rem;">{deadline_html}</div>
                <div style="opacity:0.6;font-size:0.75rem;">{assigned_html}</div>
                <div style="opacity:0.6;">{pages_html}</div>
                <div>{indicators}</div>
            </div>
            """

        # Decide which download (if any) to attach to this card.
        # Compiled PDF wins over raw ticket \u2014 if the order is fully ready,
        # the operator gets the finished file; otherwise we offer the ticket scan
        # so she can process it manually while approvals are pending.
        dl_payload = None
        if show_download and o.get("compiled_files"):
            compiled_path = o["compiled_files"][0]
            order = data_loader.get_order_by_id(o["order_id"])
            dl_filename = (pdf_name_fn(order) + ".pdf") if order else f"{o['order_id']}.pdf"
            dl_payload = (compiled_path, dl_filename, "compiled")
        elif show_ticket_dl and o.get("in_excel") and o.get("has_ticket"):
            ticket_path = scan_index.get_scan_pdf(o["order_id"])
            if not ticket_path and o.get("so") not in (None, "", "—"):
                ticket_path = scan_index.get_scan_pdf(o["so"])
            if ticket_path and os.path.exists(ticket_path):
                order = data_loader.get_order_by_id(o["order_id"])
                base = pdf_name_fn(order) if order else o["order_id"]
                dl_filename = f"{base}_ticket.pdf"
                dl_payload = (ticket_path, dl_filename, "ticket")

        # Layout: when this section supports download icons, ALWAYS use the
        # 14:1 split so every card lines up vertically with the column
        # headers, even when this particular order has nothing to download.
        # Cards in download-less sections fall through to full width.
        section_has_dl_column = show_download or show_ticket_dl

        if section_has_dl_column:
            # Match the [30, 1] ratio used by _column_headers — keeps the
            # card visually full-width while leaving room for the popover
            # icon outside the card grid.
            col_card, col_dl = st.columns([30, 1])
            with col_card:
                st.markdown(card_html, unsafe_allow_html=True)
            with col_dl:
                if dl_payload:
                    path, fname, kind = dl_payload
                    already = (
                        o["order_id"] in downloaded_set if kind == "compiled"
                        else o["order_id"] in downloaded_tickets_set
                    )
                    mark_fn = _mark_downloaded if kind == "compiled" else _mark_ticket_downloaded
                    base_help = "compiled PDF" if kind == "compiled" else "ticket scan"

                    if already:
                        # Re-download confirmation: popover wraps the icon
                        # so the operator gets a clear "are you sure?" before
                        # pulling the same file twice.
                        with st.popover("\u2713", help=f"Already downloaded {base_help} \u2014 click to re-download"):
                            st.warning(
                                f"You already downloaded the {base_help} for "
                                f"**{o['order_id']}**. Pull it again?"
                            )
                            with open(path, "rb") as f:
                                st.download_button(
                                    "Yes, download again",
                                    f,
                                    file_name=fname,
                                    mime="application/pdf",
                                    key=f"redl_{key_prefix}_{kind}_{o['row_key']}",
                                    on_click=mark_fn,
                                    args=(o["order_id"],),
                                    use_container_width=True,
                                )
                    else:
                        with open(path, "rb") as f:
                            st.download_button(
                                "\u2913",
                                f,
                                file_name=fname,
                                mime="application/pdf",
                                key=f"dl_{key_prefix}_{kind}_{o['row_key']}",
                                help=f"Download {base_help}",
                                on_click=mark_fn,
                                args=(o["order_id"],),
                            )
                # else: empty column \u2014 keeps the card aligned with siblings
        else:
            st.markdown(card_html, unsafe_allow_html=True)

    # ── Duplicate detection: flag rows sharing the same Order_ID ──
    # User wants to see duplicates (not hide them) so they can clean up
    # the Excel. Each order gets a `dup_count` (1 = unique, 2+ = duplicated).
    from collections import Counter
    id_counts = Counter(o["order_id"] for o in order_data if o.get("order_id"))
    for o in order_data:
        o["dup_count"] = id_counts.get(o["order_id"], 1)
        o["is_duplicate"] = o["dup_count"] > 1

    total_duplicates = sum(1 for o in order_data if o["is_duplicate"])
    unique_duplicated = sum(1 for oid, n in id_counts.items() if n > 1)

    # ── Filter lookup: free-text search across order fields ──
    # Note: month_options + selected_month + _passes_month were already
    # computed at the top so they could scope the metrics, bulk download,
    # and buckets. The selectbox here just renders the picker.
    col_search, col_month, col_status, col_count = st.columns([3, 1.5, 2, 1])
    with col_search:
        query = st.text_input(
            "Search",
            placeholder="Order, SO, customer, ship-to, assignee...",
            label_visibility="collapsed",
            key="order_search",
        )
    with col_month:
        st.selectbox(
            "Month",
            options=month_options,
            index=month_options.index(selected_month) if selected_month in month_options else 0,
            label_visibility="collapsed",
            key="order_month_filter",
        )
    with col_status:
        status_options = ["All", "Needs action", "Complete"]
        if total_duplicates > 0:
            status_options.append(f"Duplicates ({total_duplicates})")
        status_filter = st.selectbox(
            "Status",
            options=status_options,
            label_visibility="collapsed",
            key="order_status_filter",
        )

    def _matches(o, q):
        if not q:
            return True
        q = q.lower().strip()
        haystack = " ".join(
            str(o.get(k, "")) for k in (
                "order_id", "so", "customer", "ship_to", "requested_by", "status"
            )
        ).lower()
        return q in haystack

    def _passes_status(o, s):
        if s == "All":
            return True
        if s == "Complete":
            return o["flag"] == "complete"
        if s.startswith("Duplicates"):
            return o["is_duplicate"]
        # Needs action: anything else
        return o["flag"] not in ("complete", "ready")

    # Search and status filters operate inside the already-month-scoped
    # `month_orders` so the bottom list is consistent with the metrics
    # and tab buckets above.
    filtered_orders = [
        o for o in month_orders
        if _matches(o, query) and _passes_status(o, status_filter)
    ]

    with col_count:
        st.caption(f"**{len(filtered_orders)}** / {len(month_orders)}")

    if unique_duplicated > 0:
        st.caption(
            f":warning: {unique_duplicated} Order_ID(s) are duplicated across "
            f"{total_duplicates} rows — use the **Duplicates** filter to review."
        )

    # ── All Orders (always visible, scrollable) ──
    _column_headers(has_ticket_dl=True)
    with st.container(height=500):
        if not filtered_orders:
            st.caption("No orders match the current filter.")
        for o in filtered_orders:
            section_color = "#22C55E" if o["flag"] in ("complete", "ready") else "#EF4444" if o["flag"] in ("not_in_excel", "no_scan") else "#F59E0B"
            _render_order_card(o, section_color, show_download=False, show_ticket_dl=True, key_prefix="all")

    st.markdown("<br>", unsafe_allow_html=True)

    # ── Tab buttons at the bottom ──
    if "order_tab" not in st.session_state:
        st.session_state.order_tab = None

    col_action_btn, col_complete_btn = st.columns(2)
    with col_action_btn:
        if st.button(f"Action Needed  ({len(action_needed)})", key="tab_action", use_container_width=True):
            st.session_state.order_tab = "action" if st.session_state.order_tab != "action" else None
            st.rerun()
    with col_complete_btn:
        if st.button(f"Complete  ({len(complete_orders)})", key="tab_complete", use_container_width=True):
            st.session_state.order_tab = "complete" if st.session_state.order_tab != "complete" else None
            st.rerun()

    # ── Show selected tab content below buttons ──
    if st.session_state.order_tab == "action":
        if action_needed:
            _section_header("Action Needed", len(action_needed), "#EF4444")

            # Filter by flag type
            flag_types_present = sorted(set(o["flag"] for o in action_needed))
            flag_options = {f: FLAG_LABELS.get(f, f) for f in flag_types_present}
            selected_flags = st.multiselect(
                "Filter by issue",
                options=list(flag_options.keys()),
                format_func=lambda x: flag_options[x],
                default=list(flag_options.keys()),
                key="action_filter",
            )
            filtered_action = [o for o in action_needed if o["flag"] in selected_flags] if selected_flags else action_needed

            _column_headers(has_ticket_dl=True)
            for o in filtered_action:
                _render_order_card(o, "#EF4444", show_download=False, show_ticket_dl=True, key_prefix="action")
        else:
            st.success("No orders need action right now.")

    elif st.session_state.order_tab == "complete":
        if complete_orders:
            _section_header("Complete", len(complete_orders), "#22C55E")
            _column_headers(has_download=True)
            for o in complete_orders:
                _render_order_card(
                    o,
                    "#22C55E",
                    show_download=True,
                    show_ticket_dl=True,
                    key_prefix="complete",
                )
        else:
            st.info("No completed orders yet.")


# ─────────────────────────────────────────────
# VIEW: Records
# ─────────────────────────────────────────────
# Month sheet names in chronological order so heatmaps don't show APR before FEB.
_MONTH_ORDER = ["JAN", "FEB", "MAR", "APR", "APRIL", "MAY", "JUN", "JUNE", "JUL", "JULY",
                "AUG", "SEP", "SEPT", "OCT", "NOV", "DEC"]


def _sorted_months(months) -> list:
    """Return the given month labels sorted in calendar order, unknown labels last."""
    rank = {m: i for i, m in enumerate(_MONTH_ORDER)}
    return sorted({m for m in months if m}, key=lambda m: (rank.get(m.upper(), 999), m))


def _render_customer_charts(df: pd.DataFrame, focus_customer: str | None = None) -> None:
    """Interactive Altair charts driven by the table's customer selection.

    - focus_customer=None → "All Customers" mode: customer-level overview.
    - focus_customer="Foo" → drill mode: ship-to/address-level breakdown for
      just that customer (so the bars stay informative instead of collapsing
      to a single row).
    Hover any bar/cell for the full label + value tooltip.
    """

    def _col(name: str, fallback: str = "") -> pd.Series:
        if name not in df.columns:
            return pd.Series([fallback] * len(df), index=df.index)
        s = df[name].fillna("").astype(str).str.strip()
        return s.mask(s.str.lower().isin({"nan", "nat", "none", "<na>"}), fallback)

    work = pd.DataFrame({
        "customer": _col("Customer_name", "Unknown").replace("", "Unknown"),
        "ship_to": _col("Ship_to", "—"),
        "status": _col("Status"),
        "month": _col("Source_Sheet"),
    })

    if focus_customer:
        work = work[work["customer"] == focus_customer]

    # ── Months filter (sole filter — customer comes from the table picker) ──
    available_months = _sorted_months(work["month"].unique())
    if available_months:
        chosen_months = st.multiselect(
            "Months",
            options=available_months,
            default=available_months,
            key="analysis_months",
        )
        if chosen_months:
            work = work[work["month"].isin(chosen_months)]

    if work.empty:
        st.info("No rows match the current filter.")
        return

    def _short(name: str, limit: int = 18) -> str:
        return name if len(name) <= limit else name[: limit - 1] + "…"

    # When focused on a single customer we pivot from customer → ship_to
    # so the charts keep telling a story (one customer = one bar otherwise).
    if focus_customer:
        dim_col = "ship_to"
        dim_label = "Ship-to"
        chart_title_top = f"Top 15 ship-to addresses — {focus_customer}"
        chart_title_rate = f"Completion rate by ship-to — {focus_customer}"
        chart_title_heat = f"Ship-to × Month — {focus_customer}"
    else:
        dim_col = "customer"
        dim_label = "Customer"
        chart_title_top = "Top 15 customers by volume"
        chart_title_rate = "Completion rate — top 15 by volume"
        chart_title_heat = "Order volume — top 20 customers × month"

    # ── Row 1: top entities + completion rate side by side ──
    r1c1, r1c2 = st.columns(2)

    with r1c1:
        st.markdown(f"**{chart_title_top}**")
        top = (
            work.groupby(dim_col).size()
            .reset_index(name="orders")
            .sort_values("orders", ascending=False)
            .head(15)
        )
        top["label"] = top[dim_col].map(_short)
        if top.empty:
            st.info("Nothing to plot.")
        else:
            chart = (
                alt.Chart(top)
                .mark_bar(color="#3B82F6")
                .encode(
                    x=alt.X("orders:Q", title="Orders"),
                    y=alt.Y("label:N", sort="-x", title="", axis=alt.Axis(labelLimit=140)),
                    tooltip=[
                        alt.Tooltip(f"{dim_col}:N", title=dim_label),
                        alt.Tooltip("orders:Q", title="Orders"),
                    ],
                )
                .properties(height=260)
            )
            st.altair_chart(chart, use_container_width=True)

    with r1c2:
        st.markdown(f"**{chart_title_rate}**")
        grouped = work.groupby(dim_col).agg(
            total=("status", "size"),
            complete=("status", lambda s: s.str.upper().eq("COMPLETE").sum()),
        ).reset_index()
        grouped["rate"] = (grouped["complete"] / grouped["total"]).fillna(0) * 100
        repeated = grouped[grouped["total"] > 1].copy()
        if repeated.empty:
            top_rate = grouped.sort_values("total", ascending=False).head(15)
            st.caption("Completion rate includes one-order entries because no repeated entries match this filter.")
        else:
            top_rate = repeated.sort_values("total", ascending=False).head(15)
            skipped = len(grouped) - len(repeated)
            if skipped:
                st.caption(f"Completion rate excludes {skipped} {dim_label.lower()} entries with only 1 order.")
        top_rate["label"] = top_rate[dim_col].map(_short)
        if top_rate.empty:
            st.info("Nothing to plot.")
        else:
            chart = (
                alt.Chart(top_rate)
                .mark_bar(color="#22C55E")
                .encode(
                    x=alt.X("rate:Q", title="% complete", scale=alt.Scale(domain=[0, 100])),
                    y=alt.Y("label:N", sort=alt.SortField(field="total", order="descending"),
                            title="", axis=alt.Axis(labelLimit=140)),
                    tooltip=[
                        alt.Tooltip(f"{dim_col}:N", title=dim_label),
                        alt.Tooltip("rate:Q", title="% complete", format=".1f"),
                        alt.Tooltip("complete:Q", title="Complete"),
                        alt.Tooltip("total:Q", title="Total orders"),
                    ],
                )
                .properties(height=260)
            )
            st.altair_chart(chart, use_container_width=True)

    # ── Row 2: dimension × month heatmap ──
    st.markdown(f"**{chart_title_heat}**")
    heat_top_n = 20 if not focus_customer else 15
    top_entities = work.groupby(dim_col).size().sort_values(ascending=False).head(heat_top_n).index
    heat_source = work[work[dim_col].isin(top_entities)].copy()
    if heat_source.empty:
        st.info("Nothing to plot.")
    else:
        heat = (
            heat_source.groupby([dim_col, "month"]).size()
            .reset_index(name="orders")
        )
        heat["label"] = heat[dim_col].map(_short)
        ordered_months = [m for m in _sorted_months(heat["month"].unique())]
        cust_order = (
            heat.groupby("label")["orders"].sum()
            .sort_values(ascending=False).index.tolist()
        )
        chart = (
            alt.Chart(heat)
            .mark_rect()
            .encode(
                x=alt.X("month:N", title="Month", sort=ordered_months),
                y=alt.Y("label:N", title="", sort=cust_order, axis=alt.Axis(labelLimit=140)),
                color=alt.Color("orders:Q", scale=alt.Scale(scheme="yellowgreenblue"),
                                legend=alt.Legend(title="Orders")),
                tooltip=[
                    alt.Tooltip(f"{dim_col}:N", title=dim_label),
                    alt.Tooltip("month:N", title="Month"),
                    alt.Tooltip("orders:Q", title="Orders"),
                ],
            )
            .properties(height=max(180, 22 * min(len(cust_order), heat_top_n)))
        )
        st.altair_chart(chart, use_container_width=True)

    # ── Row 3: in "all" mode show top ship-to overall; in focus mode show
    #         monthly order trend so the story finishes on a time axis ──
    if focus_customer:
        st.markdown(f"**Monthly order volume — {focus_customer}**")
        trend = (
            work.groupby("month").size()
            .reset_index(name="orders")
        )
        ordered = [m for m in _sorted_months(trend["month"].unique())]
        if trend.empty:
            st.info("Nothing to plot.")
        else:
            chart = (
                alt.Chart(trend)
                .mark_bar(color="#F59E0B")
                .encode(
                    x=alt.X("month:N", title="Month", sort=ordered),
                    y=alt.Y("orders:Q", title="Orders"),
                    tooltip=[
                        alt.Tooltip("month:N", title="Month"),
                        alt.Tooltip("orders:Q", title="Orders"),
                    ],
                )
                .properties(height=260)
            )
            st.altair_chart(chart, use_container_width=True)
    else:
        st.markdown("**Top 15 ship-to locations**")
        ship_data = work[work["ship_to"] != "—"]
        top_ship = (
            ship_data.groupby("ship_to").size()
            .reset_index(name="orders")
            .sort_values("orders", ascending=False)
            .head(15)
        )
        top_ship["label"] = top_ship["ship_to"].map(_short)
        if top_ship.empty:
            st.info("No ship-to values to plot.")
        else:
            chart = (
                alt.Chart(top_ship)
                .mark_bar(color="#F59E0B")
                .encode(
                    x=alt.X("orders:Q", title="Orders"),
                    y=alt.Y("label:N", sort="-x", title="", axis=alt.Axis(labelLimit=160)),
                    tooltip=[
                        alt.Tooltip("ship_to:N", title="Ship-to"),
                        alt.Tooltip("orders:Q", title="Orders"),
                    ],
                )
                .properties(height=260)
            )
            st.altair_chart(chart, use_container_width=True)


def view_records():
    st.header("Analysis Table")
    st.caption("Pick a customer to drill in, or keep 'All Customers' for the overview.")

    # ── Polish the default Streamlit multiselect chips: out-of-the-box
    # they're flat red. Restyle once at the top of this page so every
    # filter pill below shares the look. Targeting BaseWeb's tag element
    # rather than Streamlit's wrapper means this still works through
    # version upgrades.
    st.markdown(
        """
        <style>
        div[data-baseweb="select"] [data-baseweb="tag"] {
            background-color: #1E293B !important;
            color: #93C5FD !important;
            border: 1px solid #334155 !important;
            border-radius: 6px !important;
            font-weight: 600;
        }
        div[data-baseweb="select"] [data-baseweb="tag"] svg {
            fill: #93C5FD !important;
        }
        div[data-baseweb="select"] [data-baseweb="tag"]:hover {
            background-color: #334155 !important;
            border-color: #475569 !important;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    df = data_loader.excel_df.copy()
    if df.empty:
        st.info("No Excel records are loaded.")
        return

    def _clean_col(name: str, fallback: str = "") -> pd.Series:
        if name not in df.columns:
            return pd.Series([fallback] * len(df), index=df.index)
        s = df[name].fillna("").astype(str).str.strip()
        return s.mask(s.str.lower().isin({"nan", "nat", "none", "<na>"}), fallback)

    records_df = pd.DataFrame({
        "customer": _clean_col("Customer_name", "Unknown"),
        "order_type": _clean_col("Order_Type"),
        "order_id": _clean_col("Order_ID"),
        "so": _clean_col("SO"),
        "ship_to": _clean_col("Ship_to"),
        "status": _clean_col("Status"),
        "order_date": _clean_col("Today"),
        "deadline": _clean_col("Deadline"),
        "requested_by": _clean_col("Requested by"),
        "month": _clean_col("Source_Sheet"),
    })
    records_df["order_date_dt"] = pd.to_datetime(records_df["order_date"], errors="coerce")
    records_df["deadline_dt"] = pd.to_datetime(records_df["deadline"], errors="coerce")
    records_df["customer"] = records_df["customer"].replace("", "Unknown")
    records_df["order_key"] = records_df["order_id"].where(records_df["order_id"] != "", records_df["so"])
    records_df["ro_number"] = records_df["so"].where(records_df["so"] != "", "—")
    records_df = records_df[records_df["order_key"].astype(str).str.strip() != ""].copy()

    if records_df.empty:
        st.info("No customer records have an Order ID or SO yet.")
        return

    grouped_rows = []
    for customer, group in records_df.groupby("customer", dropna=False):
        unique_orders = sorted({v for v in group["order_key"].astype(str) if v and v.lower() != "nan"})
        unique_sos = sorted({v for v in group["so"].astype(str) if v and v.lower() != "nan"})
        ship_to_values = sorted({v for v in group["ship_to"].astype(str) if v and v != "—"})
        month_values = [v for v in group["month"].astype(str) if v]
        completed = int(group["status"].astype(str).str.upper().eq("COMPLETE").sum())
        grouped_rows.append({
            "Customer": customer,
            "Orders": len(unique_orders),
            "Rows": len(group),
            "Complete": completed,
            "Open": max(0, len(group) - completed),
            "SOs": len(unique_sos),
            "Ship-To Locations": len(ship_to_values),
            "Months": ", ".join(dict.fromkeys(month_values[-4:])),
        })

    customer_summary = pd.DataFrame(grouped_rows).sort_values(
        ["Orders", "Rows", "Customer"],
        ascending=[False, False, True],
    )

    import html

    def _e(value) -> str:
        text = str(value or "—").strip() or "—"
        return html.escape(text)

    def _record_metric(label: str, value, color: str):
        st.markdown(f"""
        <div style="
            border:1px solid {color}44;border-top:3px solid {color};
            border-radius:8px;padding:12px 14px;background:{color}11;
            font-family:{MONO};margin-bottom:10px;">
            <div style="font-size:0.68rem;opacity:0.55;text-transform:uppercase;">{label}</div>
            <div style="font-size:1.45rem;font-weight:800;color:{color};">{value}</div>
        </div>
        """, unsafe_allow_html=True)

    def _is_closed_status(status) -> bool:
        return str(status or "").strip().upper() in {"COMPLETE", "COMPLETED", "CLOSED"}

    today_norm = pd.Timestamp.now().normalize()

    def _days_open(row) -> int | None:
        start = row.get("order_date_dt")
        if pd.isna(start):
            return None
        end = today_norm if not _is_closed_status(row.get("status")) else row.get("deadline_dt")
        if pd.isna(end):
            end = today_norm
        return max(0, int((pd.Timestamp(end).normalize() - pd.Timestamp(start).normalize()).days))

    def _days_until_deadline(row) -> int | None:
        deadline = row.get("deadline_dt")
        if pd.isna(deadline):
            return None
        return int((pd.Timestamp(deadline).normalize() - today_norm).days)

    search_col, customer_col = st.columns([2.15, 1])
    with search_col:
        q = st.text_input(
            "Search",
            placeholder="Customer, W-order, RO #, ship-to, requested by...",
            label_visibility="collapsed",
            key="records_search",
        )
    filtered_records = records_df.copy()
    if q:
        needle = q.lower().strip()
        mask = filtered_records.apply(
            lambda row: needle in " ".join(str(row[col]) for col in filtered_records.columns).lower(),
            axis=1,
        )
        filtered_records = filtered_records[mask].copy()
        matching_customers = set(filtered_records["customer"])
        customer_summary = customer_summary[customer_summary["Customer"].isin(matching_customers)]

    if customer_summary.empty:
        c1, c2, c3 = st.columns(3)
        with c1:
            _record_metric("Customers", 0, "#3B82F6")
        with c2:
            _record_metric("Orders Placed", 0, "#22C55E")
        with c3:
            _record_metric("Open Rows", 0, "#F59E0B")
        st.caption("No customer records match the current search.")
        return

    matching_customer_names = customer_summary["Customer"].tolist()
    ALL_CUSTOMERS = "All Matching Customers" if q else "All Customers"
    customer_names = [ALL_CUSTOMERS] + matching_customer_names

    current_customer = st.session_state.get("records_customer_select")
    if current_customer in ("All Customers", "All Matching Customers") and current_customer != ALL_CUSTOMERS:
        st.session_state.records_customer_select = ALL_CUSTOMERS
    elif q and len(matching_customer_names) == 1:
        st.session_state.records_customer_select = matching_customer_names[0]
    elif st.session_state.get("records_customer_select") not in customer_names:
        st.session_state.records_customer_select = ALL_CUSTOMERS

    if q and matching_customer_names:
        with search_col:
            st.caption("Suggestions")
            suggestion_cols = st.columns(min(4, len(matching_customer_names)))
            for idx, customer in enumerate(matching_customer_names[:4]):
                label = customer if len(customer) <= 24 else customer[:21] + "..."
                with suggestion_cols[idx]:
                    if st.button(
                        label,
                        key=f"records_suggestion_{idx}",
                        help=f"Show {customer}",
                        use_container_width=True,
                    ):
                        st.session_state.records_customer_select = customer
                        st.rerun()

    with customer_col:
        selected_customer = st.selectbox(
            "Customer",
            customer_names,
            label_visibility="collapsed",
            key="records_customer_select",
        )

    # When the user picks "All Customers" we skip per-customer detail
    # rendering entirely — they want the overview charts, not one
    # customer's order list. Charts fall through at the bottom.
    if selected_customer == ALL_CUSTOMERS:
        overview_rows = filtered_records.copy()
        overview_total = int(customer_summary["Orders"].sum())
        overview_closed = int(overview_rows["status"].apply(_is_closed_status).sum())
        overview_open = max(0, len(overview_rows) - overview_closed)
        overview_ship_to = len({v for v in overview_rows["ship_to"].astype(str) if v and v != "—"})
        overview_complete_rate = (overview_closed / len(overview_rows) * 100) if len(overview_rows) else 0

        o1, o2, o3, o4, o5 = st.columns(5)
        with o1:
            _record_metric("Customers", len(customer_summary), "#3B82F6")
        with o2:
            _record_metric("Total Orders", overview_total, "#22C55E")
        with o3:
            open_color = "#22C55E" if overview_open == 0 else "#F59E0B"
            _record_metric("Open", overview_open, open_color)
        with o4:
            rate_color = "#22C55E" if overview_complete_rate >= 80 else "#F59E0B" if overview_complete_rate >= 50 else "#EF4444"
            _record_metric("Complete %", f"{overview_complete_rate:.0f}%", rate_color)
        with o5:
            _record_metric("Ship-To", overview_ship_to, "#8B5CF6")

        st.caption(
            f"{len(customer_summary)} customers · {int(customer_summary['Orders'].sum())} unique orders. "
            "Pick a customer above to drill into their orders, or scroll for charts."
        )
        st.divider()
        st.subheader("Charts")
        chart_df = df.loc[filtered_records.index.intersection(df.index)] if q else df
        _render_customer_charts(chart_df, focus_customer=None)
        return

    detail_source = filtered_records if q else records_df
    detail = detail_source[detail_source["customer"] == selected_customer].copy()
    detail = detail.sort_values(["month", "order_id", "so"], ascending=[False, True, True])
    unique_orders = sorted({v for v in detail["order_key"].astype(str) if v and v.lower() != "nan"})
    unique_sos = sorted({v for v in detail["so"].astype(str) if v and v.lower() != "nan"})
    ship_to_values = sorted({v for v in detail["ship_to"].astype(str) if v and v != "—"})
    detail["closed"] = detail["status"].apply(_is_closed_status)
    detail["days_open"] = detail.apply(_days_open, axis=1)
    detail["days_until_deadline"] = detail.apply(_days_until_deadline, axis=1)
    completed = int(detail["closed"].sum())
    open_rows = max(0, len(detail) - completed)
    open_detail = detail[~detail["closed"]].copy()
    oldest_open_days = open_detail["days_open"].dropna().max() if not open_detail.empty else None
    due_soon = int((open_detail["days_until_deadline"].dropna().between(0, 3)).sum()) if not open_detail.empty else 0
    overdue = int((open_detail["days_until_deadline"].dropna() < 0).sum()) if not open_detail.empty else 0
    complete_rate = (completed / len(detail) * 100) if len(detail) else 0

    c1, c2, c3, c4, c5 = st.columns(5)
    with c1:
        _record_metric("Total Orders", len(unique_orders), "#22C55E")
    with c2:
        open_color = "#22C55E" if open_rows == 0 else "#F59E0B"
        _record_metric("Open", open_rows, open_color)
    with c3:
        rate_color = "#22C55E" if complete_rate >= 80 else "#F59E0B" if complete_rate >= 50 else "#EF4444"
        _record_metric("Complete %", f"{complete_rate:.0f}%", rate_color)
    with c4:
        oldest_label = f"{int(oldest_open_days)}d" if pd.notna(oldest_open_days) else "—"
        oldest_color = "#EF4444" if overdue else "#F59E0B" if due_soon or oldest_open_days else "#22C55E"
        _record_metric("Oldest Open", oldest_label, oldest_color)
    with c5:
        _record_metric("Ship-To", len(ship_to_values), "#8B5CF6")

    status_note = (
        f"{completed} closed in Excel · {open_rows} open · "
        f"{len(unique_sos)} ROs · {len(ship_to_values)} ship-to"
    )
    st.markdown(
        f"""
        <div style="
            border:1px solid rgba(128,128,128,0.18);border-radius:8px;
            padding:12px 14px;margin:2px 0 10px 0;background:rgba(128,128,128,0.04);
            font-family:{MONO};display:flex;justify-content:space-between;gap:16px;
            align-items:center;">
            <div style="font-size:1rem;font-weight:800;">{_e(selected_customer)}</div>
            <div style="font-size:0.75rem;opacity:0.62;">{_e(status_note)}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    header = (
        "<div>Order #</div><div>Ship To</div>"
        "<div>Status</div><div>Order Date</div><div>Deadline</div>"
        "<div>Days Open</div><div>Requested By</div>"
    )
    ro_sections = []
    grouped_detail = detail.sort_values(["ro_number", "order_id", "ship_to"])
    for ro_number, group in grouped_detail.groupby("ro_number", dropna=False, sort=True):
        ro_text = str(ro_number or "").strip()
        type_values = [
            value for value in group["order_type"].astype(str).str.strip()
            if value and value.lower() not in {"nan", "nat", "none", "<na>"}
        ]
        ro_prefix = type_values[0] if type_values else "RO"
        ro_label = f"{ro_prefix}.{ro_text}" if ro_text and ro_text != "—" else "No RO"
        order_values = sorted({v for v in group["order_key"].astype(str) if v and v.lower() != "nan"})
        ship_values = sorted({v for v in group["ship_to"].astype(str) if v and v != "—"})
        closed_count = int(group["closed"].sum())
        open_count = max(0, len(group) - closed_count)
        oldest_ro_open = group.loc[~group["closed"], "days_open"].dropna().max()
        complete_pct = (closed_count / len(group) * 100) if len(group) else 0
        oldest_label = f"{int(oldest_ro_open)}d" if pd.notna(oldest_ro_open) else "—"
        group_color = "#EF4444" if open_count else "#22C55E"

        row_html = []
        for _, row in group.iterrows():
            status = str(row.get("status", "") or "").strip()
            closed = _is_closed_status(status)
            status_color = "#22C55E" if closed else "#EF4444" if (row.get("days_until_deadline") is not None and row.get("days_until_deadline") < 0) else "#F59E0B" if status else "rgba(255,255,255,0.45)"
            order_date_label = row["order_date_dt"].strftime("%Y-%m-%d") if pd.notna(row.get("order_date_dt")) else "—"
            deadline_label = row["deadline_dt"].strftime("%Y-%m-%d") if pd.notna(row.get("deadline_dt")) else "—"
            days_open_label = f'{int(row["days_open"])}d' if pd.notna(row.get("days_open")) else "—"
            row_html.append(
                '<div class="records-row">'
                f'<div class="strong">{_e(row.get("order_id"))}</div>'
                f'<div class="truncate">{_e(row.get("ship_to"))}</div>'
                f'<div style="color:{status_color};font-weight:800;">{_e(status)}</div>'
                f'<div>{_e(order_date_label)}</div>'
                f'<div>{_e(deadline_label)}</div>'
                f'<div class="strong">{_e(days_open_label)}</div>'
                f'<div>{_e(row.get("requested_by"))}</div>'
                '</div>'
            )

        ro_sections.append(
            '<div class="ro-group">'
            f'<div class="ro-title" style="border-left-color:{group_color};">'
            f'<div class="ro-name">{_e(ro_label)}</div>'
            '<div class="ro-stats">'
            f'<span class="ro-stat"><span class="ro-stat-label">Orders:</span> {len(order_values)}</span>'
            '<span class="ro-stat-separator">|</span>'
            f'<span class="ro-stat" style="color:{group_color};"><span class="ro-stat-label">Orders Open:</span> {open_count}</span>'
            '<span class="ro-stat-separator">|</span>'
            f'<span class="ro-stat"><span class="ro-stat-label">Completion:</span> {complete_pct:.0f}%</span>'
            '<span class="ro-stat-separator">|</span>'
            f'<span class="ro-stat"><span class="ro-stat-label">Oldest Open:</span> {_e(oldest_label)}</span>'
            '<span class="ro-stat-separator">|</span>'
            f'<span class="ro-stat"><span class="ro-stat-label">Ship-To:</span> {len(ship_values)}</span>'
            '</div>'
            '</div>'
            f'<div class="records-head">{header}</div>'
            f'{"".join(row_html)}'
            '</div>'
        )

    records_html = f"""<style>
.records-shell {{
    font-family: {MONO};
}}
.records-head, .records-row {{
    display: grid;
    grid-template-columns: 120px minmax(220px, 1.5fr) 105px 115px 115px 95px 140px;
    gap: 10px;
    align-items: center;
    padding: 8px 14px;
}}
.records-head {{
    background: rgba(128,128,128,0.08);
    color: rgba(255,255,255,0.55);
    font-size: 0.68rem;
    font-weight: 800;
    text-transform: uppercase;
    letter-spacing: 0.7px;
}}
.records-body {{
    max-height: 430px;
    overflow: auto;
    padding: 2px 6px 12px 0;
}}
.ro-group {{
    border: 1px solid rgba(128,128,128,0.18);
    border-radius: 8px;
    overflow: hidden;
    background: rgba(128,128,128,0.035);
    margin-bottom: 20px;
    box-shadow: 0 4px 12px rgba(0,0,0,0.10);
}}
.ro-group:last-child {{
    margin-bottom: 0;
}}
.ro-title {{
    border-left: 4px solid #3B82F6;
    background: rgba(128,128,128,0.06);
    display: flex;
    justify-content: space-between;
    gap: 16px;
    align-items: center;
    padding: 10px 14px;
}}
.ro-name {{
    font-size: 0.92rem;
    font-weight: 900;
}}
.ro-stats {{
    display: flex;
    flex-wrap: wrap;
    column-gap: 8px;
    row-gap: 5px;
    color: rgba(255,255,255,0.62);
    font-size: 0.72rem;
    font-weight: 800;
}}
.ro-stat {{
    white-space: nowrap;
}}
.ro-stat-label {{
    color: rgba(255,255,255,0.78);
}}
.ro-stat-separator {{
    color: rgba(255,255,255,0.24);
}}
.records-row {{
    border-top: 1px solid rgba(128,128,128,0.10);
    font-size: 0.78rem;
}}
.records-row:hover {{
    background: rgba(59,130,246,0.08);
}}
.records-row .strong {{
    font-weight: 800;
}}
.records-row .truncate {{
    overflow: hidden;
    white-space: nowrap;
    text-overflow: ellipsis;
}}
</style>
<div class="records-shell">
<div class="records-body">{''.join(ro_sections)}</div>
</div>"""
    st.markdown("**Orders grouped by RO**")
    st.markdown(records_html, unsafe_allow_html=True)

    st.divider()
    st.subheader(f"Charts — {selected_customer}")
    chart_df = df.loc[detail.index.intersection(df.index)] if q else df
    _render_customer_charts(chart_df, focus_customer=selected_customer)


# ─────────────────────────────────────────────
# VIEW: Scan Bucket
# ─────────────────────────────────────────────
def view_ocr_debug():
    """Window into what OCR actually produced.

    Cross-references every OCR-derived order_id from ticket PDFs against
    Excel, the compiled output, and the download registries so
    you can answer: 'I uploaded N images — what did OCR do with them and
    why aren't more of them showing up in the Order Index?'
    """
    st.header("Scan Bucket")
    st.caption(
        "Everything OCR has indexed, including matches that aren't visible "
        "in the Order Index because they're not in Excel, are in a different "
        "month, or had their source file removed."
    )

    df = data_loader.excel_df
    excel_ids = set()
    excel_status_by_id = {}
    if not df.empty:
        for col in ("Order_ID", "SO"):
            if col in df.columns:
                values = df[col].fillna("").astype(str).str.strip()
                excel_ids.update(values.str.lstrip("0"))
                for idx, raw_value in values.items():
                    value = str(raw_value).strip()
                    if not value or value.lower() in ("nan", "<na>", "none"):
                        continue
                    status = str(df.at[idx, "Status"] if "Status" in df.columns else "").strip()
                    for key in {value, value.lstrip("0") or value}:
                        excel_status_by_id[key] = status
        excel_ids.discard("")
        excel_ids.discard("nan")

    # ── Visual chip helpers — tiny colored badges, no dataframes ──
    def _chip(label: str, color: str, faded: bool = False) -> str:
        opacity = "0.35" if faded else "1"
        return (
            f'<span style="display:inline-block;background:{color}22;'
            f'color:{color};border:1px solid {color}55;border-radius:10px;'
            f'padding:1px 8px;font-size:0.65rem;font-weight:700;'
            f'margin-right:4px;opacity:{opacity};font-family:{MONO};">'
            f'{label}</span>'
        )

    def _order_line(oid: str, n_pages: int, in_excel: bool, closed_excel: bool, src_gone: bool) -> str:
        # TICKET is always lit: every order in this view came out of OCR,
        # so by definition we have its ticket scan in upload_ready/.
        chips = (
            _chip("TICKET", "#3B82F6")
            + _chip("EXCEL", "#22C55E", faded=not in_excel)
        )
        if closed_excel:
            chips += _chip("CLOSED", "#8B5CF6")
        if src_gone:
            chips += _chip("SRC REMOVED", "#F59E0B")
        return (
            f'<div style="display:flex;align-items:center;gap:10px;'
            f'padding:4px 0;border-bottom:1px solid rgba(128,128,128,0.08);'
            f'font-family:{MONO};font-size:0.8rem;">'
            f'<span style="font-weight:700;min-width:110px;">{_html_text(oid)}</span>'
            f'<span style="opacity:0.5;min-width:60px;">{_html_text(n_pages)} pg</span>'
            f'{chips}'
            f'</div>'
        )

    # ── Section 1: PDF OCR — grouped by source PDF ──
    st.subheader("📄 What the OCR pulled out of each PDF")

    matched_items = [
        (oid, entries) for oid, entries in scan_index.index.items()
        if not oid.startswith("UNMATCHED_")
    ]
    unmatched_items = [
        (oid, entries) for oid, entries in scan_index.index.items()
        if oid.startswith("UNMATCHED_")
    ]

    source_groups: dict[str, dict] = {}
    for oid, entries in matched_items:
        srcs = sorted({pdf for pdf, _ in entries}, key=lambda p: str(p).lower())
        for src in srcs:
            source_path = Path(src).expanduser()
            source_key = str(source_path)
            on_disk = source_path.exists()
            n_pages_from_src = sum(1 for pdf, _ in entries if pdf == src)
            bare = oid.lstrip("0") or oid
            in_excel = oid in excel_ids or bare in excel_ids
            excel_status = excel_status_by_id.get(oid) or excel_status_by_id.get(bare) or ""
            closed_excel = excel_status.upper() in {"COMPLETE", "COMPLETED", "CLOSED"}
            is_ready = in_excel
            group = source_groups.setdefault(source_key, {
                "name": source_path.name,
                "path": source_path,
                "on_disk": on_disk,
                "orders": [],
            })
            group["on_disk"] = group["on_disk"] or on_disk
            group["orders"].append({
                "order_id": oid,
                "pages": n_pages_from_src,
                "in_excel": in_excel,
                "is_ready": is_ready,
                "closed_excel": closed_excel,
                "excel_status": excel_status,
                "source_gone": not on_disk,
            })

    unmatched_records = []
    for oid, entries in sorted(unmatched_items):
        source_path = Path(entries[0][0]).expanduser() if entries else None
        unmatched_records.append({
            "key": oid,
            "source_name": source_path.name if source_path else "—",
            "on_disk": source_path.exists() if source_path else False,
        })

    active_groups = sorted(
        (g for g in source_groups.values() if g["on_disk"]),
        key=lambda g: g["name"].lower(),
    )
    removed_groups = sorted(
        (g for g in source_groups.values() if not g["on_disk"]),
        key=lambda g: g["name"].lower(),
    )
    active_orders = [o for g in active_groups for o in g["orders"]]
    active_unmatched = [r for r in unmatched_records if r["on_disk"]]
    removed_unmatched = [r for r in unmatched_records if not r["on_disk"]]

    active_missing_excel = [o for o in active_orders if not o["in_excel"]]
    active_ready_count = sum(1 for o in active_orders if o["is_ready"])
    active_closed_excel_count = sum(1 for o in active_orders if o["closed_excel"])
    needs_input_count = len(active_missing_excel) + len(active_unmatched)
    removed_source_count = len(removed_groups)

    def _mini_metric(label: str, value, color: str, note: str | None = None):
        delta_html = ""
        if note:
            delta_html += (
                f'<span style="font-size:0.72rem;font-weight:800;color:#EF4444;'
                f'margin-left:8px;vertical-align:middle;">{note}</span>'
            )
        st.markdown(f"""
        <div style="
            border:1px solid {color}44;border-top:3px solid {color};
            border-radius:8px;padding:10px 12px;background:{color}11;
            font-family:{MONO};margin-bottom:8px;">
            <div style="font-size:0.68rem;opacity:0.55;text-transform:uppercase;">{label}</div>
            <div style="font-size:1.35rem;font-weight:800;color:{color};">{value}{delta_html}</div>
        </div>
        """, unsafe_allow_html=True)

    def _render_source_groups(groups, row_filter=None, empty_message="No rows to show."):
        rendered = 0
        for group in groups:
            rows = group["orders"]
            if row_filter:
                rows = [r for r in rows if row_filter(r)]
            if not rows:
                continue
            rendered += 1
            icon = "📄" if group["on_disk"] else "🗑"
            title = (
                f"{icon} {group['name']} · {len(rows)} order(s)"
                f"{' (source removed)' if not group['on_disk'] else ''}"
            )
            with st.expander(title, expanded=False):
                html_lines = [
                    _order_line(
                        r["order_id"],
                        r["pages"],
                        r["in_excel"],
                        r["closed_excel"],
                        r["source_gone"],
                    )
                    for r in sorted(rows, key=lambda row: row["order_id"])
                ]
                st.markdown("".join(html_lines), unsafe_allow_html=True)
        if rendered == 0:
            st.caption(empty_message)

    tab_labels = [
        f"Workflow ({len(active_orders)})",
        f"Needs Input ({needs_input_count})",
    ]
    has_archive = bool(removed_source_count or removed_unmatched)
    if has_archive:
        tab_labels.append(f"Archive ({removed_source_count})")
    tabs = st.tabs(tab_labels)

    with tabs[0]:
        c1, c2, c3, c4 = st.columns(4)
        with c1:
            _mini_metric("OCR Orders", len(active_orders), "#3B82F6")
        with c2:
            excel_note = f"-{len(active_missing_excel)} in Excel" if active_missing_excel else None
            _mini_metric("Ready: Ticket + Excel", active_ready_count, "#22C55E", note=excel_note)
        with c3:
            _mini_metric("Closed in Excel", active_closed_excel_count, "#8B5CF6")
        with c4:
            _mini_metric("Needs Input", needs_input_count, "#F59E0B")
        _render_source_groups(active_groups, empty_message="No active source PDFs are indexed.")

    with tabs[1]:
        c1, c2 = st.columns(2)
        with c1:
            _mini_metric("Missing Excel Inputs", len(active_missing_excel), "#F59E0B")
        with c2:
            _mini_metric("Unread OCR Pages", len(active_unmatched), "#EF4444")
        st.caption("Rows here need a person to decide whether Excel is missing the order or OCR could not read the page.")
        _render_source_groups(
            active_groups,
            row_filter=lambda r: not r["in_excel"],
            empty_message="No active OCR rows are missing from Excel.",
        )
        if active_unmatched:
            st.markdown(
                "<div style='height:6px;'></div>",
                unsafe_allow_html=True,
            )
            st.caption("Unread OCR pages")
            for rec in active_unmatched:
                st.markdown(
                    f'<div style="font-family:{MONO};font-size:0.78rem;'
                    f'padding:4px 0;border-bottom:1px solid rgba(128,128,128,0.08);">'
                    f'<span style="opacity:0.6;">{_html_text(rec["source_name"])}</span>  '
                    f'<span style="color:#EF4444;font-weight:600;">no order found</span>'
                    f'</div>',
                    unsafe_allow_html=True,
                )

    if has_archive:
        with tabs[2]:
            c1, c2 = st.columns(2)
            with c1:
                _mini_metric("Removed PDFs", removed_source_count, "#EF4444")
            with c2:
                _mini_metric("Removed Unread Pages", len(removed_unmatched), "#F59E0B")
            _render_source_groups(
                removed_groups,
                empty_message="No removed source PDFs are still indexed.",
            )
            if removed_unmatched:
                st.caption("Unread pages from removed sources")
                for rec in removed_unmatched:
                    st.markdown(
                        f'<div style="font-family:{MONO};font-size:0.78rem;'
                        f'padding:4px 0;border-bottom:1px solid rgba(128,128,128,0.08);">'
                        f'<span style="opacity:0.6;">{_html_text(rec["source_name"])}</span>  '
                        f'<span style="color:#F59E0B;font-weight:600;">no order found · source removed</span>'
                        f'</div>',
                        unsafe_allow_html=True,
                    )

# ─────────────────────────────────────────────
# ROUTING
# ─────────────────────────────────────────────
if page == "Order Index":
    view_order_index()
elif page == "Analysis Table":
    view_records()
elif page == "Scan Bucket":
    # Underlying function still named view_ocr_debug() — it shows the
    # OCR results overview (the "bucket of scans").
    view_ocr_debug()
