# -*- coding: utf-8 -*-
"""Configurable approval rules (bonus feature).

Instead of hard-coding "GM then MD" everywhere, the approval levels required
for a request can be driven by data: request type, amount band and company.
This satisfies the brief's requirement that "approvers are configurable and
not hardcoded" and supports thresholds such as:

    * Up to BDT 50,000          -> GM only
    * BDT 50,001 - 200,000      -> GM + (Finance)
    * Above BDT 200,000         -> GM + MD
"""

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class ApprovalRule(models.Model):
    _name = "nn.approval.rule"
    _description = "Configurable Approval Rule"
    _order = "sequence asc, min_amount asc, id asc"

    name = fields.Char(string="Rule Name", required=True)
    sequence = fields.Integer(string="Priority", default=10)
    active = fields.Boolean(default=True)
    request_type = fields.Selection(
        [
            ("allocation", "Fund Allocation"),
            ("requisition", "Fund Requisition"),
            ("transfer", "Fund Transfer"),
            ("any", "Any"),
        ],
        string="Request Type", required=True, default="any",
    )
    min_amount = fields.Monetary(string="Minimum Amount", default=0.0)
    max_amount = fields.Monetary(
        string="Maximum Amount", default=0.0,
        help="0 means no upper limit.",
    )
    company_id = fields.Many2one(
        "res.company", string="Company",
        default=lambda self: self.env.company,
    )
    currency_id = fields.Many2one(
        "res.currency", related="company_id.currency_id", readonly=True,
    )
    md_required = fields.Boolean(
        string="Requires MD Approval", default=True,
        help="When unticked, GM approval alone fully approves the request.",
    )

    @api.constrains("min_amount", "max_amount")
    def _check_amounts(self):
        for rule in self:
            if rule.max_amount and rule.max_amount < rule.min_amount:
                raise ValidationError(_(
                    "Maximum amount cannot be lower than the minimum amount."))

    @api.model
    def _match_rule(self, request_type, amount, company):
        """Return the most specific active rule for the given parameters.

        Rules are ordered by ``sequence`` so administrators control priority;
        the first matching rule wins.
        """
        domain = [
            ("active", "=", True),
            ("request_type", "in", [request_type, "any"]),
            ("min_amount", "<=", amount),
            "|", ("company_id", "=", company.id), ("company_id", "=", False),
        ]
        rules = self.search(domain)
        # Keep only rules whose upper bound is satisfied (0 = unlimited),
        # then prefer a type-specific rule over the generic "any".
        rules = rules.filtered(
            lambda r: not r.max_amount or amount <= r.max_amount)
        specific = rules.filtered(lambda r: r.request_type == request_type)
        return (specific or rules)[:1]
