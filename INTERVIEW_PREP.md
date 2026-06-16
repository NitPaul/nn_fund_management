# Interview Preparation — NN Fund Management

This is your study guide for the technical interview. The assessment lists the
exact things you may be asked (section 16). Each one is answered below in plain
language, with the file to open and a short script you can say. Read it twice,
then practise saying the **balance** and **approval** explanations out loud —
those two are the heart of the module.

> Golden rule for the interview: when unsure, fall back to one sentence —
> *"Balances are computed from the state of the records, so money on hold is
> just the sum of pending records; nothing is ever stored and edited by hand."*
> Almost every question traces back to that idea.

---

## 0. The 60-second module summary

"It's an Odoo 17 module that manages company funds. Money comes in to a **fund
account**, gets **allocated** to a **target** — which is either a project or an
expense head — through a **GM then MD approval** workflow. Approved money can be
**requisitioned** and then **billed** when actually spent, or **transferred**
between targets. The key property is that the same money can never be spent
twice, which I achieve by computing every balance from the *state* of the
records instead of storing editable numbers."

---

## 1. Explain how balances are calculated

**File:** `models/fund_account.py` and `models/fund_target.py`
(the `_compute_balances` methods).

**Say this:**
"No code ever writes a balance. Each balance is an `@api.depends` computed
field that sums related records filtered by their state. For a fund account:

* **received** = sum of *confirmed* incoming funds,
* **held** = sum of allocations that are *submitted or awaiting MD* (pending),
* **assigned** = sum of *approved* allocations,
* **available = received − held − assigned**.

For a target it's the same idea but with allocations in, transfers in/out,
requisition holds, approved-but-unspent requisitions and posted bills. Because
the fields are computed, the moment a record changes state the numbers
recalculate. I also `store=True` them so they're searchable and fast, and Odoo
recomputes them automatically when a dependency changes."

**Why computed, not stored-editable?** "If I stored a number and updated it on
every action, I'd have two sources of truth and a chance to forget one path.
Computing from state means there is exactly one source of truth."

---

## 2. Demonstrate how double spending is prevented

**Files:** the computes above + `_validate_submit()` in each document +
`@api.constrains` on `available_balance` / `available_fund`.

**Three layers, say all three:**
1. **State-based holds** — submitting an allocation/requisition/transfer
   instantly moves that amount into a "hold" in the compute, so it drops out of
   `available` and can't be picked up by a second request.
2. **Up-front validation** — `_validate_submit()` blocks a request whose amount
   exceeds the current available balance, with a clear error message.
3. **Backstop constraint** — `@api.constrains` refuses to let any balance go
   negative, so even an unexpected path can't corrupt the data.

**Live demo:** allocate almost all of an account, then try to allocate again —
the second submit is blocked. Or show the test `test_02_over_allocation_blocked`.

---

## 3. Add or remove an approval level

**File:** `models/approval_mixin.py` (and the views' header buttons).

The workflow is centralised, so adding a level is a *local* change. Talk
through it:

* To make MD optional you don't touch code at all — you add an **approval
  rule** with *Requires MD Approval* unticked (see Q4). That already lets you
  effectively "remove" the MD level for chosen amounts.
* To add a brand-new level (say a *Finance* approval between GM and MD):
  1. add a `finance_approval` state to `STATE_SELECTION`;
  2. add an `action_finance_approve` method modelled on `action_gm_approve`
     (check the `group_fund_finance` group, move state from `gm_approval` →
     `finance_approval`);
  3. point `action_md_approve` to start from `finance_approval`;
  4. add a button in the three header views.

Because the logic lives in one mixin, all three documents gain the new level at
once — that's the payoff of the reusable design.

---

## 4. Change an approval rule

**File:** data model `nn.approval.rule`; UI at *Configuration → Approval Rules*.

**Say this:** "Approvers aren't hard-coded. `md_required` is computed by
`_match_rule`, which finds the most specific active rule for the request type,
amount band and company. To change behaviour I just edit a rule in the UI — for
example set *‘Above 50,000 → GM + MD’* or add a new band. No code change, no
redeploy." Demonstrate by toggling a rule and showing the **MD Approval
Required** flag flip on a new request.

---

## 5. Explain what happens when a bill is cancelled

**File:** `models/fund_bill.py` (`action_cancel`).

**Say this:** "Cancelling a posted bill is a pure **state change** to
`cancelled`. The target's `total_spent` only sums *posted* bills and the
requisition's `remaining_billable_amount` is `requested − posted bills`, so the
moment the bill is no longer posted, the compute returns that amount to the
requisition's remaining balance. Crucially **no new funds are created** — the
reversal just stops counting the bill as spent. I also block deleting a posted
bill outright; you must cancel it, which keeps the audit trail intact."

---

## 6. Fix a workflow issue (live)

Be ready to debug on the spot. A safe, impressive example to offer:

> "Right now `action_reject` lets either approver reject. If they wanted
> rejection to require the *current* level only, I'd add the same
> `state`-based guard I use for approval."

Or fix an intentionally introduced bug. General method to narrate:
1. Reproduce it (show the wrong behaviour / failing test).
2. Find the responsible method (`grep` the action name).
3. Make the minimal change.
4. Re-run `tests/test_fund_flow.py` to prove it's fixed.

Mention you can hot-reload with `docker compose restart odoo` and upgrade the
module with `-u nn_fund_management`.

---

## 7. Add a new automated test

**File:** `tests/test_fund_flow.py`.

**Say this:** "Tests subclass `TransactionCase`. `setUpClass` creates one user
per role and the base data. To add a test I write a `test_...` method, build a
record with `with_user(...)` to exercise permissions, run the workflow, and
`assertEqual` the resulting balances or `assertRaises` for blocked actions."

Be ready to *write one live*, e.g. "a cancelled allocation releases the hold":

```python
def test_09_cancel_releases_hold(self):
    self._receive(500000, "TXN-CANCEL")
    alloc = self.env["nn.fund.allocation"].with_user(self.requester).create({
        "fund_account_id": self.account.id,
        "target_id": self.project_a.id,
        "amount": 300000,
    })
    alloc.with_user(self.requester).action_submit()
    self.assertEqual(self.account.held_amount, 300000)
    alloc.with_user(self.requester).action_cancel()
    self.assertEqual(self.account.held_amount, 0)
    self.assertEqual(self.account.available_balance, 500000)
```

Run: `docker compose run --rm odoo odoo -d testdb -i nn_fund_management
--test-enable --stop-after-init`.

---

## 8. Explain how unauthorized approval is blocked

**File:** `models/approval_mixin.py` (`_check_group`, `_check_not_own_request`,
and the state guards) + `security/`.

**Say this — four protections:**
1. **Group check** — `action_gm_approve` calls `_check_group(... group_fund_gm
   _approver ...)`; a non-GM gets a `UserError` even if they craft the call,
   because the check is **server-side**, not a hidden button.
2. **GM before MD** — `action_md_approve` only runs from the `gm_approval`
   state, so MD physically can't go first.
3. **No self-approval** — `_check_not_own_request` blocks approving a request
   you created or that names you as requester, unless you're a Fund
   Administrator.
4. **ACLs + record rules** — approvers have write access; fund users only see
   their own records. Hiding the button is never the only defence.

**Demo:** `test_03_md_cannot_approve_before_gm` and
`test_04_cannot_approve_own_request`.

---

## 9. Demonstrate that pending transfer funds cannot be used

**File:** `models/fund_target.py` (`transfer_hold` in `_compute_balances`).

**Say this:** "When a transfer is submitted, its amount is summed into the
source target's `transfer_hold`, which subtracts from `available_fund`
immediately — before any approval. So a second transfer, requisition or bill
that tries to use that money sees a reduced available balance and is blocked.
Only when the transfer is *approved* does the amount move to the destination;
if it's rejected, the hold disappears and the money is free again."

**Demo:** steps 6–8 of the demo, or assert `project_a.transfer_hold == 200000`
and `available_fund == 400000` right after submit (it's in
`test_01_sample_demonstration`).

---

## 10. Make a small live modification to the module

Have one or two rehearsed, low-risk changes ready. Good candidates:

**A. Add a field** — e.g. a `priority` selection on requisitions:
1. add `priority = fields.Selection([...], default='normal')` in
   `models/fund_requisition.py`;
2. add `<field name="priority"/>` to the form view;
3. `docker compose run --rm odoo odoo -d <db> -u nn_fund_management
   --stop-after-init` then restart, and the field appears.

**B. Add a constraint** — e.g. block requisitions over a hard cap:
```python
@api.constrains("requested_amount")
def _check_cap(self):
    for rec in self:
        if rec.requested_amount > 1000000:
            raise ValidationError(_("Requisitions over 1,000,000 are not allowed."))
```

Narrate the **upgrade cycle**: edit file → `-u nn_fund_management` →
test. Mention that Python changes need a restart; XML view changes need the
`-u` upgrade.

---

## Likely follow-up questions & crisp answers

* **Why one target model?** "A transaction uses a project *or* an expense head,
  never both, so one model with a type flag gives one clean reference and makes
  transfers between any combination trivial."
* **Why a custom bill model instead of `account.move`?** "The brief allows it,
  and it keeps the billing-control rules self-contained and easy to explain."
* **What stops deleting financial records?** "`ondelete` guards on confirmed
  incoming funds and posted bills, and `nn.fund.history.unlink` is restricted
  to admins — you must cancel/reverse, never silently delete."
* **How are notifications done?** "Odoo activities scheduled to the next
  approver group on submit/GM-approve, and an ‘almost fully used’ activity when
  a requisition crosses 90% billed."
* **Multi-company?** "A global record rule filters every model by the user's
  allowed companies."
* **Biggest limitation?** "Bank-email parsing isn't shipped (designed in
  ARCHITECTURE.md), and balance checks aren't row-locked, so a production build
  would add `SELECT … FOR UPDATE` for concurrent submissions."

---

## What to be 100% able to do unaided
1. Open `_compute_balances` and explain each line.
2. Open `approval_mixin.py` and trace a request from submit to approved.
3. Add a field and upgrade the module.
4. Write and run one new test.
5. Point to where each security layer lives.

If you can do those five, you can handle the interview.
