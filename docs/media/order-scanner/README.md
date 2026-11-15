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
