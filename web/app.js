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
const navItems = [
  ["overview", "Overview", "grid"],
  ["tickets", "Order Tracker", "orders"],
  ["documents", "Documents", "file"],
  ["ocr", "OCR activity", "scan"],
  ["review", "Review queue", "circlecheck"],
  ["imports", "Ingestion history", "clock"],
];
function navigate(view) {
  state.view = view;
  state.page = 1;
  state.query = "";
  state.filter = "all";
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
        key === "review" && state.summary.review_queue
          ? el("span", { class: "nav-count" }, state.summary.review_queue)
          : null,
      ),
    ),
  );
  $("#breadcrumb-title").textContent =
    navItems.find((n) => n[0] === state.view)?.[1] || "Order Tracker";
}
function datasetControl() {
  return el(
    "label",
    { class: "dataset-control" },
    icon("grid"),
    el(
      "select",
      {
        "aria-label": "Dataset",
        onChange: (event) => {
          state.dataset = event.target.value;
          localStorage.setItem("ocr-dataset", state.dataset);
          state.page = 1;
          state.documentFilter = "";
          closeDetail();
          loadView();
        },
      },
      state.datasets.map((d) =>
        el(
          "option",
          { value: d.id, selected: d.id === state.dataset },
          d.label,
        ),
      ),
    ),
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
function summaryCards() {
  const s = state.summary;
  return el(
    "div",
    { class: "summary-grid" },
    ...[
      [
        "Registered orders",
        s.tickets,
        "orders",
        "neutral",
        "Across this workspace",
      ],
      [
        "OCR verified",
        s.verified_tickets,
        "circlecheck",
        "green",
        `${s.verified_pages} pages matched`,
      ],
      [
        "Awaiting OCR",
        s.tickets - s.verified_tickets,
        "scan",
        "amber",
        "Ready for processing",
      ],
      ["To review", s.review_queue, "eye", "blue", "Awaiting a human review"],
    ].map(([label, value, glyph, tone, note]) =>
      el(
        "article",
        { class: "summary-card" },
        el(
          "div",
          { class: "summary-label" },
          label,
          el("span", { class: `metric-icon ${tone}` }, icon(glyph)),
        ),
        el("div", { class: "summary-value" }, value ?? "—"),
        el(
          "div",
          { class: `summary-note ${tone === "green" ? "positive" : ""}` },
          tone === "green" ? icon("check") : null,
          note,
        ),
      ),
    ),
  );
}
function exportTickets() {
  const cols = [
    "Work order",
    "Shipment",
    "Customer",
    "Delivery location",
    "Billing address",
    "Status",
    "OCR verified pages",
    "Total pages",
    "Reviewed",
  ];
  const rows = state.tickets.map((t) => [
    t.work_order,
    t.shipment,
    t.customer,
    t.delivery_location,
    t.billing_address,
    t.status,
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
function ocrBadge(ticket) {
  return el(
    "div",
    { class: "ocr-cell" },
    badge(
      ticket.ocr_status === "verified"
        ? "Verified"
        : ticket.ocr_status === "partial"
          ? "In progress"
          : "Awaiting OCR",
      ticket.ocr_status === "verified"
        ? "green"
        : ticket.ocr_status === "partial"
          ? "blue"
          : "neutral",
      ticket.ocr_status === "verified" ? "check" : "scan",
    ),
    el(
      "small",
      {},
      `${ticket.verified_pages} of ${ticket.expected_pages} pages matched`,
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
          el("strong", {}, ticket.customer),
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
        "Work order",
        "Customer & location",
        "Address",
        "Order status",
        "OCR result",
        "Due date",
        "",
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
  const review = state.view === "review";
  main.replaceChildren(
    heading(
      review ? "Review queue" : "Order Tracker",
      review
        ? "Give every verified ticket a final human check."
        : "Every work order, document, and OCR result. In one place.",
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
        el("h2", {}, review ? "Waiting for review" : "Work orders"),
        el(
          "span",
          { class: "panel-subtitle" },
          "Source records, organized and connected.",
        ),
      ),
      el(
        "div",
        { class: "panel-heading-right" },
        badge(
          state.summary.verified_pages ? "Azure verified" : "Demo data",
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
      tabButton("OCR verified", "verified", state.summary.verified_tickets),
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
      "Synthetic documents. Azure results shown separately from expected page mappings.",
    ),
  );
}
function query() {
  const p = new URLSearchParams();
  if (state.query) p.set("q", state.query);
  if (state.status !== "all") p.set("status", state.status);
  if (["verified", "pending"].includes(state.filter))
    p.set("ocr", state.filter);
  if (state.view === "review") p.set("review", "pending");
  if (state.documentFilter) p.set("document_id", state.documentFilter);
  return p;
}
async function getTickets() {
  const filter = state.filter;
  const result = await api(`${base()}/tickets?${query()}`);
  return filter === "reviewed"
    ? result.tickets.filter((t) => t.reviewed)
    : result.tickets;
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
    if (generation !== state.request) return;
    navigation();
    if (["tickets", "review"].includes(state.view)) {
      const tickets = await getTickets();
      if (generation === state.request) {
        state.tickets = tickets;
        orderTracker();
      }
    } else if (state.view === "overview") {
      const tickets = await getTickets();
      if (generation === state.request) {
        state.tickets = tickets;
        overview();
      }
    } else if (state.view === "documents") {
      const data = await api(`${base()}/documents`);
      if (generation === state.request) documents(data.documents);
    } else if (state.view === "ocr") {
      const data = await api(`${base()}/activity`);
      if (generation === state.request) activity(data.activity);
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
  const s = state.summary;
  main.replaceChildren(
    heading(
      "A clear view of your documents.",
      "Track the journey from a scanned page to a verified work order.",
      [
        datasetControl(),
        button(
          "Open Order Tracker",
          () => navigate("tickets"),
          "button primary",
          "arrow",
        ),
      ],
    ),
    summaryCards(),
  );
  const coverage = s.pages ? Math.round((s.verified_pages / s.pages) * 100) : 0;
  const coveragePanel = el(
    "section",
    { class: "panel coverage-panel" },
    el(
      "div",
      { class: "section-heading" },
      el("h2", {}, "OCR verification"),
      badge(
        s.verified_pages ? "Verified with Azure" : "Ready to process",
        s.verified_pages ? "green" : "neutral",
        "shield",
      ),
    ),
    el(
      "div",
      { class: "coverage-content" },
      el(
        "div",
        { class: "coverage-ring", style: { "--coverage": `${coverage}%` } },
        el(
          "div",
          {},
          el("strong", {}, `${coverage}%`),
          el("small", {}, "pages matched"),
        ),
      ),
      el(
        "div",
        {},
        el("h3", {}, `${s.verified_pages} pages, connected.`),
        el(
          "p",
          {},
          `${s.documents} source documents. ${s.tickets} organized work orders. Every matched page links back to its original document.`,
        ),
        el(
          "small",
          { class: "muted" },
          s.last_verified_at
            ? `Last verified ${time(s.last_verified_at)}`
            : "No live OCR attempts yet.",
        ),
      ),
    ),
  );
  const actions = [
    [
      "orders",
      "Browse work orders",
      "Find a ticket by customer, address, or order number.",
      "tickets",
    ],
    [
      "eye",
      "Review matched tickets",
      `${s.review_queue} tickets are waiting for a human review.`,
      "review",
    ],
    [
      "scan",
      "Inspect OCR activity",
      "See what Azure extracted from each page.",
      "ocr",
    ],
  ];
  const quickPanel = el(
    "section",
    { class: "panel quick-panel" },
    el("h2", {}, "Your next steps"),
  );
  for (const [glyph, title, description, view] of actions) {
    quickPanel.append(
      el(
        "button",
        { class: "quick-action", onClick: () => navigate(view) },
        el("span", { class: "quick-icon" }, icon(glyph)),
        el("span", {}, el("strong", {}, title), el("small", {}, description)),
        icon("chevron"),
      ),
    );
  }
  main.append(el("div", { class: "overview-grid" }, coveragePanel, quickPanel));
  const recent = el("div", { class: "recent-list" });
  for (const ticket of state.tickets.slice(0, 5)) {
    recent.append(
      el(
        "button",
        { class: "recent-row", onClick: () => openDetail(ticket.id) },
        el("span", { class: "document-glyph" }, icon("file")),
        el(
          "span",
          {},
          el("strong", { class: "mono" }, ticket.work_order),
          el("small", {}, ticket.customer),
        ),
        el("span", { class: "recent-location" }, ticket.delivery_location),
        ocrBadge(ticket),
        icon("chevron"),
      ),
    );
  }
  main.append(
    el(
      "section",
      { class: "panel recent-panel" },
      el(
        "div",
        { class: "section-heading" },
        el("h2", {}, "Recent work orders"),
        button("View all", () => navigate("tickets"), "text-button", "arrow"),
      ),
      recent,
    ),
  );
}
function documents(rows) {
  main.replaceChildren(
    heading("Documents", "The original files behind your work orders.", [
      datasetControl(),
    ]),
  );
  if (!rows.length) {
    main.append(
      empty(
        "No documents registered",
        "Prepare a synthetic dataset to see its files here.",
      ),
    );
    return;
  }
  main.append(
    el(
      "div",
      { class: "document-grid" },
      rows.map((doc) =>
        el(
          "article",
          { class: "panel document-card" },
          el(
            "div",
            { class: "document-thumbnail" },
            doc.first_page_id
              ? el("img", {
                  src: `${base()}/pages/${doc.first_page_id}/preview`,
                  alt: `First page of ${doc.name}`,
                  loading: "lazy",
                })
              : icon("file"),
            badge("PDF", "neutral"),
          ),
          el(
            "div",
            { class: "document-card-body" },
            el("h3", {}, doc.name),
            el("p", {}, `${doc.pages} pages · Synthetic ticket batch`),
            el(
              "div",
              { class: "document-card-footer" },
              badge("Registered", "green", "check"),
              button(
                "View orders",
                () => {
                  state.query = "";
                  state.documentFilter = doc.id;
                  state.filter = "all";
                  state.status = "all";
                  state.view = "tickets";
                  state.page = 1;
                  location.hash = "/tickets";
                  loadView();
                },
                "text-button",
                "arrow",
              ),
            ),
          ),
        ),
      ),
    ),
  );
}
function activity(rows) {
  main.replaceChildren(
    heading("OCR activity", "A page-by-page record of what Azure found.", [
      datasetControl(),
      button("Refresh", loadView, "button secondary", "refresh"),
    ]),
  );
  const panel = el(
    "section",
    { class: "panel activity-panel" },
    el(
      "div",
      { class: "section-heading" },
      el("h2", {}, "Processing history"),
      badge(`${rows.length} recent attempts`),
    ),
  );
  if (!rows.length)
    panel.append(
      empty(
        "No OCR activity yet",
        "Manifest expectations are available, but no pages have been sent to Azure.",
      ),
    );
  else
    panel.append(
      el(
        "div",
        { class: "table-scroll" },
        el(
          "table",
          { class: "orders-table activity-table" },
          el(
            "thead",
            {},
            el(
              "tr",
              {},
              ...[
                "Extracted shipment",
                "Source document",
                "Page",
                "Result",
                "Processed",
              ].map((h) => el("th", { scope: "col" }, h)),
            ),
          ),
          el(
            "tbody",
            {},
            rows.map((row) =>
              el(
                "tr",
                {},
                el(
                  "td",
                  {},
                  el(
                    "strong",
                    { class: "mono" },
                    row.identifier || "No identifier",
                  ),
                ),
                el("td", {}, row.document),
                el("td", {}, row.page),
                el(
                  "td",
                  {},
                  badge(
                    row.status === "success"
                      ? "Matched"
                      : row.status.replaceAll("_", " "),
                    row.status === "success"
                      ? "green"
                      : row.status === "error"
                        ? "red"
                        : "neutral",
                    row.status === "success" ? "check" : null,
                  ),
                ),
                el("td", { class: "muted" }, time(row.at)),
              ),
            ),
          ),
        ),
      ),
    );
  main.append(panel);
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
async function openDetail(id) {
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
    state.detailTab = "details";
    renderDetail();
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
function detailInfo(ticket) {
  const grid = el(
    "dl",
    { class: "detail-grid" },
    field("Work order", ticket.work_order, "mono-value"),
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
  const matched = ticket.pages.filter((p) => p.matched).length;
  return el(
    "div",
    { class: "ocr-information" },
    el(
      "div",
      {
        class: `ocr-summary ${matched === ticket.pages.length && matched ? "complete" : ""}`,
      },
      icon(matched === ticket.pages.length && matched ? "circlecheck" : "scan"),
      el("strong", {}, `${matched} of ${ticket.pages.length} pages matched`),
      el(
        "p",
        {},
        matched
          ? "Shipment IDs returned by Azure match the expected ticket."
          : "These pages have not all been verified through Azure.",
      ),
    ),
    el("h3", { class: "detail-section-title" }, "Page-level evidence"),
    ...ticket.pages.map((page, index) =>
      el(
        "button",
        {
          class: `evidence-row ${index === state.pageIndex ? "selected" : ""}`,
          onClick: () => {
            state.pageIndex = index;
            renderDetail();
          },
        },
        el("span", { class: "page-number" }, index + 1),
        el(
          "span",
          { class: "evidence-copy" },
          el("strong", {}, page.paper),
          el("small", {}, page.copy ? `${page.copy} copy` : "Source page"),
        ),
        el(
          "span",
          { class: "evidence-values" },
          el("small", {}, `Expected ${page.expected}`),
          el("strong", { class: "mono" }, page.extracted || "Not processed"),
        ),
        el(
          "span",
          { class: `evidence-status ${page.matched ? "positive" : ""}` },
          icon(page.matched ? "check" : "clock"),
        ),
      ),
    ),
    el(
      "p",
      { class: "evidence-note" },
      "OCR verifies the shipment identifier. Addresses and equipment details are source data, not OCR-extracted fields.",
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
function renderDetail() {
  const t = state.detail;
  if (!t) return;
  const page = t.pages[state.pageIndex];
  const close = button("", closeDetail, "icon-button", "close");
  close.setAttribute("aria-label", "Close work order");
  const review = button(
    t.reviewed ? "Reviewed" : "Mark reviewed",
    toggleReview,
    t.reviewed ? "button success" : "button primary",
    "check",
  );
  review.id = "review-toggle";
  const dl = el(
    "a",
    { class: "button secondary", href: `${base()}/tickets/${t.id}/download` },
    icon("down"),
    "Download ticket",
  );
  const prev = button(
    "",
    () => {
      state.pageIndex--;
      renderDetail();
    },
    "icon-button",
    "left",
  );
  prev.disabled = state.pageIndex === 0;
  prev.setAttribute("aria-label", "Previous ticket page");
  const next = button(
    "",
    () => {
      state.pageIndex++;
      renderDetail();
    },
    "icon-button",
    "chevron",
  );
  next.disabled = state.pageIndex >= t.pages.length - 1;
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
        el("div", { class: "detail-kicker" }, "WORK ORDER"),
        el("h2", { id: "detail-title" }, t.work_order),
        el("p", {}, t.customer),
      ),
      el(
        "div",
        { class: "drawer-heading-actions" },
        badge(
          t.ocr_status === "verified" ? "OCR verified" : "Awaiting OCR",
          t.ocr_status === "verified" ? "green" : "neutral",
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
        { class: "detail-left" },
        el(
          "div",
          { class: "detail-tabs" },
          ...["details", "ocr"].map((key) =>
            button(
              key === "details" ? "Order details" : "OCR results",
              () => {
                state.detailTab = key;
                renderDetail();
              },
              `detail-tab ${state.detailTab === key ? "active" : ""}`,
              key === "details" ? "file" : "scan",
            ),
          ),
        ),
        state.detailTab === "details" ? detailInfo(t) : ocrInfo(t),
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
            el("span", {}, `${state.pageIndex + 1} / ${t.pages.length}`),
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
                alt: `${page.paper}, ${page.copy || ""} copy, ${t.work_order}, page ${state.pageIndex + 1}`,
              }),
            )
          : empty(
              "No pages available",
              "This work order has no registered documents.",
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
                page.matched
                  ? `Matched ${page.extracted}`
                  : page.ocr_status.replaceAll("_", " "),
                page.matched ? "green" : "neutral",
                page.matched ? "check" : "clock",
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
  close.focus({ preventScroll: true });
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
    state.view = navItems.some((n) => n[0] === route) ? route : "tickets";
    await loadView();
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
