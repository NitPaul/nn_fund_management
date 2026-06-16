# -*- coding: utf-8 -*-
"""Incoming funds recording.

Money received into a fund account. Only *confirmed* incoming funds count
towards the account's unassigned balance, and the same transaction reference
can never be confirmed twice within one account (a hard database constraint).
"""

from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError


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
                vals["name"] = self.env["ir.sequence"].next_by_code(
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
