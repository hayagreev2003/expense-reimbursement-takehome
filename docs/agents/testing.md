# Testing

## The two halves

Most of `backend/tests/` runs against mocked sessions. What that cannot reach is behaviour that
only exists in the database — transaction boundaries, constraint interaction, two approvers
acting on one claim.

The rule: **a test belongs in the database half when the database, not Python, decides the
outcome.**

Concretely, for this codebase:

| Half | What lives there |
|---|---|
| Mocked | The policy rule registry, tax apportionment, amount parsing, reconciliation, dedup fingerprinting, approval-chain resolution. All pure functions with known inputs. |
| Database | Claim state transitions, resubmission superseding prior approvals, concurrent approver decisions, audit-trail append-only behaviour, migration round-trips. |

Database tests carry `pytestmark = [pytest.mark.db, pytest.mark.asyncio]`. There is nothing to
provision — the database is a SQLite file the run creates in a temp directory — so these never
skip, in CI or locally. That is the main practical win of the SQLite choice: the integration half
cannot silently go unrun.

**The honest limitation.** SQLite serialises writers. A concurrent-approver test therefore proves
that the application's own guard holds under contention, but it does not exercise row-level
locking the way Postgres would, so it is weaker evidence than the same test on Postgres. Treat
the application-level version check as the thing under test, not the storage engine's locking.

## Fixtures

| Fixture | What it gives |
|---|---|
| `db_session` | One session on an always-rolled-back outer transaction. The default. |
| `db_session_maker` | `join_transaction_mode="create_savepoint"`, so code under test can call `commit()` and still be rolled back. |
| `committing_session_maker` | Independent connections that really commit, file deleted on teardown. For concurrency tests. |

Two guards worth keeping:

- An autouse fixture that **refuses any connection on the application engine**, so a mis-aimed
  patch cannot write to the development database and quietly pass.
- `conftest.py` points `DATABASE_PATH` at a **fresh temp directory per run**, before any
  `expense_api` import. The development database lives at `backend/data/expense.db` and no test
  should be able to reach it however a later fixture is mis-wired.

Row builders live in `tests/db_helpers.py` as plain async functions taking a session and
keyword-only arguments — no factory library. Express relative times as server-side SQL, not
Python datetimes, or a test that depends on ordering will pass on a fast machine and fail on a
slow one.

## The acceptance test

`tests/test_acceptance_nortex_trip.py` runs the whole pipeline over the sample inbox and asserts
each specific way the claim can go wrong. It is the requirements document in executable form, and
it is the only test that proves the units compose.

Each assertion is named for the failure it prevents:

| Failure it prevents | Assertion |
|---|---|
| A duplicate claimed more than once | exactly one 172.00 line across three related messages |
| Absorbing a colleague's expense | 640.00 Chennai cab rejected, reason names the colleague |
| Promotional mail becoming a line | no claim line from the promo email |
| A failure notice read as a receipt | no claim line from the payment-failure notice |
| Claiming what the company already paid | 10,556.00 flights memo-only |
| Reimbursing folio personal items | laundry 450.00, mini bar 380.00 disallowed with remarks |
| Reimbursing tax on disallowed items | 99.60 of tax disallowed; parts sum to 2,304.00 |
| Discarding legitimate food on a folio | in-room dining 1,120.00 reclassified to Meals, allowed |
| Disallowing a compliant tariff | 5,750.00/night produces no disallowance against a 6,000 limit |
| Entertainment filed as a meal allowance | 2,255.00 held for attendees and prior approval |
| Inventing an unevidenced night | 19 Jun flagged as a coverage gap, no line created |
| Routing on a pre-disallowance value | 26,388.44 → RM + HoD; withdraw the held line → 24,133.44 → RM only |
| A silent OCR shortfall | corrupted folio OCR raises needs-input, never a quiet 13,450 |

Plus the settlement figures: gross 27,318.04, disallowed 929.60, net 26,388.44, advance
20,000.00, payable 6,388.44, recoverable 0.00.

## The closing check

Then break the code on purpose and confirm the test fails. Every assertion above should have been
written against a deliberately mutated version of the code it covers — a test that has never
failed has not been shown to test anything.
