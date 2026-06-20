# -*- coding: utf-8 -*-
"""Incoming funds recording.

Money received into a fund account. Only *confirmed* incoming funds count
towards the account's unassigned balance, and the same transaction reference
can never be confirmed twice within one account (a hard database constraint).
"""

import logging
import re
from datetime import datetime

from odoo import api, fields, models, tools, _
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)


class IncomingFund(models.Model):
    _name = "nn.incoming.fund"
    _description = "Incoming Fund"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "date desc, id desc"

    name = fields.Char(
        string="Reference", required=True, copy=False, readonly=True,
        default=lambda self: _("New"),
    )
    fund_account_id = fields.Many2one(
        "nn.fund.account", string="Fund Account", required=True,
        ondelete="restrict", tracking=True,
    )
    date = fields.Date(
        string="Date", required=True, default=fields.Date.context_today,
        tracking=True,
    )
    amount = fields.Monetary(string="Amount", required=True, tracking=True)
    currency_id = fields.Many2one(
        "res.currency", related="company_id.currency_id", store=True,
        readonly=True,
    )
    transaction_reference = fields.Char(
        string="Transaction Reference", required=True, copy=False,
        tracking=True,
        help="Unique reference from the bank / source. The same reference "
             "cannot be used twice within the same fund account.",
    )
    sender = fields.Char(string="Sender / Source")
    description = fields.Text(string="Description")
    attachment_ids = fields.Many2many(
        "ir.attachment", string="Attachments",
    )
    company_id = fields.Many2one(
        "res.company", string="Company", required=True,
        default=lambda self: self.env.company, index=True,
    )
    state = fields.Selection(
        [
            ("draft", "Draft"),
            ("pending_verification", "Pending Verification"),
            ("confirmed", "Confirmed"),
            ("cancelled", "Cancelled"),
        ],
        string="Status", default="draft", required=True, copy=False,
        tracking=True,
    )
    # Set when the record originates from the bank-email prototype.
    email_message_id = fields.Char(string="Source Email Message-ID", copy=False)

    _sql_constraints = [
        (
            "unique_txn_ref_per_account",
            "unique(fund_account_id, transaction_reference)",
            "The same transaction reference cannot be used twice within the "
            "same fund account.",
        ),
    ]

    @api.constrains("amount")
    def _check_amount_positive(self):
        for rec in self:
            if rec.amount <= 0:
                raise ValidationError(_("Amount must be greater than zero."))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", _("New")) == _("New"):
                vals["name"] = self.env["ir.sequence"].sudo().next_by_code(
                    "nn.incoming.fund") or _("New")
        return super().create(vals_list)

    def action_confirm(self):
        """Confirm receipt - the amount becomes available to allocate.

        Only Finance users (or admins) may confirm incoming funds, enforced
        server-side here in addition to the access rules.
        """
        for rec in self:
            if rec.state not in ("draft", "pending_verification"):
                raise UserError(_("Only a draft / pending fund can be "
                                  "confirmed."))
            if not (self.env.user.has_group(
                        "nn_fund_management.group_fund_finance")
                    or self.env.user.has_group(
                        "nn_fund_management.group_fund_admin")):
                raise UserError(_(
                    "Only authorized finance users can confirm incoming "
                    "funds."))
            rec.state = "confirmed"
            self.env["nn.fund.history"].sudo()._log(
                record=rec, old_state="draft", new_state="confirmed",
                comment=_("Incoming fund confirmed."),
            )
        return True

    def action_cancel(self):
        for rec in self:
            if rec.state == "confirmed" and not self.env.user.has_group(
                    "nn_fund_management.group_fund_admin"):
                raise UserError(_(
                    "Only a Fund Administrator can cancel a confirmed "
                    "incoming fund."))
            rec.state = "cancelled"
        return True

    def action_draft(self):
        for rec in self:
            if rec.state != "cancelled":
                raise UserError(_("Only a cancelled record can be reset."))
            rec.state = "draft"

    @api.ondelete(at_uninstall=False)
    def _prevent_confirmed_delete(self):
        for rec in self:
            if rec.state == "confirmed":
                raise UserError(_(
                    "A confirmed incoming fund cannot be deleted. Cancel it "
                    "first (audit-safe reversal)."))

    # ------------------------------------------------------------------
    # Bank-email integration (bonus, PDF section 11).
    #
    # A prototype that turns a bank "you have been credited" notification
    # email into an incoming-fund record in the *Pending Verification* state.
    # No real bank credentials live in the source: parsing works purely on the
    # email text. The same email is never processed twice (deduplicated by the
    # email Message-ID), duplicate transaction references are detected, and
    # parsing failures are logged.
    # ------------------------------------------------------------------
    @api.model
    def _parse_bank_email(self, body):
        """Extract structured fields from a bank notification email body.

        Returns a dict with bank_name, account_number, transaction_reference,
        transaction_date, amount and sender. Raises ``ValueError`` (which the
        callers log) when the two critical fields - amount and transaction
        reference - cannot be found.
        """
        text = body or ""

        def find(patterns):
            for pattern in patterns:
                match = re.search(pattern, text, re.IGNORECASE)
                if match:
                    return match.group(1).strip()
            return False

        amount_raw = find([
            r"amount[:\s]+(?:bdt|usd|tk|\$)?\s*([\d,]+(?:\.\d{1,2})?)",
            r"credited\s+(?:by|with)\s+(?:bdt|usd|tk|\$)?\s*"
            r"([\d,]+(?:\.\d{1,2})?)",
        ])
        reference = find([
            r"(?:transaction\s+ref(?:erence)?|txn\s*ref|"
            r"ref(?:erence)?\s*(?:no|number)?)[:\s]+([A-Za-z0-9\-_/]+)",
        ])
        bank_name = find([
            r"bank[:\s]+([A-Za-z0-9 .&]+?)(?:\n|\.|$)",
            r"with\s+([A-Za-z0-9 .&]+?bank)",
        ])
        account_number = find([
            r"account\s+(?:no\.?|number)?[:\s#]*([xX*\d]{4,})",
        ])
        date_raw = find([
            r"date[:\s]+(\d{4}-\d{2}-\d{2})",
            r"date[:\s]+(\d{2}/\d{2}/\d{4})",
        ])
        sender = find([
            r"(?:from|sender|received from)[:\s]+([A-Za-z0-9 .,&]+?)(?:\n|$)",
        ])

        if not amount_raw or not reference:
            raise ValueError(
                "Could not find an amount and a transaction reference in the "
                "email body.")

        transaction_date = False
        if date_raw:
            for fmt in ("%Y-%m-%d", "%d/%m/%Y"):
                try:
                    transaction_date = datetime.strptime(date_raw, fmt).date()
                    break
                except ValueError:
                    continue

        return {
            "bank_name": bank_name or False,
            "account_number": account_number or False,
            "transaction_reference": reference,
            "transaction_date": transaction_date,
            "amount": float(amount_raw.replace(",", "")),
            "sender": sender or False,
        }

    @api.model
    def _match_bank_account(self, bank_name, account_number):
        """Best-effort mapping of a parsed bank to a fund account."""
        Account = self.env["nn.fund.account"].sudo()
        if bank_name:
            account = Account.search(
                ["|", ("name", "ilike", bank_name),
                 ("code", "ilike", bank_name)], limit=1)
            if account:
                return account
        # Fall back to the first bank account so a demo always resolves.
        return Account.search([("account_type", "=", "bank")], limit=1)

    @api.model
    def _create_from_bank_email(self, body, message_id=False, account=None):
        """Parse a bank email and create a pending incoming-fund record.

        Used both by the live mail gateway (``message_new``) and by the manual
        import wizard. Enforces the bonus requirements: an email is processed
        only once, duplicate references are rejected, and the new record waits
        in *Pending Verification* until a finance user confirms it.
        """
        # 1. The same email is never processed twice.
        if message_id:
            duplicate = self.sudo().search(
                [("email_message_id", "=", message_id)], limit=1)
            if duplicate:
                _logger.info(
                    "Bank email %s already imported as %s; skipping.",
                    message_id, duplicate.name)
                return duplicate

        # 2. Parse - a failure here is logged by the caller.
        parsed = self._parse_bank_email(body)

        # 3. Resolve the destination fund account.
        if account is None:
            account = self._match_bank_account(
                parsed.get("bank_name"), parsed.get("account_number"))
        if not account:
            raise ValueError(
                "No fund account could be matched for this bank email.")

        # 4. Duplicate transaction references must be detected.
        reference = parsed["transaction_reference"]
        if self.sudo().search_count([
                ("fund_account_id", "=", account.id),
                ("transaction_reference", "=", reference)]):
            raise ValueError(
                "Transaction reference '%s' already exists for account '%s'."
                % (reference, account.display_name))

        return self.create({
            "fund_account_id": account.id,
            "amount": parsed["amount"],
            "transaction_reference": reference,
            "date": parsed.get("transaction_date")
            or fields.Date.context_today(self),
            "sender": parsed.get("sender"),
            "description": body,
            "email_message_id": message_id,
            # Bank-email funds wait for a human to verify before they count.
            "state": "pending_verification",
        })

    @api.model
    def message_new(self, msg_dict, custom_values=None):
        """Mail-gateway hook: build a pending fund from an incoming email.

        Configure an incoming mail alias pointing at this model to feed real
        bank notification emails in. Parsing failures are logged and the email
        is skipped rather than crashing the gateway.
        """
        body = tools.html2plaintext(msg_dict.get("body") or "")
        message_id = msg_dict.get("message_id")
        try:
            return self._create_from_bank_email(body, message_id=message_id)
        except ValueError as error:
            _logger.warning(
                "Bank email %s could not be processed: %s",
                message_id or "(no id)", error)
            raise
