# -*- coding: utf-8 -*-
"""Fund allocation request.

Moves money from a fund account's unassigned balance to a project or expense
head, going through the shared GM -> MD approval workflow. The "hold while
pending" and "assigned when approved" behaviour is achieved purely through the
computed balances on :class:`nn.fund.account` and :class:`nn.fund.target`,
which key off this record's ``state``. That means rejecting or cancelling a
request automatically returns the money - there is no manual balance writing
to get wrong.
"""

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class FundAllocation(models.Model):
    _name = "nn.fund.allocation"
    _description = "Fund Allocation Request"
    _inherit = ["nn.approval.mixin"]
    _order = "request_date desc, id desc"

    _approval_type = "allocation"

    fund_account_id = fields.Many2one(
        "nn.fund.account", string="Fund Account", required=True,
        ondelete="restrict", tracking=True,
    )
    target_id = fields.Many2one(
        "nn.fund.target", string="Project / Expense Head", required=True,
        ondelete="restrict", tracking=True,
    )
    target_type = fields.Selection(
        related="target_id.target_type", string="Target Type", store=True,
    )
    amount = fields.Monetary(
        string="Amount", required=True, tracking=True,
    )
    purpose = fields.Text(string="Purpose")
    attachment_ids = fields.Many2many(
        "ir.attachment", string="Attachments")

    # Convenience: live snapshot of the source account's free balance, shown
    # on the form so the requester sees what is available before submitting.
    account_available = fields.Monetary(
        related="fund_account_id.available_balance",
        string="Account Available", readonly=True,
    )

    @api.constrains("amount")
    def _check_amount_positive(self):
        for rec in self:
            if rec.amount <= 0:
                raise ValidationError(_("Amount must be greater than zero."))

    def _get_approval_amount(self):
        self.ensure_one()
        return self.amount

    def _validate_submit(self):
        """Block submission if the account does not have enough free money.

        At this point the record is still ``draft`` so the account's
        ``available_balance`` excludes it - a direct comparison is correct.
        """
        for rec in self:
            available = rec.fund_account_id.available_balance
            if rec.amount > available:
                raise ValidationError(_(
                    "Cannot allocate %(amount)s: only %(available)s is "
                    "available (unassigned) in account '%(account)s'."
                ) % {
                    "amount": rec.amount,
                    "available": available,
                    "account": rec.fund_account_id.display_name,
                })
        return True

    def _on_submit(self):
        # Nothing to do: the account's stored balances depend on the
        # allocation state, so Odoo recomputes ``held_amount`` automatically
        # the moment this record moves to ``submitted``. Calling the compute
        # method directly here would instead perform an ACL-checked write on
        # the account, which the requesting Fund User is not allowed to do.
        return True
