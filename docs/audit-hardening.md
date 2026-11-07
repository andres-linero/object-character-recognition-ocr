# Audit hardening — 2026-11-07

## Scope and evidence

This audit applies to `andres-linero/object-character-recognition-ocr`, branch `fix/audit-hardening`. The supplied issues #18–#33 belong to the office `Gen_AI` repository and are reference findings, not issues closed by this change. That repository, its history, and its settings were not modified. UI redesign is deferred at the owner's request.

The new repository has independent history. A local Gitleaks 8.30.1 scan of all local refs found no secrets; historical tracked paths contain no PDF, XLSX, XLS, `.env`, or Streamlit secret files. This does not certify all text/media as free of private information or establish publication rights. Do not import the office repository's history. No history rewrite is needed for this copy based on these checks.

Before CI: 71 Python tests passed locally on macOS/Python 3.13, with eight skips (seven PostgreSQL variants and one real Win32 API test); four frontend DOM tests passed. Ruff's configured correctness rules passed. Cloud OCR was mocked; no paid Azure calls were made during this audit. Existing live synthetic validation results predate these parser changes. Remote CI results are authoritative for Linux/PostgreSQL and Windows and must be green before merging.

## Original audit mapping

| Reference | Status in this copy |
| --- | --- |
| #18 CI | Ubuntu/PostgreSQL, Windows, frontend, correctness lint, and history secret scan run on PRs. No production CD target exists. |
| #19 Ruff/pre-commit | Ruff is pinned, with syntax/import/undefined-name/unused-code rules. Hooks check Ruff, TOML, YAML, and conflict markers. Broader style modernization is deferred. |
| #20 project metadata | `pyproject.toml` defines Python support, dependencies, development group, pytest and Ruff settings. |
| #21 lock and updates | `uv.lock` locks Python resolution; npm already has a lock. CI uses frozen installs. Dependabot covers uv, npm, and Actions. Convenience requirements files are not frozen exports. |
| #22 secrets | `.env.example` documents names without credentials. Gitleaks scans fetched history with redacted output. Actual `.env` remains ignored and local. |
| #23 inherited customer files | Original history was never imported. No listed data/secret filenames were found in this copy's history. Office history exposure remains a separate task. |
| #24 synchronous/concurrent OCR | Open. The primary synthetic UI does not start cloud indexing on reruns. CLI attempts/retries are persisted, but atomic job claiming, worker leasing, and multi-process duplicate-call protection are still needed. Legacy Streamlit retains synchronous indexing. |
| #25 golden corpus | Added 18 text cases covering label variants, typed identifiers, postal/year/customer noise, fragments, and overlong IDs. No Azure needed. |
| #26 application tests | Existing legacy preview/SSO-gate tests and API/DOM tests pass. Authenticated tenant callback coverage is still missing. |
| #27 quoted Excel reload | Fixed shared path normalization and full path/size/nanosecond-time signature comparison. Regression test added. |
| #28 wrong compiled PDF | Replaced substring globbing with exact normalized leading filename tokens and traversal protection. Shipment 1001 cannot select W-11001 or 10010. |
| #29 stale Excel cache | Added cache schema version and rejected old payloads. Pickle remains trusted-local-only. |
| #30 OAuth redirect state | Open/unverified. No tenant credentials were used for integration tests; legacy SSO remains mandatory. Do not treat the synthetic localhost workspace as production authentication. |
| #31 ID cross-matching | New parser retains shipment/work-order type; SQL matches one corresponding column. Legacy index no longer aliases bare numbers to W-prefixed IDs. A two-order numeric collision regression runs on SQLite and PostgreSQL. Unlabeled numeric fallback is now opt-in. |
| #32 dead code/logging | Removed correctness-lint findings; broader dead-method removal, structured logging, and legacy decomposition remain open. |
| #33 documentation | README now describes locks and actual CI. Updated stale empty-state guidance. This report supersedes initial validation/dependency status in `PRP.md`. Other legacy architecture cleanup remains incremental. |
| Original #6 filename | Sanitized Windows-illegal filename characters; regression coverage added. |

Do not close or rewrite original issues #2/#12 from this branch. Their applicability belongs to the office architecture review.

## Behavior changes and remaining priorities

Typed OCR extraction is used by the SQL processor; the legacy string-returning wrapper remains compatible. Shipment labels take priority over unrelated work-order text. Numeric `Order No` values remain work orders. `OCR_ALLOW_UNLABELED_FALLBACK=0` is the safe default; enabling it restores heuristic numeric extraction and may increase false matches. Review no-match pages rather than inferring an association from a postcode.

Next: implement atomic OCR job claiming and recovery; verify Entra login/redirect behavior in a real tenant; then address the deferred navigation/table redesign and legacy logging/decomposition. Publication still requires rights/license review and deliberate data/media review. Branch protection and repository access settings were not changed by this PR.

Dependabot's uv configuration follows the [official uv integration guide](https://docs.astral.sh/uv/guides/integration/dependabot/). CI checks do not deploy the app. Install local hooks with `uv run --locked pre-commit install`; refresh hook environments after relocating the project.
