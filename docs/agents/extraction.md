# Evidence extraction

Turning fifteen `.eml` files and two receipt images into typed line items that a policy engine
can reason about.

## Pipeline

```
ingest → classify → extract → reconcile → dedup → attribute → head + Paid By → policy
```

Each stage persists its output. That is what lets any figure on the settlement summary be traced
back to a specific source document, which is the whole point — a number Finance cannot trace is a
number Finance will not pay.

## Adapters

One protocol, two implementations, identical output shape:

- **`RuleBasedExtractor`** — per-sender parsers plus tesseract for images. No credentials, fully
  tested, the default.
- **`LlmExtractor`** — a model with vision and structured output. Activated only when a
  credential is present.

Everything downstream is adapter-agnostic.

The rule-based adapter has two layers. The **per-sender parsers** decompose a bill the way its
sender lays it out, which is what policy needs — a folio is five differently-treated charges,
not one total. Underneath sits a **generic reader** for a vendor nobody wrote a parser for: one
line for the whole bill, taken from a labelled total in the message body or in OCR of its
attachment.

The fallback is deliberately narrow, and the two constraints on it are load-bearing:

- It runs **only when the specific parser produced no lines at all**. Once that parser has read
  even one line, its reconciliation verdict stands — a whole-bill total balances against itself
  and would bury exactly the discrepancy `reconcile.py` exists to surface.
- It **never infers a figure**. No labelled total means needs-input, which is visible in the UI
  and blocks submission. An unlabelled number in a bill is a table number or a PNR as often as
  it is money.

A decomposed read is still strictly better than a generic one, so the LLM seam remains the
answer for reading an unseen vendor properly rather than adding regexes indefinitely.

> The LLM adapter has never been executed. There is no API credential in the build environment.
> It ships as a seam and is described as untested — do not present it as working.

## Classification comes before extraction

Two documents must never reach the extractor:

- **The promotional email.** Noise.
- **The payment-failure notice.** It carries a merchant, a date and an amount, and it is not a
  receipt. The successful receipt for the same ride arrives separately.

Both are recorded so the UI can show they were seen and set aside, rather than looking like
something was missed.

## Two forms of attachment, one thing downstream

Nothing after ingest can read bytes: the OCR adapter and the LLM adapter both take a path. So
`ingest.py` turns both forms a message can carry into a path on disk.

**The pack's form is a placeholder.** Messages 11 and 12 declare
`Content-Transfer-Encoding: base64`, but the part body is the literal text
`[ATTACHMENT: see receipts/<name> in this pack]`. A standard MIME parser produces a part with
nothing decodable in it and both receipt images vanish silently. The placeholder is resolved
against `pack/receipts/`.

**A real mailbox's form is the bytes.** They are written to `extract_dir` under a name derived
from the message (`<message stem>--<attachment name>`), and that path is what the pipeline sees.
The name is derived rather than randomised because a draft claim is recomputed from its evidence
on every read, so the same message is parsed many times and has to find the file it wrote last
time. Every attachment is kept, not only the first — two pages of one folio arrive as two parts.

`extract_dir` has to be writable, which `pack/` is not: callers reading pack mail pass
`settings.extracted_dir` (under `upload_dir`). An upload defaults to the message's own
directory, which already is the upload directory.

## Four things the pack does deliberately

**Attachments are placeholders**, per the section above.

**Consolidated bills must be decomposed.** The hotel folio is not a 21,504 expense. It is three
room charges, a laundry charge, a mini bar charge and an in-room dining charge, each of which the
policy treats differently. A folio captured as one total cannot produce a correct claim.

**OCR loses a line.** Both images have a fold drawn across them. On `hotel_invoice_1188.png` the
fold sits on the second room-charge line:

```
16-Jun Room Charge          5,750.00
Spodun—Reom—Cheange.        5.750.00     ← 17-Jun Room Charge
17-Jun Laundry                450.00
```

The label is destroyed and the amount degrades from `5,750.00` to `5.750.00`. Card digits split
too (`****22 88`). Extracted lines then sum to 13,450 against a stated 19,200 subtotal — a claim
understated by 3,750, reported as a success.

**Identifiers are baited.** The dinner bill's number is `4471`, which is also the claimant's
employee code. The hotel's GSTIN contains `1188`, which is also its invoice number. Match on
position and label, not on a number that happens to look familiar.

## The reconciliation guard

`evidence/reconcile.py` is the answer to the OCR problem, and it is not a workaround — it is what
a system handling money should do regardless of how good the extractor is.

Extracted line items must sum to the document's own stated subtotal. On a mismatch the document
is flagged needs-input, carrying the OCR text and the source image so a human can correct it, and
no claim line is created from the unbalanced set.

Because it sits below the adapters, it protects the LLM path too. **Do not weaken it because
preprocessing improved an OCR result.** Better OCR narrows the failure; it does not close it.

## Amount parsing

Indian formatting, degraded by OCR. Where a value has more than one separator, all but the last
are thousands separators — so `5.750.00` recovers to 5750.00 even though its label is gone. The
line then surfaces as an uncategorised 5,750 needing classification, which is a caught problem
rather than a missing 5,750.

## Dedup and attribution

**Fingerprint** on normalised merchant, transaction timestamp, amount, and bill number where
present. An exact match on all available components collapses; a match on merchant, amount and
date with a differing time warns instead of merging. Suppressions are recorded and shown — a
duplicate silently discarded looks identical to a receipt that was never ingested.

**Attribution** compares the payer or rider name on the evidence against the claim's employee.
A mismatch is rejected with the reason naming whose expense it is. Who forwarded it is
irrelevant, and so is which trip it belongs to.

**`Paid By` comes from the payment evidence, never from the plan.** The sample trip's hotel was
budgeted Company-borne and the booking voucher says "Pay at Hotel"; the invoice shows it settled
on the employee's personal card. Trusting the travel request gets it wrong, and the settlement
form's `SUMIF` keys on that exact word.
