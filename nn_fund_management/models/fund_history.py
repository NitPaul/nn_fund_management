# -*- coding: utf-8 -*-
"""Immutable audit log of financial actions.

Section 10 of the brief requires a clear, preserved history of who did what.
The chatter (mail.thread) already records messages, but a dedicated, queryable
history model gives finance users a single place to audit every fund movement
with structured fields (amount, account, target, reference document...).
"""

from odoo import api, fields, models, _
from odoo.exceptions import UserError


class FundHistory(models.Model):
    _name = "nn.fund.history"
    _description = "Fund Action History"
    _order = "create_date desc, id desc"

    name = fields.Char(string="Action", required=True)
    res_model = fields.Char(string="Document Model", index=True)
    res_id = fields.Integer(string="Document ID", index=True)
    document_ref = fields.Reference(
        selection="_selection_document_ref", string="Document",
        compute="_compute_document_ref", store=False,
    )

    creator_id = fields.Many2one("res.users", string="Record Creator")
    submitter_id = fields.Many2one("res.users", string="Submitted By")
    actor_id = fields.Many2one(
        "res.users", string="Performed By",
        default=lambda self: self.env.user,
    )
    old_state = fields.Char(string="Previous Status")
    new_state = fields.Char(string="New Status")
    action_date = fields.Datetime(
        string="Date & Time", default=fields.Datetime.now,
    )
    comment = fields.Text(string="Comment")
    amount = fields.Monetary(string="Amount")
    currency_id = fields.Many2one(
        "res.currency", default=lambda self: self.env.company.currency_id,
    )
    fund_account_id = fields.Many2one(
        "nn.fund.account", string="Related Fund Account",
    )
    target_id = fields.Many2one(
        "nn.fund.target", string="Related Project / Expense Head",
    )
    company_id = fields.Many2one(
        "res.company", default=lambda self: self.env.company,
    )

    @api.model
    def _selection_document_ref(self):
        return [
            ("nn.fund.allocation", "Fund Allocation"),
            ("nn.fund.requisition", "Fund Requisition"),
            ("nn.fund.transfer", "Fund Transfer"),
            ("nn.fund.bill", "Bill"),
            ("nn.incoming.fund", "Incoming Fund"),
        ]

    @api.depends("res_model", "res_id")
    def _compute_document_ref(self):
        for rec in self:
            if rec.res_model and rec.res_id:
                rec.document_ref = "%s,%s" % (rec.res_model, rec.res_id)
            else:
                rec.document_ref = False

    @api.model
    def _log(self, record, old_state=False, new_state=False, comment=False):
        """Create a history entry for ``record``.

        Pulls structured fields off the source record when they exist so the
        audit log is useful without each caller having to spell them out.
        """
        vals = {
            "name": "%s: %s -> %s" % (
                record.display_name, old_state or "-", new_state or "-"),
            "res_model": record._name,
            "res_id": record.id,
            "creator_id": record.create_uid.id,
            # ``record`` keeps the *real* user environment even though this
            # method is called via sudo(), so the audit log shows who actually
            # performed the action rather than the superuser.
            "actor_id": record.env.user.id,
            "old_state": old_state,
            "new_state": new_state,
            "comment": comment,
            "company_id": getattr(record, "company_id", self.env.company).id,
        }
        if "requested_by" in record._fields:
            vals["submitter_id"] = record.requested_by.id
        # Best-effort capture of the monetary amount and related records.
        for amount_field in ("amount", "requested_amount"):
            if amount_field in record._fields and record[amount_field]:
                vals["amount"] = record[amount_field]
                break
        if "fund_account_id" in record._fields and record.fund_account_id:
            vals["fund_account_id"] = record.fund_account_id.id
        if "target_id" in record._fields and record.target_id:
            vals["target_id"] = record.target_id.id
        return self.create(vals)

    def unlink(self):
        # Audit records are immutable: confirmed financial history must not be
        # silently deleted. Only a Fund Administrator may prune logs.
        if not self.env.user.has_group(
                "nn_fund_management.group_fund_admin"):
            raise UserError(_(
                "Fund history is an audit trail and cannot be deleted."))
        return super().unlink()
