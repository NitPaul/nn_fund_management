# -*- coding: utf-8 -*-
"""Fund accounts (bank / cash / other) and their live balances.

All four balances are *computed* from the underlying records and can never be
edited by hand. This is the foundation of the "money cannot be spent twice"
guarantee: held and assigned amounts are derived from the state of the
allocation records, so the same money is never counted as available twice.
"""

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class FundAccount(models.Model):
    _name = "nn.fund.account"
    _description = "Fund Account"
    _inherit = ["mail.thread"]
    _order = "name"

    name = fields.Char(string="Account Name", required=True, tracking=True)
    account_type = fields.Selection(
        [("bank", "Bank"), ("cash", "Cash"), ("other", "Other")],
        string="Account Type", required=True, default="bank", tracking=True,
    )
    code = fields.Char(string="Reference / Account No.")
    company_id = fields.Many2one(
        "res.company", string="Company", required=True,
        default=lambda self: self.env.company, index=True,
    )
    currency_id = fields.Many2one(
        "res.currency", related="company_id.currency_id", store=True,
        readonly=True,
    )
    active = fields.Boolean(default=True)

    incoming_fund_ids = fields.One2many(
        "nn.incoming.fund", "fund_account_id", string="Incoming Funds",
    )
    allocation_ids = fields.One2many(
        "nn.fund.allocation", "fund_account_id", string="Allocations",
    )

    # --- Computed balances (read-only, never manually editable) ----------
    total_received = fields.Monetary(
        string="Total Received", compute="_compute_balances", store=True,
    )
    held_amount = fields.Monetary(
        string="On Hold", compute="_compute_balances", store=True,
        help="Amount reserved by allocation requests awaiting approval.",
    )
    total_assigned = fields.Monetary(
        string="Total Assigned", compute="_compute_balances", store=True,
        help="Amount allocated to projects / expense heads (approved).",
    )
    available_balance = fields.Monetary(
        string="Available Unassigned", compute="_compute_balances", store=True,
        help="Received minus held minus assigned. This is the money free to "
             "be allocated.",
    )

    @api.depends(
        "incoming_fund_ids.state", "incoming_fund_ids.amount",
        "allocation_ids.state", "allocation_ids.amount",
    )
    def _compute_balances(self):
        for account in self:
            received = sum(account.incoming_fund_ids.filtered(
                lambda f: f.state == "confirmed").mapped("amount"))
            # Pending allocations (awaiting approval) hold money.
            held = sum(account.allocation_ids.filtered(
                lambda a: a.state in ("submitted", "gm_approval")
            ).mapped("amount"))
            # Approved allocations have left the unassigned pool.
            assigned = sum(account.allocation_ids.filtered(
                lambda a: a.state == "approved").mapped("amount"))
            account.total_received = received
            account.held_amount = held
            account.total_assigned = assigned
            account.available_balance = received - held - assigned

    @api.constrains("available_balance")
    def _check_no_negative(self):
        for account in self:
            if account.available_balance < 0:
                raise ValidationError(_(
                    "Fund account '%s' would have a negative available "
                    "balance. The operation has been blocked to prevent "
                    "double spending."
                ) % account.display_name)
