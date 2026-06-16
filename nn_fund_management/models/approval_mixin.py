# -*- coding: utf-8 -*-
"""Reusable multi-level approval workflow.

This abstract model is the heart of the module. Fund allocations, fund
requisitions and fund transfers all share the *exact* same approval rules
(Draft -> Submitted -> GM Approval -> MD Approval -> Approved / Rejected /
Cancelled), so the workflow is written once here and inherited by each
document.  Concrete models only override a few small *hook* methods to apply
their own fund logic, which keeps the approval rules in one place and
guarantees they behave identically everywhere.
"""

from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError


class ApprovalMixin(models.AbstractModel):
    _name = "nn.approval.mixin"
    _description = "Approval Workflow Mixin"
    # Every approvable document also gets a chatter (audit trail) and the
    # ability to raise Odoo activities (notifications).
    _inherit = ["mail.thread", "mail.activity.mixin"]

    # Each concrete model sets this so approval rules can be looked up by type.
    # Values: 'allocation', 'requisition', 'transfer'.
    _approval_type = None

    STATE_SELECTION = [
        ("draft", "Draft"),
        ("submitted", "Submitted"),
        ("gm_approval", "GM Approval"),
        ("approved", "Approved"),
        ("rejected", "Rejected"),
        ("cancelled", "Cancelled"),
    ]

    name = fields.Char(
        string="Number", required=True, copy=False, readonly=True,
        index=True, default=lambda self: _("New"),
    )
    company_id = fields.Many2one(
        "res.company", string="Company", required=True,
        default=lambda self: self.env.company, index=True,
    )
    currency_id = fields.Many2one(
        "res.currency", related="company_id.currency_id", store=True,
        readonly=True,
    )
    requested_by = fields.Many2one(
        "res.users", string="Requested By", required=True,
        default=lambda self: self.env.user, tracking=True,
    )
    request_date = fields.Date(
        string="Request Date", required=True,
        default=fields.Date.context_today, tracking=True,
    )
    state = fields.Selection(
        STATE_SELECTION, string="Status", default="draft",
        required=True, copy=False, tracking=True, index=True,
    )
    # Read-only audit of every approval / rejection decision on this document.
    # Computed (not a stored One2many) because the approval lines link back via
    # a generic (res_model, res_id) reference rather than a Many2one.
    approval_line_ids = fields.Many2many(
        "nn.approval.line", string="Approval History",
        compute="_compute_approval_line_ids",
    )
    md_required = fields.Boolean(
        string="MD Approval Required", compute="_compute_md_required",
        help="Computed from the configurable approval rules. When False, GM "
             "approval is enough and the request is approved directly.",
    )

    def _compute_approval_line_ids(self):
        Line = self.env["nn.approval.line"]
        for rec in self:
            if isinstance(rec.id, int):
                rec.approval_line_ids = Line.search([
                    ("res_model", "=", rec._name),
                    ("res_id", "=", rec.id),
                ])
            else:
                rec.approval_line_ids = Line.browse()

    # ------------------------------------------------------------------
    # Hooks: concrete models override these. Default implementations do
    # nothing so a model only implements what it actually needs.
    # ------------------------------------------------------------------
    def _get_approval_amount(self):
        """Monetary amount used to evaluate approval rules. Override me."""
        self.ensure_one()
        return 0.0

    def _validate_submit(self):
        """Raise a ValidationError if there are not enough funds to submit.

        Called *before* the record becomes ``submitted``. Because balances
        are computed from record states, the relevant available balance at
        this moment still excludes this (draft) record - so a simple
        ``available >= amount`` comparison is correct.
        """
        return True

    def _on_submit(self):
        """Hook fired right after a record moves to ``submitted``."""
        return True

    def _on_approve(self):
        """Hook fired exactly once when a record becomes ``approved``."""
        return True

    def _on_reject(self):
        """Hook fired when a record is rejected (funds are released)."""
        return True

    def _on_cancel(self):
        """Hook fired when a record is cancelled (funds are released)."""
        return True

    # ------------------------------------------------------------------
    # Approval rule evaluation (configurable, not hard-coded).
    # ------------------------------------------------------------------
    @api.depends("company_id")
    def _compute_md_required(self):
        for rec in self:
            rec.md_required = rec._evaluate_md_required()

    def _evaluate_md_required(self):
        """Decide whether MD approval is required for this record.

        Looks up the most specific :class:`nn.approval.rule`. If no rule
        matches we fall back to the safe default of *requiring* MD approval,
        which matches the documented minimum workflow (GM then MD).
        """
        self.ensure_one()
        if not self._approval_type:
            return True
        rule = self.env["nn.approval.rule"]._match_rule(
            self._approval_type, self._get_approval_amount(), self.company_id
        )
        if rule:
            return rule.md_required
        return True

    # ------------------------------------------------------------------
    # Security helpers - all checks run server-side.
    # ------------------------------------------------------------------
    def _is_admin(self):
        return self.env.user.has_group(
            "nn_fund_management.group_fund_admin"
        )

    def _check_not_own_request(self):
        """A user may not approve their own request unless specially
        authorized (Fund Administrator)."""
        for rec in self:
            if rec._is_admin():
                continue
            if self.env.user in (rec.requested_by | rec.create_uid):
                raise UserError(_(
                    "You cannot approve your own request (%s). Only a "
                    "different authorized approver may approve it."
                ) % rec.name)

    def _check_group(self, group_xmlid, level_label):
        if not (self.env.user.has_group(group_xmlid) or self._is_admin()):
            raise UserError(_(
                "Only a %s approver can perform this action."
            ) % level_label)

    # ------------------------------------------------------------------
    # History recording.
    # ------------------------------------------------------------------
    def _record_decision(self, level, decision, comment=False):
        """Create an approval-line audit record and post to the chatter."""
        self.ensure_one()
        self.env["nn.approval.line"].create({
            "res_model": self._name,
            "res_id": self.id,
            "approver_id": self.env.user.id,
            "level": level,
            "decision": decision,
            "comment": comment or False,
        })
        self.message_post(body=_(
            "%(level)s %(decision)s by %(user)s.") % {
            "level": dict(self.env["nn.approval.line"]._fields[
                "level"].selection).get(level, level),
            "decision": decision,
            "user": self.env.user.display_name,
        })

    # ------------------------------------------------------------------
    # Workflow actions.
    # ------------------------------------------------------------------
    def action_submit(self):
        for rec in self:
            if rec.state != "draft":
                raise UserError(_("Only draft requests can be submitted."))
            rec._validate_submit()
            old = rec.state
            rec.state = "submitted"
            rec._on_submit()
            rec.env["nn.fund.history"].sudo()._log(
                record=rec, old_state=old, new_state=rec.state,
                comment=_("Submitted for approval."),
            )
            rec._notify_next_approver()
        return True

    def action_gm_approve(self):
        for rec in self:
            if rec.state != "submitted":
                raise UserError(_(
                    "GM approval is only possible on a submitted request."
                ))
            rec._check_group(
                "nn_fund_management.group_fund_gm_approver", _("General Manager")
            )
            rec._check_not_own_request()
            rec._record_decision("gm", "approved")
            if rec.md_required:
                # GM done, now awaiting MD.
                old = rec.state
                rec.state = "gm_approval"
                rec.env["nn.fund.history"].sudo()._log(
                    record=rec, old_state=old, new_state=rec.state,
                    comment=_("GM approved; awaiting MD."),
                )
                rec._notify_next_approver()
            else:
                # Rule says MD not required - approve directly.
                rec._set_approved()
        return True

    def action_md_approve(self):
        for rec in self:
            if rec.state != "gm_approval":
                raise UserError(_(
                    "MD approval requires GM approval first."
                ))
            rec._check_group(
                "nn_fund_management.group_fund_md_approver",
                _("Managing Director"),
            )
            rec._check_not_own_request()
            rec._record_decision("md", "approved")
            rec._set_approved()
        return True

    def _set_approved(self):
        """Single, guarded transition to ``approved``.

        Centralising the transition guarantees the ``_on_approve`` fund
        movement runs *exactly once*, so repeated approval clicks can never
        create duplicate fund movements.
        """
        self.ensure_one()
        old = self.state
        self.state = "approved"
        self._on_approve()
        self.env["nn.fund.history"].sudo()._log(
            record=self, old_state=old, new_state=self.state,
            comment=_("Fully approved."),
        )

    def action_reject(self):
        for rec in self:
            if rec.state not in ("submitted", "gm_approval"):
                raise UserError(_(
                    "Only a pending request can be rejected."
                ))
            # Whichever level the user belongs to may reject.
            if not (
                self.env.user.has_group(
                    "nn_fund_management.group_fund_gm_approver")
                or self.env.user.has_group(
                    "nn_fund_management.group_fund_md_approver")
                or rec._is_admin()
            ):
                raise UserError(_(
                    "Only an assigned approver can reject this request."))
            rec._check_not_own_request()
            level = "md" if rec.state == "gm_approval" else "gm"
            rec._record_decision(level, "rejected")
            old = rec.state
            rec.state = "rejected"
            rec._on_reject()
            rec.env["nn.fund.history"].sudo()._log(
                record=rec, old_state=old, new_state=rec.state,
                comment=_("Rejected - funds released."),
            )
        return True

    def action_cancel(self):
        for rec in self:
            if rec.state == "approved":
                # Cancelling an approved (committed) record needs the cancel
                # right; this is the "only authorized users can cancel
                # approved transactions" rule.
                if not (self.env.user.has_group(
                        "nn_fund_management.group_fund_admin")):
                    raise UserError(_(
                        "Only a Fund Administrator can cancel an already "
                        "approved transaction."))
            if rec.state in ("rejected", "cancelled"):
                raise UserError(_("This request is already closed."))
            old = rec.state
            rec.state = "cancelled"
            rec._on_cancel()
            rec.env["nn.fund.history"].sudo()._log(
                record=rec, old_state=old, new_state=rec.state,
                comment=_("Cancelled - funds released."),
            )
        return True

    def action_reset_to_draft(self):
        for rec in self:
            if rec.state not in ("rejected", "cancelled"):
                raise UserError(_(
                    "Only rejected or cancelled requests can be reset."))
            rec.state = "draft"
        return True

    # ------------------------------------------------------------------
    # Notifications (Odoo activities).
    # ------------------------------------------------------------------
    def _notify_next_approver(self):
        """Schedule an activity for the group that must act next."""
        self.ensure_one()
        if self.state == "submitted":
            group_xmlid = "nn_fund_management.group_fund_gm_approver"
            summary = _("GM approval required: %s") % self.name
        elif self.state == "gm_approval":
            group_xmlid = "nn_fund_management.group_fund_md_approver"
            summary = _("MD approval required: %s") % self.name
        else:
            return
        group = self.env.ref(group_xmlid, raise_if_not_found=False)
        if not group:
            return
        # Notify the first member of the approver group (a simple, reliable
        # routing approach; production setups would use a dedicated queue).
        approver = group.users[:1]
        if approver:
            try:
                self.activity_schedule(
                    "mail.mail_activity_data_todo",
                    user_id=approver.id,
                    summary=summary,
                )
            except Exception:
                # Activities are a convenience; never block the workflow.
                pass

    # ------------------------------------------------------------------
    # Numbering.
    # ------------------------------------------------------------------
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", _("New")) == _("New"):
                # Sequence numbers are generated with sudo: a Fund User who is
                # allowed to create a request has no direct read access to
                # ir.sequence, but should still receive a document number.
                seq = self.env["ir.sequence"].sudo().next_by_code(self._name)
                vals["name"] = seq or _("New")
        return super().create(vals_list)


class ApprovalLine(models.Model):
    _name = "nn.approval.line"
    _description = "Approval History Line"
    _order = "create_date asc, id asc"

    # Generic link so a single table stores the history of every approvable
    # document (allocations, requisitions, transfers).
    res_model = fields.Char(string="Document Model", required=True, index=True)
    res_id = fields.Integer(string="Document ID", required=True, index=True)
    document_ref = fields.Reference(
        selection="_selection_document_ref", string="Document",
        compute="_compute_document_ref",
    )
    approver_id = fields.Many2one(
        "res.users", string="Approver", required=True,
        default=lambda self: self.env.user,
    )
    level = fields.Selection(
        [("gm", "General Manager"), ("md", "Managing Director")],
        string="Approval Level", required=True,
    )
    decision = fields.Selection(
        [("approved", "Approved"), ("rejected", "Rejected")],
        string="Decision", required=True,
    )
    comment = fields.Text(string="Comment")

    @api.model
    def _selection_document_ref(self):
        return [
            ("nn.fund.allocation", "Fund Allocation"),
            ("nn.fund.requisition", "Fund Requisition"),
            ("nn.fund.transfer", "Fund Transfer"),
        ]

    @api.depends("res_model", "res_id")
    def _compute_document_ref(self):
        for line in self:
            if line.res_model and line.res_id:
                line.document_ref = "%s,%s" % (line.res_model, line.res_id)
            else:
                line.document_ref = False
