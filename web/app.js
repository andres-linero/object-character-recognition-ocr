const $ = (selector, parent = document) => parent.querySelector(selector);
const main = $("#main"),
  overlay = $("#overlay-root");
const state = {
  dataset: "",
  datasets: [],
  view: "tickets",
  query: "",
  filter: "all",
  status: "all",
  page: 1,
  pageSize: 10,
  tickets: [],
  summary: {},
  detail: null,
  pageIndex: 0,
  detailTab: "details",
  request: 0,
};
const paths = {
  grid: "M3 3h7v7H3z M14 3h7v7h-7z M3 14h7v7H3z M14 14h7v7h-7z",
  orders:
    "M8 4h11a2 2 0 0 1 2 2v14H8a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2Z M3 8v12a2 2 0 0 0 2 2h12 M10 9h7 M10 13h7 M10 17h4",
  file: "M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8Z M14 2v6h6 M8 13h8 M8 17h5",
  scan: "M4 8V4h4 M16 4h4v4 M20 16v4h-4 M8 20H4v-4 M4 12h16 M8 8h8 M8 16h8",
  check: "m5 12 4 4L19 6",
  circlecheck: "M22 11a10 10 0 1 1-6-9 M22 4 12 14l-3-3",
  clock: "M12 8v5l3 2 M22 12a10 10 0 1 1-20 0 10 10 0 0 1 20 0",
  search: "M21 21l-5-5 M18 10a8 8 0 1 1-16 0 8 8 0 0 1 16 0",
  down: "M12 3v12 m-5-5 5 5 5-5 M5 17v4h14v-4",
  arrow: "M5 12h14 m-6-6 6 6-6 6",
  chevron: "m9 5 7 7-7 7",
  left: "m15 5-7 7 7 7",
  close: "m6 6 12 12 M18 6 6 18",
  pin: "M20 10c0 6-8 12-8 12S4 16 4 10a8 8 0 1 1 16 0Z M15 10a3 3 0 1 1-6 0 3 3 0 0 1 6 0",
  refresh: "M20 7a9 9 0 1 0 1 9 M20 3v5h-5",
  upload: "M12 16V4 m-5 5 5-5 5 5 M4 16v5h16v-5",
  filter: "M4 7h16 M7 12h10 M10 17h4",
  shield: "m12 2 8 4v6c0 5-8 10-8 10S4 17 4 12V6Z m-4 10 3 3 5-5",
  inbox: "M4 4h16l2 10v6H2v-6Z M2 14h6l2 3h4l2-3h6",
  eye: "M2 12s4-7 10-7 10 7 10 7-4 7-10 7S2 12 2 12 M15 12a3 3 0 1 1-6 0 3 3 0 0 1 6 0",
  mail: "M3 5h18v14H3Z m0 0 9 8 9-8",
  plus: "M12 4v16 M4 12h16",
};
function icon(name, className = "") {
  const node = document.createElement("span");
  node.className = `icon ${className}`;
  node.setAttribute("aria-hidden", "true");
  node.innerHTML = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="${paths[name] || paths.file}"/></svg>`;
  return node;
}
function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (value == null) continue;
    if (key === "class") node.className = value;
    else if (key === "text") node.textContent = value;
    else if (key.startsWith("on"))
      node.addEventListener(key.slice(2).toLowerCase(), value);
    else if (key === "style") Object.assign(node.style, value);
    else if (["value", "checked", "disabled", "selected"].includes(key))
      node[key] = value;
    else node.setAttribute(key, String(value));
  }
  for (const child of children.flat(Infinity)) {
    if (child != null)
      node.append(
        child instanceof Node ? child : document.createTextNode(String(child)),
      );
  }
  return node;
}
function button(label, action, cls = "button secondary", glyph) {
  return el(
    "button",
    { class: cls, type: "button", onClick: action },
    glyph ? icon(glyph) : null,
    label,
  );
}
function badge(label, tone = "neutral", glyph) {
  return el(
    "span",
    { class: `badge ${tone}` },
    glyph ? icon(glyph) : null,
    label,
  );
}
function date(
  value,
  options = { month: "short", day: "numeric", year: "numeric" },
) {
  if (!value) return "Not provided";
  return new Date(
    value.length === 10 ? `${value}T12:00:00` : value,
  ).toLocaleDateString(undefined, options);
}
function time(value) {
  return value
    ? new Date(
        /Z$|[+-]\d\d:\d\d$/.test(value) ? value : `${value}Z`,
      ).toLocaleString(undefined, {
        month: "short",
        day: "numeric",
        hour: "numeric",
        minute: "2-digit",
      })
    : "Not processed";
}
function initials(name) {
  return name
    .split(" ")
    .filter((w) => w !== "Demo")
    .slice(0, 2)
    .map((w) => w[0])
    .join("");
}
function toast(message) {
  const node = $("#toast");
  node.textContent = message;
  node.classList.add("visible");
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => node.classList.remove("visible"), 3500);
}
async function api(path, options) {
  const response = await fetch(path, options);
  if (!response.ok) {
    let message = "Something went wrong. Please try again.";
    try {
      message = (await response.json()).detail || message;
    } catch {}
    throw new Error(message);
  }
  return response.json();
}
const base = () => `/api/workspaces/${encodeURIComponent(state.dataset)}`;
function rentalNumber(record) {
  return (
    (record?.parent_rental_number || record?.rental_order || "").replace(
      /^RA-/i,
      "RO-",
    ) || null
  );
}
function rememberDownloads(tickets) {
  state.downloads = Object.fromEntries(
    tickets.map((ticket) => [ticket.id, ticket]),
  );
}
async function refreshDownloadMarks() {
  const dataset = state.dataset;
  const result = await api(`${base()}/tickets`);
  if (dataset !== state.dataset) return;
  rememberDownloads(result.tickets);
  const marks = (ticket) => {
    const latest = state.downloads[ticket.id];
    return latest
      ? {
          ...ticket,
          downloaded: latest.downloaded,
          downloaded_at: latest.downloaded_at,
          download_count: latest.download_count,
          download_version: latest.download_version,
        }
      : ticket;
  };
  state.tickets = state.tickets.map(marks);
  if (state.view === "overview")
    document
      .querySelector("#overview-order-results")
      ?.replaceWith(overviewOrderResults());
  if (state.view === "tickets") updateTable();
  if (state.detail) {
    state.detail = marks(state.detail);
    renderDetail();
  }
  document
    .querySelector(".scan-download-panel")
    ?.replaceWith(liveProcessing().querySelector(".scan-download-panel"));
}
async function requestFileDownload(event, url, fallbackName) {
  event.preventDefault();
  event.stopPropagation();
  const active = state.activeDownloads || (state.activeDownloads = new Set());
  if (active.has(url)) return;
  active.add(url);
  const control = event.currentTarget;
  const original = control.innerHTML;
  control.textContent = "Downloading…";
  control.setAttribute("aria-disabled", "true");
  try {
    const response = await fetch(url);
    if (!response.ok) {
      let message = "Download failed. Please try again.";
      try {
        message = (await response.json()).detail || message;
      } catch {}
      throw new Error(message);
    }
    const blob = await response.blob();
    const filename =
      response.headers
        .get("Content-Disposition")
        ?.match(/filename="([^"]+)"/)?.[1] || fallbackName;
    const objectUrl = URL.createObjectURL(blob);
    const link = el("a", { href: objectUrl, download: filename });
    document.body.append(link);
    link.click();
    link.remove();
    setTimeout(() => URL.revokeObjectURL(objectUrl), 1000);
    try {
      await refreshDownloadMarks();
    } catch {
      toast("Downloaded. Refresh to update its mark.");
    }
  } catch (error) {
    toast(error.message);
  } finally {
    active.delete(url);
    if (control.isConnected) {
      control.innerHTML = original;
      control.removeAttribute("aria-disabled");
    }
  }
}
function fileDownloadLink(url, label, className, filename, ariaLabel) {
  return el(
    "a",
    {
      class: className,
      href: url,
      "aria-label": ariaLabel,
      onClick: (event) => requestFileDownload(event, url, filename),
      onKeydown: (event) => event.stopPropagation(),
    },
    icon("down"),
    label,
  );
}
function ticketDownloadControl(
  ticket,
  label = "Download PDF",
  className = "button primary row-download",
) {
  return el(
    "span",
    { class: "download-control" },
    ticket.downloaded
      ? el(
          "span",
          {
            class: "badge green downloaded-mark",
            title: ticket.downloaded_at
              ? `Downloaded ${time(ticket.downloaded_at)}`
              : "Downloaded",
          },
          icon("check"),
          "Downloaded",
        )
      : null,
    fileDownloadLink(
      `${base()}/tickets/${ticket.id}/download`,
      ticket.downloaded ? "Download again" : label,
      ticket.downloaded ? `${className} download-again` : className,
      `${ticket.work_order}.pdf`,
      `${ticket.downloaded ? "Download again" : "Download"} ${ticket.work_order}`,
    ),
  );
}
const navItems = [
  ["overview", "Overview", "grid"],
  ["tickets", "Dataset", "orders"],
  ["ocr", "OCR activity", "scan"],
  ["flags", "Flags", "eye"],
  ["imports", "Ingestion history", "clock"],
];
function navigate(view, filter = "all") {
  state.view = view;
  state.page = 1;
  state.query = "";
  state.filter = filter;
  state.status = "all";
  state.documentFilter = "";
  closeDetail();
  location.hash = `/${view}`;
  loadView();
  $("#sidebar").classList.remove("open");
}
function navigation() {
  const node = $("#navigation");
  node.replaceChildren(
    ...navItems.map(([key, label, glyph]) =>
      el(
        "button",
        {
          class: `nav-item ${state.view === key ? "active" : ""}`,
          onClick: () => navigate(key),
          "aria-current": state.view === key ? "page" : null,
        },
        icon(glyph),
        el("span", {}, label),
      ),
    ),
  );
  $("#breadcrumb-title").textContent =
    navItems.find((n) => n[0] === state.view)?.[1] || "Order Tracker";
}
function datasetControl() {
  return el(
    "span",
    { class: "dataset-control", "aria-label": "Dataset" },
    icon("grid"),
    `${state.summary.rental_orders ? `${state.summary.rental_orders} rental orders · ` : ""}${state.summary.tickets ?? 0} tickets`,
  );
}
function heading(title, subtitle, actions = []) {
  return el(
    "section",
    { class: "page-heading" },
    el(
      "div",
      {},
      el("div", { class: "eyebrow" }, "DOCUMENT OPERATIONS"),
      el("h1", {}, title),
      el("p", {}, subtitle),
    ),
    el("div", { class: "heading-actions" }, ...actions),
  );
}
function intakeDropzone() {
  const input = el("input", {
    type: "file",
    accept: ".pdf,application/pdf",
    multiple: true,
    class: "intake-file-input",
    "aria-label": "Select PDF files",
    onChange: (event) => uploadIntakeFiles(event.target.files),
  });
  const choose = button(
    state.uploading ? "Adding PDFs…" : "Choose PDF",
    () => input.click(),
    "button secondary",
    "upload",
  );
  choose.disabled = !!state.uploading;
  const zone = el(
    "section",
    {
      id: "pdf-dropzone",
      class: "intake-dropzone",
      "aria-label": "PDF intake",
      onDragOver: (event) => {
        event.preventDefault();
        if (!state.uploading) zone.classList.add("is-dragging");
      },
      onDragLeave: (event) => {
        if (!zone.contains(event.relatedTarget))
          zone.classList.remove("is-dragging");
      },
      onDrop: (event) => {
        event.preventDefault();
        zone.classList.remove("is-dragging");
        uploadIntakeFiles(event.dataTransfer?.files);
      },
    },
    icon("upload"),
    el(
      "div",
      { class: "intake-drop-copy" },
      el("strong", {}, "Drop a PDF to start OCR"),
      el("p", {}, "Or choose a file. OCR starts when the upload finishes."),
      el(
        "small",
        { class: "intake-upload-status", role: "status" },
        state.uploadMessage || "Generated demo PDFs · up to 50 MB per file",
      ),
      el(
        "ul",
        { class: "intake-file-list", "aria-label": "Submitted PDFs" },
        ...(state.uploadFiles || []).map((file) =>
          el("li", {}, `${file.name} — ${file.status}`),
        ),
      ),
    ),
    input,
    choose,
  );
  return zone;
}
// Keep file drops inside the application, including drops outside the target.
document.addEventListener("dragover", (event) => {
  if (Array.from(event.dataTransfer?.types || []).includes("Files"))
    event.preventDefault();
});
document.addEventListener("drop", (event) => {
  if (!event.dataTransfer?.files?.length) return;
  event.preventDefault();
  if (!event.target.closest?.("#pdf-dropzone"))
    uploadIntakeFiles(event.dataTransfer.files);
});
async function uploadIntakeFiles(files) {
  if (state.uploading || !files?.length) return;
  const selected = Array.from(files);
  if (
    selected.some(
      (file) =>
        !file.name.toLowerCase().endsWith(".pdf") ||
        file.size > 50 * 1024 * 1024,
    )
  ) {
    state.uploadMessage = "Choose PDF files no larger than 50 MB.";
    document.querySelector("#pdf-dropzone")?.replaceWith(intakeDropzone());
    return;
  }
  state.uploading = true;
  state.uploadFiles = selected.map((file) => ({
    name: file.name,
    status: "Waiting to upload",
  }));
  let added = 0;
  state.uploadMessage = `Adding ${selected.length} PDF file(s) to intake…`;
  document.querySelector("#pdf-dropzone")?.replaceWith(intakeDropzone());
  try {
    for (const [index, file] of selected.entries()) {
      state.uploadFiles[index].status = "Uploading…";
      document.querySelector("#pdf-dropzone")?.replaceWith(intakeDropzone());
      const submitted = await api(`${base()}/intake`, {
        method: "POST",
        headers: {
          "Content-Type": "application/pdf",
          "X-File-Name": encodeURIComponent(file.name),
        },
        body: file,
      });
      if (submitted.page_count > 0) {
        state.uploadedScan = {
          file: submitted.file,
          total: submitted.page_count,
          completed: 0,
        };
        updateOcrPageSummary();
      }
      state.uploadFiles[index].status = "Submitted to OCR";
      added++;
    }
    state.uploadMessage = `${added} PDF file(s) added. OCR will start automatically.`;
  } catch (error) {
    state.uploadFiles[added].status = `Upload failed: ${error.message}`;
    state.uploadFiles
      .slice(added + 1)
      .forEach((file) => (file.status = "Not submitted"));
    state.uploadMessage = `${added ? `${added} added. ` : ""}${error.message}`;
  } finally {
    state.uploading = false;
    document.querySelector("#pdf-dropzone")?.replaceWith(intakeDropzone());
  }
}

const OCR_STAGE_MIN_MS = 1400;
function progressTarget(p) {
  if (
    p.phase === "ready" ||
    (p.phase === "needs_attention" && p.ready_tickets?.length)
  )
    return 4;
  if (p.phase === "preparing_pdf") return 3;
  if (p.total > 0 && p.completed === p.total) return 2;
  return ["reading", "matching"].includes(p.phase) ? 1 : 0;
}
function paceProgress() {
  const p = state.liveProgress || {};
  clearTimeout(state.progressTimer);
  if (state.progressFile !== p.file || state.progressStage == null) {
    state.progressFile = p.file;
    state.progressStage = 0;
    state.progressStageSince = Date.now();
  }
  const target = progressTarget(p);
  if (["error", "needs_attention", "waiting"].includes(p.phase)) {
    state.progressStage = target;
    return;
  }
  if (state.progressStage < target) {
    const delay = Math.max(
      0,
      OCR_STAGE_MIN_MS - (Date.now() - state.progressStageSince),
    );
    state.progressTimer = setTimeout(() => {
      state.progressStage++;
      state.progressStageSince = Date.now();
      updateLiveVerification();
      paceProgress();
    }, delay);
  }
}
function liveVerification() {
  const p = state.liveProgress || {
    phase: "waiting",
    total: 0,
    completed: 0,
    matched: 0,
  };
  const failed = ["error", "needs_attention"].includes(p.phase);
  const busy =
    ["receiving", "reading", "matching", "preparing_pdf"].includes(p.phase) ||
    (p.phase === "ready" && state.progressStage < 4);
  const read = p.total > 0 && p.completed === p.total;
  const matched = read && p.matched === p.total;
  const phases = [
    [
      "PDF detected",
      p.total > 0 || p.phase === "ready",
      p.phase === "receiving",
      p.total > 0 ? "PDF registered" : "Waiting for a completed file copy",
    ],
    [
      "OCR reading",
      read,
      ["reading", "matching"].includes(p.phase) && !read,
      `${p.completed || 0} / ${p.total || 0} pages processed`,
    ],
    [
      "Grouping pages",
      matched,
      read && p.phase === "matching" && !matched,
      `${p.matched || 0} / ${p.total || 0} pages matched`,
    ],
    [
      "Ticket PDF ready",
      p.phase === "ready",
      p.phase === "preparing_pdf",
      p.phase === "ready" && state.progressStage >= 4
        ? "Order completed · PDF created and checked"
        : "Created after successful matching",
    ],
  ];
  const failedIndex =
    p.phase === "needs_attention"
      ? 2
      : ({ receiving: 0, reading: 1, matching: 2, preparing_pdf: 3 }[
          p.failed_at
        ] ?? 1);
  const steps = el(
    "ol",
    { class: "ocr-live-steps" },
    ...phases.map(([label, done, active, note], index) => {
      const error = failed && index === failedIndex;
      if (!failed && state.progressStage != null) {
        done = done && index < state.progressStage;
        active = index === state.progressStage && busy;
      }
      const status = error
        ? "error"
        : done
          ? "done"
          : active && !failed
            ? "active"
            : "waiting";
      return el(
        "li",
        {
          class: `ocr-live-step is-${status}`,
          "aria-current": status === "active" ? "step" : null,
          hidden: status === "waiting" && index !== 0 ? "" : null,
        },
        el(
          "span",
          { class: "progress-node", "aria-hidden": "true" },
          error
            ? "!"
            : done
              ? icon("check")
              : el("span", { class: "progress-dot" }),
        ),
        el(
          "div",
          {},
          el("strong", {}, label),
          el("small", {}, error ? "Needs attention" : note),
        ),
        index < 3
          ? el(
              "span",
              { class: "progress-connector", "aria-hidden": "true" },
              el("span", {
                class: "progress-connector-fill",
                "data-fill": error
                  ? 0
                  : done
                    ? 1
                    : index === 1 && p.total
                      ? p.completed / p.total
                      : index === 2 && p.total
                        ? p.matched / p.total
                        : 0,
              }),
            )
          : null,
      );
    }),
  );
  const panel = el(
    "section",
    {
      id: "ocr-live-progress",
      class: `panel ocr-live-panel ${failed ? "has-error" : ""}`,
      "aria-label": "Live OCR verification",
      "aria-live": "polite",
      "aria-busy": busy,
    },
    el(
      "div",
      { class: "ocr-live-heading" },
      el(
        "div",
        {},
        el("div", { class: "eyebrow" }, "LIVE PROCESSING"),
        el("h2", {}, "OCR status"),
      ),
      badge(
        state.progressOffline
          ? "Reconnecting…"
          : p.phase === "ready" && !busy
            ? "Order completed"
            : failed
              ? "Needs attention"
              : busy
                ? "Processing"
                : "Waiting for upload",
        p.phase === "ready" && !busy ? "green" : failed ? "amber" : "blue",
      ),
    ),
    el(
      "p",
      { class: "ocr-live-filename" },
      p.file || "Waiting for your next PDF",
    ),
    steps,
    el(
      "div",
      { class: "ocr-live-caption" },
      busy ? el("span", { class: "live-pulse", "aria-hidden": "true" }) : null,
      el(
        "span",
        {},
        state.progressOffline
          ? "Live connection interrupted. Reconnecting automatically; processing continues."
          : p.phase === "ready" && busy
            ? "Updating completed scan stages…"
            : p.message || "Upload a demo PDF to start.",
      ),
    ),
  );
  if (p.total > 0)
    panel.append(
      el(
        "div",
        {
          class: "ocr-page-progress",
          role: "progressbar",
          "aria-label": "OCR pages processed",
          "aria-valuemin": 0,
          "aria-valuemax": p.total,
          "aria-valuenow": p.completed || 0,
        },
        el("span", {
          style: {
            width: `${Math.min(100, ((p.completed || 0) / p.total) * 100)}%`,
          },
        }),
      ),
    );
  panel
    .querySelectorAll(".progress-connector-fill")
    .forEach((line) => line.style.setProperty("--fill", line.dataset.fill));
  return panel;
}
function liveProcessing() {
  const p = state.liveProgress || {};
  const ready =
    ["ready", "needs_attention"].includes(p.phase) &&
    state.progressStage >= 4 &&
    p.ready_tickets?.length > 0;
  const downloaded =
    ready &&
    p.ready_tickets.every((ticket) => state.downloads?.[ticket.id]?.downloaded);
  const summary = p.download_summary;
  const totals = summary
    ? el(
        "div",
        {
          class: "scan-download-summary",
          "aria-label": "ZIP contents summary",
        },
        el(
          "p",
          { class: "scan-download-total" },
          `${summary.total_orders} orders detected in this scan`,
        ),
        el(
          "dl",
          { class: "scan-download-counts" },
          ...[
            ["Ready for ZIP", summary.ready_orders, "ready"],
            ["Not ready", summary.not_ready_orders, "attention"],
            ["Pages to resolve", summary.missing_pages, "pages"],
          ].map(([label, count, kind]) =>
            el(
              "div",
              { class: `scan-download-count ${kind}` },
              el("dt", {}, label),
              el("dd", {}, String(count)),
            ),
          ),
        ),
        summary.pending_pages > 0
          ? el(
              "small",
              {},
              `${summary.pending_pages} pages still processing. Totals may change.`,
            )
          : summary.unidentified_pages > 0 && summary.missing_pages === 0
            ? el(
                "small",
                {},
                `${summary.unidentified_pages} unidentified images also need review.`,
              )
            : null,
      )
    : null;
  return el(
    "div",
    { id: "ocr-processing", class: "ocr-processing" },
    liveVerification(),
    el(
      "section",
      {
        class: "panel scan-download-panel",
        "aria-label": "Scanned ticket ZIP",
      },
      icon(ready ? "circlecheck" : "file"),
      el("h2", {}, ready ? "Completed orders are ready" : "Scanned tickets"),
      el(
        "p",
        {},
        ready
          ? summary
            ? "The ZIP includes ready orders only. Orders in review stay out."
            : `${p.ready_tickets.length} completed ticket PDF(s) from this scan. Download them together.`
          : "Your ZIP download will appear here when OCR and ticket preparation finish.",
      ),
      totals,
      ready
        ? el(
            "span",
            { class: "download-control" },
            downloaded ? badge("Downloaded", "green", "check") : null,
            fileDownloadLink(
              `${base()}/progress/tickets.zip?revision=${p.revision}`,
              downloaded ? "Download ZIP again" : "Download tickets ZIP",
              "button primary",
              "scanned-tickets.zip",
            ),
          )
        : el(
            "button",
            { class: "button secondary", disabled: true },
            icon("down"),
            "Waiting for tickets",
          ),
    ),
  );
}
function updateLiveVerification() {
  document.querySelectorAll("#ocr-processing").forEach((node) => {
    const previous = [...node.querySelectorAll(".progress-connector-fill")].map(
      (line) => line.dataset.fill,
    );
    const next = liveProcessing();
    next.querySelectorAll(".progress-connector-fill").forEach((line, index) => {
      line.style.setProperty("--fill", previous[index] || 0);
      window.requestAnimationFrame(() =>
        line.style.setProperty("--fill", line.dataset.fill),
      );
    });
    node.replaceWith(next);
  });
}
function connectLiveProgress() {
  if (typeof window.EventSource !== "function") return;
  state.progressSource?.close();
  const source = new window.EventSource(`${base()}/progress/stream`);
  state.progressSource = source;
  source.onmessage = (event) => {
    try {
      const progress = JSON.parse(event.data);
      if (
        state.liveProgress?.revision === progress.revision &&
        !state.progressOffline
      )
        return;
      state.liveProgress = progress;
      updateOcrPageSummary();
      state.progressOffline = false;
      paceProgress();
      updateLiveVerification();
      if (state.view === "overview") {
        clearTimeout(state.overviewRefreshTimer);
        state.overviewRefreshTimer = setTimeout(refreshOverviewOrders, 250);
      }
      if (["tickets", "flags"].includes(state.view)) {
        clearTimeout(state.trackerRefreshTimer);
        state.trackerRefreshTimer = setTimeout(refreshTracker, 250);
      }
    } catch {
      /* Ignore malformed transport data; keep the last known state. */
    }
  };
  source.onerror = () => {
    state.progressOffline = true;
    updateLiveVerification();
  };
  source.onopen = () => {
    state.progressOffline = false;
    updateLiveVerification();
  };
}

function ocrSummaryScan() {
  const live = state.liveProgress;
  const uploaded = state.uploadedScan;
  if (
    uploaded &&
    (!live?.file ||
      (["ready", "needs_attention", "error", "waiting"].includes(live.phase) &&
        live.file !== uploaded.file))
  )
    return uploaded;
  if (live?.file && live.total > 0) return live;
  return (
    uploaded || state.scanCounts?.current_scan || { total: 0, completed: 0 }
  );
}
function updateOcrPageSummary() {
  const scan = ocrSummaryScan();
  document
    .querySelectorAll("[data-ocr-page-summary] .summary-value")
    .forEach((node) => {
      node.textContent = `${Math.min(scan.completed || 0, scan.total)} / ${scan.total}`;
    });
}
function summaryCards() {
  const s = state.scanCounts || {};
  const total = s.files ?? 0,
    read = s.files_read ?? 0;
  const scan = ocrSummaryScan();
  return el(
    "div",
    { class: "summary-grid" },
    ...[
      ["PDF files received", total, "Source files in this intake"],
      [
        "OCR complete",
        `${Math.min(scan.completed || 0, scan.total)} / ${scan.total}`,
        "Pages processed in this PDF",
      ],
      ["Files remaining", total - read, "Not yet completely matched"],
    ].map(([label, value, note]) =>
      el(
        "article",
        {
          class: "summary-card",
          "data-ocr-page-summary": label === "OCR complete" ? "" : null,
        },
        el("div", { class: "summary-label" }, label),
        el("div", { class: "summary-value" }, value),
        el("div", { class: "summary-note" }, note),
      ),
    ),
  );
}
function exportTickets() {
  const cols = [
    "Rental order (RO)",
    "Order number",
    "Shipment",
    "Customer",
    "Delivery location",
    "Billing address",
    "Status",
    "OCR verified pages",
    "Manually approved pages",
    "Identified pages",
    "Total pages",
    "Reviewed",
  ];
  const rows = state.tickets.map((t) => [
    t.parent_rental_number || "",
    t.work_order,
    t.shipment,
    t.customer,
    t.delivery_location,
    t.billing_address,
    t.status,
    t.ocr_verified_pages ?? t.verified_pages,
    t.manually_approved_pages || 0,
    t.verified_pages,
    t.expected_pages,
    t.reviewed ? "Yes" : "No",
  ]);
  const csv = [cols, ...rows]
    .map((row) =>
      row.map((v) => `"${String(v ?? "").replaceAll('"', '""')}"`).join(","),
    )
    .join("\r\n");
  const url = URL.createObjectURL(
    new Blob([csv], { type: "text/csv;charset=utf-8" }),
  );
  const a = el("a", { href: url, download: "order-tracker.csv" });
  a.click();
  URL.revokeObjectURL(url);
  toast(`Exported ${rows.length} work orders`);
}
function empty(title, message, action) {
  return el(
    "div",
    { class: "empty-state" },
    el("div", { class: "empty-icon" }, icon("inbox")),
    el("h3", {}, title),
    el("p", {}, message),
    action,
  );
}
function pageGapMessage(ticket) {
  const pages = ticket.unaccounted_pages || ticket.missing_pages || [];
  if (!pages.length) return "Some page results still need review.";
  if (ticket.page_gap_status === "not_in_scan")
    return `Printed pages not found in the processed scan: ${pages.join(", ")}.`;
  if (ticket.page_gap_status === "no_compatible_image")
    return `No matching image for page ${pages.join(", ")}. The other images have different order or page details. Upload the missing page.`;
  if (ticket.page_gap_status === "processing" || ticket.processing)
    return `Pages ${pages.join(", ")} have not been identified yet; this scan is still processing.`;
  const unidentified = ticket.unidentified_scan_pages?.length || 0;
  const scope = ticket.parent_rental_number
    ? `under ${ticket.parent_rental_number}`
    : "in the same scan";
  return `Not identified for this order: pages ${pages.join(", ")}.${unidentified ? ` ${unidentified} unassigned page(s) remain ${scope}. A page may be present but unmatched; review those pages before treating it as absent.` : " This does not by itself prove the image is absent."}`;
}
function unidentifiedScanEvidence(ticket) {
  const pages = ticket.unidentified_scan_pages || [];
  if (!pages.length) return null;
  return el(
    "details",
    { class: "unidentified-evidence" },
    el(
      "summary",
      {},
      `${pages.length} unassigned page(s) ${ticket.parent_rental_number ? `under ${ticket.parent_rental_number}` : "in the same scan"}`,
    ),
    el(
      "p",
      { class: "muted" },
      "These pages are not confirmed to belong to this order. Review them before declaring a page absent.",
    ),
    el(
      "ul",
      {},
      ...pages.map((page) =>
        el(
          "li",
          {},
          el(
            "a",
            {
              href: `${base()}/pages/${page.id}/preview`,
              target: "_blank",
              rel: "noopener",
            },
            `Source page ${page.source_page}${page.identifier ? ` · OCR read ${page.identifier}` : " · No readable identifier"}`,
          ),
          pageFieldsPanel(page, true),
        ),
      ),
    ),
  );
}
function ocrBadge(ticket) {
  return el(
    "div",
    { class: "ocr-cell" },
    badge(
      ticket.ocr_status === "verified"
        ? "Ready to download"
        : ticket.missing_pages?.length && !ticket.processing
          ? ["not_in_scan", "no_compatible_image"].includes(
              ticket.page_gap_status,
            )
            ? "Needs upload"
            : "Incomplete"
          : ticket.flagged
            ? "Needs review"
            : ticket.ocr_status === "partial"
              ? "Detected"
              : "Awaiting OCR",
      ticket.ocr_status === "verified"
        ? "green"
        : ticket.flagged
          ? "amber"
          : ticket.ocr_status === "partial"
            ? "blue"
            : "neutral",
      ticket.ocr_status === "verified" ? "check" : "scan",
    ),
    el(
      "small",
      {},
      `${ticket.verified_pages} of ${ticket.expected_pages} pages identified${ticket.missing_pages?.length && !ticket.processing ? ` · Not identified: ${ticket.missing_pages.join(", ")}` : ""}`,
    ),
  );
}
function rowFor(ticket) {
  const row = el(
    "tr",
    {
      tabindex: "0",
      "aria-label": `Open ${ticket.work_order}`,
      onClick: () => openDetail(ticket.id),
      onKeydown: (event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          openDetail(ticket.id);
        }
      },
    },
    el("td", { class: "mono" }, rentalNumber(ticket) || "Not read"),
    el(
      "td",
      {},
      el(
        "div",
        { class: "order-cell" },
        el("span", { class: "document-glyph" }, icon("file")),
        el(
          "div",
          {},
          el("strong", { class: "mono order-number" }, ticket.work_order),
          el("small", {}, `Shipment ${ticket.shipment}`),
        ),
      ),
    ),
    el(
      "td",
      {},
      el(
        "div",
        { class: "customer-cell" },
        el("span", { class: "customer-avatar" }, initials(ticket.customer)),
        el(
          "div",
          {},
          el("strong", {}, ticket.customer.replace(/^Demo\s+/i, "")),
          el(
            "small",
            { class: "location-line" },
            icon("pin"),
            ticket.delivery_location || "Location not provided",
          ),
        ),
      ),
    ),
    el(
      "td",
      { class: "address-cell" },
      ticket.billing_address
        ? el("span", {}, ticket.billing_address)
        : el("span", { class: "muted" }, "Not provided"),
      el("small", {}, "Billing address"),
    ),
    el(
      "td",
      {},
      badge(
        ticket.status === "COMPLETE" ? "Complete" : "Open",
        ticket.status === "COMPLETE" ? "neutral" : "blue",
      ),
    ),
    el("td", {}, ocrBadge(ticket)),
    el(
      "td",
      { class: "date-cell" },
      el(
        "strong",
        {},
        date(ticket.due_date, { month: "short", day: "numeric" }),
      ),
      el(
        "small",
        {},
        ticket.due_date ? new Date(ticket.due_date).getFullYear() : "—",
      ),
    ),
    el(
      "td",
      { class: "row-action" },
      ticket.download_ready === true ||
        (ticket.download_ready == null && ticket.ocr_status === "verified")
        ? ticketDownloadControl(ticket)
        : el(
            "span",
            { class: "muted download-pending" },
            ticket.flagged ? "Needs review" : "Not ready",
          ),
      el(
        "button",
        {
          class: "icon-button",
          "aria-label": `View ${ticket.work_order}`,
          onClick: (event) => {
            event.stopPropagation();
            openDetail(ticket.id);
          },
        },
        icon("chevron"),
      ),
    ),
  );
  return row;
}
function table() {
  const first = (state.page - 1) * state.pageSize;
  const rows = state.tickets.slice(first, first + state.pageSize);
  const total = state.tickets.length;
  const pages = Math.ceil(total / state.pageSize) || 1;
  const region = el("div", { id: "ticket-table-region" });
  if (!total) {
    region.append(
      empty(
        state.filter === "verified"
          ? "No verified orders yet"
          : "No orders found",
        state.query
          ? "Try another order number, customer, or address."
          : "There are no work orders in this view.",
        button("Show all orders", () => {
          state.query = "";
          state.filter = "all";
          state.status = "all";
          state.documentFilter = "";
          loadView();
        }),
      ),
    );
    return region;
  }
  const header = el(
    "thead",
    {},
    el(
      "tr",
      {},
      ...[
        "Rental order (RO)",
        "Order number",
        "Customer & location",
        "Address",
        "Order status",
        "OCR result",
        "Due date",
        "Download",
      ].map((h) => el("th", { scope: "col" }, h)),
    ),
  );
  region.append(
    el(
      "div",
      { class: "table-scroll" },
      el(
        "table",
        { class: "orders-table" },
        el(
          "caption",
          { class: "sr-only" },
          "Work orders from the SQL tracker. Select a row to inspect documents and OCR results.",
        ),
        header,
        el("tbody", {}, rows.map(rowFor)),
      ),
    ),
  );
  const pageButtons = [];
  for (let i = 1; i <= pages; i++)
    if (i === 1 || i === pages || Math.abs(i - state.page) < 2)
      pageButtons.push(
        button(
          String(i),
          () => {
            state.page = i;
            updateTable();
          },
          `page-button ${i === state.page ? "selected" : ""}`,
        ),
      );
  const prev = button(
    "",
    () => {
      state.page--;
      updateTable();
    },
    "page-button",
    "left",
  );
  prev.setAttribute("aria-label", "Previous page");
  prev.disabled = state.page <= 1;
  const next = button(
    "",
    () => {
      state.page++;
      updateTable();
    },
    "page-button",
    "chevron",
  );
  next.setAttribute("aria-label", "Next page");
  next.disabled = state.page >= pages;
  region.append(
    el(
      "div",
      { class: "table-footer" },
      el(
        "span",
        {},
        `Showing ${first + 1}–${Math.min(first + state.pageSize, total)} of ${total} orders`,
      ),
      el("div", { class: "pagination" }, prev, ...pageButtons, next),
    ),
  );
  return region;
}
function updateTable() {
  $("#ticket-table-region")?.replaceWith(table());
}
function tabButton(label, key, count) {
  return el(
    "button",
    {
      class: `filter-tab ${state.filter === key ? "active" : ""}`,
      "data-filter": key,
      onClick: () => {
        state.filter = key;
        state.page = 1;
        loadView();
      },
    },
    label,
    el("span", {}, count),
  );
}
function orderTracker() {
  main.replaceChildren(
    heading(
      "Order Tracker",
      "Every work order, document, and OCR result. In one place.",
      [
        datasetControl(),
        button("Export", exportTickets, "button secondary", "down"),
      ],
    ),
    summaryCards(),
  );
  const panel = el("section", { class: "panel tracker-panel" });
  panel.append(
    el(
      "div",
      { class: "panel-heading" },
      el(
        "div",
        {},
        el("h2", {}, "Work orders"),
        el(
          "span",
          { class: "panel-subtitle" },
          "Orders found in your uploaded documents.",
        ),
      ),
      el(
        "div",
        { class: "panel-heading-right" },
        badge(
          state.summary.verified_pages ? "Page evidence" : "No processed pages",
          state.summary.verified_pages ? "green" : "neutral",
          state.summary.verified_pages ? "shield" : "file",
        ),
        button(
          "",
          () => {
            loadView();
            toast("Workspace updated");
          },
          "icon-button",
          "refresh",
        ),
      ),
    ),
  );
  panel.append(
    el(
      "div",
      { class: "filter-tabs" },
      tabButton("All orders", "all", state.summary.tickets),
      tabButton(
        "Ready to download",
        "verified",
        state.summary.verified_tickets,
      ),
      tabButton(
        "Incomplete orders",
        "missing",
        state.summary.missing_tickets || 0,
      ),
      tabButton(
        "Awaiting OCR",
        "pending",
        state.summary.tickets - state.summary.verified_tickets,
      ),
      tabButton(
        "Reviewed",
        "reviewed",
        state.summary.tickets - state.summary.review_queue,
      ),
    ),
  );
  const input = el("input", {
    type: "search",
    value: state.query,
    placeholder: "Search work order, customer, shipment, or address…",
    "aria-label": "Search work orders",
    onInput: (event) => {
      state.query = event.target.value;
      clearTimeout(state.searchTimer);
      state.searchTimer = setTimeout(() => loadTicketsOnly(), 220);
    },
  });
  const select = el(
    "select",
    {
      "aria-label": "Filter order status",
      onChange: (event) => {
        state.status = event.target.value;
        state.page = 1;
        loadView();
      },
    },
    ...["all", "OPEN", "COMPLETE"].map((v) =>
      el(
        "option",
        { value: v, selected: v === state.status },
        v === "all" ? "All statuses" : v === "OPEN" ? "Open" : "Complete",
      ),
    ),
  );
  panel.append(
    el(
      "div",
      { class: "table-toolbar" },
      el(
        "label",
        { class: "search-field" },
        icon("search"),
        input,
        el("kbd", {}, "/"),
      ),
      el("div", { class: "status-filter" }, icon("filter"), select),
    ),
  );
  panel.append(table());
  main.append(
    panel,
    el(
      "div",
      { class: "tracker-footnote" },
      icon("shield"),
      "Only uploaded documents create orders. Printed page numbers determine completeness.",
    ),
  );
}
function query() {
  const p = new URLSearchParams();
  if (state.query) p.set("q", state.query);
  if (state.status !== "all") p.set("status", state.status);
  if (["verified", "pending", "missing"].includes(state.filter))
    p.set("ocr", state.filter);
  if (state.documentFilter) p.set("document_id", state.documentFilter);
  return p;
}
async function getTickets() {
  const filter = state.filter;
  const result = await api(`${base()}/tickets?${query()}`);
  rememberDownloads(result.tickets);
  return filter === "reviewed"
    ? result.tickets.filter((t) => t.reviewed)
    : result.tickets;
}
async function refreshTracker() {
  if (!["tickets", "flags"].includes(state.view)) return;
  const generation = state.request;
  const view = state.view;
  const filters = query().toString();
  try {
    const [summary, tickets, activity, rentals] = await Promise.all([
      api(base()),
      getTickets(),
      view === "flags"
        ? api(`${base()}/activity?issues_only=true`)
        : Promise.resolve(null),
      view === "flags" ? api(`${base()}/rental-orders`) : Promise.resolve(null),
    ]);
    if (
      generation !== state.request ||
      view !== state.view ||
      filters !== query().toString()
    )
      return;
    state.summary = summary;
    state.tickets = tickets;
    state.page = Math.min(
      state.page,
      Math.max(1, Math.ceil(tickets.length / state.pageSize)),
    );
    updateTable();
    if (activity) {
      state.scanCounts = activity;
      state.rentalOrders = rentals?.rental_orders || state.rentalOrders || [];
      document.querySelector("#flags-results")?.replaceWith(flagsResults());
    }
    if (view === "flags" && state.detail && !state.approvingPage) {
      const current = state.detail;
      const latest = tickets.find((t) => t.id === current.id);
      const fingerprint = (t) =>
        JSON.stringify([
          t.verified_pages,
          t.processing,
          t.missing_pages,
          (t.unidentified_scan_pages || []).map((p) => p.id),
        ]);
      if (latest && fingerprint(latest) !== fingerprint(current)) {
        const updated = await api(`${base()}/tickets/${current.id}`);
        if (state.detail?.id === current.id && !state.approvingPage) {
          state.detail = updated;
          if (!(updated.unaccounted_pages || []).includes(state.fixPrintedPage))
            state.fixPrintedPage = updated.unaccounted_pages?.[0] || null;
          if (
            !updated.unidentified_scan_pages?.some(
              (p) => p.id === state.fixPageId,
            )
          ) {
            state.fixPageId = null;
            state.fixAcknowledged = false;
          }
          if (isReadyOrder(updated) && state.detailTab === "fix")
            state.detailTab = "ocr";
          renderDetail();
        }
      }
    }
    const counts = {
      all: summary.tickets,
      verified: summary.verified_tickets,
      pending: summary.tickets - summary.verified_tickets,
      missing: summary.missing_tickets || 0,
      reviewed: summary.tickets - summary.review_queue,
    };
    for (const [key, count] of Object.entries(counts)) {
      const node = document.querySelector(
        `.filter-tab[data-filter="${key}"] span`,
      );
      if (node) node.textContent = count;
    }
  } catch (error) {
    toast(error.message);
  }
}
async function loadTicketsOnly() {
  const generation = ++state.request;
  try {
    const tickets = await getTickets();
    if (generation !== state.request) return;
    state.tickets = tickets;
    state.page = 1;
    updateTable();
  } catch (error) {
    toast(error.message);
  }
}
async function loadView() {
  const generation = ++state.request;
  navigation();
  main.setAttribute("aria-busy", "true");
  try {
    state.summary = await api(base());
    state.scanCounts = await api(`${base()}/activity`);
    const rentals = await api(`${base()}/rental-orders`);
    state.rentalOrders = rentals.rental_orders || [];
    if (generation !== state.request) return;
    navigation();
    if (["tickets", "flags"].includes(state.view)) {
      const tickets = await getTickets();
      if (generation === state.request) {
        state.tickets = tickets;
        if (state.view === "flags") {
          const issues = await api(`${base()}/activity?issues_only=true`);
          if (generation === state.request) {
            state.scanCounts = issues;
            flagsView();
          }
        } else orderTracker();
      }
    } else if (state.view === "overview") {
      const tickets = await getTickets();
      if (generation === state.request) {
        state.tickets = tickets;
        overview();
      }
    } else if (state.view === "ocr") {
      rememberDownloads((await api(`${base()}/tickets`)).tickets);
      const data = await api(`${base()}/activity`);
      if (generation === state.request) {
        state.scanCounts = data;
        activity(data.activity);
      }
    } else if (state.view === "imports") {
      const data = await api(`${base()}/imports`);
      if (generation === state.request) imports(data.imports);
    }
  } catch (error) {
    if (generation === state.request)
      main.replaceChildren(
        empty(
          "Couldn’t open this workspace",
          error.message,
          button("Try again", loadView, "button primary", "refresh"),
        ),
      );
  } finally {
    main.removeAttribute("aria-busy");
  }
}
function overview() {
  main.replaceChildren(
    heading(
      "A clear view of your documents.",
      "Upload scans to build your order data and find missing pages.",
      [datasetControl()],
    ),
    summaryCards(),
    liveProcessing(),
    intakeDropzone(),
  );
  main.append(overviewOrderResults());
}
function overviewOrderResults() {
  const ready = state.tickets.filter(isReadyOrder);
  const attention = state.tickets.filter((ticket) => !isReadyOrder(ticket));
  const selected = state.overviewResultTab || "ready";
  const switchTab = (key, focus = false) => {
    state.overviewResultTab = key;
    document
      .querySelector("#overview-order-results")
      ?.replaceWith(overviewOrderResults());
    if (focus) document.querySelector(`#overview-tab-${key}`)?.focus();
  };
  const tabs = el(
    "div",
    { class: "filter-tabs", role: "tablist", "aria-label": "Order results" },
    ...[
      ["ready", "Approved", ready.length],
      ["attention", "In review", attention.length],
    ].map(([key, label, count]) =>
      el(
        "button",
        {
          id: `overview-tab-${key}`,
          class: `filter-tab ${selected === key ? "active" : ""}`,
          type: "button",
          role: "tab",
          "aria-selected": selected === key,
          "aria-controls": `overview-results-${key}`,
          tabindex: selected === key ? 0 : -1,
          onClick: () => switchTab(key),
          onKeydown: (event) => {
            if (
              ["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)
            ) {
              event.preventDefault();
              switchTab(
                event.key === "Home"
                  ? "ready"
                  : event.key === "End"
                    ? "attention"
                    : selected === "ready"
                      ? "attention"
                      : "ready",
                true,
              );
            }
          },
        },
        label,
        el("span", {}, count),
      ),
    ),
  );
  const panel = el(
    "section",
    { id: "overview-order-results", class: "panel overview-order-results" },
    tabs,
  );
  for (const [key, tickets] of [
    ["ready", ready],
    ["attention", attention],
  ]) {
    const content = el("div", {
      id: `overview-results-${key}`,
      role: "tabpanel",
      "aria-labelledby": `overview-tab-${key}`,
      hidden: selected !== key ? true : null,
    });
    if (!tickets.length)
      content.append(
        empty(
          key === "ready" ? "No approved orders yet" : "No orders in review",
          "",
        ),
      );
    for (const ticket of tickets)
      content.append(
        el(
          "article",
          { class: "overview-order-row", "data-order-id": ticket.id },
          el(
            "strong",
            { class: "overview-order-label" },
            `${ticket.customer.replace(/^Demo\s+/i, "")} · ${ticket.work_order}`,
          ),
          badge(
            key === "ready" ? "Approved" : "In review",
            key === "ready" ? "green" : "amber",
          ),
          key === "ready"
            ? ticketDownloadControl(
                ticket,
                "Download",
                "button secondary overview-row-download",
              )
            : null,
        ),
      );
    panel.append(content);
  }
  return panel;
}
async function refreshOverviewOrders() {
  if (state.view !== "overview") return;
  const generation = state.request;
  try {
    const [result, activity, rentals] = await Promise.all([
      api(`${base()}/tickets`),
      api(`${base()}/activity`),
      api(`${base()}/rental-orders`),
    ]);
    if (generation !== state.request || state.view !== "overview") return;
    const previous = JSON.stringify([
      state.tickets,
      state.scanCounts?.counts,
      state.rentalOrders,
    ]);
    state.tickets = result.tickets;
    rememberDownloads(result.tickets);
    state.scanCounts = activity;
    state.rentalOrders = rentals.rental_orders || [];
    if (
      previous !==
      JSON.stringify([
        state.tickets,
        state.scanCounts?.counts,
        state.rentalOrders,
      ])
    )
      document
        .querySelector("#overview-order-results")
        ?.replaceWith(overviewOrderResults());
  } catch (error) {
    toast(error.message);
  }
}

function activity() {
  main.replaceChildren(
    heading("Scan intake", "Upload a PDF and follow its processing progress.", [
      datasetControl(),
      button("Refresh results", loadView, "button secondary", "refresh"),
    ]),
    liveProcessing(),
    intakeDropzone(),
    summaryCards(),
  );
}
function isReadyOrder(ticket) {
  return (
    ticket.download_ready === true ||
    (ticket.download_ready == null && ticket.ocr_status === "verified")
  );
}
function needsOrderAttention(ticket) {
  return (
    !isReadyOrder(ticket) &&
    (ticket.flagged ||
      (!ticket.processing &&
        (ticket.missing_pages?.length || ticket.ocr_status === "partial")))
  );
}
function resultDisclosure(key, summary, content, attributes = {}) {
  const expanded = state.expandedResults || (state.expandedResults = {});
  return el(
    "details",
    {
      class: "order-result-group",
      ...attributes,
      open: expanded[key] ? true : null,
      onToggle: (event) => {
        if (event.currentTarget.isConnected)
          expanded[key] = event.currentTarget.open;
      },
    },
    summary,
    content,
  );
}
function orderResultGroup(ticket) {
  const ready = isReadyOrder(ticket);
  const missing = ticket.missing_pages || [];
  const summary = el(
    "summary",
    { class: "order-result-summary" },
    el(
      "div",
      { class: "overview-order-info" },
      el(
        "strong",
        {},
        `${ticket.work_order} · Shipment ${ticket.shipment || "not read"}`,
      ),
      el(
        "small",
        {},
        `${ticket.customer.replace(/^Demo\s+/i, "")} · ${ticket.verified_pages} / ${ticket.expected_pages} pages`,
      ),
    ),
    badge(
      ready
        ? "Ready to download"
        : missing.length && !ticket.processing
          ? ["not_in_scan", "no_compatible_image"].includes(
              ticket.page_gap_status,
            )
            ? "Needs upload"
            : "Incomplete"
          : "Needs attention",
      ready ? "green" : "amber",
    ),
    icon("chevron"),
  );
  const content = el(
    "div",
    { class: "order-result-content" },
    el(
      "p",
      { class: "muted" },
      ready
        ? "All verified pages are grouped into one PDF in printed page order."
        : missing.length
          ? pageGapMessage(ticket)
          : "Conflicting or unreadable pages need review.",
    ),
  );
  const actions = el("div", { class: "heading-actions" });
  if (ready)
    actions.append(
      ticketDownloadControl(ticket, "Download compiled PDF", "button primary"),
      el(
        "a",
        {
          class: "button secondary",
          href: `${base()}/tickets/${ticket.id}/download?preview=true`,
          target: "_blank",
          rel: "noopener",
        },
        icon("eye"),
        "Open compiled PDF",
      ),
    );
  else {
    if (ticket.unidentified_scan_pages?.length)
      actions.append(
        button(
          "Fix missing page",
          () => openDetail(ticket.id, "fix"),
          "button primary",
          "scan",
        ),
      );
    actions.append(
      button(
        "Inspect order",
        () => openDetail(ticket.id),
        "button secondary",
        "eye",
      ),
    );
  }
  content.append(actions);
  return resultDisclosure(`order:${ticket.id}`, summary, content, {
    "data-order-id": ticket.id,
  });
}
function rentalResultGroup(rental, tickets, scope, additional = []) {
  const allChildren = rental.tickets || tickets;
  const content = el("div", { class: "rental-child-groups" });
  if (scope === "ready" && allChildren.some(isReadyOrder))
    content.append(
      el(
        "div",
        { class: "rental-actions" },
        el(
          "a",
          {
            class: "button secondary",
            href: `${base()}/rental-orders/${rental.id}/download.zip`,
          },
          icon("down"),
          "Download ready TKs ZIP",
        ),
      ),
    );
  for (const ticket of tickets) content.append(orderResultGroup(ticket));
  content.append(...additional);
  return resultDisclosure(
    `rental:${rental.id}:${scope}`,
    el(
      "summary",
      { class: "order-result-summary" },
      el(
        "div",
        { class: "overview-order-info" },
        el("strong", {}, rental.rental_number),
        el(
          "small",
          {},
          `${allChildren.length} work orders · ${new Set(allChildren.map((t) => t.shipment).filter(Boolean)).size} shipments${rental.unassigned_pages ? ` · ${rental.unassigned_pages} unassigned images` : ""}`,
        ),
      ),
      icon("chevron"),
    ),
    content,
    {
      "data-rental-id": rental.id,
      class: "order-result-group rental-order-group",
    },
  );
}
function rentalMetadata(id, fallback) {
  return (
    (state.rentalOrders || []).find((r) => r.id === id) || {
      id,
      rental_number: fallback.parent_rental_number,
      customer: fallback.customer,
    }
  );
}
function flaggedPageGroup(key, pages, label) {
  const body = el(
    "div",
    { class: "order-result-content" },
    pages[0].document
      ? el("p", { class: "muted" }, `Source: ${pages[0].document}`)
      : null,
  );
  for (const row of pages.sort((a, b) => a.page - b.page))
    body.append(
      el(
        "div",
        { class: "flag-page-row" },
        el(
          "div",
          {},
          el(
            "strong",
            {},
            `Source page ${row.page} · ${row.parent_rental_number ? "RO identified, ticket needs review" : row.status === "error" ? "OCR failed" : "Needs identification"}`,
          ),
          el(
            "small",
            {},
            row.identifier
              ? `OCR read: ${row.identifier}`
              : "No readable identifier",
          ),
          pageFieldsPanel({ ...row, source_page: row.page }, true),
        ),
        row.page_id
          ? el(
              "a",
              {
                class: "button secondary",
                href: `${base()}/pages/${row.page_id}/preview`,
                target: "_blank",
                rel: "noopener",
                "aria-label": `View flagged page ${row.page}`,
              },
              "View page",
            )
          : null,
      ),
    );
  return resultDisclosure(
    `unassigned:${key}`,
    el(
      "summary",
      { class: "order-result-summary" },
      el("strong", {}, label),
      badge(`${pages.length} flagged pages`, "amber"),
      icon("chevron"),
    ),
    body,
    { "data-flag-scan": key },
  );
}
function flagsView() {
  main.replaceChildren(
    heading(
      "Flags",
      "Rental orders stay grouped even when a TK/work-order number is missing.",
      [datasetControl()],
    ),
    flagsResults(),
  );
}
function flagsResults() {
  const orders = state.tickets.filter(needsOrderAttention);
  const issues = (state.scanCounts?.activity || []).filter((row) =>
    ["no_match", "error"].includes(row.status),
  );
  const result = el("div", { id: "flags-results" });
  if (!orders.length && !issues.length) {
    result.append(
      el(
        "section",
        { class: "panel" },
        empty(
          "No flags",
          "Incomplete tickets and unassigned RO pages will appear here after processing.",
        ),
      ),
    );
    return result;
  }
  const parents = new Map();
  for (const ticket of orders.filter((t) => t.rental_id)) {
    if (!parents.has(ticket.rental_id))
      parents.set(ticket.rental_id, {
        tickets: [],
        pages: [],
        fallback: ticket,
      });
    parents.get(ticket.rental_id).tickets.push(ticket);
  }
  for (const row of issues.filter((p) => p.rental_id)) {
    if (!parents.has(row.rental_id))
      parents.set(row.rental_id, { tickets: [], pages: [], fallback: row });
    parents.get(row.rental_id).pages.push(row);
  }
  if (parents.size) {
    const section = el(
      "section",
      { class: "panel overview-order-results" },
      el(
        "div",
        { class: "section-heading" },
        el("h2", {}, "Rental orders needing attention"),
      ),
    );
    for (const [id, group] of parents)
      section.append(
        rentalResultGroup(
          rentalMetadata(id, group.fallback),
          group.tickets,
          "flags",
          group.pages.length
            ? [
                flaggedPageGroup(
                  id,
                  group.pages,
                  "Unassigned TK/work-order pages",
                ),
              ]
            : [],
        ),
      );
    result.append(section);
  }
  const legacy = orders.filter((t) => !t.rental_id);
  if (legacy.length)
    result.append(
      el(
        "section",
        { class: "panel overview-order-results" },
        el(
          "div",
          { class: "section-heading" },
          el("h2", {}, "Orders needing attention · RO not read"),
          badge(`${legacy.length} orders`, "amber"),
        ),
        ...legacy.map(orderResultGroup),
      ),
    );
  const scans = new Map();
  for (const row of issues.filter((p) => !p.rental_id)) {
    const key = row.document_id || row.document || "scan";
    if (!scans.has(key)) scans.set(key, []);
    scans.get(key).push(row);
  }
  if (scans.size) {
    const section = el(
      "section",
      { class: "panel overview-order-results" },
      el(
        "div",
        { class: "section-heading" },
        el("h2", {}, "Unidentified pages · RO not read"),
      ),
    );
    let number = 0;
    for (const [key, pages] of scans)
      section.append(flaggedPageGroup(key, pages, `Scan ${++number}`));
    result.append(section);
  }
  return result;
}
function imports(rows) {
  main.replaceChildren(
    heading(
      "Ingestion history",
      "See how source trackers became organized work orders.",
      [datasetControl()],
    ),
  );
  const panel = el(
    "section",
    { class: "panel" },
    el(
      "div",
      { class: "section-heading" },
      el("h2", {}, "Tracker imports"),
      badge(`${rows.length} runs`),
    ),
  );
  if (!rows.length)
    panel.append(
      empty(
        "No imports yet",
        "Import a generated tracker to start organizing tickets.",
      ),
    );
  else
    panel.append(
      el(
        "div",
        { class: "table-scroll" },
        el(
          "table",
          { class: "orders-table" },
          el(
            "thead",
            {},
            el(
              "tr",
              {},
              ...[
                "Import",
                "Started",
                "Records read",
                "Loaded",
                "Rejected",
                "Status",
              ].map((h) => el("th", { scope: "col" }, h)),
            ),
          ),
          el(
            "tbody",
            {},
            rows.map((row, index) =>
              el(
                "tr",
                {},
                el(
                  "td",
                  {},
                  el(
                    "div",
                    { class: "order-cell" },
                    el("span", { class: "document-glyph" }, icon("upload")),
                    el(
                      "div",
                      {},
                      el("strong", {}, "Tracker import"),
                      el("small", {}, `Run ${rows.length - index}`),
                    ),
                  ),
                ),
                el("td", {}, time(row.started_at)),
                el("td", {}, row.rows_seen),
                el("td", {}, row.rows_loaded),
                el("td", {}, row.rows_rejected),
                el(
                  "td",
                  {},
                  badge(
                    row.status === "success" ? "Complete" : row.status,
                    row.status === "success"
                      ? "green"
                      : row.status === "failed"
                        ? "red"
                        : "amber",
                  ),
                ),
              ),
            ),
          ),
        ),
      ),
    );
  main.append(
    panel,
    el(
      "p",
      { class: "tracker-footnote" },
      icon("shield"),
      "Repeat imports update existing records without duplicating your work orders.",
    ),
  );
}
let previousFocus;
function closeDetail() {
  overlay.replaceChildren();
  document.body.classList.remove("modal-open");
  state.detail = null;
  if (previousFocus?.isConnected) previousFocus.focus();
}
async function openDetail(id, initialTab = "details") {
  previousFocus = document.activeElement;
  document.body.classList.add("modal-open");
  overlay.replaceChildren(
    el("div", { class: "drawer-backdrop", onClick: closeDetail }),
    el(
      "section",
      {
        class: "detail-drawer",
        role: "dialog",
        "aria-modal": "true",
        "aria-label": "Work order details",
      },
      el(
        "div",
        { class: "loading-state" },
        el("span", { class: "spinner" }),
        "Opening work order…",
      ),
    ),
  );
  try {
    state.detail = await api(`${base()}/tickets/${encodeURIComponent(id)}`);
    state.pageIndex = 0;
    state.detailTab =
      initialTab === "fix" && state.view !== "flags" ? "ocr" : initialTab;
    state.fixPageId = null;
    state.fixPrintedPage =
      state.detail.unaccounted_pages?.[0] ||
      state.detail.missing_pages?.[0] ||
      null;
    state.fixError = "";
    state.fixAcknowledged = false;
    state.fixCandidateFilter = "possible";
    state.detailScroll = {};
    renderDetail(true);
  } catch (error) {
    toast(error.message);
    closeDetail();
  }
}
function field(label, value, cls = "") {
  return el(
    "div",
    { class: `detail-field ${cls}` },
    el("dt", {}, label),
    el("dd", {}, value || "Not provided"),
  );
}
function pageFieldsPanel(page, collapsible = false) {
  const fields = page?.fields;
  if (!fields || !Object.keys(fields).length) return null;
  const signature =
    {
      explicitly_unsigned: "Not signed — stated on page",
      digital_signature_present:
        "PDF signature present — validity not verified",
      field_present: "Signature text or field found — needs review",
      not_determined: "Not determined from this page",
    }[fields.signature_status] || "Not determined from this page";
  const title = `Extracted details · source page ${page.source_page || page.page || page.number}`;
  const grid = el(
    "dl",
    { class: "detail-grid page-fields-grid" },
    field("Customer", fields.customer || "Not read"),
    !fields.work_order?.startsWith("OD-")
      ? field(
          "Customer order #",
          fields.customer_order_number || "Not read",
          "mono-value",
        )
      : null,
    field(
      fields.work_order?.startsWith("OD-")
        ? "Order number (OD)"
        : "Ticket / work order",
      fields.work_order || "Not read",
      "mono-value",
    ),
    field("Shipment / SO", fields.shipment || "Not read", "mono-value"),
    field(
      "Rental order (RO)",
      rentalNumber(fields) || "Not read",
      "mono-value",
    ),
    field("Billing address", fields.address || "Not read", "page-field-wide"),
    field("Delivery location", fields.destination || "Not read"),
    field("Delivery address / dispatch", fields.delivery_address || "Not read"),
    field("Document", fields.document_type || "Not read"),
    field(
      "Printed page",
      fields.page_number
        ? `${fields.page_number} / ${fields.expected_pages || "?"}`
        : "Not read",
    ),
    field(
      "Signature document",
      fields.signature_document
        ? "Acknowledgment / signature page"
        : "Not identified",
    ),
    field("Signature status", signature),
    fields.signature_evidence
      ? field(
          "Signature evidence",
          fields.signature_evidence,
          "page-field-wide",
        )
      : null,
  );
  return el(
    collapsible ? "details" : "section",
    { class: "page-fields-panel" },
    el(collapsible ? "summary" : "h3", {}, title),
    el(
      "p",
      { class: "muted" },
      "Read from this image. These details do not by themselves confirm an order match.",
    ),
    grid,
  );
}
function detailInfo(ticket) {
  const grid = el(
    "dl",
    { class: "detail-grid" },
    field(
      "Rental order (RO)",
      rentalNumber(ticket) || "Not read",
      "mono-value",
    ),
    field("Order number", ticket.work_order, "mono-value"),
    field("Shipment number", ticket.shipment, "mono-value"),
    field("Order date", date(ticket.order_date)),
    field("Due date", date(ticket.due_date)),
    field("Assigned to", ticket.assigned_to),
    field("Order type", ticket.order_type.toLowerCase()),
  );
  return el(
    "div",
    { class: "detail-information" },
    el("h3", { class: "detail-section-title" }, "Order information"),
    grid,
    el(
      "div",
      { class: "address-block" },
      el(
        "div",
        { class: "address-block-title" },
        icon("pin"),
        "Delivery location",
      ),
      el("strong", {}, ticket.delivery_location || "Not provided"),
      el("p", {}, "Destination recorded in the tracker"),
    ),
    el(
      "div",
      { class: "address-block" },
      el("div", { class: "address-block-title" }, icon("file"), "Bill to"),
      el("strong", {}, ticket.customer),
      el("p", {}, ticket.billing_address || "Billing address not provided"),
      el("small", {}, "Address from the synthetic source packet"),
    ),
    ticket.contact_email
      ? el("div", { class: "contact-line" }, icon("mail"), ticket.contact_email)
      : null,
    ticket.items.length
      ? el(
          "div",
          { class: "items-block" },
          el(
            "h3",
            { class: "detail-section-title" },
            `Equipment · ${ticket.items.length} items`,
          ),
          ...ticket.items.map((item) =>
            el(
              "div",
              { class: "item-row" },
              el(
                "div",
                {},
                el("strong", {}, item.description),
                el("small", { class: "mono" }, item.code),
              ),
              el("span", { class: "item-quantity" }, `× ${item.quantity}`),
            ),
          ),
        )
      : null,
  );
}
function ocrInfo(ticket) {
  const matched =
    ticket.verified_pages ?? ticket.pages.filter((p) => p.matched).length;
  const expected = ticket.expected_pages || ticket.pages.length;
  const complete = isReadyOrder(ticket) && expected > 0 && matched >= expected;
  return el(
    "div",
    { class: "ocr-information" },
    el(
      "div",
      {
        class: `ocr-summary ${complete ? "complete" : "incomplete"}`,
      },
      icon(complete ? "circlecheck" : "scan"),
      el("strong", {}, `${matched} of ${expected} pages identified`),
      el(
        "p",
        {},
        complete
          ? "All expected printed pages are identified and verified."
          : pageGapMessage(ticket),
      ),
    ),
    ticket.manually_approved_pages
      ? el(
          "p",
          { class: "evidence-note" },
          `${ticket.ocr_verified_pages} OCR-verified pages · ${ticket.manually_approved_pages} manually approved pages`,
        )
      : null,
    state.view === "flags" ? unidentifiedScanEvidence(ticket) : null,
    state.view === "flags"
      ? el(
          "div",
          { id: "selected-page-review" },
          selectedPageReview(ticket.pages[state.pageIndex]),
        )
      : null,
    state.view !== "flags" && !complete
      ? button(
          "Review in Flags",
          () => {
            navigate("flags");
            openDetail(
              ticket.id,
              ticket.unidentified_scan_pages?.length ? "fix" : "ocr",
            );
          },
          "button secondary",
          "eye",
        )
      : null,
    el("h3", { class: "detail-section-title" }, "Page-level evidence"),
    ...ticket.pages.map((page, index) =>
      el(
        "button",
        {
          class: `evidence-row ${index === state.pageIndex ? "selected" : ""}`,
          "data-page-index": index,
          "aria-pressed": index === state.pageIndex,
          onClick: () => {
            state.pageIndex = index;
            updatePageSelection();
          },
        },
        el(
          "span",
          { class: "page-number" },
          page.printed_page || page.number || index + 1,
        ),
        el(
          "span",
          { class: "evidence-copy" },
          el("strong", {}, page.paper),
          el("small", {}, page.copy ? `${page.copy} copy` : "Source page"),
        ),
        el(
          "span",
          { class: "evidence-values" },
          el(
            "small",
            {},
            page.manually_approved
              ? "Manually linked"
              : page.accepted || page.matched
                ? "Verified page"
                : "Needs review",
          ),
        ),
        el(
          "span",
          {
            class: `evidence-status ${page.manually_approved || page.matched ? "positive" : ""}`,
          },
          icon(page.manually_approved || page.matched ? "check" : "clock"),
        ),
      ),
    ),
    el(
      "p",
      { class: "evidence-note" },
      "Printed page numbers determine completeness. An unlinked page may still be present among the scan’s unidentified pages.",
    ),
  );
}
async function toggleReview() {
  const ticket = state.detail;
  const control = $("#review-toggle");
  control.disabled = true;
  try {
    await api(`${base()}/tickets/${ticket.id}/review`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ reviewed: !ticket.reviewed }),
    });
    ticket.reviewed = !ticket.reviewed;
    toast(
      ticket.reviewed
        ? "Work order marked as reviewed"
        : "Work order returned to review queue",
    );
    renderDetail();
    await loadView();
  } catch (error) {
    toast(error.message);
    control.disabled = false;
  }
}
function pageComparison(page, printedPage = state.fixPrintedPage) {
  if (page?.review?.[String(printedPage)])
    return page.review[String(printedPage)];
  if (page?.comparison) return page.comparison;
  const t = state.detail,
    f = page?.fields || {};
  const normalize = (value, key) => {
    let text = String(value ?? "")
      .trim()
      .toLowerCase();
    if (key === "customer") text = text.replace(/^demo\s+/, "");
    if (key === "shipment" && /^\d+$/.test(text))
      return text.replace(/^0+/, "") || "0";
    return text.replace(/[^\p{L}\p{N}_]/gu, "");
  };
  const checks = [
    ["customer", "Customer", t.customer, f.customer],
    ["address", "Address", t.billing_address, f.address],
    [
      "customer_order_number",
      "Customer order #",
      t.customer_order_number,
      f.customer_order_number,
    ],
    [
      "parent_rental_number",
      "Rental order (RO)",
      rentalNumber(t),
      rentalNumber(f),
    ],
    ["work_order", "Order number", t.work_order, f.work_order],
    ["shipment", "Shipment / SO", t.shipment, f.shipment],
    ["page_number", "Printed page", printedPage, f.page_number],
    ["expected_pages", "Page total", t.expected_pages, f.expected_pages],
  ]
    .filter(
      ([key]) =>
        key !== "customer_order_number" || !t.work_order?.startsWith("OD-"),
    )
    .map(([key, label, expected, found]) => {
      const status =
        found == null || found === ""
          ? "not_read"
          : expected == null || expected === ""
            ? "no_target"
            : normalize(found, key) === normalize(expected, key)
              ? "match"
              : "different";
      return {
        key,
        label,
        expected,
        found,
        status,
        blocking: key !== "shipment" && status === "different",
      };
    });
  const identified = checks.some(
    (c) =>
      c.status === "match" &&
      !["shipment", "page_number", "expected_pages"].includes(c.key),
  );
  return {
    checks,
    blocked: checks.some((c) => c.blocking),
    conflicts: checks.filter((c) => c.blocking).map((c) => c.label),
    differences: checks
      .filter((c) => c.status === "different" && !c.blocking)
      .map((c) => c.label),
    needs_acknowledgment:
      !identified ||
      checks.some((c) => c.status === "different" && !c.blocking),
    identified,
  };
}
function selectedPageReview(page, isFix = state.detailTab === "fix") {
  if (!page) return el("p", { class: "muted" }, "Select an image to compare.");
  const review = pageComparison(
    page,
    isFix ? state.fixPrintedPage : page.printed_page || page.number,
  );
  const labels = {
    match: "Match",
    different: "Different",
    not_read: "Not read",
    no_target: "No target value",
  };
  return el(
    "div",
    { class: "selection-review" },
    el(
      "h3",
      {},
      isFix
        ? `Source ${page.source_page} → ${state.detail.work_order} · page ${state.fixPrintedPage}`
        : `Source ${page.source_page} · field checks`,
    ),
    el(
      "table",
      { class: "page-comparison" },
      el(
        "thead",
        {},
        el(
          "tr",
          {},
          el("th", {}, "Field"),
          el("th", {}, "Target order"),
          el("th", {}, "Selected image"),
        ),
      ),
      el(
        "tbody",
        {},
        ...review.checks.map((check) =>
          el(
            "tr",
            { class: `comparison-${check.status}`, "data-check": check.key },
            el("th", { scope: "row" }, check.label),
            el("td", {}, check.expected || "—"),
            el(
              "td",
              {},
              el("span", {}, check.found || "—"),
              el("small", { class: "comparison-status" }, labels[check.status]),
              check.ocr_differs
                ? el(
                    "small",
                    { class: "comparison-ocr-difference" },
                    `Header OCR: ${check.ocr_found} · differs`,
                  )
                : null,
            ),
          ),
        ),
      ),
    ),
    isFix
      ? el(
          "p",
          {
            class: review.blocked ? "comparison-error" : "comparison-note",
            role: review.blocked ? "alert" : null,
          },
          review.blocked
            ? `Different ${review.conflicts.join(", ").toLowerCase()}. Choose another image.`
            : review.needs_acknowledgment
              ? "Check the image and acknowledge the difference below."
              : "The available fields agree. Check the image before linking it.",
        )
      : null,
    pageFieldsPanel(page, true),
  );
}
function updateApprovalControls() {
  const ticket = state.detail;
  const chosen = ticket?.unidentified_scan_pages?.find(
    (p) => p.id === state.fixPageId,
  );
  const review = chosen ? pageComparison(chosen) : null;
  const ack = document.querySelector("#fix-acknowledgment");
  if (ack) {
    ack.hidden = !chosen || review.blocked || !review.needs_acknowledgment;
    ack.querySelector("input").checked = !!state.fixAcknowledged;
    ack.querySelector("input").disabled = !!state.approvingPage;
    ack.querySelector("span").textContent = review?.differences.length
      ? `I checked the image and accept the ${review.differences.join(", ").toLowerCase()} difference.`
      : "I checked the image and confirm it belongs to this order.";
  }
  const control = document.querySelector("#approve-page");
  if (control) {
    control.textContent = state.approvingPage
      ? "Linking image…"
      : chosen
        ? `Link source ${chosen.source_page} → ${ticket.work_order} · page ${state.fixPrintedPage}`
        : "Select an image to link";
    control.disabled =
      !!state.approvingPage ||
      !chosen ||
      review.blocked ||
      (review.needs_acknowledgment && !state.fixAcknowledged) ||
      !(ticket.unaccounted_pages || ticket.missing_pages || []).includes(
        state.fixPrintedPage,
      ) ||
      ticket.processing;
  }
  document.querySelectorAll(".fix-thumbnail").forEach((button) => {
    button.disabled = !!state.approvingPage;
  });
  const select = document.querySelector(
    '[aria-label="Assign as printed page"]',
  );
  if (select) select.disabled = !!state.approvingPage;
  const error = document.querySelector("#fix-error");
  if (error) {
    error.textContent = state.fixError || "";
    error.hidden = !state.fixError;
  }
}
function chooseFixImage(id) {
  if (state.approvingPage) return;
  if (id !== state.fixPageId) state.fixAcknowledged = false;
  state.fixPageId = id;
  state.fixError = "";
  updatePageSelection();
}
function candidateCategory(page) {
  return pageComparison(page).blocked ? "different" : "possible";
}
function updateCandidateFilter() {
  if (state.detailTab !== "fix" || !state.detail) return;
  const pages = state.detail.unidentified_scan_pages || [];
  const counts = {
    possible: pages.filter((p) => candidateCategory(p) === "possible").length,
    different: pages.filter((p) => candidateCategory(p) === "different").length,
  };
  const filter = state.fixCandidateFilter || "possible";
  document.querySelectorAll("[data-candidate-filter]").forEach((node) => {
    const key = node.dataset.candidateFilter;
    node.setAttribute("aria-pressed", String(key === filter));
    node.textContent = `${key === "possible" ? "Possible matches" : "Different images"} (${counts[key]})`;
  });
  document.querySelectorAll(".fix-thumbnail").forEach((node) => {
    const page = pages.find((p) => p.id === node.dataset.sourceId);
    const category = page ? candidateCategory(page) : "different";
    node.hidden = category !== filter;
    const status = node.querySelector(".candidate-status");
    if (status) {
      status.textContent =
        category === "possible"
          ? "Needs your review"
          : "Different order / page";
      status.className = `candidate-status ${category}`;
    }
  });
  const notice = document.querySelector("#candidate-empty");
  if (notice) {
    notice.hidden = counts[filter] > 0;
    notice.textContent =
      filter === "possible"
        ? `No image matches page ${state.fixPrintedPage}. ${counts.different ? `${counts.different} different images can be inspected in the other tab. ` : ""}Upload the missing page to continue.`
        : "No different images in this scan.";
  }
}
function setCandidateFilter(filter) {
  state.fixCandidateFilter = filter;
  const selected = state.detail?.unidentified_scan_pages?.find(
    (p) => p.id === state.fixPageId,
  );
  if (selected && candidateCategory(selected) !== filter) {
    state.fixPageId = null;
    state.fixAcknowledged = false;
  }
  updatePageSelection();
}
function currentPageSelection() {
  const ticket = state.detail,
    isFix = state.detailTab === "fix";
  const allCandidates = ticket?.unidentified_scan_pages || [];
  const candidates = isFix
    ? allCandidates.filter(
        (p) =>
          candidateCategory(p) === (state.fixCandidateFilter || "possible"),
      )
    : allCandidates;
  const index = isFix
    ? candidates.findIndex((p) => p.id === state.fixPageId)
    : state.pageIndex;
  const candidate = allCandidates.find((p) => p.id === state.fixPageId);
  const page = isFix
    ? candidate
      ? {
          ...candidate,
          paper: candidate.fields?.document_type || "Unidentified page",
          copy: candidate.fields?.copy,
          extracted: candidate.identifier,
          matched: false,
        }
      : null
    : ticket?.pages[index];
  return { ticket, isFix, candidates, index, page };
}
function moveSelectedImage(delta) {
  const { ticket, isFix, candidates, index } = currentPageSelection();
  if (state.approvingPage) return;
  if (isFix) {
    if (candidates[index + delta]) chooseFixImage(candidates[index + delta].id);
  } else if (ticket.pages[index + delta]) {
    state.pageIndex += delta;
    updatePageSelection();
  }
}
function selectionCaption(page, isFix) {
  return el(
    "div",
    { class: "preview-caption" },
    icon("scan"),
    el(
      "span",
      {},
      `Source page ${page.source_page} · ${page.copy || "Original"} copy`,
    ),
    badge(
      page.manually_approved
        ? "Manually linked"
        : isFix
          ? "Unassigned image"
          : page.matched
            ? "Verified page"
            : "Needs review",
      page.manually_approved || page.matched ? "green" : "neutral",
      page.manually_approved || page.matched ? "check" : "clock",
    ),
  );
}
function updatePageSelection() {
  if (!state.detail || !document.querySelector(".detail-drawer")) return;
  const { ticket, isFix, candidates, index, page } = currentPageSelection();
  document.querySelectorAll(".evidence-row").forEach((node) => {
    const selected = Number(node.dataset.pageIndex) === state.pageIndex;
    node.classList.toggle("selected", selected);
    node.setAttribute("aria-pressed", String(selected));
  });
  document.querySelectorAll(".fix-thumbnail").forEach((node) => {
    const selected = node.dataset.sourceId === state.fixPageId;
    node.classList.toggle("selected", selected);
    node.setAttribute("aria-pressed", String(selected));
  });
  const title = document.querySelector(
    ".preview-toolbar > div:first-child strong",
  );
  if (title) title.textContent = page?.paper || "Document preview";
  const pagination = document.querySelector(".preview-pagination > span");
  if (pagination)
    pagination.textContent = isFix
      ? page
        ? `Source page ${page.source_page} · ${index + 1} / ${candidates.length}`
        : "Select an image"
      : page?.printed_page
        ? `Page ${page.printed_page} / ${ticket.expected_pages}`
        : `${index + 1} / ${ticket.pages.length}`;
  const prev = document.querySelector('[aria-label="Previous ticket page"]');
  const next = document.querySelector('[aria-label="Next ticket page"]');
  if (prev) prev.disabled = index <= 0 || !!state.approvingPage;
  if (next)
    next.disabled =
      index < 0 ||
      index >= (isFix ? candidates.length : ticket.pages.length) - 1 ||
      !!state.approvingPage;
  const preview = document.querySelector(".detail-preview");
  if (preview && page) {
    preview.querySelector(".paper-stage")?.removeAttribute("hidden");
    const emptyPreview = preview.querySelector(".empty-state");
    if (emptyPreview) emptyPreview.hidden = true;
    let image = preview.querySelector(".paper-image");
    if (!image) {
      image = el("img", { class: "paper-image" });
      const stage = el("div", { class: "paper-stage" }, image);
      const placeholder = preview.querySelector(".empty-state");
      if (placeholder) placeholder.replaceWith(stage);
      else preview.append(stage);
    }
    const src = `${base()}/pages/${page.id}/preview`;
    if (image.getAttribute("src") !== src) image.setAttribute("src", src);
    image.alt = isFix
      ? `Unidentified source page ${page.source_page}`
      : `${page.paper}, ${page.copy || ""} copy, ${ticket.work_order}, page ${page.printed_page || page.number || index + 1}`;
    const caption = selectionCaption(page, isFix);
    if (preview.querySelector(".preview-caption"))
      preview.querySelector(".preview-caption").replaceWith(caption);
    else preview.append(caption);
  } else if (preview && isFix) {
    if (preview.querySelector(".paper-stage"))
      preview.querySelector(".paper-stage").hidden = true;
    if (preview.querySelector(".preview-caption"))
      preview.querySelector(".preview-caption").hidden = true;
    let placeholder = preview.querySelector(".empty-state");
    if (!placeholder) {
      placeholder = empty(
        "Select an image",
        "Possible matches need review. Different images stay unassigned.",
      );
      preview.append(placeholder);
    }
    placeholder.hidden = false;
  }
  const reviewRegion = document.querySelector("#selected-page-review");
  if (reviewRegion) {
    const expanded = reviewRegion.querySelector(".page-fields-panel")?.open;
    const reviewContent = selectedPageReview(page, isFix);
    const details = reviewContent.querySelector(".page-fields-panel");
    if (details && expanded) details.open = true;
    reviewRegion.replaceChildren(reviewContent);
  }
  updateApprovalControls();
  updateCandidateFilter();
}
function pageFixer(ticket) {
  const candidates = ticket.unidentified_scan_pages || [];
  const gaps = ticket.unaccounted_pages || ticket.missing_pages || [];
  const content = el(
    "div",
    { class: "page-fixer" },
    el(
      "h3",
      {},
      ticket.parent_rental_number
        ? `${ticket.parent_rental_number} → ${ticket.work_order}`
        : `Complete ${ticket.work_order}`,
    ),
    el(
      "p",
      { class: "muted" },
      "Choose an image, compare its fields, then link it to the missing page.",
    ),
    el(
      "div",
      { class: "fix-target" },
      el(
        "strong",
        {},
        `${ticket.work_order} · ${ticket.customer.replace(/^Demo\s+/i, "")}`,
      ),
      el("p", {}, ticket.billing_address || "Address not recorded"),
    ),
  );
  const gallery = el("div", {
    class: "fix-gallery",
    "aria-label": "Unidentified image notebook",
  });
  content.append(
    el(
      "div",
      {
        class: "candidate-filters",
        role: "group",
        "aria-label": "Candidate images",
      },
      ...["possible", "different"].map((key) =>
        el(
          "button",
          {
            class: "button secondary",
            type: "button",
            "data-candidate-filter": key,
            onClick: () => setCandidateFilter(key),
          },
          key === "possible" ? "Possible matches" : "Different images",
        ),
      ),
    ),
  );
  content.append(
    el("p", { id: "candidate-empty", class: "candidate-empty", hidden: true }),
  );
  for (const page of candidates)
    gallery.append(
      el(
        "button",
        {
          type: "button",
          class: `fix-thumbnail ${page.id === state.fixPageId ? "selected" : ""}`,
          "aria-label": `Select source page ${page.source_page}`,
          "aria-pressed": page.id === state.fixPageId,
          "data-source-id": page.id,
          disabled: state.approvingPage || false,
          onClick: () => chooseFixImage(page.id),
          onKeydown: (event) => {
            if (!["ArrowLeft", "ArrowRight"].includes(event.key)) return;
            event.preventDefault();
            const visible = currentPageSelection().candidates;
            const index = visible.findIndex((p) => p.id === page.id);
            const next = visible[index + (event.key === "ArrowLeft" ? -1 : 1)];
            if (next) {
              chooseFixImage(next.id);
              [...document.querySelectorAll(".fix-thumbnail")]
                .find((node) => node.dataset.sourceId === next.id)
                ?.focus({ preventScroll: true });
            }
          },
        },
        el("img", {
          src: `${base()}/pages/${page.id}/preview`,
          alt: `Unidentified source page ${page.source_page}`,
          loading: "lazy",
        }),
        el("strong", {}, `Source page ${page.source_page}`),
        el("small", { class: "candidate-status" }),
        el(
          "small",
          {},
          page.identifier
            ? `OCR read ${page.identifier}`
            : "No readable identifier",
        ),
        page.fields?.customer ? el("small", {}, page.fields.customer) : null,
      ),
    );
  content.append(gallery);
  const upload = el("input", {
    type: "file",
    accept: "application/pdf,.pdf",
    multiple: true,
    class: "intake-file-input",
    "aria-label": "Upload missing page PDFs",
    onChange: async (event) => {
      await uploadIntakeFiles(event.target.files);
      const status = document.querySelector("#fix-upload-status");
      if (status) status.textContent = state.uploadMessage;
    },
  });
  content.append(
    el(
      "div",
      { class: "fix-upload" },
      upload,
      button(
        "Upload missing pages",
        () => upload.click(),
        "button secondary",
        "upload",
      ),
      el("small", { id: "fix-upload-status", role: "status" }),
    ),
  );
  if (!candidates.length)
    content.append(
      el(
        "p",
        {},
        "There are no unidentified images available in this scan to assign.",
      ),
    );
  const select = el(
    "select",
    {
      "aria-label": "Assign as printed page",
      disabled: state.approvingPage || false,
      onChange: (event) => {
        state.fixPrintedPage = Number(event.target.value);
        state.fixAcknowledged = false;
        updatePageSelection();
      },
    },
    ...gaps.map((number) =>
      el(
        "option",
        { value: number, selected: number === state.fixPrintedPage },
        `Printed page ${number} of ${ticket.expected_pages}`,
      ),
    ),
  );
  content.append(
    el(
      "label",
      { class: "fix-page-select" },
      "Assign the selected image as",
      select,
    ),
  );
  const chosen = candidates.find((p) => p.id === state.fixPageId);
  content.append(
    el("div", { id: "selected-page-review" }, selectedPageReview(chosen)),
  );
  content.append(
    el(
      "label",
      { id: "fix-acknowledgment", class: "fix-acknowledgment", hidden: true },
      el("input", {
        type: "checkbox",
        checked: !!state.fixAcknowledged,
        onChange: (event) => {
          state.fixAcknowledged = event.target.checked;
          updateApprovalControls();
        },
      }),
      el("span", {}),
    ),
  );
  const approve = button(
    state.approvingPage
      ? "Approving…"
      : chosen
        ? `Link source ${chosen.source_page} → ${ticket.work_order} · page ${state.fixPrintedPage}`
        : "Select an image to approve",
    approveFixPage,
    "button primary",
    "check",
  );
  approve.disabled =
    !!state.approvingPage ||
    !chosen ||
    !gaps.includes(state.fixPrintedPage) ||
    ticket.processing;
  approve.id = "approve-page";
  content.append(
    approve,
    el(
      "p",
      { class: "muted fix-approval-note" },
      "Approval adds this original image to the order and records a manual decision. The OCR result and source PDF remain unchanged.",
    ),
  );
  if (ticket.processing)
    content.append(
      el("p", {}, "Wait for this scan to finish before approving a page."),
    );
  content.append(
    el(
      "p",
      {
        id: "fix-error",
        role: "alert",
        class: "fix-error",
        hidden: !state.fixError,
      },
      state.fixError || "",
    ),
  );
  return content;
}
async function approveFixPage() {
  if (state.approvingPage || !state.detail || !state.fixPageId) return;
  updateApprovalControls();
  if (document.querySelector("#approve-page")?.disabled) return;
  const id = state.detail.id;
  const originalDetail = state.detail;
  const printed = state.fixPrintedPage;
  state.approvingPage = true;
  state.fixError = "";
  updateApprovalControls();
  try {
    await api(`${base()}/tickets/${id}/page-approvals`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        page_id: state.fixPageId,
        printed_page: printed,
        ...(state.fixAcknowledged ? { acknowledge_differences: true } : {}),
      }),
    });
    const updated = await api(`${base()}/tickets/${id}`);
    if (state.detail?.id === id) {
      state.detail = updated;
      state.fixPrintedPage =
        updated.unaccounted_pages?.[0] || updated.missing_pages?.[0] || null;
      state.detailTab =
        updated.unidentified_scan_pages?.length &&
        updated.unaccounted_pages?.length
          ? "fix"
          : "ocr";
      state.pageIndex = Math.max(
        0,
        updated.pages.findIndex((p) => p.printed_page === printed),
      );
      state.fixPageId = null;
      state.fixAcknowledged = false;
    }
    await loadView();
    toast(
      isReadyOrder(updated)
        ? "Page approved. Order ready to download."
        : "Page approved. More pages still need attention.",
    );
  } catch (error) {
    state.fixError = error.message;
  } finally {
    state.approvingPage = false;
    if (state.detail?.id === id) {
      if (state.detail !== originalDetail) renderDetail();
      else updateApprovalControls();
    }
  }
}
function renderDetail(initial = false) {
  const t = state.detail;
  if (!t) return;
  const oldLeft = overlay.querySelector(".detail-left");
  const scroll = state.detailScroll || (state.detailScroll = {});
  if (oldLeft) scroll[oldLeft.dataset.detailTab] = oldLeft.scrollTop;
  const oldStage = overlay.querySelector(".paper-stage");
  const stageScroll = {
    top: oldStage?.scrollTop || 0,
    left: oldStage?.scrollLeft || 0,
  };
  const focused = overlay.contains(document.activeElement)
    ? document.activeElement
    : null;
  const focusedLabel = focused?.getAttribute("aria-label"),
    focusedId = focused?.id;
  const isFix = state.detailTab === "fix";
  const candidates = t.unidentified_scan_pages || [];
  const candidateIndex = candidates.findIndex((p) => p.id === state.fixPageId);
  const candidate = candidates[candidateIndex];
  const page = isFix
    ? candidate
      ? {
          ...candidate,
          paper: candidate.fields?.document_type || "Unidentified page",
          copy: candidate.fields?.copy,
          extracted: candidate.identifier,
          matched: false,
        }
      : null
    : t.pages[state.pageIndex];
  const close = button("", closeDetail, "icon-button", "close");
  close.setAttribute("aria-label", "Close work order");
  const review = button(
    t.reviewed ? "Reviewed" : "Mark reviewed",
    toggleReview,
    t.reviewed ? "button success" : "button primary",
    "check",
  );
  review.id = "review-toggle";
  const dl =
    t.ocr_status === "verified"
      ? ticketDownloadControl(t, "Download ticket", "button secondary")
      : el(
          "button",
          { class: "button secondary", disabled: true },
          "Waiting for verified pages",
        );
  const prev = button(
    "",
    () => {
      moveSelectedImage(-1);
    },
    "icon-button",
    "left",
  );
  prev.disabled = isFix ? candidateIndex <= 0 : state.pageIndex === 0;
  prev.setAttribute("aria-label", "Previous ticket page");
  const next = button(
    "",
    () => {
      moveSelectedImage(1);
    },
    "icon-button",
    "chevron",
  );
  next.disabled = isFix
    ? candidateIndex < 0 || candidateIndex >= candidates.length - 1
    : state.pageIndex >= t.pages.length - 1;
  next.setAttribute("aria-label", "Next ticket page");
  const drawer = el(
    "section",
    {
      class: "detail-drawer",
      role: "dialog",
      "aria-modal": "true",
      "aria-labelledby": "detail-title",
    },
    el(
      "div",
      { class: "drawer-toolbar" },
      el("span", {}, "Order Tracker", icon("chevron"), t.work_order),
      close,
    ),
    el(
      "div",
      { class: "drawer-heading" },
      el(
        "div",
        {},
        el(
          "div",
          { class: "detail-kicker" },
          t.work_order?.startsWith("OD-") ? "ORDER" : "WORK ORDER",
        ),
        el("h2", { id: "detail-title" }, t.work_order),
        el("p", {}, t.customer),
      ),
      el(
        "div",
        { class: "drawer-heading-actions" },
        badge(
          isReadyOrder(t)
            ? "Ready to download"
            : t.processing
              ? "Processing"
              : t.missing_pages?.length
                ? "Incomplete"
                : "Needs review",
          isReadyOrder(t) ? "green" : "amber",
          t.ocr_status === "verified" ? "shield" : "scan",
        ),
        review,
      ),
    ),
    el(
      "div",
      { class: "drawer-body" },
      el(
        "div",
        { class: "detail-left", "data-detail-tab": state.detailTab },
        el(
          "div",
          { class: "detail-tabs" },
          ...[
            "details",
            "ocr",
            ...(state.view === "flags" &&
            candidates.length &&
            t.missing_pages?.length
              ? ["fix"]
              : []),
          ].map((key) =>
            button(
              key === "details"
                ? "Order details"
                : key === "fix"
                  ? "Fix pages"
                  : "OCR results",
              () => {
                state.detailTab = key;
                renderDetail();
                document
                  .querySelector(".detail-tab.active")
                  ?.focus({ preventScroll: true });
              },
              `detail-tab ${state.detailTab === key ? "active" : ""}`,
              key === "details" ? "file" : "scan",
            ),
          ),
        ),
        state.detailTab === "details"
          ? detailInfo(t)
          : isFix
            ? pageFixer(t)
            : ocrInfo(t),
      ),
      el(
        "div",
        { class: "detail-preview" },
        el(
          "div",
          { class: "preview-toolbar" },
          el(
            "div",
            {},
            icon("file"),
            el("strong", {}, page?.paper || "Document preview"),
          ),
          el(
            "div",
            { class: "preview-pagination" },
            prev,
            el(
              "span",
              {},
              isFix
                ? candidate
                  ? `Source page ${candidate.source_page} · ${candidateIndex + 1} / ${candidates.length}`
                  : "Select an image"
                : page?.printed_page
                  ? `Page ${page.printed_page} / ${t.expected_pages}`
                  : `${state.pageIndex + 1} / ${t.pages.length}`,
            ),
            next,
          ),
        ),
        page
          ? el(
              "div",
              { class: "paper-stage" },
              el("img", {
                class: "paper-image",
                src: `${base()}/pages/${page.id}/preview`,
                alt: isFix
                  ? `Unidentified source page ${page.source_page}`
                  : `${page.paper}, ${page.copy || ""} copy, ${t.work_order}, page ${page.printed_page || page.number || state.pageIndex + 1}`,
              }),
            )
          : empty(
              isFix ? "Select an unidentified image" : "No pages available",
              isFix
                ? "Choose a thumbnail in the image notebook to compare it with this order."
                : "This work order has no registered documents.",
            ),
        page
          ? el(
              "div",
              { class: "preview-caption" },
              icon("scan"),
              el(
                "span",
                {},
                `Source page ${page.source_page} · ${page.copy || "Original"} copy`,
              ),
              badge(
                page.manually_approved
                  ? "Manually linked"
                  : isFix
                    ? "Unassigned image"
                    : page.matched
                      ? "Verified page"
                      : "Needs review",
                page.manually_approved || page.matched ? "green" : "neutral",
                page.manually_approved || page.matched ? "check" : "clock",
              ),
            )
          : null,
      ),
    ),
    el(
      "div",
      { class: "drawer-footer" },
      el("span", {}, icon("shield"), "Original document preserved"),
      dl,
    ),
  );
  overlay.replaceChildren(
    el("div", { class: "drawer-backdrop", onClick: closeDetail }),
    drawer,
  );
  const left = overlay.querySelector(".detail-left");
  if (left) left.scrollTop = scroll[state.detailTab] || 0;
  const stage = overlay.querySelector(".paper-stage");
  if (stage) {
    stage.scrollTop = stageScroll.top;
    stage.scrollLeft = stageScroll.left;
  }
  updatePageSelection();
  if (initial) close.focus({ preventScroll: true });
  else if (focused) {
    const replacement = [
      ...overlay.querySelectorAll("button, input, select, a"),
    ].find(
      (node) =>
        (focusedId && node.id === focusedId) ||
        (focusedLabel && node.getAttribute("aria-label") === focusedLabel),
    );
    replacement?.focus({ preventScroll: true });
  }
}
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape") closeDetail();
  if (
    event.key === "/" &&
    !["INPUT", "TEXTAREA", "SELECT"].includes(document.activeElement.tagName) &&
    !state.detail
  ) {
    const input = $("input[type=search]");
    if (input) {
      event.preventDefault();
      input.focus();
    }
  }
  if (event.key === "Tab" && state.detail) {
    const focusable = [
      ...overlay.querySelectorAll(
        'button:not(:disabled),a[href],input,select,[tabindex="0"]',
      ),
    ];
    const first = focusable[0],
      last = focusable.at(-1);
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  }
});
window.addEventListener("hashchange", () => {
  const view = location.hash.slice(2);
  if (view === "documents" || view === "review") {
    navigate(view === "documents" ? "tickets" : "flags");
    return;
  }
  if (navItems.some((n) => n[0] === view) && state.view !== view)
    navigate(view);
});
$("#menu-toggle").addEventListener("click", () =>
  $("#sidebar").classList.toggle("open"),
);
async function boot() {
  try {
    const result = await api("/api/datasets");
    state.datasets = result.datasets;
    if (!state.datasets.length)
      throw new Error(
        "Prepare a synthetic dataset before opening the workspace.",
      );
    const saved = localStorage.getItem("ocr-dataset");
    state.dataset = state.datasets.some((d) => d.id === saved)
      ? saved
      : result.default;
    const route = location.hash.slice(2);
    state.view =
      route === "documents"
        ? "tickets"
        : route === "review"
          ? "flags"
          : navItems.some((n) => n[0] === route)
            ? route
            : "ocr";
    if (["documents", "review"].includes(route))
      history.replaceState(
        null,
        "",
        route === "documents" ? "#/tickets" : "#/flags",
      );
    await loadView();
    connectLiveProgress();
  } catch (error) {
    main.replaceChildren(
      empty(
        "Your workspace is not ready",
        error.message,
        button("Try again", boot, "button primary", "refresh"),
      ),
    );
  }
}
boot();
