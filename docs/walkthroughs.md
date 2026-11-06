# Walkthrough videos

The README includes two short, silent GIF clips derived from the supplied recordings. GIFs render inline without an external video host. Only the edited clips are committed; the source MP4s and temporary review frames remain local.

## Published clips

| Clip | Source recording | Source interval | Editing |
| --- | --- | --- | --- |
| [Scan intake](media/scan-intake.gif) | Recording dated 2026-10-22 | 00:20–00:31 | Cropped to the file panel, excluding the account sidebar and desktop |
| [Incremental indexing](media/incremental-indexing.gif) | Screen recording dated 2026-10-21 | 00:00–00:18 | Only cache, reload, completion-summary, and changed-file-count log lines retained; other content concealed; retained source pixels arranged as a compact log panel |

Both clips use four frames per second, loop, and contain no audio. The log counts are historical observations, not performance claims. The clips do not demonstrate current authentication behavior. The intake recording shows a historical ID-related folder name; ID collection is outside the current application scope.

Each emitted frame was checked with text recognition; representative exported frames were visually inspected. Text recognition is a supporting check, not a guarantee. The intake crop excludes the desktop/account sidebar on every emitted frame. The indexing export reveals only approved summary-line categories. Source audio is omitted entirely.

## Supplied recordings

| Recording | Duration | Sampled visual content | Public-release disposition |
| --- | --- | --- | --- |
| Recording dated 2026-10-22 | 00:32.33 | Windows desktop and scan-folder intake | Only the cropped intake excerpt is published; the original remains local |
| Screen recording dated 2026-10-21 | 04:40.30 | PowerShell OCR/indexing logs and cache reuse | Only the redacted summary-log excerpt is published; the original remains local |

Approximate visual anchors, based on sampled frames:

- **Intake, 00:00–00:08:** desktop and opening the scans directory.
- **Intake, around 00:20:** scan-folder organization.
- **Intake, around 00:24–00:28:** incoming PDF listing.
- **Indexing, 00:00:** grouped-output summary, workbook reload, and cache-hit messages.
- **Indexing, around 00:35:** new/changed PDF detection while unchanged PDFs are skipped.
- **Indexing, around 01:10–04:05:** sequential page-to-order extraction progress.

These recordings predate the public copy. Folder names and displayed totals are historical observations, not current configuration requirements or performance benchmarks. They do not establish current sign-in behavior or show a complete dashboard walkthrough.

## Future walkthroughs

For a full product walkthrough, use synthetic inputs and a neutral account, and show matching, preview, and download. Review the complete video and audio before publishing a longer version. The existing short clips illustrate intake and cache behavior only.

## Recommended coverage

| Walkthrough | Show | Companion documentation |
| --- | --- | --- |
| Product overview | Problem, sample inputs, order matching, readiness, downloads | Root README |
| Setup | Environment, dependency installation, synthetic inputs, sign-in prerequisites | README and configuration guide |
| Architecture | UI, workbook loader, scan index, Azure boundary, local persistence | Architecture guide |
| Troubleshooting | No-match page, wrong crop, missing configuration, safe recovery | Operations guide |

## Maintaining clips

Keep only short edited clips in this repository. Host full-length recordings externally if needed, and link to them with deliberate sharing settings. Record the source interval, edits, and behavior shown. Do not publish raw recordings containing account details, private documents, or unreviewed audio. Provide a text explanation alongside every animation.
