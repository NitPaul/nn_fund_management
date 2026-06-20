# -*- coding: utf-8 -*-
"""Manual import of a bank-notification email.

The bonus brief asks for a prototype that turns bank "you have been credited"
emails into incoming-fund records. In production an incoming mail alias would
feed ``nn.incoming.fund.message_new`` automatically; this wizard lets a finance
user paste an email and exercise exactly the same parser from the UI, which
makes the feature easy to demonstrate without a configured mail server.
"""

from odoo import fields, models, _
from odoo.exceptions import UserError

SAMPLE_EMAIL = """Dear Customer,

Your account XXXX1234 with City Bank has been credited.

Amount: BDT 250,000.00
Transaction Reference: TXN-EMAIL-0001
Date: 2026-06-17
From: ACME Industries Ltd

Thank you for banking with us."""


class BankEmailWizard(models.TransientModel):
    _name = "nn.bank.email.wizard"
    _description = "Import Incoming Fund from Bank Email"

    fund_account_id = fields.Many2one(
        "nn.fund.account", string="Fund Account",
        domain=[("account_type", "=", "bank")],
        help="Leave empty to let the parser match the account from the email.",
    )
    email_body = fields.Text(
        string="Bank Email Content", required=True, default=SAMPLE_EMAIL,
        help="Paste the raw bank notification email text here.",
    )
    message_id = fields.Char(
        string="Email Message-ID",
        help="Optional. When provided, the same email cannot be imported "
             "twice (mirrors how the live mail gateway de-duplicates).",
    )

    def action_import(self):
        self.ensure_one()
        try:
            record = self.env["nn.incoming.fund"]._create_from_bank_email(
                self.email_body,
                message_id=self.message_id or False,
                account=self.fund_account_id or None,
            )
        except ValueError as error:
            # Parsing / duplicate failures surface as a clear user message
            # (and are logged server-side by the model).
            raise UserError(_("Could not import this bank email: %s") % error)
        return {
            "type": "ir.actions.act_window",
            "name": _("Imported Incoming Fund"),
            "res_model": "nn.incoming.fund",
            "res_id": record.id,
            "view_mode": "form",
            "target": "current",
        }
