# Demo Script — Screen Recording Walkthrough

Use this script to record the submission video. Keep it short (aim 6–10 min).
Turn your **facecam on** (required by the brief). Speak to each point in the
"What to say" callouts — these map to the video-explanation checklist.

## Before you record
* `docker compose up -d --build`, open <http://localhost:8069>, create a DB
  **with demo data**, install **NN Fund Management**.
* Have these demo logins ready (password `demo`):
  `fund.user@demo.com`, `finance@demo.com`, `gm@demo.com`, `md@demo.com`.
* Open the module: **Fund Management** app.

## Intro (30s)
> "This is the NN Fund Management module for Odoo 17. It tracks money from
> receipt through allocation, approval, requisition, billing and transfers, and
> it guarantees the same money can't be spent twice. I'll run the official
> 13-step scenario, then show the security and code."

---

## Part A — the 13-step sample scenario

| # | Action (in the UI) | What to show / say |
|---|---|---|
| 1 | **Incoming Funds → New**: account *City Bank - Main*, amount **1,000,000**, reference `TXN-001`. As `finance@demo.com`, **Confirm**. | Open the Fund Account: **Available Unassigned = 1,000,000**. "Only confirmed funds count." |
| 2 | **Allocations → New**: account *City Bank*, target *Project A*, amount **600,000**. Submit (as fund user). | Statusbar moves Draft → Submitted. |
| 3 | Open *City Bank* account. | **On Hold = 600,000**, **Available = 400,000**. "Submitting puts the money on hold immediately." |
| 4 | On the allocation, log in as `gm@demo.com` and **Reject**. | Account back to **Available = 1,000,000**, Hold = 0. "Rejecting returns the money automatically — no manual maths." |
| 5 | **Reset to Draft → Submit** again. **GM Approve** (gm), then **MD Approve** (md). | State → Approved. Project A: **Total Allocated = 600,000**, **Available = 600,000**. "GM must approve before MD." |
| 6 | **Transfers → New**: source *Project A*, destination *Project B*, amount **200,000**. Submit. | — |
| 7 | Open *Project A*. | **Transfer Hold = 200,000**, **Available = 400,000**; Project B still 0. "Pending transfer is held and can't be reused." |
| 8 | Approve the transfer (GM then MD). | Project B: **Available = 200,000**. |
| 9 | **Requisitions → New**: target *Project B*, amount **150,000**. Submit → GM → MD approve. | Project B **Requisition Hold = 150,000** while pending; after approval **Approved but Unspent = 150,000**, Remaining Billable = 150,000. |
| 10 | **Bills → New**: requisition = the approved one, amount **100,000**. **Post** (as finance). | Project B **Total Spent = 100,000**. |
| 11 | Open the requisition. | **Remaining Billable = 50,000**. |
| 12 | **Bills → New**: same requisition, amount **60,000**. **Post**. | A red error appears: exceeds remaining billable. "Over-billing is blocked." |
| 13 | **Bills → New**: requisition = Project B's, but set **target = Project A**. Try to save/post. | Validation error: target must match the requisition. "Project A can't use Project B's requisition." |

---

## Part A-bonus — bank email integration (30–60s)
As `finance@demo.com`, go to **Operations → Import Bank Email**. A sample
email is pre-filled. Click **Import**.
* An **Incoming Fund** opens in **Pending Verification** with the amount
  (250,000), reference (`TXN-EMAIL-0001`), date and sender parsed from the text.
* **What to say:** "A regex parser turns a bank notification email into a
  pending fund. The same email can't be imported twice — it's deduplicated by
  the email Message-ID — and a duplicate transaction reference is rejected.
  It stays *Pending Verification* until a finance user confirms it, so an email
  alone never moves the balance." Optionally set a **Message-ID**, Import, then
  Import again with the same ID to show it returns the same record (no copy).

---

## Part B — security & integrity (1–2 min)
* Log in as `fund.user@demo.com`: show they **cannot** see the *Configuration*
  menu and only see **their own** requests.
* Show that the GM **GM Approve** button is hidden for the fund user, and that
  even calling it is blocked server-side (mention the `_check_group` method).
* Show the **balance fields are greyed out / read-only** everywhere.
* Open **Audit → Fund History**: every action is logged with actor and time.

## Part C — code (2–3 min)
Open the repo in your editor and walk through:
* `models/approval_mixin.py` — "the GM→MD workflow is written once and reused."
* the computed balances in `models/fund_account.py` and `models/fund_target.py`
  — "balances come from record state, which is why money can't be double-spent."
* `security/ir.model.access.csv` + `security/fund_security.xml`.
* `tests/test_fund_flow.py` — run `docker compose run --rm odoo odoo -d testdb
  -i nn_fund_management --test-enable --stop-after-init` and show it passing.

## Required spoken checklist (don't skip — the brief asks for these)
- **AI tools used**: which assistant(s) you used.
- **Implemented features**: list what works.
- **Which parts were AI-assisted** vs hand-written.
- **Important prompts** you gave.
- **Errors found in AI-generated code** and how you fixed them.
- **Changes you made** to the generated code.
- **Known limitations** (bank email not shipped; concurrency note).
- **Which parts you fully understand** — talk through the balance compute and
  the approval mixin in your own words (see `INTERVIEW_PREP.md`).
