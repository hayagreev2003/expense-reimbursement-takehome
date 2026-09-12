# Note

## What I took the problem to be

The 25 minutes is transcription. The errors are policy judgement. The follow-ups are the absence
of visible status. Those are three different problems and only the first is data entry.

So the system is built around the middle one. Reading fifteen emails into a form is the easy
part; deciding that the mini bar is excluded, that the tax charged on it is excluded with it,
that in-room dining is *not* excluded, that a colleague's forwarded cab is not this person's
expense, and that the resulting total needs a Head of Department rather than just a manager —
that is where a person currently earns their 25 minutes, and it is what I spent the effort on.

I read the pack as a specification with deliberate traps in it, and treated each one as an
acceptance test. There are thirteen. `backend/tests/test_acceptance_nortex_trip.py` asserts every
one against the real files, and settles the sample trip at **6,388.44 payable**.

## Assumptions

- **The pack is the whole input.** No HRMS, no travel desk API, no bank.
- **Tier 2 city classifications are mine, not the policy's.** §3.1 enumerates only Tier 1. The
  Tier 2 list is seeded with `source: assumption` and an unrecognised city falls to Tier 3, the
  lowest limit, flagged for Finance. A test fails if that marker is ever dropped.
- **A meal is Business Entertainment when the employee's own note says who it was for.** The
  pack's note names the customer from the travel request. This errs toward Business
  Entertainment because that head *holds* a line for attendee names rather than quietly paying
  it — the safer direction to be wrong in.
- **`Paid By` comes from payment evidence, never from the travel request.** The sample hotel was
  budgeted Company-borne and its voucher says "Pay at Hotel"; the invoice shows a personal card.
- **The unaccounted night of 19 Jun is flagged, not filled.** Something happened; the system does
  not know what, and inventing a line would be worse than saying so.

## What I built

FastAPI + Next.js, SQLite, `docker compose up`. `make check` runs 335 tests, ruff, mypy `--strict`,
eslint, `tsc` and vitest.

**Two profiles, one workflow.** An employee uploads bills, sees what policy allows and submits;
the claim is written down, routed by its value, and lands in exactly one approver's queue; the
approver approves, returns or rejects it; both sides are notified at every hand-off. The second
acceptance test, `backend/tests/test_api_workflow.py`, drives that over HTTP end to end.

- **Ingestion** of `.eml` and photographed receipts, idempotent on Message-ID.
- **Employee uploads.** A photograph of a paper bill is wrapped in a message envelope on disk and
  goes through the same classify/extract/reconcile path as mailed evidence, so there is one
  extraction path rather than two. Uploads land under `backend/data/uploads`, never in `pack/`.
- **Submission freezes the claim.** Up to submission the claim is computed live from the
  evidence; submitting writes the lines, the policy decisions behind them and the resolved chain
  to rows. An approver has to see the figures that were submitted to them, and a recomputation
  is a different number the moment anything behind it moves.
- **Notifications.** Every transition writes an addressed, separately-read row to the person who
  now has to act and the person who was waiting - in the same transaction as the state change,
  so a claim cannot move without someone being told.
- **A policy engine** of rules registered against clause citations, evaluated against an
  effective-dated policy version. Every disallowance names the clause that caused it.
- **Approval routing** keyed on the claim value *after* disallowances, recomputed on every change.
- **Export** into the pack's own template, leaving its formulas intact. A test evaluates the
  workbook's SUMIF by hand and checks it reaches the same payable the application did.

## What I deliberately left out

- **Authentication.** A profile picker stands in for it: the client names itself with an
  `X-Emp-Code` header and the server resolves that to an employee. Authorisation is real -
  scoping, routing and the approver checks are all enforced server-side and tested - but anyone
  who can reach the API can claim to be anyone. Swapping the header for a signed session touches
  `identity/deps.py` and nothing else.
- **A live mailbox.** Evidence is files. The parser is not pack-specific, but nothing connects to
  IMAP or Gmail.
- **Push notifications.** The bell polls every fifteen seconds. A claim changes hands a handful
  of times a week, so a websocket would be a connection to authenticate and reconnect for an
  event rate of roughly zero. No email is sent - the notification exists in the application only.
- **The payment run.** `next_payment_run()` and the PaymentRecord table exist and are tested, but
  nothing schedules a verified claim or marks it paid: the workflow stops at *verified*.
- **Payment integration, multi-currency, international travel.**

## Where it breaks

- **The rule-based parsers are tuned to this pack's senders.** An unseen vendor will not parse.
  That is the real limitation, and it is why extraction sits behind an adapter interface.
- **The model-based extractor has never been run.** There is no API credential in the environment
  I built this in — no key, no `ant` CLI, no OAuth profile. It is a seam with a concrete
  implementation behind it and it is untested. Do not believe it works.
- **OCR loses a line, and that is not hypothetical.** `hotel_invoice_1188.png` has a fold drawn
  across its second room charge; tesseract returns the label as `Spodun—Reom—Cheange.` and
  degrades `5,750.00` to `5.750.00`. Five legible lines then sum to 13,450 against a stated
  19,200 — a claim understated by 3,750, reported as a success.

  The claim is still correct, because amounts come from the message body where a bill has one and
  OCR is the fallback. What makes that *safe* rather than lucky is the reconciliation guard:
  extracted lines are checked against the bill's own stated subtotal, and a mismatch becomes a
  flag for a human instead of a claim. It sits below both extractors. A genuine phone photograph
  of a crumpled bill, with no email body behind it, would fail that check and land on someone's
  desk — which is the right outcome, and also slower than the 25 minutes I was asked to remove.
- **SQLite serialises writers.** Two approvers acting at once is prevented by an application-level
  version check, not by row-level locking. The test exercises the version check, which is the
  honest thing it proves. On Postgres the same code would be stronger.
- **The profile picker is not a permission boundary.** The server enforces every rule - an
  employee's claim is 404 to anyone else, an approver out of turn is refused, a decision is
  pinned to the version it was shown - but identity itself is a header the client sets.
- **CORS has to allow the identity header explicitly.** `X-Emp-Code` is not CORS-safelisted, so
  without it in `allow_headers` every browser request fails its preflight and the API looks
  down while the server logs nothing. Found by clicking through it, not by a test; there is now
  a test.
- **A returned claim is re-evaluated, not re-shown.** Resubmission rebuilds the lines from the
  evidence as it stands, so a claim returned after new evidence arrives comes back with new
  figures. That is what §2.3 asks for, but the approver who returned it sees no diff of what
  changed.
- **Folio lines all carry the check-in date.** Amounts come from the message body, which states
  `Nights 3` but not a date per line, so laundry and in-room dining are dated 16 Jun rather than
  the 17th and 18th the image shows. It does not change this claim — the meal cap passes on any
  single day — but it would matter on a trip with several meals, and the display is wrong.
- **Phone-width layout is unverified.** The grid stacks below `lg` and the table scrolls
  horizontally, but I could not resize the browser to check it.
- **Withdrawn lines are per-process state.** They belong on the claim row and are not persisted
  yet, so a restart forgets them - and, worse, a claim returned after a restart loses the
  withdrawal and blocks on the same held line again.
- **An upload is trusted by kind.** The employee declares what a photographed bill is, because a
  photograph carries no sender to classify on. Declaring a hotel folio as a cab receipt selects
  the wrong parser; the reconciliation guard catches an unbalanced result but not a confidently
  wrong one.
- **The Tier 2 list is a guess**, as above. On a trip to a city nobody has classified, the system
  applies the most conservative limit and says so, which is defensible but will occasionally be
  wrong in the employee's disfavour.
