# NN Fund Management — Odoo 17 Custom Module

A custom Odoo module (`nn_fund_management`) that manages company funds end to
end: receiving money, allocating it to projects and expense heads, a
configurable multi-level approval workflow (GM → MD), requisitions, bill
control and transfers — while **guaranteeing the same money can never be
allocated, transferred or spent more than once**.

> Built for the NN Services & Engineering Ltd. Trainee Software Developer
> technical assessment.

---

## Table of contents
1. [Odoo version](#odoo-version)
2. [Required dependencies](#required-dependencies)
3. [Installation instructions](#installation-instructions)
4. [Configuration steps](#configuration-steps)
5. [Testing instructions](#testing-instructions)
6. [Architecture explanation](#architecture-explanation)
7. [Security model](#security-model)
8. [Assumptions](#assumptions)
9. [Known limitations](#known-limitations)
10. [Live deployment](#live-deployment)

---

## Odoo version

* **Odoo 17.0** (Community edition).
* **PostgreSQL 15**.
* **Python 3.10+** (provided by the official `odoo:17.0` Docker image).

---

## Required dependencies

The module only depends on standard Odoo Community modules — **no external
Python libraries or third-party addons are required**:

| Dependency | Why |
|---|---|
| `base` | Core models, users, companies, sequences. |
| `mail` | Chatter (audit trail), activities (notifications), tracking. |

Everything else (`ir.sequence`, `ir.attachment`, security groups, record
rules) is part of Odoo core.

---

## Installation instructions

### Option A — Docker (recommended, fully self-contained)

Prerequisites: **Docker Desktop** (Windows/Mac) or Docker Engine + Compose
(Linux).

```bash
# from the repository root (the folder containing docker-compose.yml)
docker compose up -d --build

# watch the logs until you see "HTTP service (werkzeug) running"
docker compose logs -f odoo
```

Then:

1. Open <http://localhost:8069>.
2. Create a new database (master password is `admin`, set in `config/odoo.conf`).
   Tick **"Load demonstration data"** to get sample accounts, projects and the
   role users described below.
3. Go to **Apps**, remove the "Apps" filter, search **"NN Fund Management"**
   and click **Install**.

### Option B — Existing Odoo 17 instance

1. Copy the `nn_fund_management/` folder into your Odoo `addons` path.
2. Restart Odoo with `--update-list` (or *Apps → Update Apps List*).
3. Install **NN Fund Management** from the Apps menu.

---

## Configuration steps

After installing **with demo data**, you already have everything to run the
demonstration. To configure manually:

1. **Assign roles to users** — *Settings → Users → (a user) → Fund Management*
   section. Roles: Fund User, Finance User, GM Approver, MD Approver, Fund
   Administrator. (Demo users `gm@demo.com`, `md@demo.com`, `finance@demo.com`,
   `fund.user@demo.com` are created automatically, password `demo`.)
2. **Create fund accounts** — *Fund Management → Configuration → Fund Accounts*
   (bank / cash / other).
3. **Create projects & expense heads** — *Fund Management → Configuration →
   Projects / Expense Heads*.
4. **(Optional) Approval rules** — *Fund Management → Configuration → Approval
   Rules*. Define amount bands that decide whether MD approval is required.
   With demo data two rules exist (≤ 50,000 → GM only; > 50,000 → GM + MD).

---

## Testing instructions

The module ships with an automated test suite (`tests/test_fund_flow.py`) that
reproduces the official 13-step sample demonstration plus negative tests for
over-allocation, MD-before-GM, self-approval, duplicate references,
non-editable balances and source = destination transfers.

Run the tests in a throwaway database:

```bash
docker compose run --rm odoo \
  odoo -d testdb -i nn_fund_management --test-enable --stop-after-init
```

A successful run ends with `0 failed, 0 error(s)` and the line
`Modules loaded.` Look for the test logger output near the end.

> Tip: re-running uses the same `testdb`; add `--without-demo=False` is **not**
> needed (tests create their own data). To start clean: `docker compose run
> --rm odoo odoo -d testdb2 -i nn_fund_management --test-enable
> --stop-after-init`.

---

## Architecture explanation

See **[`nn_fund_management/ARCHITECTURE.md`](nn_fund_management/ARCHITECTURE.md)**
for the full write-up. In short:

* **One unified `nn.fund.target` model** represents both projects and expense
  heads (a `target_type` selector). Because a transaction uses *either* a
  project *or* an expense head, a single `target_id` reference keeps every
  document clean and makes transfers between any combination trivial.

* **A reusable approval mixin** (`nn.approval.mixin`, an `AbstractModel`)
  implements the entire Draft → Submitted → GM → MD → Approved workflow once.
  Fund allocations, requisitions and transfers inherit it and only override a
  few hook methods. This is the "reusable approval logic" the brief asks for.

* **All balances are computed from record state, never stored as editable
  numbers.** "Money on hold" is simply the sum of the records currently in a
  pending state. This is the core anti-double-spend mechanism: rejecting or
  cancelling a request automatically returns the money because the compute
  re-runs — there is no manual balance arithmetic to get wrong.

```
nn.fund.account ──< nn.incoming.fund          (received money)
       │
       └──< nn.fund.allocation >── nn.fund.target ──< nn.fund.requisition ──< nn.fund.bill
                   │                     │
            nn.approval.mixin      nn.fund.transfer (source/destination)
                   │
            nn.approval.line  +  nn.fund.history   (audit)
                   │
            nn.approval.rule  (configurable routing)
```

---

## Security model

Security is enforced **server-side**, not by hiding buttons:

* **5 groups**: Fund User, Finance User, GM Approver, MD Approver, Fund
  Administrator (defined in `security/fund_security.xml`).
* **Access control lists** per model × group (`security/ir.model.access.csv`).
* **Record rules**: multi-company isolation (global) + ownership (Fund Users
  see only their own requests; approvers/finance/admin see all).
* **Method-level checks** in the workflow actions: only the right approver can
  approve, GM must precede MD, nobody approves their own request, only finance
  confirms incoming funds, only admins cancel approved/confirmed records.

---

## Assumptions

* A single currency is used (the company currency, e.g. BDT). Multi-currency
  conversion is out of scope.
* "Projects" and "expense heads" are managed inside this module
  (`nn.fund.target`) rather than reusing Odoo's `project.project`, so both
  share identical computed balances and one clean reference type.
* The minimum approval chain is GM → MD; approval **rules** decide whether MD
  is required for a given amount/type, satisfying "approvers are configurable
  and not hardcoded."
* Bills are a custom model (`nn.fund.bill`) rather than `account.move`, which
  the brief explicitly permits, to keep the control logic self-contained.
* Notifications use Odoo **activities** assigned to the first member of the
  relevant approver group (a simple, dependency-free routing choice).

## Known limitations

* **Bank email integration** (section 11 bonus) is implemented as a
  **prototype**, not a production mail pipeline. A regex parser
  (`nn.incoming.fund._parse_bank_email`) extracts the amount, transaction
  reference, date, bank, account and sender from an email body and creates a
  record in the **Pending Verification** state; the same email is never
  processed twice (deduplicated by `email_message_id`), duplicate references
  are rejected and parse failures are logged. It can be driven live from the
  UI via **Operations → Import Bank Email** (paste an email), and the
  `message_new` mail-gateway hook is in place so a real incoming-mail alias can
  feed it. What is *not* shipped is a configured mail server / alias and
  bank-specific templates - the parser targets a generic notification format.
* Concurrency: balance checks compare against computed availability at submit
  time. Two simultaneous submissions in separate transactions could
  theoretically both pass; a production setup would add row-level locking
  (`SELECT ... FOR UPDATE`) on the account/target. Negative-balance
  `@api.constrains` act as a backstop.
* The dashboard is a lightweight kanban + history list (no custom OWL widget),
  which keeps the module free of a JavaScript build step.

---

## Live deployment

The Docker image is self-contained and can be deployed to any container host.
See **[`DEPLOY.md`](DEPLOY.md)** for step-by-step instructions for Render.com
(free tier), Railway and a generic VPS.

---

## Repository contents

| Path | Purpose |
|---|---|
| `nn_fund_management/` | The Odoo module. |
| `nn_fund_management/ARCHITECTURE.md` | Design deep-dive. |
| `docker-compose.yml`, `Dockerfile`, `config/odoo.conf` | Containerisation. |
| `DEPLOY.md` | Live deployment guide. |
| `DEMO_SCRIPT.md` | Screen-recording walkthrough (the 13-step demo). |
| `INTERVIEW_PREP.md` | Study guide for the technical interview. |
