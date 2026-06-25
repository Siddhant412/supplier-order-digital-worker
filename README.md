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
7. Route exceptions for approval or safely update the mock ERP.
8. Generate supplier communication and write an auditable event timeline.
9. Persist workflow state, audit events, idempotency keys, and ERP update markers in PostgreSQL when `DATABASE_URL` is configured.
10. Manage versioned trading partner profiles for EDI qualifier and acknowledgment-code interpretation.
11. Manage versioned approval policies with draft, published, and archived lifecycle controls.
12. Run evaluation scenarios and inspect pass/fail results from the operations console.

## Run Locally

Start the full local stack:

```bash
docker compose up --build
```

Then open:

- Frontend: http://localhost:5173
- Backend API: http://localhost:8000
- API health check: http://localhost:8000/health

Run backend tests:

```bash
PYTHONPATH=backend pytest -q backend/tests
```

Docker Compose runs the backend with PostgreSQL persistence enabled through `DATABASE_URL`. If `DATABASE_URL` is not set, the backend falls back to an in-memory store for isolated local tests.

## Principles

- Deterministic code owns arithmetic, threshold checks, state transitions, idempotency, and ERP writes.
- Language models, if used, are limited to recommendation summaries and drafted communication from already-validated facts.
- Risky supplier changes require explicit approval before system mutation.
- Every workflow must be replay-safe, observable, and auditable.
