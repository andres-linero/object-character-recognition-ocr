> Historical initial-copy report. See [the current hardening audit](docs/audit-hardening.md) for dependency locks, CI, and updated verification.

# PRP — Public repository preparation

## Result

Created Object Character Recognition (OCR) from the tracked source snapshot of the original project. This is an independent repository with fresh history, not a fork. Original source files, private environment, private spreadsheets, and Git history were not modified or copied into the release.

## Changes

- Copied application source, existing tests, Streamlit configuration, and runtime/development dependency manifests.
- Removed original company branding and named employee references from source and tests.
- Replaced the fixed company Key Vault endpoint with AZURE_KEY_VAULT_URL; enabling Key Vault without a URL now fails explicitly.
- Replaced company address/phone/email OCR exclusions with optional OCR_HEADER_NOISE and OCR_EXCLUDED_NUMBERS configuration. Configure these for your forms; extraction behavior can differ from the original company-specific rules.
- Added root dependency entrypoint, .env.example, setup documentation, and a synthetic workbook/PDF generator.
- Excluded credentials, local data, generated caches, and virtual environments. No inherited commits or contributor metadata are included. Only the repository owner's initial commit is intended; collaborators must be checked separately in GitHub settings.
- Corrected the public README's unconditional privacy claim: a crop is not a PII detector. Authentication remains mandatory and localhost binding is retained.

## Audit findings and limits

- Private .env and customer workbooks existed outside tracked source and were deliberately excluded; their contents were not inspected or published.
- Reviewed the copied tracked text for original branding, employee references, company contacts, local paths, and obvious credential assignments. This is a source review, not a formal security certification or exhaustive secret scanner run.
- Existing Excel cache uses pickle and must be treated as trusted local state.
- All authenticated users share one permission level. Live Entra callback/session behavior and Azure access require integration testing before shared deployment.
- The OCR crop depends on document geometry and the utility permits uncropped calls. Inspect layouts before processing confidential material.
- Dependencies retain original minimum version constraints. A clean-install reproduction, exact version lock, vulnerability scan, and dependency license inventory remain outstanding.
- No license was invented or third-party attribution removed. Confirm rights to publish the inherited source and choose an appropriate license before encouraging redistribution.

## Validation

- 13 existing tests passed using the source workspace's existing virtual environment; Azure is mocked. Five PyMuPDF/SWIG deprecation warnings were reported.
- Synthetic workbook and PDF generation succeeded using that environment.
- Private Azure credentials were not copied. Live OCR and authenticated dashboard operation were not exercised.

## Reproduction

Follow README.md from a new Python environment. Install requirements, generate synthetic inputs, and supply your own Azure and Entra configuration. The repository can run independently once those prerequisites are supplied.
