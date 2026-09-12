# AGENTS.md

Canonical project context. Deep-dive docs live in `docs/agents/` — read the relevant one before
touching that area. This file keeps only what is needed on nearly every task.

## What this is

A travel expense reimbursement system for Nortex Industries. An employee's trip inbox becomes a
policy-checked settlement claim that routes to the approvers its final value requires.

- Requirements: `docs/brainstorms/2026-09-11-travel-expense-settlement-requirements.md`
- Plan: `docs/plans/2026-09-11-001-feat-travel-expense-settlement-plan.md`

## Hard rules

**`pack/` is read-only.** It is the specification: the policy, the employee master, the form
template, fifteen `.eml` files and two receipt images. Nothing in this application writes to it.
The Docker mount is `:ro` to make that structural rather than a promise.

**Disallow, never drop.** Every excluded amount appears as a line with a reason and a policy
citation. Silently omitting a non-reimbursable item is the single worst failure mode here — it
produces a claim that looks right and is wrong.

**Money is decimal.** No floats anywhere in the money path.

## Commands

```bash
make up          # one command: api + ui in Docker
make dev         # native, hot reload
make check       # lint + typecheck + test, everything CI runs
make test        # both suites
make seed        # load employees and the policy version from pack/
make reset-db    # delete the local db file, rebuild from migrations + seed
make revision m="add claims"   # autogenerate a migration
```

## Database

**SQLite, one file, at `backend/data/expense.db`.** Deliberate: it binds no port and shares no
server, so it cannot collide with — or be mistaken for — any other database on the machine. There
is no database service in Compose and nothing to provision in CI.

Two consequences to design around:

- **Portable column types only.** `sa.JSON`, not `JSONB`. UUID defaults generated in Python, not
  by the database. No advisory locks.
- **SQLite serialises writers.** The concurrent-approver test exercises coarser locking than
  Postgres would, and that is a stated limitation rather than a solved problem. See
  `docs/agents/testing.md`.

Relative `DATABASE_PATH` values resolve against `backend/`, not the current working directory —
uvicorn, pytest and alembic all start from different places, and resolving against CWD would
quietly create a second database.

Alembic on SQLite needs `render_as_batch=True` in `env.py`; without it any `ALTER TABLE` that
SQLite cannot do natively fails at migration time rather than at autogenerate time.

## Demo reset and deployment

`POST /api/v1/demo/reset` wipes every claim and re-seeds from the pack, so a hosted walkthrough
can be replayed without a shell. Off unless `DEMO_RESET_ENABLED=true`, and 404 - not 403 - when
off. It drops the append-only triggers on `claim_event` to do the wipe and restores them in a
`finally`; `tests/test_demo_reset.py` is what stops that regressing.

`backend/Dockerfile` builds from the **repository root**, because the image has to carry
`pack/`. A build with a `./backend` context cannot see it and the container starts with an empty
seed.

Read `docs/agents/deployment.md` before changing any of that, or before touching CORS - the
allowed origins are now `WEB_HOST` plus an optional `WEB_ORIGIN_REGEX_EXTRA` pattern for
Vercel's per-deployment preview subdomains.

## Layout

```
backend/src/expense_api/     FastAPI service, installed package (not a root main.py)
  config/                    settings singleton, logging
  db/                        SQLAlchemy models, engine, session dependency
  handlers/                  global exception handlers
  identity/                  who the caller is, and which of the two profiles they get
  evidence/                  ingest, classify, extractors, dedup, reconcile, uploads
  policy/                    versioned parameters + rule registry
  claims/                    pipeline (computed draft), materialise (rows at submit), router
  approvals/                 routing, decision service, approver queue router
  notifications/             addressed messages, one row per recipient
  demo/                      reset: wipe everything the demo produced, re-seed from pack/
  finance/  export/  seed/
backend/tests/               flat, test_<subject>.py
frontend/src/
  app/                       App Router, route groups per role
  api/                       client.ts, error.ts, generated.ts (codegen — do not hand-edit)
  features/<feature>/        api/ components/ hooks/ types/ colocated
  components/ui/             shadcn primitives
pack/                        READ-ONLY specification input
```

## Profiles and identity

Two profiles, both derived from `employee.role` rather than stored separately: **employee**
(submits, uploads, sees only their own trips) and **admin** (every approver role plus Finance;
sees only what has been routed to them).

The caller names themselves with an `X-Emp-Code` header, resolved in `identity/deps.py`. That
stands in for authentication and is the only thing standing in for it - authorisation is real
and enforced per route. When a session arrives, that module changes and nothing else does.

Claim state has two phases and the distinction matters:

- **Draft** - computed live from the evidence on every read, so an uploaded bill shows up
  immediately and there is no second copy of the figures to drift.
- **Submitted** - written to rows by `claims/materialise.py`, and served from them. An approver
  must see the figures that were submitted to them; a recomputation is a different number the
  moment anything behind it moves. Uploads and withdrawals are refused (409) until a return
  puts the claim back in draft.

## Conventions

**Backend**
- uv with a committed lockfile. `~=` pins. Dev deps in PEP 735 `[dependency-groups]`.
- Domain packages export a bare `APIRouter` with no prefix. Prefixes are applied once, in
  `create_app()`, so the whole URL map is readable in one place. Everything under `/api/v1`.
- Pydantic v2 with `model_config = ConfigDict(...)`. Never the v1 `class Config`.
- Schema naming: `<Verb><Noun>Request` / `<Verb><Noun>Response`. One model per direction, never
  a shared input/output model. `Literal[...]` and `Field(max_length=...)` on client-controlled
  values so a bad value fails at the boundary.
- Timestamps serialise as explicit UTC `Z`. A naive datetime gets reparsed in the browser's local
  timezone and the status timeline silently shifts.
- Clients see opaque `external_id` UUIDs. Integer PKs never leave the server. A lookup for
  someone else's resource returns 404, not 403 — a 403 confirms the row exists.
- Migrations run from the entrypoint, never from the app lifespan. An app that migrates on boot
  races itself as soon as it has more than one worker.
- Settings: one singleton, required fields with no default so a missing environment is a boot
  crash. Gates allowlist the safe value; they never denylist the unsafe ones.

**Frontend**
- Feature-first: `src/features/<feature>/{api,components,hooks,types}`.
- Tailwind + shadcn/ui only. No MUI, no CSS modules, no second styling system.
- TanStack Query for server state, Zustand for client state, react-hook-form + zod for forms.
- `src/api/generated.ts` is generated from `/openapi.json` by `npm run generate:api`. Never edit
  it by hand; CI fails on drift.
- One exported `baseUrl` in `src/app/global_config.ts`. Never read `process.env` elsewhere.
- `ApiError.userMessage` is safe to render. `detail` and `status` are for logging only.

## Gotchas worth knowing before you lose an hour

**Test isolation needed a SQLite fix.** The `db_session` fixture promises that anything written
in a test disappears, but the sqlite3 driver opens its own implicit transaction and commits
around statements it treats as DDL, which silently defeated the outer transaction - a route that
called `session.commit()` wrote for real and leaked into every later test. `tests/conftest.py`
now takes transaction control off the driver and issues `BEGIN` itself. Do not remove it; the
symptom is a test that passes alone and fails in the suite.

**RTK intercepts `eslint`.** A bare `npx eslint` returns
`ESLint output (JSON parse failed: EOF while parsing a value at line 1 column 0)` and exit 2.
ESLint is fine; RTK's wrapper is failing to parse its output. Run `rtk proxy "npx eslint ."`.
`make lint` already does this, with a fallback for machines without rtk.

**`LayoutProps` is not available to a standalone `tsc`.** Next 16 generates it into
`.next/types` during a build, so `tsc --noEmit` on a clean checkout — which is what CI runs —
cannot find it. Type layout props explicitly.

**The pack's `.eml` attachments are placeholders, not base64.** Messages 11 and 12 declare
`Content-Transfer-Encoding: base64` but the part body is the literal text
`[ATTACHMENT: see receipts/<name> in this pack]`. A standard MIME parser yields nothing. The
ingester resolves that placeholder against `pack/receipts/`.

**OCR loses a line on the hotel folio.** Both receipt images have a fold drawn across them, and
on `hotel_invoice_1188.png` the fold sits on a room-charge line — the label is destroyed and
`5,750.00` degrades to `5.750.00`. Extracted lines then sum to 13,450 against a stated 19,200
subtotal. This is why `evidence/reconcile.py` exists and why it must not be weakened.

## CORS

Never `allow_origins=["*"]`. Starlette answers a bare `Access-Control-Allow-Origin: *` to
requests with no Cookie header, and browsers reject `*` for `credentials: "include"` — the
symptom is every first-time request failing as an opaque network error while the server logs a
clean 200. Use `allow_origin_regex` anchored at both ends. `expose_headers` must be an explicit
list; a wildcard is ignored on credentialed requests.

Middleware order: `add_middleware` prepends, so anything added before `CORSMiddleware` ends up
wrapped by it. Upload guards go before it, or their 413/429 responses arrive without CORS headers
and the browser reports a network error instead of the real status.

## Git

Do not commit or push unless asked. Branch prefixes: `feat/`, `fix/`, `refactor/`.
