# Walkthrough videos

Two local recordings were supplied and eight frames per recording were inspected at evenly spaced timestamps. These notes are a sampled visual review, not a full-frame review or audio transcript. Both files contain an audio track; audio has not been reviewed. Neither recording has been uploaded, shared, or committed.

## Supplied recordings

| Recording | Duration | Sampled visual content | Public-release disposition |
| --- | --- | --- | --- |
| Recording dated 2026-10-22 | 00:32.33 | Windows desktop and scan-folder intake | Redact employee/company account labels and private context, or re-record using synthetic files |
| Screen recording dated 2026-10-21 | 04:40.30 | PowerShell OCR/indexing logs and cache reuse | Replace operational identifiers/filenames with synthetic examples and review audio |

Approximate visual anchors, based on sampled frames:

- **Intake, 00:00–00:08:** desktop and opening the scans directory.
- **Intake, around 00:20:** scan-folder organization.
- **Intake, around 00:24–00:28:** incoming PDF listing.
- **Indexing, 00:00:** grouped-output summary, workbook reload, and cache-hit messages.
- **Indexing, around 00:35:** new/changed PDF detection while unchanged PDFs are skipped.
- **Indexing, around 01:10–04:05:** sequential page-to-order extraction progress.

These recordings predate the public copy. Folder names and displayed totals are historical observations, not current configuration requirements or performance benchmarks. They do not establish current sign-in behavior or show a complete dashboard walkthrough.

## Public version plan

Recreate the intake and cache demonstration with the generated synthetic workbook/PDF, a neutral desktop/account, and generic filenames. Include successful matching and preview/download in a separate product walkthrough. Review the complete video and audio before publishing. Add an externally hosted, deliberately shared link and text summary to the README afterward. Local file paths are not useful public watch links.

## Recommended coverage

| Walkthrough | Show | Companion documentation |
| --- | --- | --- |
| Product overview | Problem, sample inputs, order matching, readiness, downloads | Root README |
| Setup | Environment, dependency installation, synthetic inputs, sign-in prerequisites | README and configuration guide |
| Architecture | UI, workbook loader, scan index, Azure boundary, local persistence | Architecture guide |
| Troubleshooting | No-match page, wrong crop, missing configuration, safe recovery | Operations guide |

## Integrating a recording

Keep recordings hosted externally and link them from the README; do not commit large video files to Git. For each approved recording, record its title, verified URL, duration, relevant timestamps, source revision, and a short text summary or transcript so the guide remains useful without video.

Use only synthetic documents and demo identities in public walkthroughs. Review frames, browser tabs, account names, paths, terminal output, and audio for credentials and private data. A private Drive video remains private even when linked from a public README; choose sharing deliberately.

The README should show a short description and working watch link once supplied. Add a thumbnail only after a suitable public image and target video are available. Do not insert broken placeholder URLs.
