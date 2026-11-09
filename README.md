# Optical Character Recognition (OCR)

A document operations workspace for tracking work orders, delivery details, ticket pages, and Azure OCR verification. A custom web UI talks to a FastAPI backend over the relational data pipeline.

[See the workflow clips](#video-clips) for scan intake and incremental indexing.

## Run the product UI

The local synthetic workspace needs no API key to browse existing records. From an activated Python environment:

```sh
python3 -m pip install -r requirements.txt
# Only if generated datasets are not already present:
python3 scripts/create_demo_data.py --count 100 --seed 42 --output demo_data
python3 scripts/prepare_workspace.py
sh scripts/run_web.sh
```

Open **http://127.0.0.1:8700**. The tabs are Overview, Dataset (tracker records), Documents, OCR activity, Review queue, and Ingestion history. There is one live workspace, with no test-stage dropdown. Source records do not become scanned files until a PDF is placed into intake.

Drag a generated demo PDF onto **Drop a PDF to start OCR**, use **Choose PDF**, or place it directly in **`Scans/incoming/`**. Browser uploads are limited to 50 MB and use the same watched-folder workflow. While the server is running, its background worker waits for the copy to stabilize, preserves a source snapshot, and invokes Azure OCR for each unattempted page. Configure `AZURE_DOC_INTEL_ENDPOINT` and `AZURE_DOC_INTEL_KEY` in your local `.env` first; processing incurs provider charges. The view refreshes every five seconds. The local unauthenticated demo accepts PDFs matching the generated fixture manifests; unknown files are skipped rather than labeled synthetic.

The three new sample PDFs wait outside intake at **`demo_batches/intake_test_03/ready_to_scan/`**. Move or copy one into `Scans/incoming/` to test automatic detection. Earlier test databases remain local archives and are not exposed as separate workspaces.

The Dataset tab shows tracker records. Source PDF file counts, actual OCR page results, previews and ticket-only downloads remain separate from that record count. Company and jobsite are resolved from the tracker after OCR identifies the order. See the [product UI guide](docs/product-ui.md).

## Legacy signed-in interface

The original Streamlit interface remains available for compatibility. Its dependencies and Microsoft sign-in settings are separate from the new local product UI.

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt -r requirements-dev.txt
cp .env.example .env
python scripts/create_sample_data.py
# Fill .env with your own Azure and Entra settings.
streamlit run ADK_Agentic/streamlit_app.py
```

Register `http://localhost:8501` as a web redirect URI in Entra, create a client secret, and supply the tenant ID, client ID, and secret. Authentication remains mandatory in the live app. The separate synthetic preview requires no sign-in. Key Vault is optional and requires `AZURE_KEY_VAULT_URL` plus appropriate Azure identity access.

The sample script generates a fictional workbook and PDF. Replace `EXCEL_PATH` and place your own ticket PDFs in `Scans/incoming_scans/` when ready. Workbook columns include `Order_ID`, `SO`, `Customer_name`, `Ship_to`, and `Status`; monthly sheets are combined. Optional tracker columns enable additional dashboard views.

## Live OCR validation

The two new synthetic batches passed live Azure verification: **120/120 pages matched their expected shipment IDs**, across 20 tickets, with no mismatches or provider errors. See the [method, evidence, and limitations](docs/ocr-validation-results.md).

## Full demo dataset

Generate 100 fictional ticket packets with 6, 9, or 12 pages each, including equipment, demo terms, and acknowledgement papers:

```sh
python scripts/create_demo_data.py --count 100 --seed 42 --output demo_data
```

The generator produces scanned-style PDFs, a matching Excel/CSV tracker, and a reproducibility manifest. It uses entirely fictional data, leaves the reference PDF untouched, and makes no Azure calls. See the [demo-data guide](docs/demo-data.md) for options and dashboard setup.

## Data and privacy

The default OCR crop sends the top-right half of the top quarter of each page to Azure. A geometric crop cannot guarantee that personal information is absent: inspect your document layout first. The OCR utility also exposes an uncropped option. Local workbooks, PDFs, caches, outputs, credentials, and virtual environments are excluded from Git. Use trusted local cache files only: the Excel cache uses Python pickle.

The product UI is a localhost synthetic-data workspace. The legacy interface retains Microsoft sign-in. Production private-data access is outside the new UI's current scope. Azure processing is invoked separately and can incur charges.

## Dependencies and checks

`pyproject.toml` and `uv.lock` define the reproducible Python environment (Python 3.12–3.13). The requirement files remain compatible convenience entrypoints; CI uses the lock. Frontend development dependencies are locked in `web/package-lock.json`.

```sh
uv sync --locked --all-groups
uv run --locked ruff check ADK_Agentic scripts tests
uv run --locked pytest -q
uv run --locked pre-commit install
cd web
npm ci
npm test
```

Pull requests run Ubuntu tests with PostgreSQL 17, Windows tests including the real shared-read API, frontend DOM tests, lint, and a redacted Gitleaks history scan. Dependabot proposes Python, npm, and Actions updates. Deployments remain manual: there is no configured production target or automatic CD. Merge through reviewed feature branches.

Tests mock Azure OCR; they do not prove live sign-in or Azure connectivity. See the [current audit and remaining work](docs/audit-hardening.md). `PRP.md` preserves the initial public-copy audit.

## Architecture and documentation

The primary interface is a static HTML/CSS/JavaScript client served by FastAPI. Its API reads the SQL order/page model and keeps expected associations separate from actual OCR evidence. Azure processing and tracker ETL are explicit backend operations. See the [product architecture](docs/product-ui.md) and [data flow](docs/architecture.md).

Start with the [documentation guide](docs/README.md), then use the [configuration reference](docs/configuration.md), [operations guide](docs/operations.md), and [proposed architecture decision](docs/decisions/0001-modular-monolith.md). The guides identify implemented features and remaining migration work.

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
