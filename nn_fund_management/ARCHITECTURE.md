# Architecture — NN Fund Management

This document explains *how* the module is built and *why* the key decisions
were made. It is the companion to the user-facing `README.md`.

## 1. Design goals

The single most important requirement is integrity: **the same money can never
be allocated, transferred or spent twice.** Every design choice below serves
that goal, plus the secondary goals of clean Odoo modelling, reusable approval
logic and server-side security.

## 2. Models at a glance

| Model | Role |
|---|---|
| `nn.fund.account` | A bank / cash / other account. Holds received money. |
| `nn.incoming.fund` | A single receipt into an account. |
| `nn.fund.target` | A **project or expense head** (unified, see §3). |
| `nn.approval.mixin` | Abstract reusable approval workflow (see §4). |
| `nn.fund.allocation` | Moves money account → target. |
| `nn.fund.requisition` | Reserves target money for spending. |
| `nn.fund.bill` | Actual spend against an approved requisition. |
| `nn.fund.transfer` | Moves money target → target. |
| `nn.approval.line` | One audit row per approval/rejection decision. |
| `nn.fund.history` | Structured audit log of every financial action. |
| `nn.approval.rule` | Configurable routing (when is MD required?). |

## 3. Why one `nn.fund.target` instead of two models

The brief says *"a transaction must use either a project or an expense head,
not both."* Two natural designs exist:

* **Two models** (`nn.project`, `nn.expense.head`) + two nullable Many2one
  fields on every document + a constraint that exactly one is set. Transfers
  then need four fields (source project/expense, destination project/expense).
* **One model** `nn.fund.target` with a `target_type` selector. Every document
  references a single `target_id`. Transfers are just `source_id` →
  `destination_id`, both targets, so *any* combination
  (project↔project, project↔expense, …) works with no special cases.

The unified model is chosen because it keeps every relationship to a single
field, makes the computed-balance code identical for projects and expense
heads, and is trivial to explain: *"a fund target is anything money can be
allocated to; a flag says whether it's a project or an expense head."*

## 4. The reusable approval workflow (`nn.approval.mixin`)

Allocations, requisitions and transfers share the **exact** same approval
rules. Rather than copy them three times, they live once in an
`AbstractModel`:

```
Draft ──submit──> Submitted ──GM approve──> GM Approval ──MD approve──> Approved
                      │                          │
                      └────── reject / cancel ───┴──> Rejected / Cancelled
```

The mixin provides:

* the `state` field and the `name`, `requested_by`, `request_date`,
  `company_id`, `currency_id` common fields;
* the action methods `action_submit`, `action_gm_approve`,
  `action_md_approve`, `action_reject`, `action_cancel`,
  `action_reset_to_draft`;
* the server-side approver checks (group membership, GM-before-MD, no
  self-approval);
* document numbering via `ir.sequence`;
* notifications via Odoo activities.

Concrete models customise behaviour by overriding small **hooks**:

| Hook | Purpose |
|---|---|
| `_get_approval_amount()` | Which monetary field drives approval rules. |
| `_validate_submit()` | Raise if there are not enough funds to submit. |
| `_on_submit / _on_approve / _on_reject / _on_cancel` | Optional side effects. |

Because the transition into `approved` happens in one guarded place
(`_set_approved`), `_on_approve` runs **exactly once** — *"repeated approval
actions do not create duplicate fund movements."*

### Configurable levels (`nn.approval.rule`)

`md_required` is **computed** from the most specific matching approval rule
(by request type, amount band and company). If no rule matches, the safe
default is "MD required". When a rule turns MD off, GM approval transitions
straight to `approved`. Approvers are therefore configured by **security
group + data rules**, never hard-coded user IDs.

## 5. Balances are computed from state — the anti-double-spend core

No code ever writes a balance. Instead each balance is a `@api.depends`
compute that sums the related records **filtered by their state**:

**Fund account**
```
total_received = Σ confirmed incoming funds
held_amount    = Σ allocations in (submitted, gm_approval)     # pending hold
total_assigned = Σ allocations in (approved)
available      = total_received − held_amount − total_assigned
```

**Fund target**
```
total_allocated     = Σ approved allocations
incoming_transfers  = Σ approved transfers in
outgoing_transfers  = Σ approved transfers out
requisition_hold    = Σ requested_amount of requisitions in (submitted, gm_approval)
transfer_hold       = Σ amount of outgoing transfers in (submitted, gm_approval)
approved_unspent    = Σ remaining_billable of requisitions in (approved)
total_spent         = Σ amount of posted bills
available_fund      = total_allocated + incoming_transfers − outgoing_transfers
                      − requisition_hold − transfer_hold − approved_unspent − total_spent
```

**Why this prevents double spending:** a pending request *is* a hold the moment
its state changes, so the same money instantly drops out of `available`.
Rejecting or cancelling simply moves the record out of the pending states and
the compute returns the money — there is no second place to update and
therefore nothing to forget. `@api.constrains` on `available_balance` /
`available_fund` blocks anything that would push a balance negative, and the
`_validate_submit()` hooks block over-requests up front with a friendly error.

A worked example (the sample demo) is traced step by step in
`../DEMO_SCRIPT.md`.

## 6. Bill control

A bill links to an **approved** requisition. `remaining_billable_amount`
= `requested_amount − Σ posted bills`. On posting, the module checks:

* the requisition is `approved`;
* `bill.target_id == requisition.target_id` (Project A cannot bill Project B's
  requisition — enforced by `@api.constrains` *and* re-checked in
  `action_post`);
* `amount ≤ remaining_billable_amount` (no over-billing; partial bills allowed).

Cancelling a posted bill is a pure state change: the compute stops counting it
as spent, so the amount returns to the requisition **without creating new
funds.**

## 7. Audit & history

Two complementary mechanisms:

* **Chatter** (`mail.thread`) on every document — human-readable message log
  and follower notifications, with field tracking on `state`, amounts, etc.
* **`nn.fund.history`** — a structured, queryable log written on every state
  change with actor, old/new state, amount, related account/target and the
  source document reference. Confirmed financial records cannot be deleted
  (`ondelete` guards + an `unlink` restricted to Fund Administrators), matching
  *"confirmed financial records should not be deleted without a proper
  cancellation or reversal process."*

## 8. Security

* Groups, ACLs and record rules as described in the README's *Security model*.
* Every privileged action is re-checked in Python (`_check_group`,
  `_check_not_own_request`, finance-only confirm, admin-only cancel of
  approved records). Hiding a button is never the only defence.

## 9. Bank email integration (designed, not shipped)

The receiving model already carries `email_message_id` and a
`pending_verification` state. The intended prototype:

1. An incoming-mail alias routes bank notification emails to
   `nn.incoming.fund` via `message_new`.
2. A regex parser extracts bank name, (masked) account number, transaction
   reference, date, amount and sender from the body.
3. A record is created in `pending_verification`, deduplicated by
   `email_message_id` (same email never processed twice) and by the
   `(account, transaction_reference)` SQL unique constraint (duplicate
   references detected). Parsing failures are logged. No real bank credentials
   live in the source.

This is listed under *Known limitations* in the README as the one bonus left
out of the current submission.
