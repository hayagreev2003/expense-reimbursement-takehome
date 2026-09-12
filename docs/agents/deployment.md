# Deploying a demo, and resetting it

Two related problems. A hosted walkthrough has no shell, so `make reset-db` is unreachable from
it; and the application's database is a SQLite file, which is an awkward shape for a platform
that gives a free service no disk. Both have answers, and the answers interact.

## The reset

`POST /api/v1/demo/reset` returns the demo to its starting state: the anchor trip, its inbox of
fifteen messages, nothing claimed against it yet.

```bash
curl -X POST https://<api-host>/api/v1/demo/reset -H "X-Demo-Token: <token>"
```

The UI has the same thing behind a two-step "Reset demo" button in the header, shown when
`NEXT_PUBLIC_DEMO_RESET_ENABLED=true`.

**It is off unless switched on.** `DEMO_RESET_ENABLED` defaults to false and the route answers
404 — not 403 — when it is. The existence of an endpoint that deletes every claim is itself
information, and a 403 confirms it. Once the feature is on, a wrong `X-Demo-Token` is a 403,
because at that point the route is no secret and only the credential is wrong.

Four details worth knowing before changing it:

**Employees and policy versions survive.** They are reference data seeded from the pack, every
approval step points at an employee row, and re-creating them would mint new primary keys for
nothing. The seed is idempotent over both.

**Rows are deleted; the database file is not.** The engine holds open connections to that file,
and unlinking it leaves the process talking to an unlinked inode that still answers queries.

**The audit trail's guard comes off and goes back on.** `claim_event` is append-only by database
trigger, so the wipe drops both triggers first — before the first delete, because the sqlite3
driver commits around DDL and doing it later would commit a half-finished wipe — and recreates
them in a `finally`. `backend/tests/test_demo_reset.py` asserts the guard is back afterwards. If
you touch `demo/service.py`, keep that test.

**Uploads go too.** Everything under `settings.upload_dir`, never anything under `pack/`.

The token is passed to the browser as `NEXT_PUBLIC_DEMO_RESET_TOKEN`, which Next inlines into
the bundle. It is readable by anyone who opens the page. It deters a scanner; it is not a
secret, and nothing else in this application depends on it being one.

## Render (API) + Vercel (UI)

`render.yaml` at the repository root is a Blueprint for the API. The UI is a normal Vercel
import of `frontend/`.

**The image carries `pack/`.** A deployment has no repository checkout to bind-mount from, and
the seed reads the employee master, the policy, fifteen `.eml` files and two receipts out of the
pack on every start. So `backend/Dockerfile` builds from the *repository root*, not from
`backend/`, and copies `pack/` in. Compose passes the same root context and still mounts the
working copy over it, so a local edit to the pack needs no rebuild. `PACK_DIR` points at
`/app/pack` in the image.

**The database is ephemeral on the free plan, deliberately.** Render gives a free web service no
disk, so `/app/data/expense.db` is lost on every restart and redeploy. The entrypoint runs
`alembic upgrade head` and the seed on every boot, so a cold start *is* a reset. The endpoint
above covers the other case — resetting mid-walkthrough. To make it survive, move to
`plan: starter` and uncomment the `disk:` block, which mounts at `/app/data`; a disk is not
available on the free plan and mounting one there silently changes nothing.

**A free service sleeps.** Roughly fifteen minutes idle, and this image carries tesseract, so
the wake-up is slow enough that a client will think the link is broken. Open the URL a few
minutes before the demo.

**CORS has to know about preview URLs.** `WEB_HOST` is one exact origin, and Vercel mints a new
subdomain for every preview deployment, so an exact origin can only ever match production. Set
`WEB_ORIGIN_REGEX_EXTRA` to a pattern for the rest:

```
WEB_ORIGIN_REGEX_EXTRA=https://nortex-expense-[a-z0-9-]+\.vercel\.app
```

It is a regex fragment; the anchors are added for you, and the exact origin is `re.escape`d
before the two are joined. Leave it unset and the allowed set is `WEB_HOST` and nothing else.
An empty string counts as unset in both cases — Compose and Render substitute an unset variable
as `""` rather than omitting it, and an empty alternative would match the empty origin.

### The order to do it in

1. Deploy the API from `render.yaml`. `WEB_HOST` is `sync: false`, so Render asks for it; put a
   placeholder in. Copy the generated `DEMO_RESET_TOKEN` out of the dashboard.
2. Import `frontend/` on Vercel. Set `NEXT_PUBLIC_API_BASE_URL` to the Render URL,
   `NEXT_PUBLIC_DEMO_RESET_ENABLED=true`, and `NEXT_PUBLIC_DEMO_RESET_TOKEN` to that token.
   These are inlined at build time, so a change to any of them needs a redeploy, not a restart.
3. Set `WEB_HOST` on Render to the Vercel production URL — scheme and host, no trailing slash,
   no path — and `WEB_ORIGIN_REGEX_EXTRA` if previews should work too.
4. Open the API's `/api/v1/health`, then the UI. A CORS mismatch shows up in the browser as an
   opaque network error while the server logs a clean 200; that symptom is almost always a
   trailing slash or `http` against `https` in `WEB_HOST`.

`APP_ENV=production` turns off `/docs` and `/openapi.json`. `npm run generate:api` therefore
has to run against a local API, not the deployed one.

## If it needs a real database

Nothing here is Postgres-hostile: the schema uses portable column types only, UUIDs are
generated in Python, and there are no advisory locks — see the database section of `AGENTS.md`,
which explains why those constraints were kept. The change is the driver and the URL, plus
dropping `render_as_batch` from Alembic. Worth doing when demo state has to survive for days;
not worth doing for a walkthrough, where an ephemeral database is a feature.
