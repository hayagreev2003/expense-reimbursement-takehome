# Nortex Travel Expense Settlement

An employee comes back from a trip with an inbox: an approval thread, an advance confirmation,
travel-desk bookings, cab receipts, a photographed restaurant bill, a hotel tax invoice. Today
they spend 25–30 minutes copying all of that into a blank settlement form by hand, and that
copying is where the errors come from.

This turns the inbox into a policy-checked claim — with the personal items caught, the duplicate
receipts collapsed, the colleague's cab rejected, and the whole thing routed to the approvers its
final value actually requires.

## Run it

Requires Docker.

```bash
make up
```

That brings up the API and the UI, applies migrations, and seeds the employee master and policy
version from `pack/`.

- UI — http://localhost:3000
- API docs — http://localhost:8000/docs

There is no database server to install or start. The database is a single SQLite file this
application owns, so it binds no port and shares nothing with anything else on the machine.

## Develop on it

Requires [uv](https://docs.astral.sh/uv/) and Node 20+. No Docker needed for this path.

```bash
make dev       # API and UI native with hot reload
make check     # lint + typecheck + both test suites — what CI runs
make reset-db  # throw the database away and rebuild it from migrations + seed
```

`make help` lists everything.

## Layout

```
backend/     FastAPI service. Ingestion, policy engine, approval workflow.
frontend/    Next.js App Router UI. Employee, approver and finance views.
pack/        READ-ONLY specification input. Policy, employee master, form template, sample inbox.
docs/        Requirements, plan, and area deep-dives in docs/agents/.
```

`pack/` is the brief, not data the application owns. Nothing writes to it, and the container
mounts it read-only.

## How it works

Evidence flows through separately testable stages, each persisting its output, so any number on
the final claim traces back to a source document:

```
ingest → classify → extract → reconcile → dedup → attribute → policy → claim lines → routing
```

Two things worth knowing about that pipeline:

**Extraction is pluggable.** The default adapter parses the sender formats in the pack and runs
tesseract over the two receipt images. A second adapter behind the same interface uses a
model with vision. The default needs no credentials and is the tested path.

**Bills must reconcile.** Extracted line items are checked against the bill's own stated
subtotal. They do not always agree — one of the receipt images has a fold across a line, and OCR
loses it — so a mismatch becomes a flag for human correction rather than a claim that is quietly
3,750 short. The guard sits below both extractors, so it protects either one.

## Tests

```bash
make test
```

The one that matters is `backend/tests/test_acceptance_nortex_trip.py`. It runs the full pipeline
over the sample inbox and asserts each specific way the claim can go wrong — a duplicate claimed
twice, a colleague's expense absorbed, a folio's personal items reimbursed, an entertainment bill
filed as a meal, a claim routed to the wrong approver because a disallowance moved it across a
threshold. It is the requirements document in executable form.

## Where it breaks

See `docs/NOTE.md`.
