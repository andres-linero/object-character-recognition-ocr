"""
Simple Excel Data Loader
Loads work order data from Excel file
"""

import io
import os
import sys
from pathlib import Path
import pandas as pd
from typing import List, Dict, Optional


CACHE_DIR = Path(__file__).parent / "cache"
EXCEL_CACHE_FILE = CACHE_DIR / "excel_cache.pkl"


def _read_file_bytes_windows_shared(path: str) -> bytes:
    """Read a file via the Win32 API with maximum share flags.

    Python's built-in open() doesn't request FILE_SHARE_WRITE, so it fails
    with PermissionError when Excel (or OneDrive) has the file locked.
    CreateFileW with FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE
    succeeds because it tells Windows "I don't care who else has this open,
    just let me read it."
    """
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    CreateFileW = kernel32.CreateFileW
    CreateFileW.argtypes = [
        wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
        ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE,
    ]
    CreateFileW.restype = wintypes.HANDLE

    GENERIC_READ = 0x80000000
    FILE_SHARE_ALL = 0x1 | 0x2 | 0x4
    OPEN_EXISTING = 3
    FILE_ATTRIBUTE_NORMAL = 0x80
    INVALID_HANDLE = ctypes.c_void_p(-1).value

    handle = CreateFileW(
        path, GENERIC_READ, FILE_SHARE_ALL, None,
        OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, None,
    )
    if not handle or handle == INVALID_HANDLE:
        err = ctypes.get_last_error()
        raise OSError(f"CreateFileW failed on {path} (Win32 error {err})")

    try:
        size = ctypes.c_longlong()
        if not kernel32.GetFileSizeEx(handle, ctypes.byref(size)):
            raise OSError("GetFileSizeEx failed")
        buf = (ctypes.c_char * size.value)()
        read = wintypes.DWORD()
        if not kernel32.ReadFile(handle, buf, size.value, ctypes.byref(read), None):
            raise OSError("ReadFile failed")
        return bytes(buf[:read.value])
    finally:
        kernel32.CloseHandle(handle)


# Header aliases. the operator sometimes shortens or re-cases column names as she
# spins up a new monthly sheet ("Customer_name" → "Customer", "Deadline
# Status" → "Deadline status"). Fold each variant back to the canonical
# name BEFORE concat so all monthly sheets land in the same column rather
# than fragmenting into two half-empty columns. Key/value pairs are exact
# matches — add new entries here if the operator invents another variant.
_COLUMN_ALIASES = {
    "Customer": "Customer_name",
    "Deadline status": "Deadline Status",
}


def _excel_signature(path: str) -> dict:
    st = os.stat(path)
    return {
        "path": os.path.abspath(path),
        "size": st.st_size,
        "mtime_ns": st.st_mtime_ns,
    }


def _load_cached_excel(signature: dict) -> Optional[pd.DataFrame]:
    if not EXCEL_CACHE_FILE.exists():
        return None
    try:
        cached = pd.read_pickle(EXCEL_CACHE_FILE)
        if cached.get("signature") == signature:
            return cached.get("data")
    except Exception:
        return None
    return None


def _save_cached_excel(signature: dict, df: pd.DataFrame) -> None:
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        pd.to_pickle({"signature": signature, "data": df}, EXCEL_CACHE_FILE)
    except Exception:
        pass


def _read_excel_resilient(path: str) -> pd.DataFrame:
    """Read every sheet from an Excel file and concat them into one DataFrame.

    the operator's tracker has one sheet per month (JAN, FEB, MAR, APRIL, MAY, …).
    Each row gets a Source_Sheet column so we know which month it came from.
    Sheets with slightly different headers are normalized via
    `_COLUMN_ALIASES` before concat so renames don't split a column in two.

    Falls back to Win32 shared-read on PermissionError so OneDrive / Excel
    holding a lock doesn't block us.
    """
    def _read(src) -> dict:
        # sheet_name=None returns {sheet_name: DataFrame}
        return pd.read_excel(src, sheet_name=None)

    try:
        sheets = _read(path)
    except PermissionError:
        if sys.platform != "win32":
            raise
        data = _read_file_bytes_windows_shared(path)
        sheets = _read(io.BytesIO(data))

    frames = []
    for name, df in sheets.items():
        if df is None or df.empty:
            continue
        df = df.copy()
        df = df.rename(columns=_COLUMN_ALIASES)
        df["Source_Sheet"] = name
        frames.append(df)

    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True, sort=False)


class DataLoader:
    """Load and search work orders from Excel"""

    def __init__(self):
        """Initialize with Excel data"""
        self.excel_df = pd.DataFrame()
        self.excel_path: Optional[str] = None
        self.excel_mtime: float = 0.0
        self._load_excel()

    def _load_excel(self):
        """Load the Excel file from EXCEL_PATH into memory."""
        # Strip whitespace AND stray quotes that users sometimes leave
        # behind in .env (e.g. IMAGE_PATH=...Scans/Foo" with a trailing ").
        raw = os.getenv("EXCEL_PATH") or ""
        excel_path = raw.strip().strip('"').strip("'").strip()

        if not excel_path:
            print("[X] EXCEL_PATH environment variable is not set")
            self.excel_df = pd.DataFrame()
            self.excel_path = None
            self.excel_mtime = 0.0
            return

        if not os.path.exists(excel_path):
            print(f"[X] Excel file not found: {excel_path}")
            self.excel_df = pd.DataFrame()
            self.excel_path = excel_path
            self.excel_mtime = 0.0
            return

        try:
            signature = _excel_signature(excel_path)
            df = _load_cached_excel(signature)
            loaded_from_cache = df is not None
            if df is None:
                df = _read_excel_resilient(excel_path)
                # Normalize: convert to string, strip whitespace, drop the trailing
                # ".0" that pandas leaves on numeric-typed columns (SO is stored
                # as a float in Excel so 19542 becomes "19542.0" after astype(str)).
                for col in ['Order_ID', 'SO']:
                    if col in df.columns:
                        df[col] = (
                            df[col]
                            .astype(str)
                            .str.strip()
                            .str.replace(r'\.0$', '', regex=True)
                        )
                # Coerce every text-ish column to a real string up front, then
                # strip. pandas tags columns differently depending on cell
                # content:
                #   - mixed types (e.g. checkbox col with bool + str) → object
                #   - pure strings with NaN gaps → the new `str` dtype (which
                #     `include='object'` does NOT match in current pandas)
                # We need both, so target every non-numeric / non-datetime /
                # non-bool column. Casting via `.astype(str)` guarantees every
                # cell is a real string and downstream code that relies on
                # string ops never blows up when a new column shows up.
                # `astype(str)` turns NaN/NaT/None into the literal strings
                # "nan"/"nat"/"none" — replace those sentinels with empty so
                # the UI doesn't render "nan" in Customer / Ship-to cells.
                _BLANK_SENTINELS = {"nan", "nat", "none", "<na>", ""}
                text_cols = df.select_dtypes(
                    exclude=['number', 'datetime', 'datetimetz', 'bool', 'timedelta']
                ).columns
                for col in text_cols:
                    if col in ('Order_ID', 'SO'):
                        continue
                    # fillna('') BEFORE astype(str) — pandas 3's StringDtype
                    # stores blanks as pd.NA, and the .astype(str) cast can
                    # leave them as float NaN downstream rather than the
                    # literal 'nan' string. fillna handles both NA and float
                    # NaN uniformly. The mask() pass then scrubs any residual
                    # legacy "nan"/"nat"/"none" strings that come from older
                    # exports.
                    s = df[col].fillna('').astype(str).str.strip()
                    df[col] = s.mask(s.str.lower().isin(_BLANK_SENTINELS), '')
                _save_cached_excel(signature, df)

            self.excel_df = df.copy()
            self.excel_path = excel_path
            self.excel_mtime = os.path.getmtime(excel_path)
            source = "Excel cache" if loaded_from_cache else "Excel"
            print(f"[OK] Loaded {len(self.excel_df)} work orders from {source}")
        except Exception as e:
            # On read failure, KEEP the previous good DataFrame rather than
            # wiping it out. Transient OneDrive / Excel-lock errors should
            # not blank the dashboard.
            print(f"[X] Error loading Excel ({type(e).__name__}: {e}) -- keeping previous {len(self.excel_df)} rows")
            import traceback
            traceback.print_exc()

    def maybe_reload(self) -> bool:
        """Reload the Excel file if it has changed on disk since last read.

        Called on every Streamlit rerun. Cheap — one getmtime() call when the
        file hasn't changed, full reload only when the file was modified.
        Returns True if a reload actually happened.
        """
        excel_path = (os.getenv("EXCEL_PATH") or "").strip()
        if not excel_path or not os.path.exists(excel_path):
            return False
        try:
            current_mtime = os.path.getmtime(excel_path)
        except OSError:
            return False
        if current_mtime > self.excel_mtime or self.excel_df.empty:
            print(f"Excel file changed on disk — reloading")
            self._load_excel()
            return True
        return False

    def get_all_orders(self, limit: int = 100) -> List[Dict]:
        """Get all work orders"""
        if self.excel_df.empty:
            return []

        return self.excel_df.head(limit).to_dict('records')

    def search_orders(self, query: str, limit: int = 100) -> List[Dict]:
        """Search Excel rows by order ID, SO, customer, ship-to, or assignee."""
        if self.excel_df.empty or not query.strip():
            return self.get_all_orders(limit)

        q = query.strip().lower()
        search_cols = [
            c for c in ("Order_ID", "SO", "Customer_name", "Ship_to", "Requested by", "Status")
            if c in self.excel_df.columns
        ]
        if not search_cols:
            return []

        mask = self.excel_df[search_cols].astype(str).apply(
            lambda row: any(q in str(v).lower() for v in row), axis=1
        )
        return self.excel_df[mask].head(limit).to_dict("records")

    def get_order_by_id(self, order_id: str) -> Optional[Dict]:
        """Get specific order by Order_ID or SO number"""
        if self.excel_df.empty:
            return None

        clean_id = order_id.strip().lstrip("0") or order_id.strip()

        for col in ['Order_ID', 'SO']:
            if col in self.excel_df.columns:
                col_vals = self.excel_df[col].astype(str).str.strip().str.lstrip("0")
                result = self.excel_df[col_vals == clean_id]
                if not result.empty:
                    return result.iloc[0].to_dict()

        return None


def get_data_loader() -> DataLoader:
    """Get data loader instance"""
    return DataLoader()
