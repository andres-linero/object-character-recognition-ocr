"""
Scan Index — Pre-scans multi-page PDFs, maps order IDs to page numbers,
and auto-classifies by extracting each order's pages into individual files.

After indexing, each order has:
  - upload_ready/{order_id}.pdf   (extracted pages)
  - upload_ready/{order_id}.png   (first page preview)
"""

import os
import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional

import fitz  # PyMuPDF

from ocr import extract_order_number, HEADER_CROP_HEIGHT, HEADER_CROP_WIDTH
from utils import normalize_order_token

logger = logging.getLogger(__name__)

CACHE_DIR = Path(__file__).parent / "cache"
SCANS_DIR = Path(__file__).parent / "upload_ready"
INDEX_FILE = CACHE_DIR / "scan_index.json"
CLEANUP_DAYS = 7  # Auto-delete output files older than this


class ScanIndex:
    """Index scanned PDFs and auto-classify into per-order files."""

    def __init__(self):
        self.pdf_path: Optional[str] = None
        self.pdf_paths: List[str] = []  # all PDFs that were indexed
        self.index: Dict[str, List] = {}  # order_id -> [(pdf_path, page_num), ...]
        self.page_source: Dict[str, str] = {}  # order_id -> primary source pdf
        # pdf_path -> {"size": bytes, "mtime_ns": modified timestamp}.
        # Older caches stored only the file size; those entries are treated
        # as stale once and rewritten with the stronger signature.
        self.pdf_signatures: Dict[str, Dict[str, int]] = {}
        self._load_cache()

    @staticmethod
    def _pdf_signature(path: Path) -> Dict[str, int]:
        st = path.stat()
        return {"size": st.st_size, "mtime_ns": st.st_mtime_ns}

    @staticmethod
    def _signature_matches(cached, current: Dict[str, int]) -> bool:
        if not isinstance(cached, dict):
            return False
        return (
            cached.get("size") == current["size"]
            and cached.get("mtime_ns") == current["mtime_ns"]
        )

    def _load_cache(self):
        """Load cached index if it exists."""
        if INDEX_FILE.exists():
            try:
                data = json.loads(INDEX_FILE.read_text())
                self.pdf_path = data.get("pdf_path")
                self.pdf_paths = data.get("pdf_paths", [])
                # Deserialize [pdf_path, page_num] lists back to tuples
                raw_index = data.get("index", {})
                self.index = {}
                for oid, entries in raw_index.items():
                    if entries and isinstance(entries[0], list):
                        self.index[oid] = [tuple(e) for e in entries]
                    else:
                        # Legacy format: bare page numbers — discard, will re-index
                        self.index = {}
                        break
                self.page_source = data.get("page_source", {})
                self.pdf_signatures = data.get("pdf_signatures", {})
                logger.info(f"Loaded scan index: {len(self.index)} orders from cache")
            except Exception as e:
                logger.warning(f"Failed to load scan index cache: {e}")

    def _save_cache(self):
        """Save index to disk. Tuples serialize as [pdf_path, page_num] lists."""
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        serializable_index = {
            oid: [list(entry) for entry in entries]
            for oid, entries in self.index.items()
        }
        data = {
            "pdf_path": self.pdf_path,
            "pdf_paths": self.pdf_paths,
            "index": serializable_index,
            "page_source": self.page_source,
            "pdf_signatures": self.pdf_signatures,
        }
        INDEX_FILE.write_text(json.dumps(data, indent=2))

    def build_index(self, pdf_path: str) -> Dict[str, List]:
        """
        Scan every page of the PDF, OCR each one, build order->pages mapping,
        then auto-classify by extracting each order into its own PDF + preview image.
        """
        pdf_path = str(pdf_path)

        # If already indexed this exact file and scans exist, return cached
        if self.pdf_path == pdf_path and self.index and SCANS_DIR.exists():
            existing = list(SCANS_DIR.glob("*.pdf"))
            if len(existing) >= len(self.index):
                print(f"  Scan index cached: {len(self.index)} orders, {len(existing)} files")
                return self.index

        print(f"  Building scan index for: {os.path.basename(pdf_path)}")
        doc = fitz.open(pdf_path)
        self.index = {}
        self.pdf_path = pdf_path

        for page_num in range(len(doc)):
            page = doc[page_num]
            page_rect = page.rect
            header_rect = fitz.Rect(
                page_rect.x0 + page_rect.width * (1 - HEADER_CROP_WIDTH),
                page_rect.y0,
                page_rect.x1,
                page_rect.y0 + page_rect.height * HEADER_CROP_HEIGHT,
            )
            pix = page.get_pixmap(dpi=200, clip=header_rect)
            image_bytes = pix.tobytes("png")

            try:
                order_id = extract_order_number(image_bytes, crop_header=False)
                if order_id:
                    clean_id = order_id.strip().lstrip("0") or order_id.strip()
                    if clean_id not in self.index:
                        self.index[clean_id] = []
                    entry = (pdf_path, page_num)
                    if entry not in self.index[clean_id]:
                        self.index[clean_id].append(entry)
                    print(f"    Page {page_num + 1}: {order_id} -> {clean_id}")
                else:
                    print(f"    Page {page_num + 1}: no order found")
            except Exception as e:
                logger.warning(f"OCR failed on page {page_num + 1}: {e}")

        total_pages = len(doc)

        # Auto-classify: extract each order's pages into individual files
        SCANS_DIR.mkdir(parents=True, exist_ok=True)
        print(f"\n  Auto-classifying {len(self.index)} orders into {SCANS_DIR}/")

        for order_id, page_entries in self.index.items():
            order_pdf = SCANS_DIR / f"{order_id}.pdf"
            new_doc = fitz.open()
            page_nums = sorted(p for _, p in page_entries)
            for p in page_nums:
                if p < total_pages:
                    new_doc.insert_pdf(doc, from_page=p, to_page=p)
            new_doc.save(str(order_pdf))
            new_doc.close()

            # Save first page as preview image
            first_page = doc[page_nums[0]]
            pix = first_page.get_pixmap(dpi=150)
            preview_path = SCANS_DIR / f"{order_id}.png"
            pix.save(str(preview_path))

            print(f"    {order_id}: {len(page_entries)} page(s) -> {order_pdf.name}")

        doc.close()
        self._save_cache()
        print(f"  Done: {len(self.index)} orders classified across {total_pages} pages")
        return self.index

    def build_index_folder(self, folder_path: str, force: bool = False) -> Dict[str, List]:
        """Scan ALL PDFs in a folder, merge results into one index.
        Skips PDFs that haven't changed since last scan (same filename,
        file size, and modified timestamp).
        """
        folder = Path(folder_path)
        pdf_files = sorted(folder.glob("*.pdf"))
        if not pdf_files:
            print(f"  No PDFs found in {folder}")
            return self.index

        current_paths = [str(p) for p in pdf_files]

        # Build current signatures: path -> {"size", "mtime_ns"}
        current_sigs = {str(p): self._pdf_signature(p) for p in pdf_files}

        # Figure out which PDFs are new or changed
        if force:
            to_scan = current_paths
            print(f"  [FORCE] Re-scanning all {len(current_paths)} PDF(s)")
        else:
            to_scan = [
                p for p in current_paths
                if p not in self.pdf_signatures
                or not self._signature_matches(self.pdf_signatures[p], current_sigs[p])
            ]
            if not to_scan:
                # Announce cache hit up-front — makes it obvious in logs that
                # we're NOT re-OCR'ing. If this never prints, the cache isn't
                # being loaded on startup.
                print(f"  [CACHE HIT] {len(current_paths)} PDF(s) unchanged, {len(self.index)} orders known")
            else:
                print(f"  [CACHE PARTIAL] {len(to_scan)} new/changed PDF(s), {len(current_paths) - len(to_scan)} from cache")

        # Source PDF removed from folder → DON'T purge the order from the
        # index. Once we OCR'd the file, the order's pages were already
        # extracted into upload_ready/{order_id}.pdf, which is the
        # permanent record. Removing the source scan should NOT undo that
        # work or flip an order's has_ticket status back to false.
        # We only drop the signature so we don't carry a stale path
        # forever; index entries stay so find_pages() / get_scan_pdf()
        # keep working.
        removed_pdfs = set(self.pdf_signatures.keys()) - set(current_paths)
        if removed_pdfs:
            self.pdf_signatures = {p: s for p, s in self.pdf_signatures.items() if p not in removed_pdfs}
            self.pdf_paths = current_paths
            self._save_cache()
            print(f"  {len(removed_pdfs)} source PDF(s) removed from folder — index entries kept (already classified)")

        # If nothing changed at all, return cached
        if not to_scan and self.index:
            print(f"  Scan index cached: {len(self.index)} orders from {len(pdf_files)} PDFs (no changes)")
            return self.index

        # Remove cached entries for PDFs that will be re-scanned
        if to_scan and not force:
            scan_set = set(to_scan)
            old_keys = [
                oid for oid, entries in self.index.items()
                if any(pdf_path in scan_set for pdf_path, _ in entries)
            ]
            for oid in old_keys:
                # Only remove entries from PDFs being re-scanned, keep others
                self.index[oid] = [
                    (pdf_path, page_num) for pdf_path, page_num in self.index[oid]
                    if pdf_path not in scan_set
                ]
                if not self.index[oid]:
                    del self.index[oid]
                    self.page_source.pop(oid, None)

            skipped = len(pdf_files) - len(to_scan)
            print(f"  Skipping {skipped} unchanged PDF(s), scanning {len(to_scan)} new/changed")
        else:
            self.index = {}
            self.page_source = {}

        self.pdf_paths = current_paths

        for pdf_path in to_scan:
            print(f"\n  Scanning: {os.path.basename(pdf_path)}")
            self._index_single_pdf(pdf_path)
            # Incremental checkpoint: save signature + cache after EACH PDF
            # so we never lose progress if a later PDF crashes the loop
            self.pdf_signatures[pdf_path] = current_sigs[pdf_path]
            self._save_cache()

        # Remove signatures for PDFs no longer in folder
        self.pdf_signatures = {p: s for p, s in self.pdf_signatures.items() if p in current_sigs}

        # Auto-classify: group by source PDF and extract correct pages
        SCANS_DIR.mkdir(parents=True, exist_ok=True)
        print(f"\n  Auto-classifying {len(self.index)} orders into {SCANS_DIR}/")

        for order_id, page_entries in self.index.items():
            # Group entries by source PDF
            by_pdf = {}
            for src_pdf, page_num in page_entries:
                by_pdf.setdefault(src_pdf, []).append(page_num)

            # Skip orders whose source PDFs are all gone — the existing
            # upload_ready/{order_id}.pdf was created on first OCR and is
            # still valid. Re-classifying with no source would just blank it.
            available_sources = {src for src in by_pdf if os.path.exists(src)}
            if not available_sources:
                continue

            order_pdf = SCANS_DIR / f"{order_id}.pdf"
            new_doc = fitz.open()
            first_page_ref = None

            for src_pdf, page_nums in by_pdf.items():
                if src_pdf not in available_sources:
                    continue
                doc = fitz.open(src_pdf)
                total = len(doc)
                for p in sorted(page_nums):
                    if p < total:
                        new_doc.insert_pdf(doc, from_page=p, to_page=p)
                        if first_page_ref is None:
                            first_page_ref = (src_pdf, p)
                doc.close()

            new_doc.save(str(order_pdf))
            new_doc.close()

            # Save first page as preview image
            if first_page_ref:
                src, p = first_page_ref
                doc = fitz.open(src)
                pix = doc[p].get_pixmap(dpi=150)
                preview_path = SCANS_DIR / f"{order_id}.png"
                pix.save(str(preview_path))
                doc.close()

            print(f"    {order_id}: {len(page_entries)} page(s) -> {order_pdf.name}")

        self._save_cache()
        print(f"  Done: {len(self.index)} orders from {len(pdf_files)} PDFs")
        return self.index

    def _index_single_pdf(self, pdf_path: str):
        """Index one PDF and merge results into self.index."""
        doc = fitz.open(pdf_path)

        for page_num in range(len(doc)):
            page = doc[page_num]
            page_rect = page.rect
            header_rect = fitz.Rect(
                page_rect.x0 + page_rect.width * (1 - HEADER_CROP_WIDTH),
                page_rect.y0,
                page_rect.x1,
                page_rect.y0 + page_rect.height * HEADER_CROP_HEIGHT,
            )
            pix = page.get_pixmap(dpi=200, clip=header_rect)
            image_bytes = pix.tobytes("png")

            try:
                order_id = extract_order_number(image_bytes, crop_header=False)
                if order_id:
                    clean_id = order_id.strip().lstrip("0") or order_id.strip()
                    if clean_id not in self.index:
                        self.index[clean_id] = []
                        self.page_source[clean_id] = pdf_path
                    entry = (pdf_path, page_num)
                    if entry not in self.index[clean_id]:
                        self.index[clean_id].append(entry)
                    print(f"    Page {page_num + 1}: {order_id} -> {clean_id}")
                else:
                    unmatched_key = f"UNMATCHED_{os.path.basename(pdf_path)}_p{page_num + 1}"
                    self.index[unmatched_key] = [(pdf_path, page_num)]
                    self.page_source[unmatched_key] = pdf_path
                    print(f"    Page {page_num + 1}: no order found -> {unmatched_key}")
            except Exception as e:
                logger.warning(f"OCR failed on page {page_num + 1}: {e}")

        doc.close()

    def find_pages(self, order_id: str) -> List[int]:
        """Find page numbers matching an order ID (returns bare page nums)."""
        key = self._resolve_order_id(order_id)
        if key and key in self.index:
            return [p for _, p in self.index[key]]
        return []

    def _resolve_order_id(self, order_id: str) -> Optional[str]:
        """Resolve exact typed IDs; a shipment never aliases a W- work order."""
        token = str(order_id).strip()
        if token.startswith("UNMATCHED_") and token in self.index:
            return token if Path(token).name == token and "\\" not in token else None
        normalized = normalize_order_token(token)
        if normalized is None:
            return None
        matches = [key for key in self.index if normalize_order_token(key) == normalized]
        return matches[0] if len(matches) == 1 else None

    def get_scan_pdf(self, order_id: str) -> Optional[str]:
        """Get path to the pre-classified PDF for an order. Returns None if not found."""
        key = self._resolve_order_id(order_id)
        if not key:
            return None
        path = SCANS_DIR / f"{key}.pdf"
        return str(path) if path.exists() else None

    def get_scan_preview(self, order_id: str) -> Optional[str]:
        """Get path to the preview PNG for an order. Returns None if not found."""
        key = self._resolve_order_id(order_id)
        if not key:
            return None
        path = SCANS_DIR / f"{key}.png"
        return str(path) if path.exists() else None


def cleanup_old_files(days: int = CLEANUP_DAYS):
    """Delete files older than X days from output/ only.

    upload_ready/ is intermediate — its files are created at OCR-scan time,
    which is usually long before the order is compiled. Cleaning them on a
    7-day clock independent of output/ caused completed orders to display
    a misleading "X Ticket" badge. Now we only clean the user-facing
    output/ folder. When that PDF is deleted, the order naturally falls
    off the Complete tab.
    """
    output_dir = Path(__file__).parent / "output"
    cutoff = datetime.now() - timedelta(days=days)
    deleted = 0

    if output_dir.exists():
        for f in output_dir.iterdir():
            if f.is_file() and datetime.fromtimestamp(f.stat().st_mtime) < cutoff:
                f.unlink()
                deleted += 1

    if deleted:
        print(f"  Cleanup: deleted {deleted} files older than {days} days")


# Singleton
_scan_index: Optional[ScanIndex] = None


def get_scan_index() -> ScanIndex:
    global _scan_index
    if _scan_index is None:
        _scan_index = ScanIndex()
    return _scan_index
