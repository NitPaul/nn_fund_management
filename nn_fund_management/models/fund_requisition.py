# -*- coding: utf-8 -*-
"""Fund requisition.

A request to use money already available under a project or expense head.
While pending it holds the target balance; once approved the amount is
reserved for bills. The remaining billable amount drives bill control, and a
requisition can be closed once fully billed or to release the unused balance.
"""

from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError


class FundRequisition(models.Model):
    _name = "nn.fund.requisition"
    _description = "Fund Requisition"
    _inherit = ["nn.approval.mixin"]
    _order = "request_date desc, id desc"

    _approval_type = "requisition"

    # Add a "closed" state to the shared workflow.
    state = fields.Selection(
        selection_add=[("closed", "Closed")],
        ondelete={"closed": "set default"},
    )

    target_id = fields.Many2one(
        "nn.fund.target", string="Project / Expense Head", required=True,
        ondelete="restrict", tracking=True,
    )
    target_type = fields.Selection(
        related="target_id.target_type", store=True)
    requested_amount = fields.Monetary(
        string="Requested Amount", required=True, tracking=True,
    )
    purpose = fields.Text(string="Purpose")
    required_date = fields.Date(string="Required Date")
    attachment_ids = fields.Many2many(
        "ir.attachment", string="Supporting Attachments")

    bill_ids = fields.One2many(
        "nn.fund.bill", "requisition_id", string="Bills")
    billed_amount = fields.Monetary(
        string="Billed Amount", compute="_compute_billed", store=True)
    remaining_billable_amount = fields.Monetary(
        string="Remaining Billable", compute="_compute_billed", store=True,
        help="Approved amount still available to bill against.")

    target_available = fields.Monetary(
        related="target_id.available_fund", string="Target Available",
        readonly=True)

    @api.depends("bill_ids.state", "bill_ids.amount", "requested_amount",
                 "state")
    def _compute_billed(self):
        for rec in self:
            billed = sum(rec.bill_ids.filtered(
                lambda b: b.state == "posted").mapped("amount"))
            rec.billed_amount = billed
            rec.remaining_billable_amount = rec.requested_amount - billed

    @api.constrains("requested_amount")
    def _check_amount_positive(self):
        for rec in self:
            if rec.requested_amount <= 0:
                raise ValidationError(_(
                    "Requested amount must be greater than zero."))

    def _get_approval_amount(self):
        self.ensure_one()
        return self.requested_amount

    def _validate_submit(self):
        for rec in self:
            available = rec.target_id.available_fund
            if rec.requested_amount > available:
                raise ValidationError(_(
                    "Cannot requisition %(amount)s: only %(available)s is "
                    "available under '%(target)s'."
                ) % {
                    "amount": rec.requested_amount,
                    "available": available,
                    "target": rec.target_id.display_name,
                })
        return True

    def action_close(self):
        """Close the requisition, releasing any unused (un-billed) amount.

        Because the target's ``approved_unspent`` only counts requisitions in
        the ``approved`` state, moving to ``closed`` automatically returns the
        unused balance to the target - no manual balance writing.
        """
        for rec in self:
            if rec.state != "approved":
                raise UserError(_(
                    "Only an approved requisition can be closed."))
            old = rec.state
            rec.state = "closed"
            self.env["nn.fund.history"].sudo()._log(
                record=rec, old_state=old, new_state=rec.state,
                comment=_("Requisition closed; unused amount released."),
            )
        return True

    def _on_approve(self):
        # Notify when a requisition is almost fully used is handled when bills
        # are posted; nothing extra needed here (balances are computed).
        return True
