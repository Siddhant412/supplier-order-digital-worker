# ProcureOps AI

ProcureOps AI is a governed supplier order automation system for processing purchase order acknowledgments, detecting material exceptions, and keeping ERP-style records aligned with supplier commitments.

The project is designed as a production-like digital worker for procurement operations. It ingests EDI supplier confirmations, validates them against purchase orders, applies deterministic approval policies, routes risky changes to humans, updates a mock ERP, sends supplier responses, and records every decision in an audit trail.

## Current Status

This repository contains the first working vertical slice:

1. Ingest one constrained X12 855-style acknowledgment.
2. Normalize it into a canonical supplier confirmation schema.
3. Retrieve the matching purchase order from a mock ERP service.
4. Compare line-level quantities, prices, units, dates, and part identities.
5. Assess inventory and shortage impact.
6. Apply configurable approval policies.
7. Run a bounded read-only risk investigation for approval-required cases.
8. Route exceptions through approve, reject, clarification, and manual-review resolution decisions.
8. Edit supplier-facing response content before human approval actions are recorded.
9. Generate supplier communication and write an auditable event timeline backed by append-only audit event records.
10. Handle deterministic unit conversion, currency changes, repeated ACK interpretation, unknown parts, and part substitutions.
11. Persist workflow state, audit events, idempotency keys, and ERP update markers in PostgreSQL when `DATABASE_URL` is configured.
12. Create and manage versioned trading partner profiles for EDI qualifier and acknowledgment-code interpretation.
13. Create and manage versioned approval policies with draft, published, and archived lifecycle controls.
14. Retry transient ERP lookup failures.
15. Retry failed supplier notifications without repeating ERP updates.
16. Filter and search the workflow queue by status, supplier, purchase order, and priority.
17. Reprocess manual-review workflows after profile or policy fixes.
18. Reset mock ERP seed data for repeatable local scenarios.
19. Inspect purchase-order and supplier-confirmation lines side by side.
20. Inspect ERP before/after snapshots and filter workflow audit events by event type, actor, and text.
21. Generate redacted, schema-validated operator briefs from workflow facts with deterministic fallback and optional OpenAI Responses API support.
22. Run evaluation scenarios and inspect pass/fail results from the operations console.

## Run Locally

Start the full local stack:

```bash
docker compose up --build
```

Then open:

- Frontend: http://localhost:5173
- Backend API: http://localhost:8000
- API liveness check: http://localhost:8000/live
- API readiness check: http://localhost:8000/ready
- JSON metrics: http://localhost:8000/api/metrics
- Metrics exporter: http://localhost:8000/metrics

Run backend tests:

```bash
PYTHONPATH=backend pytest -q backend/tests
```

Docker Compose runs the backend with PostgreSQL persistence enabled through `DATABASE_URL`. If `DATABASE_URL` is not set, the backend falls back to an in-memory store for isolated local tests.

## CI

GitHub Actions runs on pull requests, pushes to `main`, and manual dispatch. The workflow checks:

- backend tests with Python 3.12
- frontend production build with Node 20
- Docker image builds for the API and frontend

## Observability

The backend emits structured JSON logs for HTTP requests and workflow audit events. The operations console and API expose workflow metrics including automation rate, manual-review rate, retry recovery, LLM fallback rate, failed notifications, and average workflow duration.

Workflow detail pages also include a digital worker execution trace backed by `GET /api/workflows/{workflow_id}/execution-trace`. The trace maps audit events into LangGraph-oriented steps such as EDI parsing, semantic interpretation, PO retrieval, policy evaluation, bounded risk investigation, human approval, ERP update, supplier notification, and completion.

The bounded investigation agent is intentionally read-only. It can gather context such as inventory, demand, supplier performance, part aliases, alternate suppliers, purchase-order history, and trading-partner profile details, then produce a structured recommendation for the operator. It cannot approve, reject, or update ERP records. Planning is deterministic by default, with optional LLM planning available behind the same typed allowlist.

Optional operator-brief generation uses deterministic fallback by default. To enable model-generated briefs, set:

```bash
export OPENAI_API_KEY=...
export OPENAI_MODEL=gpt-5.4-mini
export OPENAI_INVESTIGATION_MODEL=gpt-5.4-mini
export OPENAI_TIMEOUT_SECONDS=20
export ENABLE_LLM_INVESTIGATION=true
```

## Principles

- Deterministic code owns arithmetic, threshold checks, state transitions, idempotency, and ERP writes.
- Language models, if used, are limited to recommendation summaries and drafted communication from already-validated facts.
- Risky supplier changes require explicit approval before system mutation.
- Every workflow must be replay-safe, observable, and auditable.
