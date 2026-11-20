# Order Scanner demo media

Recorded on November 15, 2026, using fictional sample documents. Screenshots and edited recordings are linked from the root README. The GIFs play inline on GitHub; MP4 links offer the same edits in a smaller video format.

| Clip | Length | Retained source intervals (seconds) | Shows |
| --- | --- | --- | --- |
| `ocr-complete` | 17 s | 2–9, 65–68, 140–147 | Upload, processing and 8 ready orders |
| `ocr-with-flags` | 20 s | 2–9, 100–103, 144–154 | Processing and 6 ready / 2 in review |
| `review-and-repair` | 27 s | 3–12, 19–23, 28–33, 37–46 | Inspecting evidence, linking a page and confirming one repaired order |
| `zip-download` | About 6 s | 0.2–5.8 | Download action, browser receipt and Download again state |

The retained intervals play at normal speed, with jumps between them. Waiting time is omitted. Audio and source metadata are removed. Recordings are cropped to remove capture controls and unnecessary browser chrome, then exported as H.264 MP4 at 12 fps and GIF at 6 fps. Their durations are presentation edits, not processing benchmarks. The repair clip resolves one order and leaves another flagged order visible.

`edits.json` maps each edit to the original filename and exact intervals. The four full MOV recordings are preserved locally in `docs/media/source-recordings/`, which is ignored by Git. Do not add those originals to commits.

## Screenshots

| File | Original capture time | Content |
| --- | --- | --- |
| `overview.png` | 1:05:44 PM | Overview with processing and ZIP readiness |
| `zip-summary.png` | 1:06:00 PM | 6 ready orders, 2 not ready, 2 pages to resolve |
| `order-tracker.png` | 1:06:18 PM | Order rows and individual PDF downloads |
| `rental-order-folders.png` | 1:16:53 PM | Extracted ZIP rental-order folders |
| `compiled-order-files.png` | 1:19:46 PM | Compiled PDFs inside a rental-order folder |

Screenshots retain their original pixels under descriptive filenames. They were moved from the repository root into this folder. Source frames and selected output frames were visually inspected; the media shows synthetic records, not private operational data.

## Current tracker and rental analytics (November 20, 2026)

The README now uses continuous browser-content recordings of the current Chrome workspace:

| File | Contents |
| --- | --- |
| `rental-analytics-live.mp4` / `.gif` | Tracker → analytics → customer search → invoice ledger → individual rental filter. |
| `document-tracker-live.mp4` / `.gif` | A rental work order → three original document pages → OCR evidence. |

The MP4s preserve capture timestamps at approximately 7–8 frames per second; GIF previews sample the same footage at four frames per second. Idle endings were removed. Other applications and audio are excluded. These are live interactions, not a slideshow. The recordings show fictional customer and billing data.

`current-order-tracker.jpg`, `rental-analytics.jpg`, `rental-analytics-filtered.jpg` and `rental-billing-ledger.jpg` are frames from the new live analytics recording. `current-document-preview.jpg` is a fresh Chrome capture of the source document viewer.

The earlier `rental-analytics-walkthrough.mp4` and `.gif` were screenshot slideshows and have been superseded; they are no longer linked from the project README.

## Live OCR and flag repair (November 20, 2026)

`ocr-flag-repair-live.mp4` and `.gif` show actual Azure processing of a new 48-page crop-miss sample and the browser repair of W-0001685 (RO-0001123). Initial result: six ready documents, two flagged. Source image 21 matches the customer, address, rental order, work order and printed page 6/6. Its manual link makes the document ready, leaving seven ready and one flag. The separate approval preserves the original no-match OCR attempt.

Capture starts during processing. The synthetic PDF was submitted through the local intake API after the browser file chooser stalled. OCR waiting is accelerated 8×; repair footage is accelerated 1.25×. Gaps between recording segments are removed. No statuses or OCR results were fabricated. Audio and unrelated applications are excluded.

Screenshots: `ocr-flags-detected.jpg` (before repair), `ocr-matching-page.jpg` (source image), `ocr-matching-fields.jpg` (comparison and link action), `ocr-repaired-order.jpg` (successful repair), and `ocr-after-repair.jpg` (seven ready, one remaining flag).
