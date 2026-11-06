"""Create synthetic inputs only; no Azure calls or private data."""
from pathlib import Path
import pandas as pd
import fitz

root = Path(__file__).resolve().parents[1]
(root / "examples").mkdir(exist_ok=True)
pd.DataFrame([{"Order_ID": "W-100001", "SO": "3501", "Customer_name": "Example Company", "Ship_to": "Example Depot", "Status": "Open"}]).to_excel(root / "examples/orders.xlsx", index=False)
scans = root / "Scans/incoming_scans"
scans.mkdir(parents=True, exist_ok=True)
with fitz.open() as doc:
    page = doc.new_page()
    page.insert_text((330, 40), "Delivery Ticket")
    page.insert_text((330, 60), "Shipment No. 003501")
    doc.save(scans / "sample_ticket.pdf")
print("Created synthetic workbook and ticket PDF")
