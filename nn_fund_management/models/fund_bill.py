# -*- coding: utf-8 -*-
"""Bill control.

A bill records actual spending against an *approved* requisition. The rules
here are the core anti-double-spend guarantees for spending:

  * a bill must link to an approved requisition;
  * the bill's target must match the requisition's target (Project A cannot
    use a requisition created for Project B);
  * a bill cannot exceed the requisition's remaining billable amount;
  * multiple partial bills are allowed, but the total billed can never exceed
    the approved requisition amount.

A custom bill model is used (rather than account.move) to keep the control
logic self-contained and easy to explain, as the brief allows.
"""

from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError


class FundBill(models.Model):
    _name = "nn.fund.bill"
    _description = "Fund Bill"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "date desc, id desc"

    name = fields.Char(
        string="Bill Number", required=True, copy=False, readonly=True,
        default=lambda self: _("New"))
    requisition_id = fields.Many2one(
        "nn.fund.requisition", string="Requisition", required=True,
        ondelete="restrict", tracking=True,
    )
    # Stored (not related) so we can validate it against the requisition and
    # demonstrate the "wrong target" block; defaults from the requisition.
    target_id = fields.Many2one(
        "nn.fund.target", string="Project / Expense Head", required=True,
        ondelete="restrict", index=True, tracking=True,
    )
    date = fields.Date(
        string="Bill Date", required=True,
        default=fields.Date.context_today, tracking=True)
    amount = fields.Monetary(
        string="Amount", required=True, tracking=True)
    currency_id = fields.Many2one(
        "res.currency", related="company_id.currency_id", store=True,
        readonly=True)
    description = fields.Text(string="Description")
    vendor = fields.Char(string="Vendor / Payee")
    attachment_ids = fields.Many2many(
        "ir.attachment", string="Attachments")
    company_id = fields.Many2one(
        "res.company", required=True,
        default=lambda self: self.env.company, index=True)
    state = fields.Selection(
        [("draft", "Draft"), ("posted", "Posted"), ("cancelled", "Cancelled")],
        string="Status", default="draft", required=True, copy=False,
        tracking=True)

    requisition_remaining = fields.Monetary(
        related="requisition_id.remaining_billable_amount",
        string="Requisition Remaining", readonly=True)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", _("New")) == _("New"):
                vals["name"] = self.env["ir.sequence"].sudo().next_by_code(
                    "nn.fund.bill") or _("New")
        return super().create(vals_list)

    @api.onchange("requisition_id")
    def _onchange_requisition(self):
        if self.requisition_id:
            self.target_id = self.requisition_id.target_id

    @api.constrains("amount")
    def _check_amount_positive(self):
        for rec in self:
            if rec.amount <= 0:
                raise ValidationError(_("Amount must be greater than zero."))

    @api.constrains("target_id", "requisition_id")
    def _check_target_matches_requisition(self):
        for rec in self:
            if rec.target_id != rec.requisition_id.target_id:
                raise ValidationError(_(
                    "The bill's target (%(bill)s) does not match the "
                    "requisition's target (%(req)s). A requisition can only "
                    "be billed for its own project / expense head."
                ) % {
                    "bill": rec.target_id.display_name,
                    "req": rec.requisition_id.target_id.display_name,
                })

    def action_post(self):
        """Post the bill - the amount is spent and reserved funds decrease."""
        for rec in self:
            if rec.state != "draft":
                raise UserError(_("Only a draft bill can be posted."))
            req = rec.requisition_id
            if req.state != "approved":
                raise UserError(_(
                    "Bills can only be posted against an approved "
                    "requisition. '%s' is %s."
                ) % (req.display_name, req.state))
            if rec.target_id != req.target_id:
                raise UserError(_(
                    "The bill target must match the requisition target."))
            # remaining_billable excludes this still-draft bill, so the
            # comparison is correct.
            if rec.amount > req.remaining_billable_amount:
                raise UserError(_(
                    "Bill amount %(amount)s exceeds the requisition's "
                    "remaining billable amount %(remaining)s."
                ) % {
                    "amount": rec.amount,
                    "remaining": req.remaining_billable_amount,
                })
            rec.state = "posted"
            self.env["nn.fund.history"].sudo()._log(
                record=rec, old_state="draft", new_state="posted",
                comment=_("Bill posted (spent)."),
            )
            rec._notify_if_requisition_exhausted()
        return True

    def action_cancel(self):
        """Cancel a posted bill - the amount returns to the requisition.

        This is a state change only: no new funds are created, the reversal
        simply stops counting this bill as spent (computed balances refresh).
        """
        for rec in self:
            if rec.state == "posted" and not (
                self.env.user.has_group(
                    "nn_fund_management.group_fund_admin")
                or self.env.user.has_group(
                    "nn_fund_management.group_fund_finance")):
                raise UserError(_(
                    "Only finance users can cancel a posted bill."))
            if rec.state == "cancelled":
                raise UserError(_("This bill is already cancelled."))
            old = rec.state
            rec.state = "cancelled"
            self.env["nn.fund.history"].sudo()._log(
                record=rec, old_state=old, new_state=rec.state,
                comment=_("Bill cancelled; amount returned to requisition."),
            )
        return True

    def _notify_if_requisition_exhausted(self):
        """Raise an activity when a requisition is almost fully billed."""
        self.ensure_one()
        req = self.requisition_id
        if req.requested_amount <= 0:
            return
        used_ratio = req.billed_amount / req.requested_amount
        if used_ratio >= 0.9:
            try:
                req.activity_schedule(
                    "mail.mail_activity_data_todo",
                    user_id=req.requested_by.id,
                    summary=_("Requisition %s is almost fully used")
                    % req.name,
                )
            except Exception:
                pass

    @api.ondelete(at_uninstall=False)
    def _prevent_posted_delete(self):
        for rec in self:
            if rec.state == "posted":
                raise UserError(_(
                    "A posted bill cannot be deleted. Cancel it first "
                    "(audit-safe reversal)."))
