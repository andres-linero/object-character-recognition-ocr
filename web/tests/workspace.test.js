import { test } from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { JSDOM } from "jsdom";
const html = await readFile(new URL("../index.html", import.meta.url), "utf8");
const script = await readFile(new URL("../app.js", import.meta.url), "utf8");
const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
const tickets = Array.from({ length: 20 }, (_, i) => ({
  id: `ticket-${i}`,
  work_order: `W-${990120 - i}`,
  shipment: String(900120 - i),
  rental_order: `RA-${700120 - i}`,
  customer:
    i === 0 ? "Demo <script>alert(1)</script> Builder" : `Demo Customer ${i}`,
  delivery_location: `Demo Depot ${i + 1}`,
  billing_address: `${200 + i} Simulation Way, Demo City`,
  status: i % 5 === 0 ? "COMPLETE" : "OPEN",
  order_date: "2030-04-01",
  due_date: "2030-04-10",
  assigned_to: "Dispatch Desk",
  order_type: "RENTAL",
  expected_pages: 6,
  verified_pages: 6,
  ocr_status: "verified",
  reviewed: false,
}));
async function boot(hash = "") {
  const dom = new JSDOM(html, {
    url: `http://localhost:8700${hash}`,
    runScripts: "outside-only",
    pretendToBeVisual: true,
  });
  const calls = [];
  const progressStreams = [];
  dom.window.EventSource = class {
    constructor(url) {
      this.url = url;
      progressStreams.push(this);
    }
    close() {}
  };
  dom.window.fetch = async (path, options = {}) => {
    calls.push({ path, options });
    let data;
    const url = new URL(path, "http://localhost:8700");
    if (path === "/api/datasets")
      data = {
        datasets: [{ id: "validation", label: "Azure-verified batches" }],
        default: "validation",
      };
    else if (url.pathname.endsWith("/review")) data = { reviewed: true };
    else if (url.pathname.endsWith("/tickets")) {
      let rows = tickets.map((t) => ({ ...t }));
      const q = url.searchParams.get("q");
      if (q)
        rows = rows.filter((t) =>
          [t.work_order, t.customer, t.shipment, t.billing_address].some((v) =>
            v.includes(q),
          ),
        );
      if (url.searchParams.get("status"))
        rows = rows.filter((t) => t.status === url.searchParams.get("status"));
      data = { tickets: rows, total: rows.length };
    } else if (url.pathname.match(/\/tickets\/ticket-/)) {
      const ticket = tickets.find((t) => url.pathname.endsWith(t.id));
      data = {
        ...ticket,
        contact_email: "dispatch@example.test",
        items: [{ code: "DEMO-01", description: "Demo frame", quantity: 3 }],
        pages: Array.from({ length: 6 }, (_, i) => ({
          id: `page-${i}`,
          number: i + 1,
          source_page: 55 + i,
          paper:
            i < 2
              ? "Delivery Ticket"
              : i < 4
                ? "Rental Agreement"
                : "Delivery Acknowledgement",
          copy: i % 2 ? "Yellow" : "White",
          expected: ticket.shipment,
          extracted: ticket.shipment,
          ocr_status: "success",
          matched: true,
          processed_at: "2026-11-06T19:00:00Z",
        })),
      };
    } else if (url.pathname.endsWith("/documents"))
      data = {
        documents: [
          {
            id: "doc-1",
            name: "demo_batch.pdf",
            pages: 60,
            first_page_id: "page-1",
          },
        ],
      };
    else if (url.pathname.endsWith("/activity"))
      data = {
        files: 2,
        files_read: 1,
        current_scan: { file: "demo_batch.pdf", total: 60, completed: 30 },
        activity: [
          {
            id: "attempt-1",
            page_id: "page-1",
            matched_order: tickets[0],
            identifier: "900120",
            status: "success",
            page: 55,
            document: "demo_batch.pdf",
            at: "2026-11-06T19:00:00Z",
          },
        ],
      };
    else if (url.pathname.endsWith("/imports"))
      data = {
        imports: [
          {
            id: "run-1",
            started_at: "2026-11-06T19:00:00Z",
            rows_seen: 20,
            rows_loaded: 20,
            rows_rejected: 0,
            status: "success",
          },
        ],
      };
    else
      data = {
        tickets: 20,
        pages: 120,
        documents: 2,
        verified_tickets: 20,
        verified_pages: 120,
        review_queue: 20,
        rejected_rows: 0,
        last_verified_at: "2026-11-06T19:00:00Z",
      };
    return { ok: true, json: async () => data };
  };
  dom.window.eval(script);
  await wait(30);
  return {
    dom,
    window: dom.window,
    document: dom.window.document,
    calls,
    progressStreams,
  };
}
const findButton = (document, text) =>
  [...document.querySelectorAll("button")].find(
    (b) => b.textContent.trim() === text,
  );
test("Documents is removed and its old route opens Dataset", async () => {
  const { dom, document, calls } = await boot("#/documents");
  assert.equal(dom.window.location.hash, "#/tickets");
  assert.equal(document.querySelector("h1").textContent, "Order Tracker");
  assert.equal(document.querySelectorAll("#navigation button").length, 5);
  assert.equal(findButton(document, "Documents"), undefined);
  assert.ok(document.querySelector("tbody"));
  assert.equal(
    calls.some((call) => call.path.endsWith("/documents")),
    false,
  );
  dom.window.close();
});
test("restored tabs count files and show dataset context without test-stage choices", async () => {
  const { dom, document } = await boot();
  assert.equal(document.querySelector("h1").textContent, "Scan intake");
  assert.equal(document.querySelectorAll("#navigation button").length, 5);
  assert.deepEqual(
    [...document.querySelectorAll(".summary-value")].map((n) => n.textContent),
    ["2", "30 / 60", "1"],
  );
  assert.ok(document.querySelector('[aria-label="Dataset"]'));
  assert.equal(document.querySelector(".dataset-control select"), null);
  findButton(document, "Dataset").click();
  await wait(25);
  assert.ok(document.querySelector("tbody"));
  assert.equal(document.querySelector(".customer-cell script"), null);
  assert.match(document.querySelector("tbody tr").textContent, /<script>alert/);
  assert.match(document.querySelector("tbody tr").textContent, /RO-700120/);
  assert.match(
    document.querySelector("tbody tr").textContent,
    /200 Simulation Way/,
  );
  findButton(document, "OCR activity").click();
  await wait(25);
  assert.equal(document.querySelector(".scan-result-card"), null);
  assert.equal(document.querySelector(".scan-diagnostics"), null);
  assert.equal(findButton(document, "Open Order Tracker"), undefined);
  dom.window.close();
});
test("OCR intake refresh keeps processing controls without duplicating page results", async () => {
  const { dom, document, calls } = await boot();
  assert.equal(document.querySelector(".scan-result-card"), null);
  assert.equal(
    document.querySelector('[aria-label="Filter OCR results"]'),
    null,
  );
  findButton(document, "Refresh results").click();
  await wait(25);
  assert.ok(calls.filter((c) => c.path.endsWith("/activity")).length >= 2);
  assert.equal(document.querySelector("h1").textContent, "Scan intake");
  assert.ok(document.querySelector("#ocr-processing"));
  assert.ok(document.querySelector("#pdf-dropzone"));
  assert.equal(document.querySelector(".scan-result-card"), null);
  assert.equal(findButton(document, "Open Order Tracker"), undefined);
  dom.window.close();
});
test("ticket drawer exposes the selected order, page evidence, and a six-page download route", async () => {
  const { dom, document } = await boot();
  findButton(document, "Dataset").click();
  await wait(25);
  document.querySelector('[aria-label="View W-990120"]').click();
  await wait(25);
  assert.equal(
    document.querySelector("[role=dialog] h2").textContent,
    "W-990120",
  );
  assert.match(
    document.querySelector(".address-block").textContent,
    /Delivery location/,
  );
  const download = document.querySelector(".drawer-footer a");
  assert.equal(
    download.getAttribute("href"),
    "/api/workspaces/validation/tickets/ticket-0/download",
  );
  findButton(document, "OCR results").click();
  assert.equal(document.querySelectorAll(".evidence-row").length, 6);
  document.querySelectorAll(".evidence-row")[5].click();
  assert.match(document.querySelector(".paper-image").alt, /page 6/);
  document.querySelector('[aria-label="Close work order"]').click();
  assert.equal(document.querySelector("[role=dialog]"), null);
  dom.window.close();
});

test("live worker events advance connected stages and expose downloads only on PDF readiness", async () => {
  const { dom, document, progressStreams } = await boot();
  const stream = progressStreams[0];
  assert.match(stream.url, /progress\/stream$/);
  stream.onmessage({
    data: JSON.stringify({
      phase: "receiving",
      file: "new_scan.pdf",
      revision: 0,
    }),
  });
  assert.equal(
    document.querySelectorAll(".ocr-live-step:not([hidden])").length,
    1,
  );
  assert.match(
    document.querySelector(".ocr-live-step.is-active").textContent,
    /PDF detected/,
  );

  stream.onmessage({
    data: JSON.stringify({
      phase: "reading",
      file: "new_scan.pdf",
      total: 6,
      completed: 2,
      matched: 2,
      revision: 1,
    }),
  });
  await wait(1450);
  assert.equal(
    document
      .querySelector('[aria-label="OCR pages processed"]')
      .getAttribute("aria-valuenow"),
    "2",
  );
  assert.ok(document.querySelector(".ocr-live-step.is-active"));
  assert.equal(document.querySelectorAll(".ocr-live-step.is-active").length, 1);
  assert.match(
    document.querySelector(".ocr-live-step.is-active").textContent,
    /OCR reading/,
  );
  assert.ok(
    document.querySelector(".ocr-live-step.is-done .progress-node svg"),
  );
  assert.equal(
    document.querySelectorAll(".ocr-live-step:not([hidden])").length,
    2,
  );
  // A page's matching callback must not end OCR for the remaining pages.
  stream.onmessage({
    data: JSON.stringify({
      phase: "matching",
      file: "new_scan.pdf",
      total: 6,
      completed: 2,
      matched: 2,
      revision: 2,
    }),
  });
  assert.match(
    document.querySelector(".ocr-live-step.is-active").textContent,
    /OCR reading/,
  );
  assert.equal(
    document.querySelectorAll(".ocr-live-step:not([hidden])").length,
    2,
  );

  assert.equal(document.querySelector(".ocr-ready-actions"), null);
  assert.equal(document.querySelector(".scan-download-panel a"), null);
  stream.onmessage({
    data: JSON.stringify({
      phase: "ready",
      file: "new_scan.pdf",
      total: 6,
      completed: 6,
      matched: 6,
      revision: 3,
      ready_tickets: [{ id: "ticket-0", work_order: "W-990120" }],
    }),
  });
  assert.equal(document.querySelector(".scan-download-panel a"), null);
  await wait(4400);
  assert.equal(document.querySelectorAll(".ocr-live-step.is-done").length, 4);
  assert.equal(
    document.querySelector(".scan-download-panel a").getAttribute("href"),
    "/api/workspaces/validation/progress/tickets.zip?revision=3",
  );

  assert.equal(
    document.querySelectorAll(".ocr-live-step.is-done .progress-node svg")
      .length,
    4,
  );
  assert.match(
    document.querySelector("#ocr-live-progress").textContent,
    /Order completed/,
  );
  assert.equal(document.querySelector(".ocr-ready-actions"), null);
  stream.onerror();
  assert.match(
    document.querySelector("#ocr-live-progress").textContent,
    /Reconnecting/,
  );
  dom.window.close();
});
test("unmatched OCR and PDF errors never display a ready confirmation", async () => {
  const { dom, document, progressStreams } = await boot();
  progressStreams[0].onmessage({
    data: JSON.stringify({
      phase: "error",
      failed_at: "preparing_pdf",
      file: "scan.pdf",
      total: 6,
      completed: 6,
      matched: 6,
      revision: 1,
      ready_tickets: [],
    }),
  });
  assert.match(
    document.querySelector(".ocr-live-step.is-error").textContent,
    /Ticket PDF ready/,
  );
  assert.equal(document.querySelector(".ocr-ready-actions"), null);
  assert.equal(document.querySelector(".scan-download-panel a"), null);
  assert.doesNotMatch(
    document.querySelector("#ocr-live-progress").textContent,
    /OCR \+ PDF ready/,
  );
  dom.window.close();
});

test("Overview replaces the old verification ring with one live verification panel", async () => {
  const { dom, document } = await boot();
  findButton(document, "Overview").click();
  await wait(25);
  assert.equal(document.querySelectorAll("#ocr-live-progress").length, 1);
  assert.equal(document.querySelector(".coverage-panel"), null);
  dom.window.close();
});

test("dragging a PDF submits it and retains its filename and status", async () => {
  const { dom, document, calls } = await boot();
  assert.equal(document.querySelectorAll(".progress-dot").length, 4);
  assert.equal(document.querySelectorAll(".progress-connector-fill").length, 3);
  const file = new dom.window.File(["demo PDF"], "demo_scan.pdf", {
    type: "application/pdf",
  });
  const drop = new dom.window.Event("drop", {
    bubbles: true,
    cancelable: true,
  });
  Object.defineProperty(drop, "dataTransfer", { value: { files: [file] } });
  document.querySelector("#pdf-dropzone").dispatchEvent(drop);
  await wait(25);
  const upload = calls.find((call) => call.path.endsWith("/intake"));
  assert.equal(upload.options.method, "POST");
  assert.equal(upload.options.body, file);
  assert.match(
    document.querySelector(".intake-upload-status").textContent,
    /OCR will start automatically/,
  );
  assert.equal(document.querySelectorAll("#navigation button").length, 5);
  assert.match(
    document.querySelector(".intake-file-list").textContent,
    /demo_scan.pdf.*Submitted to OCR/,
  );
  dom.window.close();
});

test("manual upload and rejected drops keep a visible filename and error", async () => {
  const { dom, document, calls } = await boot();
  const file = new dom.window.File(["pdf"], "manual.pdf", {
    type: "application/pdf",
  });
  const input = document.querySelector("input[type=file]");
  Object.defineProperty(input, "files", { value: [file] });
  input.dispatchEvent(new dom.window.Event("change", { bubbles: true }));
  await wait(25);
  assert.equal(calls.filter((c) => c.path.endsWith("/intake")).length, 1);
  assert.match(
    document.querySelector(".intake-file-list").textContent,
    /manual.pdf.*Submitted to OCR/,
  );
  dom.window.fetch = async () => ({
    ok: false,
    json: async () => ({ detail: "OCR worker unavailable" }),
  });
  const drop = new dom.window.Event("drop", {
    bubbles: true,
    cancelable: true,
  });
  Object.defineProperty(drop, "dataTransfer", { value: { files: [file] } });
  document.body.dispatchEvent(drop);
  await wait(25);
  assert.ok(drop.defaultPrevented);
  assert.match(
    document.querySelector(".intake-file-list").textContent,
    /manual.pdf.*Upload failed: OCR worker unavailable/,
  );
  dom.window.close();
});

test("tracker updates detected orders from OCR events and enables completed row downloads", async () => {
  const { dom, document, progressStreams } = await boot();
  const fetch = dom.window.fetch;
  let ready = false;
  dom.window.fetch = async (path, options) => {
    const response = await fetch(path, options);
    const data = await response.json();
    if (path.includes("/tickets?")) {
      data.tickets[0].verified_pages = ready ? 6 : 3;
      data.tickets[0].ocr_status = ready ? "verified" : "partial";
      data.tickets[0].download_ready = ready;
    }
    return { ok: true, json: async () => data };
  };
  findButton(document, "Dataset").click();
  await wait(30);
  assert.match(document.querySelector("tbody tr").textContent, /Detected/);
  assert.equal(
    document.querySelector("tbody tr").querySelector(".row-download"),
    null,
  );
  const search = document.querySelector("input[type=search]");
  search.focus();
  ready = true;
  progressStreams[0].onmessage({
    data: JSON.stringify({
      phase: "matching",
      file: "scan.pdf",
      total: 6,
      completed: 6,
      matched: 6,
      revision: 20,
    }),
  });
  await wait(350);
  assert.equal(document.activeElement, search);
  assert.match(
    document.querySelector("tbody tr").textContent,
    /Ready to download/,
  );
  const download = document
    .querySelector("tbody tr")
    .querySelector(".row-download");
  assert.equal(
    download.getAttribute("href"),
    "/api/workspaces/validation/tickets/ticket-0/download",
  );
  download.dispatchEvent(
    new dom.window.KeyboardEvent("keydown", { key: "Enter", bubbles: true }),
  );
  assert.equal(document.querySelector(".detail-drawer"), null);
  assert.equal(
    document
      .querySelector(".row-download")
      .textContent.includes("Download PDF"),
    true,
  );
  dom.window.close();
});

test("complete orders can be downloaded while other orders in the scan need review", async () => {
  const { dom, document, progressStreams } = await boot();
  progressStreams[0].onmessage({
    data: JSON.stringify({
      phase: "needs_attention",
      file: "mixed.pdf",
      total: 11,
      completed: 11,
      matched: 11,
      revision: 30,
      ready_tickets: [{ id: "ticket-0", work_order: "W-990120" }],
    }),
  });
  assert.match(
    document.querySelector(".scan-download-panel").textContent,
    /1 completed ticket/,
  );
  assert.equal(
    document.querySelector(".scan-download-panel a").getAttribute("href"),
    "/api/workspaces/validation/progress/tickets.zip?revision=30",
  );
  findButton(document, "Dataset").click();
  await wait(30);
  assert.ok(findButton(document, "Incomplete orders0"));
  dom.window.close();
});

test("ZIP summary shows scan totals before download and refreshes after a fix", async () => {
  const { dom, document, progressStreams, calls } = await boot();
  const send = (revision, ready, missing) =>
    progressStreams[0].onmessage({
      data: JSON.stringify({
        phase: "needs_attention",
        file: "current.pdf",
        revision,
        total: 48,
        completed: 48,
        matched: 48 - missing,
        ready_tickets: tickets.slice(0, ready).map((t) => ({ id: t.id })),
        download_summary: {
          total_orders: 8,
          ready_orders: ready,
          not_ready_orders: 8 - ready,
          missing_pages: missing,
          unidentified_pages: missing,
          pending_pages: 0,
        },
      }),
    });
  send(50, 6, 2);
  const readCounts = () =>
    [...document.querySelectorAll(".scan-download-count dd")].map(
      (node) => node.textContent,
    );
  assert.deepEqual(readCounts(), ["6", "2", "2"]);
  assert.match(
    document.querySelector(".scan-download-summary").textContent,
    /8 orders detected in this scan/,
  );
  assert.match(
    document.querySelector(".scan-download-panel").textContent,
    /ZIP includes ready orders only/,
  );
  assert.equal(
    calls.some(({ path }) => path.includes("tickets.zip")),
    false,
  );
  assert.equal(
    document.querySelector(".scan-download-panel a").getAttribute("href"),
    "/api/workspaces/validation/progress/tickets.zip?revision=50",
  );
  send(51, 7, 1);
  assert.deepEqual(readCounts(), ["7", "1", "1"]);
  assert.equal(
    document.querySelector(".scan-download-panel a").getAttribute("href"),
    "/api/workspaces/validation/progress/tickets.zip?revision=51",
  );
  dom.window.close();
});

test("Overview shows only Approved and In review order rows and refreshes their status", async () => {
  const { dom, document, progressStreams } = await boot();
  const fetch = dom.window.fetch;
  let complete = false;
  dom.window.fetch = async (path, options) => {
    const response = await fetch(path, options);
    const data = await response.json();
    if (path.includes("/tickets?") || path.endsWith("/tickets"))
      data.tickets = [
        { ...tickets[0], download_ready: true },
        {
          ...tickets[1],
          download_ready: complete,
          ocr_status: complete ? "verified" : "partial",
          verified_pages: complete ? 6 : 5,
          missing_pages: complete ? [] : [6],
          processing: false,
        },
        {
          ...tickets[2],
          download_ready: false,
          ocr_status: "partial",
          verified_pages: 2,
          missing_pages: [3, 4, 5, 6],
          processing: true,
        },
      ];
    if (path.endsWith("/activity")) data.counts = { no_match: 2, error: 1 };
    return { ok: true, json: async () => data };
  };
  findButton(document, "Overview").click();
  await wait(30);
  assert.doesNotMatch(
    document.querySelector("main").textContent,
    /Your next steps|Recent work orders/,
  );
  assert.equal(
    document.querySelector("#overview-tab-ready span").textContent,
    "1",
  );
  assert.equal(
    document.querySelector("#overview-tab-attention span").textContent,
    "2",
  );
  assert.equal(document.querySelector("#overview-results-ready").hidden, false);
  assert.equal(
    document.querySelector("#overview-results-ready a").getAttribute("href"),
    "/api/workspaces/validation/tickets/ticket-0/download",
  );
  document.querySelector("#overview-tab-attention").click();
  const attention = document.querySelector("#overview-results-attention");
  assert.equal(attention.hidden, false);
  assert.equal(attention.querySelectorAll(".overview-order-row").length, 2);
  assert.match(attention.textContent, /In review/);
  assert.doesNotMatch(
    attention.textContent,
    /pages|address|Not read|identified/i,
  );
  assert.equal(
    document.querySelector(
      "#overview-order-results details, #overview-order-results summary, #overview-order-results dl, #overview-order-results img",
    ),
    null,
  );
  assert.equal(attention.querySelector("a"), null);
  const upload = document.querySelector("#pdf-dropzone");
  const summary = [...document.querySelectorAll(".summary-value")]
    .filter((_, i) => i !== 1)
    .map((n) => n.textContent);
  complete = true;
  progressStreams[0].onmessage({
    data: JSON.stringify({
      phase: "matching",
      file: "scan.pdf",
      total: 12,
      completed: 12,
      matched: 12,
      revision: 60,
    }),
  });
  await wait(350);
  assert.equal(
    document.querySelector("#overview-tab-ready span").textContent,
    "2",
  );
  assert.equal(
    document
      .querySelector("#overview-tab-attention")
      .getAttribute("aria-selected"),
    "true",
  );
  assert.equal(document.querySelector("#pdf-dropzone"), upload);
  assert.deepEqual(
    [...document.querySelectorAll(".summary-value")]
      .filter((_, i) => i !== 1)
      .map((n) => n.textContent),
    summary,
  );
  document
    .querySelector("#overview-tab-attention")
    .dispatchEvent(
      new dom.window.KeyboardEvent("keydown", { key: "Home", bubbles: true }),
    );
  assert.equal(document.activeElement.id, "overview-tab-ready");
  dom.window.close();
});

test("OCR counter starts with the accepted PDF page count and advances only processed pages", async () => {
  const { dom, document, progressStreams } = await boot();
  const fetch = dom.window.fetch;
  let next = { file: "scan-47.pdf", page_count: 47 };
  dom.window.fetch = async (path, options) =>
    path.endsWith("/intake")
      ? { ok: true, json: async () => ({ status: "queued", ...next }) }
      : fetch(path, options);
  const counter = () =>
    document.querySelector("[data-ocr-page-summary] .summary-value")
      .textContent;
  const drop = () => {
    const event = new dom.window.Event("drop", {
      bubbles: true,
      cancelable: true,
    });
    Object.defineProperty(event, "dataTransfer", {
      value: {
        files: [
          new dom.window.File(["pdf"], next.file, { type: "application/pdf" }),
        ],
      },
    });
    document.querySelector("#pdf-dropzone").dispatchEvent(event);
  };
  drop();
  await wait(25);
  assert.equal(counter(), "0 / 47");
  progressStreams[0].onmessage({
    data: JSON.stringify({
      phase: "receiving",
      file: "scan-47.pdf",
      total: 47,
      completed: 0,
      matched: 0,
      revision: 70,
    }),
  });
  assert.equal(counter(), "0 / 47");
  progressStreams[0].onmessage({
    data: JSON.stringify({
      phase: "reading",
      file: "scan-47.pdf",
      total: 47,
      completed: 2,
      matched: 1,
      revision: 71,
    }),
  });
  assert.equal(counter(), "2 / 47");
  progressStreams[0].onmessage({
    data: JSON.stringify({
      phase: "needs_attention",
      file: "scan-47.pdf",
      total: 47,
      completed: 47,
      matched: 43,
      revision: 72,
    }),
  });
  assert.equal(counter(), "47 / 47");
  assert.match(
    document.querySelector("[data-ocr-page-summary]").textContent,
    /Pages processed in this PDF/,
  );
  next = { file: "scan-5.pdf", page_count: 5 };
  drop();
  await wait(25);
  assert.equal(counter(), "0 / 5");
  assert.deepEqual(
    [...document.querySelectorAll(".summary-value")]
      .filter((_, i) => i !== 1)
      .map((n) => n.textContent),
    ["2", "1"],
  );
  dom.window.close();
});

test("unidentified page issues stay in Flags and never add Overview rows", async () => {
  const { dom, document } = await boot();
  const fetch = dom.window.fetch;
  dom.window.fetch = async (path, options) => {
    const response = await fetch(path, options);
    const data = await response.json();
    if (path.includes("/activity")) {
      data.counts = { no_match: 1, error: 1, success: 1 };
      data.activity.push(
        {
          page: 4,
          page_id: "flagged-4",
          status: "no_match",
          identifier: "88888888",
          error_code: "document_fields_incomplete_or_conflicting",
        },
        {
          page: 9,
          page_id: "flagged-9",
          status: "error",
          error_code: "HTTP503",
        },
      );
    }
    return { ok: true, json: async () => data };
  };
  findButton(document, "Overview").click();
  await wait(30);
  document.querySelector("#overview-tab-attention").click();
  assert.equal(
    document.querySelector("#overview-tab-attention span").textContent,
    "0",
  );
  assert.equal(
    document.querySelector("#overview-results-attention .flag-page-row"),
    null,
  );
  assert.equal(findButton(document, "Review pages"), undefined);
  findButton(document, "Flags").click();
  await wait(30);
  assert.equal(dom.window.location.hash, "#/flags");
  assert.equal(document.querySelectorAll(".flag-page-row").length, 2);
  assert.match(
    document.querySelector("#flags-results").textContent,
    /88888888/,
  );
  assert.equal(
    document
      .querySelector('[aria-label="View flagged page 4"]')
      .getAttribute("href"),
    "/api/workspaces/validation/pages/flagged-4/preview",
  );
  assert.equal(document.querySelector("#flags-results img"), null);
  assert.equal(document.querySelector(".scan-result-card"), null);
  findButton(document, "OCR activity").click();
  await wait(30);
  assert.equal(document.querySelector(".flag-page-row"), null);
  assert.equal(document.querySelector(".scan-result-card"), null);
  assert.equal(findButton(document, "Open Order Tracker"), undefined);
  dom.window.close();
});

test("Overview rows cannot expand and repair groups exist only in Flags", async () => {
  const { dom, document, progressStreams } = await boot();
  const fetch = dom.window.fetch;
  let address = "200 Simulation Way";
  dom.window.fetch = async (path, options) => {
    const response = await fetch(path, options);
    const data = await response.json();
    if (path.includes("/tickets?") || path.endsWith("/tickets"))
      data.tickets = [
        { ...tickets[0], download_ready: true, billing_address: address },
        {
          ...tickets[1],
          download_ready: false,
          ocr_status: "partial",
          verified_pages: 5,
          missing_pages: [6],
          processing: false,
        },
        {
          ...tickets[2],
          download_ready: false,
          ocr_status: "partial",
          verified_pages: 2,
          missing_pages: [3, 4, 5, 6],
          processing: true,
        },
      ];
    if (path.includes("/activity")) {
      data.counts = { no_match: 2 };
      data.activity.push(
        {
          page: 4,
          page_id: "bad-4",
          document_id: "scan-a",
          status: "no_match",
        },
        {
          page: 9,
          page_id: "bad-9",
          document_id: "scan-a",
          status: "no_match",
        },
      );
    }
    return { ok: true, json: async () => data };
  };
  findButton(document, "Overview").click();
  await wait(30);
  let group = document.querySelector(
    "#overview-results-ready .overview-order-row",
  );
  assert.match(group.textContent, /Approved/);
  assert.equal(
    document.querySelector(
      "#overview-order-results details, #overview-order-results .page-fields-panel, #overview-order-results dl",
    ),
    null,
  );
  group.click();
  await wait(20);
  assert.equal(document.querySelector(".detail-drawer"), null);
  assert.equal(
    group.querySelector("a").getAttribute("href"),
    "/api/workspaces/validation/tickets/ticket-0/download",
  );
  address = "Updated Street";
  progressStreams[0].onmessage({
    data: JSON.stringify({
      phase: "matching",
      file: "scan.pdf",
      total: 12,
      completed: 12,
      matched: 12,
      revision: 90,
    }),
  });
  await wait(350);
  group = document.querySelector("#overview-results-ready .overview-order-row");
  assert.doesNotMatch(group.textContent, /Updated Street/);
  assert.equal(document.querySelector("#overview-order-results details"), null);
  findButton(document, "Flags").click();
  await wait(40);
  assert.equal(document.querySelector("h1").textContent, "Flags");
  assert.equal(findButton(document, "Review queue"), undefined);
  assert.equal(
    document.querySelector('#flags-results [data-order-id="ticket-0"]'),
    null,
  );
  const incomplete = document.querySelector(
    '#flags-results [data-order-id="ticket-1"]',
  );
  assert.equal(incomplete.open, false);
  assert.match(
    incomplete.textContent,
    /Not identified for this order: pages 6/,
  );
  assert.equal(
    document.querySelectorAll("#flags-results [data-flag-scan]").length,
    1,
  );
  assert.equal(
    document.querySelector("#flags-results [data-flag-scan]").open,
    false,
  );
  assert.equal(
    document.querySelectorAll("#flags-results .flag-page-row").length,
    2,
  );
  assert.equal(
    document.querySelector("#flags-results img, #flags-results iframe"),
    null,
  );
  dom.window.close();
});

test("old review route opens the dedicated Flags tab", async () => {
  const { dom, document } = await boot("#/review");
  assert.equal(dom.window.location.hash, "#/flags");
  assert.equal(document.querySelector("h1").textContent, "Flags");
  assert.match(
    document.querySelector("#flags-results").textContent,
    /No flags/,
  );
  dom.window.close();
});

test("RO groups child TKs and retains RO-only pages without mixing parent orders", async () => {
  const { dom, document } = await boot();
  const fetch = dom.window.fetch;
  const rows = tickets.slice(0, 2).map((ticket, i) => ({
    ...ticket,
    customer: "Amber Projects",
    work_order: `TK-${992001 + i}`,
    ticket_number: `TK-${992001 + i}`,
    shipment: "904001",
    rental_id: "ro-1",
    parent_rental_number: "RO-810001",
    download_ready: i === 0,
    ocr_status: i === 0 ? "verified" : "partial",
    verified_pages: i === 0 ? 6 : 5,
    missing_pages: i === 0 ? [] : [1],
    page_gap_status: "unidentified_in_scan",
  }));
  const parents = [
    {
      id: "ro-1",
      rental_number: "RO-810001",
      customer: "Amber Projects",
      tickets: rows,
      unassigned_pages: 1,
    },
    {
      id: "ro-2",
      rental_number: "RO-810002",
      customer: "Amber Projects",
      tickets: [],
      unassigned_pages: 1,
    },
  ];
  dom.window.fetch = async (path, options) => {
    const url = new URL(path, "http://localhost:8700");
    let data;
    if (url.pathname.endsWith("/tickets")) data = { tickets: rows, total: 2 };
    else if (url.pathname.endsWith("/rental-orders"))
      data = { rental_orders: parents };
    else if (url.pathname.endsWith("/activity"))
      data = {
        files: 1,
        files_read: 0,
        activity: parents.map((p, i) => ({
          id: `attempt-${i}`,
          page_id: `unassigned-${i}`,
          page: 20 + i,
          document_id: "same-scan",
          document: "mixed.pdf",
          status: "no_match",
          rental_id: p.id,
          parent_rental_number: p.rental_number,
          identifier: p.rental_number,
        })),
      };
    else return fetch(path, options);
    return { ok: true, json: async () => data };
  };
  findButton(document, "Dataset").click();
  await wait(30);
  assert.match(
    document.querySelector("thead").textContent,
    /Rental order \(RO\)/,
  );
  assert.equal(document.querySelectorAll("tbody tr").length, 2);
  assert.match(document.querySelector("tbody").textContent, /TK-992001/);
  assert.match(document.querySelector("tbody").textContent, /TK-992002/);
  findButton(document, "Overview").click();
  await wait(30);
  const ready = document.querySelector(
    '#overview-results-ready [data-order-id="ticket-0"]',
  );
  assert.match(ready.textContent, /TK-992001/);
  assert.match(ready.textContent, /Approved/);
  assert.equal(document.querySelector("#overview-order-results details"), null);
  assert.equal(
    document.querySelectorAll("#overview-order-results [data-order-id]").length,
    2,
  );
  assert.equal(
    document.querySelector(
      "#overview-order-results img, #overview-order-results iframe",
    ),
    null,
  );
  findButton(document, "Flags").click();
  await wait(30);
  const groups = document.querySelectorAll(
    "#flags-results .rental-order-group",
  );
  assert.equal(groups.length, 2);
  for (const group of groups) {
    assert.equal(group.open, false);
    assert.equal(group.querySelectorAll(".flag-page-row").length, 1);
    assert.equal(group.querySelector("[data-flag-scan]").open, false);
  }
  const second = document.querySelector(
    '#flags-results [data-rental-id="ro-2"]',
  );
  assert.match(second.textContent, /RO-810002/);
  assert.match(second.textContent, /0 work orders/);
  assert.equal(second.querySelector("[data-order-id]"), null);
  assert.match(second.textContent, /RO identified, ticket needs review/);
  assert.doesNotMatch(second.textContent, /TK-99200/);
  assert.equal(
    document.querySelector("#flags-results img, #flags-results iframe"),
    null,
  );
  dom.window.close();
});

for (const gap of ["unidentified_in_scan", "not_in_scan"]) {
  test(`drawer shows expected page count and distinguishes ${gap}`, async () => {
    const { dom, document } = await boot();
    const fetch = dom.window.fetch;
    dom.window.fetch = async (path, options) => {
      const response = await fetch(path, options);
      const data = await response.json();
      if (path.endsWith("/tickets/ticket-0")) {
        Object.assign(data, {
          download_ready: false,
          ocr_status: "partial",
          verified_pages: 5,
          expected_pages: 6,
          missing_pages: [1],
          unaccounted_pages: [1],
          page_gap_status: gap,
          unidentified_scan_pages:
            gap === "unidentified_in_scan"
              ? [{ id: "source-38", source_page: 38, identifier: "88888888" }]
              : [],
        });
        data.pages = data.pages
          .slice(1)
          .map((p) => ({ ...p, printed_page: p.number }));
      }
      return { ok: true, json: async () => data };
    };
    findButton(document, "Dataset").click();
    await wait(30);
    document.querySelector('[aria-label="View W-990120"]').click();
    await wait(30);
    findButton(document, "OCR results").click();
    assert.equal(findButton(document, "Fix pages"), undefined);
    assert.equal(document.querySelector(".unidentified-evidence"), null);
    findButton(document, "Review in Flags").click();
    await wait(30);
    findButton(document, "OCR results").click();
    const summary = document.querySelector(".ocr-summary");
    assert.match(summary.textContent, /5 of 6 pages identified/);
    assert.equal(summary.classList.contains("complete"), false);
    assert.match(
      document.querySelector(".drawer-heading-actions").textContent,
      /Incomplete/,
    );
    assert.deepEqual(
      [...document.querySelectorAll(".evidence-row .page-number")].map(
        (n) => n.textContent,
      ),
      ["2", "3", "4", "5", "6"],
    );
    assert.match(
      document.querySelector(".preview-pagination").textContent,
      /Page 2 \/ 6/,
    );
    assert.equal(document.querySelector(".drawer-footer a"), null);
    if (gap === "unidentified_in_scan") {
      assert.match(summary.textContent, /present but unmatched/);
      assert.equal(
        document.querySelector(".unidentified-evidence a").getAttribute("href"),
        "/api/workspaces/validation/pages/source-38/preview",
      );
      assert.match(
        document.querySelector(".unidentified-evidence").textContent,
        /88888888/,
      );
    } else {
      assert.match(summary.textContent, /not found in the processed scan/);
      assert.equal(document.querySelector(".unidentified-evidence"), null);
    }
    dom.window.close();
  });
}

for (const reject of [false, true]) {
  test(`image notebook ${reject ? "keeps the order incomplete after a rejected approval" : "approves a selected image and completes the order"}`, async () => {
    const { dom, document } = await boot();
    const fetch = dom.window.fetch;
    let approved = false;
    let posted;
    dom.window.fetch = async (path, options = {}) => {
      if (path.endsWith("/page-approvals")) {
        posted = JSON.parse(options.body);
        if (reject)
          return {
            ok: false,
            json: async () => ({ detail: "This image is already assigned" }),
          };
        approved = true;
        return { ok: true, json: async () => ({ approved: true }) };
      }
      const response = await fetch(path, options);
      const data = await response.json();
      if (path.endsWith("/tickets/ticket-0")) {
        Object.assign(data, {
          customer: "Demo Amber Logistics",
          billing_address: "1106 Simulation Way",
          rental_order: "RA-701007",
          download_ready: approved,
          ocr_status: approved ? "verified" : "partial",
          verified_pages: approved ? 6 : 5,
          ocr_verified_pages: 5,
          manually_approved_pages: approved ? 1 : 0,
          missing_pages: approved ? [] : [1],
          unaccounted_pages: approved ? [] : [1],
          page_gap_status: approved ? null : "unidentified_in_scan",
          unidentified_scan_pages: approved
            ? []
            : [
                { id: "source-17", source_page: 17, identifier: null },
                {
                  id: "source-38",
                  source_page: 38,
                  identifier: "88888888",
                  fields: {
                    customer: "Amber Logistics",
                    address: "1106 Simulation Way",
                    work_order: null,
                    shipment: "88888888",
                    parent_rental_number: null,
                    rental_order: "RA-701007",
                    document_type: "Delivery Acknowledgement",
                    page_number: 1,
                    expected_pages: 6,
                    signature_document: true,
                    signature_status: "explicitly_unsigned",
                    signature_evidence: "NOT SIGNED - DEMO",
                  },
                },
              ],
        });
        if (!approved) data.pages = data.pages.slice(1);
        data.pages = data.pages.map((p) => ({ ...p, printed_page: p.number }));
        if (approved)
          Object.assign(data.pages[0], {
            id: "source-38",
            manually_approved: true,
            accepted: true,
            matched: false,
            extracted: "88888888",
            ocr_status: "no_match",
          });
      }
      return { ok: true, json: async () => data };
    };
    findButton(document, "Dataset").click();
    await wait(30);
    document.querySelector('[aria-label="View W-990120"]').click();
    await wait(30);
    assert.equal(findButton(document, "Fix pages"), undefined);
    findButton(document, "OCR results").click();
    findButton(document, "Review in Flags").click();
    await wait(35);
    assert.equal(dom.window.location.hash, "#/flags");
    assert.equal(document.querySelectorAll(".fix-thumbnail").length, 2);
    assert.equal(document.querySelector("#approve-page").disabled, true);
    assert.equal(document.querySelector(".paper-image"), null);
    assert.match(document.querySelector(".fix-target").textContent, /W-990120/);
    const drawer = document.querySelector(".detail-drawer");
    const left = document.querySelector(".detail-left");
    const gallery = document.querySelector(".fix-gallery");
    left.scrollTop = 230;
    gallery.scrollLeft = 75;
    const selectedThumb = document.querySelector(
      '[aria-label="Select source page 38"]',
    );
    selectedThumb.focus();
    selectedThumb.click();
    assert.equal(document.querySelector(".detail-drawer"), drawer);
    assert.equal(document.querySelector(".detail-left"), left);
    assert.equal(document.querySelector(".fix-gallery"), gallery);
    assert.equal(document.activeElement, selectedThumb);
    assert.equal(left.scrollTop, 230);
    assert.equal(gallery.scrollLeft, 75);
    assert.match(
      document.querySelector(".paper-image").src,
      /pages\/source-38\/preview$/,
    );
    assert.equal(
      document.querySelector(".paper-image").alt,
      "Unidentified source page 38",
    );
    assert.equal(document.querySelector("#approve-page").disabled, true);
    assert.equal(document.querySelector("#fix-acknowledgment").hidden, false);
    document.querySelector("#fix-acknowledgment input").click();
    assert.equal(document.querySelector("#approve-page").disabled, false);
    const fields = document.querySelector(".page-fixer .page-fields-panel");
    assert.match(fields.textContent, /Amber Logistics/);
    assert.match(fields.textContent, /1106 Simulation Way/);
    assert.match(fields.textContent, /88888888/);
    assert.match(fields.textContent, /RO-701007/);
    assert.match(fields.textContent, /Not signed — stated on page/);
    assert.match(fields.textContent, /NOT SIGNED - DEMO/);
    assert.equal(
      [...fields.querySelectorAll(".detail-field")]
        .find(
          (n) => n.querySelector("dt").textContent === "Ticket / work order",
        )
        .querySelector("dd").textContent,
      "Not read",
    );
    assert.doesNotMatch(fields.textContent, /W-990120/);
    assert.match(
      document.querySelector("#approve-page").textContent,
      /Link source 38 → W-990120 · page 1/,
    );
    document.querySelector("#approve-page").click();
    await wait(80);
    assert.deepEqual(posted, {
      page_id: "source-38",
      printed_page: 1,
      acknowledge_differences: true,
    });
    if (reject) {
      assert.match(
        document.querySelector("[role=alert]").textContent,
        /already assigned/,
      );
      assert.equal(document.querySelector(".drawer-footer a"), null);
      assert.equal(document.querySelector("#approve-page").disabled, false);
    } else {
      assert.match(
        document.querySelector(".ocr-summary").textContent,
        /6 of 6 pages identified/,
      );
      assert.ok(
        document.querySelector(".ocr-summary").classList.contains("complete"),
      );
      assert.match(
        document.querySelector(".ocr-information").textContent,
        /5 OCR-verified pages · 1 manually approved pages/,
      );
      assert.match(
        document.querySelector(".preview-caption").textContent,
        /Manually linked/,
      );
      assert.match(
        document.querySelector(".evidence-row").textContent,
        /Manually linked/,
      );
      assert.equal(
        document.querySelector(".drawer-footer a").getAttribute("href"),
        "/api/workspaces/validation/tickets/ticket-0/download",
      );
      assert.equal(findButton(document, "Fix pages"), undefined);
    }
    dom.window.close();
  });
}

test("selected page details exist only in Flags and change with page selection", async () => {
  const { dom, document } = await boot();
  const fetch = dom.window.fetch;
  dom.window.fetch = async (path, options) => {
    const response = await fetch(path, options);
    const data = await response.json();
    if (path.endsWith("/tickets/ticket-0")) {
      data.download_ready = false;
      data.ocr_status = "partial";
      data.pages.forEach((page, i) => {
        page.fields = {
          customer: "Amber Projects",
          address: `${1100 + i} Simulation Way`,
          customer_order_number: "CO-123456",
          work_order: "TK-992001",
          shipment: "904001",
          parent_rental_number: "RO-810001",
          rental_order: "RO-810001",
          document_type: page.paper,
          page_number: i + 1,
          expected_pages: 6,
          signature_status: "not_determined",
        };
      });
    }
    return { ok: true, json: async () => data };
  };
  findButton(document, "Dataset").click();
  await wait(30);
  document.querySelector('[aria-label="View W-990120"]').click();
  await wait(30);
  findButton(document, "OCR results").click();
  assert.equal(document.querySelector(".page-fields-panel"), null);
  findButton(document, "Review in Flags").click();
  await wait(35);
  let panel = document.querySelector(
    "#selected-page-review .page-fields-panel",
  );
  assert.match(panel.textContent, /CO-123456/);
  assert.match(panel.textContent, /TK-992001/);
  assert.match(panel.textContent, /904001/);
  assert.match(panel.textContent, /RO-810001/);
  assert.doesNotMatch(panel.textContent, /Rental agreement \(RA\)/);
  assert.equal(
    document.querySelector('.page-comparison [data-check="rental_order"]'),
    null,
  );
  assert.equal(
    document.querySelectorAll(
      '.page-comparison [data-check="parent_rental_number"]',
    ).length,
    1,
  );
  assert.match(panel.textContent, /1100 Simulation Way/);
  assert.match(panel.textContent, /Not determined from this page/);
  const drawer = document.querySelector(".detail-drawer");
  const left = document.querySelector(".detail-left");
  const image = document.querySelector(".paper-image");
  const pageButton = document.querySelectorAll(".evidence-row")[1];
  left.scrollTop = 180;
  pageButton.focus();
  pageButton.click();
  assert.equal(document.querySelector(".detail-drawer"), drawer);
  assert.equal(document.querySelector(".detail-left"), left);
  assert.equal(document.querySelector(".paper-image"), image);
  assert.equal(document.activeElement, pageButton);
  assert.equal(left.scrollTop, 180);
  assert.doesNotMatch(
    document.querySelector(".evidence-row").textContent,
    /Expected|904001|900120/,
  );
  panel = document.querySelector("#selected-page-review .page-fields-panel");
  assert.match(panel.textContent, /1101 Simulation Way/);
  assert.doesNotMatch(panel.textContent, /1100 Simulation Way/);
  assert.equal(document.querySelectorAll(".paper-image").length, 1);
  findButton(document, "Order details").click();
  findButton(document, "OCR results").click();
  assert.equal(document.querySelector(".detail-left").scrollTop, 180);
  dom.window.close();
});

test("OD pages show OD, RO and SO without a duplicate customer-order identifier", async () => {
  const { dom, document, window } = await boot();
  const fetch = window.fetch;
  window.fetch = async (path, options) => {
    const response = await fetch(path, options);
    const data = await response.json();
    if (path.endsWith("/tickets/ticket-0")) {
      Object.assign(data, {
        work_order: "OD-992003",
        download_ready: false,
        ocr_status: "partial",
      });
      data.pages.forEach((page, index) => {
        page.fields = {
          work_order: "OD-992003",
          shipment: "904002",
          parent_rental_number: "RO-810001",
          customer: "Amber Workshop",
          address: "2100 Simulation Way",
          page_number: index + 1,
          expected_pages: 6,
        };
      });
    }
    return { ok: true, json: async () => data };
  };
  findButton(document, "Dataset").click();
  await wait(30);
  document.querySelector('[aria-label="View W-990120"]').click();
  await wait(30);
  findButton(document, "OCR results").click();
  findButton(document, "Review in Flags").click();
  await wait(35);
  const panel = document.querySelector(
    "#selected-page-review .page-fields-panel",
  );
  const labels = [...panel.querySelectorAll("dt")].map(
    (node) => node.textContent,
  );
  assert.ok(labels.includes("Order number (OD)"));
  assert.ok(labels.includes("Rental order (RO)"));
  assert.ok(labels.includes("Shipment / SO"));
  assert.equal(labels.includes("Customer order #"), false);
  assert.equal(
    document.querySelectorAll(
      '.page-comparison [data-check="customer_order_number"]',
    ).length,
    0,
  );
  assert.equal(document.querySelector(".detail-kicker").textContent, "ORDER");
  dom.window.close();
});

test("fixer compares the selected image with the target and blocks wrong customer or printed page", async () => {
  const { dom, document, window } = await boot();
  const fetch = window.fetch;
  const requests = [];
  let posted = false;
  const baseFields = {
    customer: "Demo Quartz Fabrication",
    address: "1161 Simulation Way",
    work_order: null,
    shipment: "901062",
    rental_order: "RA-701062",
    document_type: "Delivery Acknowledgement",
    page_number: 6,
    expected_pages: 6,
  };
  window.fetch = async (path, options) => {
    requests.push(path);
    if (path.endsWith("/page-approvals")) {
      posted = true;
      return {
        ok: false,
        json: async () => ({ detail: "Unexpected approval" }),
      };
    }
    const response = await fetch(path, options);
    const data = await response.json();
    if (path.endsWith("/tickets/ticket-0"))
      Object.assign(data, {
        work_order: "W-991062",
        customer: "Demo Quartz Fabrication",
        shipment: "901062",
        rental_order: "RA-701062",
        billing_address: "1161 Simulation Way",
        download_ready: false,
        ocr_status: "partial",
        missing_pages: [6],
        unaccounted_pages: [6],
        pages: data.pages.slice(0, 5),
        unidentified_scan_pages: [
          {
            id: "wrong-customer",
            source_page: 29,
            fields: {
              ...baseFields,
              customer: "Demo Quartz Workshop",
              address: "1160 Simulation Way",
              page_number: 1,
            },
          },
          {
            id: "wrong-page",
            source_page: 30,
            fields: { ...baseFields, page_number: 1 },
          },
          { id: "right-image", source_page: 31, fields: { ...baseFields } },
        ],
      });
    return { ok: true, json: async () => data };
  };
  findButton(document, "Dataset").click();
  await wait(30);
  document.querySelector('[aria-label="View W-990120"]').click();
  await wait(30);
  findButton(document, "OCR results").click();
  findButton(document, "Review in Flags").click();
  await wait(35);
  const count = requests.length;
  const drawer = document.querySelector(".detail-drawer");
  document.querySelector('[data-candidate-filter="different"]').click();
  document.querySelector('[aria-label="Select source page 29"]').click();
  assert.equal(document.querySelector("#approve-page").disabled, true);
  assert.match(
    document.querySelector(".comparison-error").textContent,
    /customer.*address.*printed page/i,
  );
  assert.match(
    document.querySelector('[data-check="address"]').textContent,
    /1161 Simulation Way.*1160 Simulation Way/,
  );
  document.querySelector("#approve-page").click();
  assert.equal(posted, false);
  const image = document.querySelector(".paper-image");
  document.querySelector('[aria-label="Select source page 30"]').click();
  assert.equal(document.querySelector(".paper-image"), image);
  assert.equal(document.querySelector("#approve-page").disabled, true);
  assert.match(
    document.querySelector(".comparison-error").textContent,
    /printed page/,
  );
  document.querySelector('[data-candidate-filter="possible"]').click();
  document.querySelector('[aria-label="Select source page 31"]').click();
  assert.equal(document.querySelector("#approve-page").disabled, false);
  assert.match(
    document.querySelector("#approve-page").textContent,
    /source 31 → W-991062 · page 6/,
  );
  assert.match(
    document.querySelector('[data-check="shipment"]').textContent,
    /901062/,
  );
  assert.match(
    document.querySelector('[data-check="work_order"]').textContent,
    /W-991062/,
  );
  assert.equal(document.querySelector("#fix-acknowledgment").hidden, true);
  assert.equal(document.querySelector(".detail-drawer"), drawer);
  assert.equal(requests.length, count); // Selection makes no workspace or OCR request.
  dom.window.close();
});

test("three different images are not presented as possible matches and uploading a missing page keeps the review open", async () => {
  const { dom, document, window, progressStreams } = await boot();
  const fetch = window.fetch;
  let completed = false,
    uploads = 0,
    approvals = 0;
  const values = () => ({
    download_ready: completed,
    verified_pages: completed ? 6 : 5,
    ocr_status: completed ? "verified" : "partial",
    missing_pages: completed ? [] : [6],
    unaccounted_pages: completed ? [] : [6],
    page_gap_status: "no_compatible_image",
  });
  window.fetch = async (path, options) => {
    if (path.endsWith("/intake")) {
      uploads++;
      return {
        ok: true,
        json: async () => ({
          file: "page_6.pdf",
          page_count: 1,
          status: "queued",
        }),
      };
    }
    if (path.endsWith("/page-approvals")) approvals++;
    const response = await fetch(path, options);
    const data = await response.json();
    if (Array.isArray(data.tickets))
      data.tickets[0] = { ...data.tickets[0], ...values() };
    if (path.endsWith("/tickets/ticket-0"))
      Object.assign(data, values(), {
        pages: completed ? data.pages : data.pages.slice(0, 5),
        unidentified_scan_pages: completed
          ? []
          : [9, 11, 29].map((number) => ({
              id: `different-${number}`,
              source_page: number,
              fields: {
                customer: "Another customer",
                address: "Another address",
                page_number: 1,
                expected_pages: 6,
              },
            })),
      });
    return { ok: true, json: async () => data };
  };
  findButton(document, "Dataset").click();
  await wait(30);
  document.querySelector('[aria-label="View W-990120"]').click();
  await wait(30);
  findButton(document, "OCR results").click();
  findButton(document, "Review in Flags").click();
  await wait(35);
  const drawer = document.querySelector(".detail-drawer");
  assert.equal(
    document.querySelector('[data-candidate-filter="possible"]').textContent,
    "Possible matches (0)",
  );
  assert.equal(
    document.querySelector('[data-candidate-filter="different"]').textContent,
    "Different images (3)",
  );
  assert.equal(
    [...document.querySelectorAll(".fix-thumbnail")].filter((n) => !n.hidden)
      .length,
    0,
  );
  assert.match(
    document.querySelector("#candidate-empty").textContent,
    /No image matches page 6/,
  );
  document.querySelector('[data-candidate-filter="different"]').click();
  assert.equal(
    [...document.querySelectorAll(".fix-thumbnail")].filter((n) => !n.hidden)
      .length,
    3,
  );
  document.querySelector('[aria-label="Select source page 29"]').click();
  assert.equal(document.querySelector("#approve-page").disabled, true);
  document.querySelector('[data-candidate-filter="possible"]').click();
  assert.equal(document.querySelector(".paper-stage").hidden, true);
  const input = document.querySelector(
    '[aria-label="Upload missing page PDFs"]',
  );
  Object.defineProperty(input, "files", {
    value: [
      new window.File(["%PDF"], "page_6.pdf", { type: "application/pdf" }),
    ],
  });
  input.dispatchEvent(new window.Event("change", { bubbles: true }));
  await wait(30);
  assert.equal(uploads, 1);
  assert.equal(document.querySelector(".detail-drawer"), drawer);
  assert.match(
    document.querySelector("#fix-upload-status").textContent,
    /added/,
  );
  completed = true;
  progressStreams[0].onmessage({
    data: JSON.stringify({
      phase: "needs_attention",
      file: "page_6.pdf",
      total: 1,
      completed: 1,
      matched: 1,
      revision: 210,
      ready_tickets: [{ id: "ticket-0" }],
    }),
  });
  await wait(350);
  assert.equal(document.querySelector("#detail-title").textContent, "W-990120");
  assert.match(
    document.querySelector(".drawer-heading-actions").textContent,
    /Ready to download/,
  );
  assert.equal(findButton(document, "Fix pages"), undefined);
  assert.equal(approvals, 0);
  dom.window.close();
});

for (const fail of [false, true]) {
  test(`PDF download ${fail ? "failure leaves the order unmarked" : "marks the order across views and prevents simultaneous duplicate requests"}`, async () => {
    const { dom, document, window } = await boot();
    const fetch = window.fetch;
    let marked = false,
      downloads = 0,
      release;
    const gate = new Promise((resolve) => {
      release = resolve;
    });
    const saved = [];
    window.URL.createObjectURL = () => "blob:compiled-pdf";
    window.URL.revokeObjectURL = () => {};
    const click = window.HTMLAnchorElement.prototype.click;
    window.HTMLAnchorElement.prototype.click = function () {
      if (this.href.startsWith("blob:")) {
        saved.push(this.download);
        return;
      }
      return click.call(this);
    };
    window.fetch = async (path, options) => {
      if (path.endsWith("/tickets/ticket-0/download")) {
        downloads++;
        await gate;
        if (fail)
          return {
            ok: false,
            json: async () => ({ detail: "PDF unavailable" }),
          };
        marked = true;
        return {
          ok: true,
          blob: async () => new window.Blob(["%PDF"]),
          headers: { get: () => 'attachment; filename="Amber.pdf"' },
        };
      }
      const response = await fetch(path, options);
      const data = await response.json();
      if (data.tickets && Array.isArray(data.tickets))
        data.tickets = data.tickets.map((t) => ({
          ...t,
          downloaded: t.id === "ticket-0" && marked,
          downloaded_at: marked ? "2026-11-11T17:00:00Z" : null,
        }));
      return { ok: true, json: async () => data };
    };
    findButton(document, "Dataset").click();
    await wait(30);
    const link = document.querySelector(".row-download");
    link.click();
    link.click();
    assert.equal(downloads, 1);
    assert.equal(link.getAttribute("aria-disabled"), "true");
    assert.equal(document.querySelector(".detail-drawer"), null);
    release();
    await wait(50);
    if (fail) {
      assert.equal(document.querySelector(".downloaded-mark"), null);
      assert.match(
        document.querySelector(".row-download").textContent,
        /Download PDF/,
      );
      assert.match(
        document.querySelector("#toast").textContent,
        /PDF unavailable/,
      );
      assert.deepEqual(saved, []);
    } else {
      assert.deepEqual(saved, ["Amber.pdf"]);
      assert.match(
        document.querySelector("tbody tr").textContent,
        /Downloaded/,
      );
      assert.match(
        document.querySelector(".row-download").textContent,
        /Download again/,
      );
      findButton(document, "Overview").click();
      await wait(30);
      assert.ok(
        document.querySelector(
          '#overview-order-results [data-order-id="ticket-0"] .downloaded-mark',
        ),
      );
      findButton(document, "Dataset").click();
      await wait(30);
      assert.equal(
        document.querySelectorAll("tbody .downloaded-mark").length,
        1,
      );
      assert.equal(downloads, 1); // Navigation does not download again.
    }
    dom.window.close();
  });
}

test("ZIP download marks every included ticket and changes the ZIP action to Download again", async () => {
  const { dom, document, window, progressStreams } = await boot();
  const fetch = window.fetch;
  let marked = false;
  window.URL.createObjectURL = () => "blob:ticket-zip";
  window.URL.revokeObjectURL = () => {};
  const click = window.HTMLAnchorElement.prototype.click;
  window.HTMLAnchorElement.prototype.click = function () {
    if (!this.href.startsWith("blob:")) return click.call(this);
  };
  window.fetch = async (path, options) => {
    if (path.includes("/progress/tickets.zip")) {
      marked = true;
      return {
        ok: true,
        blob: async () => new window.Blob(["zip"]),
        headers: { get: () => 'attachment; filename="scanned-tickets.zip"' },
      };
    }
    const response = await fetch(path, options);
    const data = await response.json();
    if (Array.isArray(data.tickets))
      data.tickets = data.tickets.map((t) => ({
        ...t,
        downloaded: marked && ["ticket-0", "ticket-1"].includes(t.id),
      }));
    return { ok: true, json: async () => data };
  };
  progressStreams[0].onmessage({
    data: JSON.stringify({
      phase: "needs_attention",
      file: "mixed.pdf",
      total: 11,
      completed: 11,
      matched: 11,
      revision: 121,
      ready_tickets: [{ id: "ticket-0" }, { id: "ticket-1" }],
    }),
  });
  document.querySelector(".scan-download-panel a").click();
  await wait(50);
  assert.match(
    document.querySelector(".scan-download-panel").textContent,
    /Downloaded/,
  );
  assert.match(
    document.querySelector(".scan-download-panel a").textContent,
    /Download ZIP again/,
  );
  findButton(document, "Dataset").click();
  await wait(30);
  assert.equal(document.querySelectorAll("tbody .downloaded-mark").length, 2);
  dom.window.close();
});
