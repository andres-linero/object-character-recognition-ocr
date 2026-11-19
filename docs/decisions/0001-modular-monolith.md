# ADR 0001: Separate application responsibilities within one deployable app

Status: Superseded on 2026-11-16 by the FastAPI workspace described in [current architecture](../architecture.md)

## Outcome

The single-deployment decision held; the Streamlit application it was written for did not. The UI was replaced by a static HTML/CSS/JavaScript client served by FastAPI, and the proposed boundaries now exist as modules in one package: `web_api.py` (presentation), `processing.py` and `intake_watcher.py` (application services), `page_review.py` and `document_data.py` (matching and field rules), `ocr.py` (provider adapter) and `storage.py` (persistence). Stages 3 and 4 were delivered through the relational store in [ADR 0002](0002-relational-store-and-etl.md): page attempts are persisted as success, no-match or error, and failed pages are retried without re-reading successful ones. Stage 2 no longer applies, because the sign-in flow was removed and the workspace binds to localhost only. Stage 5 remains open: no workload measurements have been taken, and no background worker service has been added.

Everything below is the original proposal of 2026-11-06, kept unchanged as a record. "The application" there means the retired Streamlit version.

Date: 2026-11-06

Decider: Repository owner

## Context

The application serves a local workbook/PDF workflow. UI rendering, authentication, readiness rules, resource initialization, and workflow persistence currently share a large Streamlit module. OCR runs synchronously during UI reruns. Local JSON/pickle state and shared resources constrain concurrent use and recovery.

Workload, user concurrency, hosting environment, processing-time targets, and data-retention requirements have not yet been established. There is no evidence that multiple independently deployed services are needed.

## Proposed decision

Retain one deployable Streamlit application and introduce explicit internal boundaries: presentation, application services, domain/data contracts, and infrastructure adapters. This is a proposal; the code has not been refactored into these layers.

The UI would call an indexing/order service. Services would depend on OCR, order-source, and state-storage interfaces. Infrastructure adapters would implement Azure OCR, workbook reading, and local persistence. Pure matching/readiness functions would be independently testable. Authentication would become a separately testable boundary before data operations.

## Options considered

| Option | Complexity | Main benefit | Main cost |
| --- | --- | --- | --- |
| Keep current structure | Low initially | No migration | Coupled UI/business behavior remains hard to validate |
| Modular monolith | Moderate | Clear boundaries with one deployment | Requires staged refactoring and contract tests |
| API plus workers and external storage | High | Independent processing/deployment capacity | New infrastructure, auth boundaries, consistency and operational work |

## Trade-offs and consequences

Internal boundaries improve testability and make later storage/worker choices easier. One deployment retains simple local setup. This does not itself solve concurrent writes, OCR latency, or session behavior. Durable error state and atomic writes need explicit implementation. Multiple services would add overhead before scale requirements are known.

## Implementation stages and acceptance criteria

1. Extract data contracts and matching/readiness functions. Preserve behavior against synthetic fixtures, including missing columns and identifier variants.
2. Separate authentication/configuration from UI rendering. Exercise real Entra success/failure/callback/sign-out paths in a controlled environment.
3. Extract indexing orchestration and OCR adapter. Persist per-page success/no-match/error status; failed pages must remain retryable without reprocessing successful pages.
4. Encapsulate local persistence. Use atomic replacement and an explicit writer/concurrency policy; test interrupted writes and recovery before shared usage.
5. Measure PDF/page volume, indexing latency, OCR failure rate, and expected concurrent users. Choose background workers or alternative storage only against documented targets.

## Questions for the next design review

What is the target host? How many operators work at once? How many pages arrive daily? What processing delay is acceptable? Must the app run offline? What data can leave the host, and how long must each artifact be kept? Which roles should view, download, or modify review state?
