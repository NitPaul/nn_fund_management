# -*- coding: utf-8 -*-
"""Fund target = a project OR an expense head.

A single model with a ``target_type`` selector represents both projects and
expense heads. Because a transaction must use *either* a project *or* an
expense head (never both), one model with one ``target_id`` reference on the
documents keeps every relationship clean and makes transfers between any
combination trivial.

Every balance here is computed from the state of the related records, so the
same money is never available twice and the figures cannot be edited by hand.
"""

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class FundTarget(models.Model):
    _name = "nn.fund.target"
    _description = "Fund Target (Project / Expense Head)"
    _inherit = ["mail.thread"]
    _order = "target_type, name"

    name = fields.Char(string="Name", required=True, tracking=True)
    target_type = fields.Selection(
        [("project", "Project"), ("expense_head", "Expense Head")],
        string="Type", required=True, default="project", tracking=True,
    )
    code = fields.Char(string="Code")
    company_id = fields.Many2one(
        "res.company", string="Company", required=True,
        default=lambda self: self.env.company, index=True,
    )
    currency_id = fields.Many2one(
        "res.currency", related="company_id.currency_id", store=True,
        readonly=True,
    )
    active = fields.Boolean(default=True)

    allocation_ids = fields.One2many(
        "nn.fund.allocation", "target_id", string="Allocations")
    requisition_ids = fields.One2many(
        "nn.fund.requisition", "target_id", string="Requisitions")
    bill_ids = fields.One2many(
        "nn.fund.bill", "target_id", string="Bills")
    transfer_out_ids = fields.One2many(
        "nn.fund.transfer", "source_id", string="Outgoing Transfers")
    transfer_in_ids = fields.One2many(
        "nn.fund.transfer", "destination_id", string="Incoming Transfers")

    # --- Computed balances ------------------------------------------------
    total_allocated = fields.Monetary(
        string="Total Allocated", compute="_compute_balances", store=True)
    incoming_transfers = fields.Monetary(
        string="Incoming Transfers", compute="_compute_balances", store=True)
    outgoing_transfers = fields.Monetary(
        string="Outgoing Transfers", compute="_compute_balances", store=True)
    requisition_hold = fields.Monetary(
        string="Requisition Hold", compute="_compute_balances", store=True,
        help="Reserved by requisitions awaiting approval.")
    transfer_hold = fields.Monetary(
        string="Transfer Hold", compute="_compute_balances", store=True,
        help="Reserved by outgoing transfers awaiting approval.")
    approved_unspent = fields.Monetary(
        string="Approved but Unspent", compute="_compute_balances",
        store=True,
        help="Approved requisition amounts still available to be billed.")
    total_spent = fields.Monetary(
        string="Total Spent", compute="_compute_balances", store=True,
        help="Posted bills against this target.")
    available_fund = fields.Monetary(
        string="Available Fund", compute="_compute_balances", store=True,
        help="Money free to be requisitioned or transferred out.")

    @api.depends(
        "allocation_ids.state", "allocation_ids.amount",
        "requisition_ids.state", "requisition_ids.requested_amount",
        "requisition_ids.remaining_billable_amount",
        "transfer_out_ids.state", "transfer_out_ids.amount",
        "transfer_in_ids.state", "transfer_in_ids.amount",
        "bill_ids.state", "bill_ids.amount",
    )
    def _compute_balances(self):
        for target in self:
            allocated = sum(target.allocation_ids.filtered(
                lambda a: a.state == "approved").mapped("amount"))
            incoming = sum(target.transfer_in_ids.filtered(
                lambda t: t.state == "approved").mapped("amount"))
            outgoing = sum(target.transfer_out_ids.filtered(
                lambda t: t.state == "approved").mapped("amount"))
            req_hold = sum(target.requisition_ids.filtered(
                lambda r: r.state in ("submitted", "gm_approval")
            ).mapped("requested_amount"))
            trf_hold = sum(target.transfer_out_ids.filtered(
                lambda t: t.state in ("submitted", "gm_approval")
            ).mapped("amount"))
            # Approved requisitions reserve only their *remaining* billable
            # amount; the portion already billed is counted under total_spent.
            unspent = sum(target.requisition_ids.filtered(
                lambda r: r.state == "approved"
            ).mapped("remaining_billable_amount"))
            spent = sum(target.bill_ids.filtered(
                lambda b: b.state == "posted").mapped("amount"))

            target.total_allocated = allocated
            target.incoming_transfers = incoming
            target.outgoing_transfers = outgoing
            target.requisition_hold = req_hold
            target.transfer_hold = trf_hold
            target.approved_unspent = unspent
            target.total_spent = spent
            target.available_fund = (
                allocated + incoming - outgoing
                - req_hold - trf_hold - unspent - spent
            )

    @api.constrains("available_fund")
    def _check_no_negative(self):
        for target in self:
            if target.available_fund < 0:
                raise ValidationError(_(
                    "Target '%s' would have a negative available balance. "
                    "The operation has been blocked to prevent double "
                    "spending."
                ) % target.display_name)

    def name_get(self):
        result = []
        type_label = dict(
            self._fields["target_type"].selection)
        for rec in self:
            label = "%s (%s)" % (rec.name, type_label.get(rec.target_type))
            result.append((rec.id, label))
        return result
