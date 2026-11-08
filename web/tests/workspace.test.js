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
async function boot() {
  const dom = new JSDOM(html, {
    url: "http://localhost:8700",
    runScripts: "outside-only",
    pretendToBeVisual: true,
  });
  const calls = [];
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
  return { dom, window: dom.window, document: dom.window.document, calls };
}
const findButton = (document, text) =>
  [...document.querySelectorAll("button")].find(
    (b) => b.textContent.trim() === text,
  );
test("restored tabs count files and show dataset context without test-stage choices", async () => {
  const { dom, document } = await boot();
  assert.equal(document.querySelector("h1").textContent, "Scan intake");
  assert.equal(document.querySelectorAll("#navigation button").length, 6);
  assert.deepEqual(
    [...document.querySelectorAll(".summary-value")].map((n) => n.textContent),
    ["2", "1 / 2", "1"],
  );
  assert.ok(document.querySelector('[aria-label="Dataset"]'));
  assert.equal(document.querySelector(".dataset-control select"), null);
  findButton(document, "Dataset").click();
  await wait(25);
  assert.ok(document.querySelector("tbody"));
  findButton(document, "OCR activity").click();
  await wait(25);
  assert.equal(document.querySelector('option[value="flagged"]'), null);
  assert.equal(document.querySelector(".scan-result-card script"), null);
  assert.match(
    document.querySelector(".scan-result-card").textContent,
    /Demo <script>alert/,
  );
  dom.window.close();
});
test("the intake filters scan results without switching workflow screens", async () => {
  const { dom, document, calls } = await boot();
  const filter = document.querySelector('[aria-label="Filter OCR results"]');
  filter.value = "pending";
  filter.dispatchEvent(new dom.window.Event("change"));
  assert.equal(document.querySelectorAll(".scan-result-card").length, 0);
  filter.value = "all";
  filter.dispatchEvent(new dom.window.Event("change"));
  assert.equal(document.querySelectorAll(".scan-result-card").length, 1);
  findButton(document, "Refresh results").click();
  await wait(25);
  assert.ok(calls.filter((c) => c.path.endsWith("/activity")).length >= 2);
  assert.equal(document.querySelector("h1").textContent, "Scan intake");
  dom.window.close();
});
test("ticket drawer exposes the selected order, page evidence, and a six-page download route", async () => {
  const { dom, document } = await boot();
  findButton(document, "Open matched ticket").click();
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
