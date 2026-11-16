# Contributing

Use a branch from current `main` and open a pull request with the problem, resulting behavior and validation. See [setup](docs/project-reference.md#run-locally) for prerequisites and Azure configuration.

```sh
uv sync --locked --all-groups
uv run --locked ruff check ocr_workspace scripts tests
uv run --locked pytest -q
cd web
npm ci
npm run check
npm test
```

Python dependencies belong in `pyproject.toml`; refresh and commit `uv.lock` after dependency changes. Frontend test dependencies belong in `web/package.json` and its lockfile. CI checks pushes and pull requests on Linux and Windows, with an optional disposable PostgreSQL test database in the Linux job.

Report bugs with the issue forms. Use synthetic inputs and sanitized OCR excerpts; include expected and actual identifiers, reproduction steps, and relevant versions. Never attach credentials, private documents or unreviewed logs. Live OCR calls may incur charges; regression tests mock Azure.

The current product is a localhost synthetic-document workspace. Streamlit sign-in and agent behavior describe retired implementations; check current code before extending an old issue. Historical reports belong in `docs/` and are not current setup instructions.
