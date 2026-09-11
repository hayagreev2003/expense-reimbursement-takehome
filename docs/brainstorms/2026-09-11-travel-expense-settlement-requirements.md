---
date: 2026-09-11
topic: travel-expense-settlement
---

# Travel Expense Reimbursement — Nortex Industries

## Problem Frame

A Nortex employee returning from a work trip spends 25–30 minutes transcribing a blank Travel Expense Settlement Form by hand from a scattered inbox: an approval thread, an advance confirmation, travel-desk bookings, cab receipts, a photographed restaurant bill, a hotel tax invoice. The transcription is where the errors come from — personal items left on the folio, duplicate receipts, a colleague's cab, an entertainment bill filed as a meal. The form then climbs an approval chain and disappears into Finance, and the employee spends two weeks chasing payment.

Three costs to remove: **the 25 minutes** (transcription), **the errors** (policy judgement), **the follow-ups** (no visible status).

Affected: employees who travel, their approvers (Reporting Manager, Head of Department, Head of Division, MD), and Finance Shared Services.

Anchor case: Chaitanya Reddy (NX-4471), Pune → Bengaluru, 16–20 Jun 2026, one 15-message inbox and two image receipts.

## Requirements

### Trip lifecycle

- **R1.** The system issues a **Travel Request ID** (`TRQ-YYYY-NNNN`) on approved travel request. Every downstream artefact — bookings, evidence, claim lines, approvals, advance, payment — is tracked against it (policy §1.1). Nothing exists outside a Travel Request ID.
- **R2.** An employee can raise a **Travel Request** capturing the Travel Request Form fields: dates, destination, purpose, travel category, mode, estimated cost broken down by head with a `Borne By` (Company / Employee) marker per head, and an advance requested.
- **R3.** The system records a **travel advance** against the Travel Request ID (reference, amount, disbursed date) and warns when the requested advance exceeds 60% of the estimated employee-borne cost (§1.2).
- **R4.** On return, the employee opens a **Settlement Claim** pre-populated from evidence, not a blank form.

### Evidence ingestion

- **R5.** The system ingests a set of `.eml` messages plus image attachments supplied as files, and turns each into an **Evidence item** with: source message, sender, date, merchant, amount, and a stable **Proof Reference** that names a specific document (never "attached mail" — form legend line 65).
- **R6.** Evidence items are classified into: **claimable expense**, **company-paid memo**, **contextual** (approval, advance note, booking voucher), or **noise**. Promotional mail is noise and never appears in the claim.
- **R7.** A payment-failure notice is not a receipt and does not create a claim line, even though it carries a merchant, date and amount.
- **R8.** Duplicate evidence is detected and collapsed to one claim line, reconciling on **merchant, date/time, amount and bill number** (§5.3). Forwards and resends of the same receipt count as duplicates. The system shows that a duplicate was suppressed rather than silently discarding it.
- **R9.** Image receipts (photographed paper bills, hotel tax invoices) are read into the same structured Evidence shape as text receipts, down to individual folio line items.
- **R10.** Every extracted field is reviewable and editable by the employee before submission, with the source document visible alongside. Extraction assists; the employee owns and signs off the claim.
- **R11.** Extraction fields carry a confidence signal, and low-confidence or missing required fields are surfaced as explicit **needs-input** prompts rather than guessed values.

### Policy evaluation

- **R12.** Each claim line resolves to exactly one of: **allowed**, **disallowed** (with reason and amount), **needs input** (with what is missing), or **rejected** (with reason).
- **R13.** `Paid By` is derived from **payment evidence**, not from the plan. A head marked Company on the Travel Request but settled on the employee's personal card is an Employee line, and vice versa.
- **R14.** Company-paid items (centrally booked air travel) appear as memo rows and are excluded from the reimbursable total (§3.2). They are recorded for audit and policy checking, never dropped.
- **R15.** Consolidated bills are **decomposed to line items**. A hotel folio yields separate room-charge, laundry, mini bar and in-room dining lines, each evaluated on its own.
- **R16.** Non-reimbursable items (§4 — laundry, mini bar, in-room entertainment, spa, gym, personal phone/data, alcohol outside approved entertainment, fines, independently purchased travel insurance) are shown as **disallowed lines with a remark**, never silently omitted (form legend line 66).
- **R17.** Taxes on a consolidated bill are **apportioned across its line items**. Tax attributable to a disallowed item is itself disallowed; tax on room tariff is reimbursable in full (§3.1).
- **R18.** Lodging is tested against the per-night tariff limit by city class, **excluding taxes** (§3.1). Excess tariff is a disallowed amount, not an omission. Tariff at or under the limit passes without comment.
- **R19.** Food on a hotel folio is **reclassified to Meals** and tested against the daily meal cap. It is not treated as non-reimbursable merely because it appeared on the folio.
- **R20.** Meals are reimbursed **on actuals up to the daily cap** by city class, with travel days counted as full days, and require a bill above INR 500 (§3.3).
- **R21.** A meal hosted for a customer or partner is **Business Entertainment**, not meal allowance. It requires **attendee names and organisation**, and above INR 2,000 requires **prior Head of Department approval** (§3.5). Absent either, the line is held as needs-input and cannot be submitted as-is.
- **R22.** Local conveyance is reimbursed on actuals against a receipt; airport transfers at both ends of the trip are covered (§3.4).
- **R23.** An expense incurred by **any person other than the claimant** is rejected with that reason stated, regardless of who forwarded it or which trip it belongs to (§4).
- **R24.** A claim line without a proof reference cannot be submitted (§5.2).
- **R25.** The system flags **coverage gaps** — a trip night or travel leg with no supporting evidence — as a warning to the employee, without inventing a claim line.
- **R26.** The settlement summary computes: employee-paid total, company-paid memo total, disallowed total, net reimbursable, less advance drawn, and then **exactly one** of amount payable to employee or amount recoverable from employee (form legend line 67).
- **R27.** Policy rules are **versioned and effective-dated** (currently NTX-HR-POL-11 Rev 4, effective 01 Apr 2026). A claim is evaluated against the policy version in force for its travel dates, and the version used is recorded on the claim.
- **R28.** Every allowed, disallowed and rejected outcome carries a **citable policy reference** shown to the employee and to approvers.

### Approvals and status

- **R29.** The approval chain is **computed from the final claim value after disallowances** against the approval matrix (§2), and is **recomputed on every resubmission**. A claim that drops below a threshold sheds the approval level it no longer needs.
- **R30.** Approvers are resolved from the employee master by walking the reporting line. An approver **cannot approve their own claim**; where the claimant occupies an approval level, that level is skipped and the next level up acts (§2.2).
- **R31.** Finance verification is required on every claim after business approvals are complete, regardless of value (§2.1).
- **R32.** An approver can **approve, reject, or return with remarks**. A returned claim goes back to the employee for correction and resubmits against the **same Travel Request ID** (§2.3), preserving the history of what changed.
- **R33.** The employee sees **current status at all times**: where the claim sits, who holds it, what they were asked, what is outstanding, and the expected payment run date. This is the mechanism that removes the follow-ups.
- **R34.** The system tracks the **submission deadline** — 7 calendar days from return (§5.1) — and the **payment run** dates of the 10th and 25th (§5.4), and shows both to the employee.
- **R35.** A complete, immutable **audit trail** is retained per claim: every evidence item ingested (including suppressed duplicates and rejected items), every extracted value and subsequent edit, every policy decision, and every approval action with actor, timestamp and remarks.
- **R36.** A finalised claim can be **exported in the shape of the existing Travel Expense Settlement Form**, so Finance can reconcile against the artefact they know.

## Success Criteria

- On the supplied inbox, the employee reaches a submit-ready claim in **under 3 minutes of review**, replacing 25–30 minutes of transcription.
- The system independently arrives at the correct settlement for the anchor trip:
  - Employee-paid gross **27,318.04**; disallowed **929.60** (laundry 450 + mini bar 380 + apportioned 12% tax 99.60); net reimbursable **26,388.44**; less advance 20,000; **payable 6,388.44**.
  - Company-paid memo **10,556.00** (both flight sectors), excluded from reimbursement.
  - Cab at 17 Jun 19:35 claimed **once at 172.00** across three related messages.
  - Colleague's 640.00 Chennai cab **rejected**, with the reason stated.
  - Business entertainment 2,255.00 **held** pending attendee names and prior HoD approval.
  - Room tariff 5,750/night **passes** the Tier 1 limit of 6,000 without comment.
  - In-room dining 1,120.00 **reclassified to Meals** and allowed within the 1,500 daily cap.
  - Promotional mail and the payment-failure notice **never produce claim lines**.
  - Missing accommodation for the night of 19 Jun **flagged** as a coverage gap.
- The claim routes to Reporting Manager and Head of Department at 26,388.44, and **re-routes to Reporting Manager alone** if the entertainment line is removed and the claim falls below 25,000.
- No disallowed or rejected amount disappears silently — every one is visible with a reason and a policy citation.
- A reviewer unfamiliar with the codebase can trace any number on the settlement summary back to a specific source document.

## Scope Boundaries

- **Evidence arrives as files.** `.eml` messages and image attachments are ingested from the supplied pack. No live mailbox connection, IMAP, Gmail OAuth, or mail-sync scheduling.
- **No real authentication.** A user switcher stands in for login so the employee, each approver, and Finance can be demonstrated in one sitting. No passwords, sessions, SSO, or password reset.
- **No payment integration.** Payment release is a recorded state and a run date, not a bank instruction.
- **Domestic INR travel only.** No multi-currency, no FX, no international-travel approval branch (the MD/CEO level exists in the matrix and in the data model, but is not the demonstrated path).
- **No travel booking.** The travel desk stays outside the system; bookings arrive as evidence.
- **Single organisation, single policy document.** No multi-tenant configuration or policy authoring UI; policy is versioned data, edited as data.
- **No mobile app.** Responsive web is sufficient.
- **No notification delivery.** Status is pulled from the app, not pushed by email or SMS.

## Key Decisions

- **The pack is the specification; every planted trap is an acceptance test.** Twelve deliberate traps were identified across the five files (duplicate receipt, payment-failure notice, colleague's expense, promo noise, company-paid flights, folio contamination, tax apportionment, in-room dining classification, tariff limit near-miss, entertainment vs meals, night-coverage gap, routing threshold sensitivity). Each becomes a named test case. Rationale: the pack's authors chose those 15 messages deliberately, and a system that silently mishandles any one of them fails at exactly the job it was built for.
- **Full end-to-end scope over a narrow slice.** The 8-hour guidance is set aside at the user's direction; the deliverable covers travel request → advance → ingestion → policy evaluation → approval chain → Finance verification → payment status. Rationale: the problem statement names all three costs (minutes, errors, follow-ups), and only the full loop removes the third.
- **Assisted, not autonomous.** The system drafts; the employee reviews, corrects and owns the submission. Rationale: extraction from photographed bills is fallible, and a claim the employee has not read is a claim they cannot defend to Finance.
- **Disallow, never drop.** Every excluded amount surfaces as a line with a reason. Rationale: the form legend states it twice, and it is the difference between an auditable claim and a plausible-looking one.
- **Policy as versioned, effective-dated data.** Rationale: the policy document is already at Rev 4 with an effective date, so it will change again; a claim must remain reproducible against the rules that applied to its travel dates.
- **Approval routing derives from the post-disallowance claim value and recomputes on resubmit.** Rationale: the matrix keys on claimed value, and disallowances move claims across thresholds — the anchor trip sits within 1,400 of a band boundary.
- **Line-item decomposition is the unit of policy evaluation.** Rationale: every interesting rule in the policy applies to a line, not a bill; a folio evaluated as a single 21,504 amount cannot be correct.
- **`Paid By` is evidence-derived.** Rationale: the anchor trip's hotel was planned as Company-borne and voucher-marked "Pay at Hotel", then settled on the employee's personal card. Trusting the plan produces the wrong answer.

## Dependencies / Assumptions

- The five pack files are the complete input; no additional Nortex systems (HRMS, ERP, travel desk API, banking) are available.
- `employee_master.csv` is authoritative for identity, reporting line, cost centre and role, and is complete enough to resolve every approval level in the matrix.
- Tier 1 cities are enumerated in the policy; **Tier 2 and Tier 3 classifications are not**, so a city not named as Tier 1 requires a classification source (see Outstanding Questions).
- Image receipts in the pack are clean, legible, machine-generated renderings. Genuine phone photographs of crumpled paper are harder, and this is a stated limitation rather than a solved problem.
- Amounts are INR throughout, and no expense in scope predates the current policy's 01 Apr 2026 effective date.
- The anchor trip is the only worked example available; behaviour on trips of a different shape is designed for but not evidenced.

## Outstanding Questions

### Resolve Before Planning

_None. Scope, boundaries and success criteria are settled._

### Deferred to Planning

- [Affects R5, R9][Technical] How evidence is parsed — deterministic parsers per sender versus a model-based extractor, and how image receipts are read. Determines whether the POC runs without external API access, and shapes the honest answer to "where it breaks".
- [Affects R11][Technical] How confidence is represented and what threshold routes a field to needs-input rather than a pre-filled value.
- [Affects R8][Technical] Exact duplicate-matching tolerance — how close two amounts or timestamps must be before they are treated as the same transaction, and whether near-matches warn rather than merge.
- [Affects R17][Technical] Tax apportionment method when a bill's tax lines do not decompose cleanly pro-rata across line items.
- [Affects R18, R20][Needs research] Source of city-class (Tier 2 / Tier 3) classification for destinations the policy does not enumerate. Options include a seeded lookup table with an explicit default and an employee-visible override.
- [Affects R27][Technical] How policy versions are represented and selected so that a claim's evaluation stays reproducible after the rules change.
- [Affects R21][Technical] Whether a held Business Entertainment line can be split off so the rest of a claim proceeds, or whether it blocks the whole submission.
- [Affects R32][Technical] What a resubmission preserves — whether prior approvals at unchanged levels stand or the chain restarts.
- [Affects R36][Technical] Export fidelity — regenerating the supplied `.xlsx` with its formulas intact versus producing an equivalent printable artefact.
- [Affects all][Technical] Stack, persistence and deployment target, and the one-command run path required by the deliverable.

## Next Steps

→ `/ce:plan` for structured implementation planning
