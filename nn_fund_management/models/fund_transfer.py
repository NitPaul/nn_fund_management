# -*- coding: utf-8 -*-
"""Fund transfer between projects / expense heads.

Moves available money from a source target to a destination target through the
shared approval workflow. While pending, the amount is held on the source (so
it cannot be spent, requisitioned or transferred again); once approved it is
credited to the destination. Both effects come from the computed balances
keyed on this record's ``state``.
"""

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class FundTransfer(models.Model):
    _name = "nn.fund.transfer"
    _description = "Fund Transfer"
    _inherit = ["nn.approval.mixin"]
    _order = "request_date desc, id desc"

    _approval_type = "transfer"

    source_id = fields.Many2one(
        "nn.fund.target", string="Source", required=True,
        ondelete="restrict", tracking=True,
    )
    destination_id = fields.Many2one(
        "nn.fund.target", string="Destination", required=True,
        ondelete="restrict", tracking=True,
    )
    amount = fields.Monetary(
        string="Amount", required=True, tracking=True,
    )
    reason = fields.Text(string="Reason")

    source_available = fields.Monetary(
        related="source_id.available_fund", string="Source Available",
        readonly=True)

    @api.constrains("amount")
    def _check_amount_positive(self):
        for rec in self:
            if rec.amount <= 0:
                raise ValidationError(_("Amount must be greater than zero."))

    @api.constrains("source_id", "destination_id")
    def _check_source_destination(self):
        for rec in self:
            if rec.source_id == rec.destination_id:
                raise ValidationError(_(
                    "The source and destination cannot be the same target."))

    def _get_approval_amount(self):
        self.ensure_one()
        return self.amount

    def _validate_submit(self):
        for rec in self:
            if rec.source_id == rec.destination_id:
                raise ValidationError(_(
                    "The source and destination cannot be the same target."))
            available = rec.source_id.available_fund
            if rec.amount > available:
                raise ValidationError(_(
                    "Cannot transfer %(amount)s: only %(available)s is "
                    "available under the source '%(source)s'."
                ) % {
                    "amount": rec.amount,
                    "available": available,
                    "source": rec.source_id.display_name,
                })
        return True
