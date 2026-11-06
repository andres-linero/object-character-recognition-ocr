# Object Character Recognition (OCR)

A Streamlit dashboard that matches scanned delivery tickets to an Excel order tracker using Azure AI Document Intelligence. OCR conventionally means **Optical Character Recognition**; the project display name follows the requested name.

[See the workflow clips](#video-clips) for scan intake and incremental indexing.

## Recreate locally

Requires Python 3.11 or 3.12, an Azure Document Intelligence resource, and a Microsoft Entra app registration for sign-in.

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt -r requirements-dev.txt
cp .env.example .env
python scripts/create_sample_data.py
# Fill .env with your own Azure and Entra settings.
streamlit run ADK_Agentic/streamlit_app.py
```

Register `http://localhost:8501` as a web redirect URI in Entra, create a client secret, and supply the tenant ID, client ID, and secret. Authentication remains mandatory; there is no anonymous demo mode. Key Vault is optional and requires `AZURE_KEY_VAULT_URL` plus appropriate Azure identity access.

The sample script generates a fictional workbook and PDF. Replace `EXCEL_PATH` and place your own ticket PDFs in `Scans/incoming_scans/` when ready. Workbook columns include `Order_ID`, `SO`, `Customer_name`, `Ship_to`, and `Status`; monthly sheets are combined. Optional tracker columns enable additional dashboard views.

## Full demo dataset

Generate 100 fictional ticket packets with 6, 9, or 12 pages each, including equipment, demo terms, and acknowledgement papers:

```sh
python scripts/create_demo_data.py --count 100 --seed 42 --output demo_data
```

The generator produces scanned-style PDFs, a matching Excel/CSV tracker, and a reproducibility manifest. It uses entirely fictional data, leaves the reference PDF untouched, and makes no Azure calls. See the [demo-data guide](docs/demo-data.md) for options and dashboard setup.

## Data and privacy

The default OCR crop sends the top-right half of the top quarter of each page to Azure. A geometric crop cannot guarantee that personal information is absent: inspect your document layout first. The OCR utility also exposes an uncropped option. Local workbooks, PDFs, caches, outputs, credentials, and virtual environments are excluded from Git. Use trusted local cache files only: the Excel cache uses Python pickle.

The application has one access level after sign-in. It listens on localhost. Review authentication, authorization, and data handling before deploying to shared infrastructure. Azure OCR can incur charges.

## Dependencies and checks

Runtime dependencies are copied in `ADK_Agentic/requirements.txt`; root `requirements.txt` forwards to them. Development dependencies are in `requirements-dev.txt`. Versions are minimum constraints, not an exact lockfile.

```sh
python -m pytest -q
```

Tests mock Azure OCR; they do not prove live sign-in or Azure connectivity. See `PRP.md` for audit findings and remaining publication checks.

## Architecture and documentation

The app runs as one Streamlit process with a local workbook loader, PDF scan index, Azure OCR adapter, and local workflow files. Microsoft Entra sign-in gates workbook loading and OCR. See the [architecture diagram and data flow](docs/architecture.md).

Start with the [documentation guide](docs/README.md), then use the [configuration reference](docs/configuration.md), [operations guide](docs/operations.md), and [proposed architecture decision](docs/decisions/0001-modular-monolith.md). Proposed architecture changes are not yet implemented.

Use the [Google Doc architecture workspace](https://docs.google.com/document/d/19lhy8-3sdm3E9ZSVoxvQ6Cty-0Tm62eW5EJPxWn24YQ/edit?usp=drivesdk) for design discussion. Versioned repository guides remain the source of truth; synchronization is manual. The document retains its existing Drive access settings.

## Video clips

Short, silent clips from the supplied recordings demonstrate scan intake and incremental indexing. These recordings predate the public copy; they show workflow behavior, not current performance benchmarks.

### Scan intake

Place scanned PDFs in the incoming scans directory. The app checks for new or changed PDFs during dashboard reruns.

![Scan intake: navigating the incoming PDF folder](docs/media/scan-intake.gif)

[Open scan-intake clip](docs/media/scan-intake.gif) · 11 seconds · account sidebar and desktop cropped out.

### Incremental indexing

Unchanged PDFs reuse their cached associations. New or changed PDFs trigger OCR; the log reports cache hits and the work that remains.

![Incremental indexing: cache hits and changed-PDF detection](docs/media/incremental-indexing.gif)

[Open indexing clip](docs/media/incremental-indexing.gif) · 18 seconds · operational identifiers and filenames concealed.

Both clips are silent animated GIFs that play directly in the README. The original videos remain local. See [clip provenance and editing notes](docs/walkthroughs.md).
