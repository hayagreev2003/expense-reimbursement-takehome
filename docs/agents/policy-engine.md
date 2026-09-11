# Policy engine

Source of truth: `pack/expense_policy.md` — NTX-HR-POL-11, Rev 4, effective 01 Apr 2026.

## Shape

Two halves, deliberately:

**Parameters are versioned data.** `PolicyVersion.payload` is a JSONB blob with an
`effective_from` / `effective_to` range: city tier lists, lodging and meal limits, the meal bill
threshold, the non-reimbursable category list, the entertainment prior-approval threshold, the
approval matrix bands, the advance percentage, the submission window, the payment run days. The
authored source is `policy/versions/*.yaml`, loaded into the row at seed time so evaluation reads
a database fact rather than a file.

**Rules are code.** Registered functions keyed by a stable `rule_id`, each carrying the clause it
enforces. A rule receives a claim line, the claim context, and the resolved parameters, and
returns a decision.

A full declarative DSL was considered and rejected — there is one policy document, and some
clauses (tax apportionment especially) do not reduce to parameters. Pure parameter-driven code
cannot express them; a DSL would be a language invented for a single speaker.

## Why version selection matters

A claim is evaluated against the policy version in force **for its travel dates**, and the
version used is recorded on the claim. Rev 4 is already the fourth revision; there will be a
fifth. A claim settled last quarter must still reproduce its own numbers after the limits change,
or Finance cannot answer a query about it.

## Rules

| `rule_id` | Clause | Effect |
|---|---|---|
| `LODGING_TARIFF_LIMIT` | §3.1 | Disallow tariff above the city-class limit. Taxes untouched. |
| `LODGING_TAX_FULL` | §3.1 | Room-tariff tax is reimbursable in full. |
| `TAX_APPORTIONMENT` | §3.1, §4 | Split bill tax across lines; a disallowed line's tax is disallowed with it. |
| `AIR_COMPANY_BORNE` | §3.2 | Centrally booked air travel is memo-only, excluded from reimbursable. |
| `MEALS_DAILY_CAP` | §3.3 | Actuals up to the per-day cap by city class. Travel days count as full days. |
| `MEALS_BILL_THRESHOLD` | §3.3 | A bill is required above INR 500. |
| `CONVEYANCE_ACTUALS` | §3.4 | Actuals against a receipt. Airport transfers at both ends are covered. |
| `ENTERTAINMENT_ATTENDEES` | §3.5 | Hold unless attendee names and organisation are present. |
| `ENTERTAINMENT_PRIOR_APPROVAL` | §3.5 | Hold above INR 2,000 without prior HoD approval. |
| `NON_REIMBURSABLE_CATEGORY` | §4 | Disallow with a remark. Never drop. |
| `THIRD_PARTY_CLAIMANT` | §4 | Reject, naming whose expense it is. |
| `PROOF_REQUIRED` | §5.2 | Block submission of any line with no proof reference. |
| `DUPLICATE_BILL` | §5.3 | Collapse to one line and record the suppression. |
| `ADVANCE_CAP` | §1.2 | Warn where the advance exceeds 60% of the employee-borne estimate. |
| `SUBMISSION_DEADLINE` | §5.1 | Track 7 calendar days from return. |
| `SUBTOTAL_RECONCILIATION` | operational | Extracted lines must sum to the bill's stated subtotal. |

## Things that are easy to get wrong

**In-room dining is not a §4 exclusion.** The list is laundry, mini bar, in-room entertainment,
spa, gym, personal phone and data, alcohol outside approved entertainment, fines, and
independently purchased travel insurance. Food is absent from it. Hotel-folio food reclassifies
to Meals and is tested against the daily cap. Disallowing it because it appeared on the folio is
as wrong as reimbursing the mini bar.

**Tax rides with its line.** The folio's 12% sits on the whole subtotal, including items that are
not reimbursable. Apportion pro-rata on pre-tax share, prefer stated per-line tax where a bill
gives it, and put the rounding residue on the largest allowed line so the parts sum exactly to
the stated tax. For the sample folio this is exact: 2,070.00 + 54.00 + 45.60 + 134.40 = 2,304.00.

**A near-miss is not a miss.** The sample stay is 5,750 per night against a Tier 1 limit of
6,000. It passes, with no adverse decision. The approving manager's email warns about past
overspend; that is context, not evidence about this claim.

**Routing keys on the value after disallowances.** The sample claim lands at 26,388.44 — 1,388.44
above the 25,000 band boundary. Withdraw one held line and it drops below, and sheds an approval
level. Never cache the chain across an edit.

**City tiers are only half specified.** The policy enumerates Tier 1. The Tier 2 list is seeded
and carries `source: assumption`; an unrecognised city falls to Tier 3, the most conservative
limit, and is flagged for Finance to confirm. Do not quietly promote a city to Tier 2 because it
seems large.

## Adding a rule

1. Add the function to the right module under `policy/rules/`, registered with a new `rule_id`
   and the clause it cites.
2. Add any thresholds it needs to the policy YAML — a magic number in a rule body is a bug the
   next revision will surface.
3. Add a test in `tests/test_policy_rules.py` with a case that fires and a case that does not.
4. If it changes a settlement figure for the sample trip, update
   `tests/test_acceptance_nortex_trip.py`. If it changes one you did not expect, the rule is
   probably wrong.

## Adding a policy version

Add a YAML under `policy/versions/` with its own `effective_from`, close the previous version's
`effective_to`, and extend the seed. Do not edit a version that has already evaluated a claim.
