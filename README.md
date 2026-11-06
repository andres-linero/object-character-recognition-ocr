# Object Character Recognition (OCR)

A Streamlit dashboard that matches scanned delivery tickets to an Excel order tracker using Azure AI Document Intelligence. OCR conventionally means **Optical Character Recognition**; the project display name follows the requested name.

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

## Video walkthroughs

The supplied recordings illustrate two parts of the workflow:

1. **Scan intake:** place a PDF directly in the configured incoming directory. The application checks that directory during dashboard reruns.
2. **Incremental indexing:** unchanged PDFs reuse cached associations; new or changed PDFs are OCRed page by page, then grouped into order PDFs and previews.

The original recordings contain account or operational details and are not published here. See the [recording review and walkthrough plan](docs/walkthroughs.md) for approximate timestamps and the plan for public versions.
