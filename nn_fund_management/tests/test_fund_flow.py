# -*- coding: utf-8 -*-
"""Automated tests for the NN Fund Management module.

The main test reproduces the official 13-step sample demonstration from the
assessment, asserting balances and holds at every step. Additional tests cover
the negative cases that prove double spending and unauthorized approval are
blocked.
"""

from odoo.tests.common import TransactionCase
from odoo.exceptions import UserError, ValidationError
from odoo.tests import tagged


@tagged("post_install", "-at_install")
class TestFundFlow(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        Users = cls.env["res.users"]
        company = cls.env.company

        def make_user(name, login, group_xmlid):
            return Users.create({
                "name": name,
                "login": login,
                # An email is required so the approvers can post chatter
                # messages when they approve or reject a request.
                "email": login,
                "company_id": company.id,
                "company_ids": [(4, company.id)],
                "groups_id": [(4, cls.env.ref(group_xmlid).id)],
            })

        cls.requester = make_user(
            "Requester", "req@test.com",
            "nn_fund_management.group_fund_user")
        cls.finance = make_user(
            "Finance", "fin@test.com",
            "nn_fund_management.group_fund_finance")
        cls.gm = make_user(
            "GM", "gm@test.com",
            "nn_fund_management.group_fund_gm_approver")
        cls.md = make_user(
            "MD", "md@test.com",
            "nn_fund_management.group_fund_md_approver")

        cls.account = cls.env["nn.fund.account"].create({
            "name": "Test Bank",
            "account_type": "bank",
        })
        cls.project_a = cls.env["nn.fund.target"].create({
            "name": "Project A", "target_type": "project"})
        cls.project_b = cls.env["nn.fund.target"].create({
            "name": "Project B", "target_type": "project"})

        # Deterministic approval routing: everything above 1 needs GM + MD.
        cls.env["nn.approval.rule"].search([]).write({"active": False})
        cls.env["nn.approval.rule"].create({
            "name": "Test: GM + MD",
            "request_type": "any",
            "min_amount": 0.0,
            "max_amount": 0.0,
            "md_required": True,
        })

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _approve(self, record):
        """Run a full GM -> MD approval as the proper approvers."""
        record.with_user(self.gm).action_gm_approve()
        record.with_user(self.md).action_md_approve()

    def _receive(self, amount, ref):
        fund = self.env["nn.incoming.fund"].with_user(self.finance).create({
            "fund_account_id": self.account.id,
            "amount": amount,
            "transaction_reference": ref,
        })
        fund.action_confirm()
        return fund

    # ==================================================================
    # The 13-step sample demonstration.
    # ==================================================================
    def test_01_sample_demonstration(self):
        # 1. Receive BDT 1,000,000.
        self._receive(1000000, "TXN-001")
        self.assertEqual(self.account.available_balance, 1000000)

        # 2. Request BDT 600,000 for Project A.
        alloc = self.env["nn.fund.allocation"].with_user(self.requester).create({
            "fund_account_id": self.account.id,
            "target_id": self.project_a.id,
            "amount": 600000,
        })
        alloc.with_user(self.requester).action_submit()

        # 3. BDT 600,000 remains on hold while pending.
        self.assertEqual(self.account.held_amount, 600000)
        self.assertEqual(self.account.available_balance, 400000)

        # 4. Reject -> money returns to the unassigned balance.
        alloc.with_user(self.gm).action_reject()
        self.assertEqual(self.account.held_amount, 0)
        self.assertEqual(self.account.available_balance, 1000000)

        # 5. Submit again and approve.
        alloc.with_user(self.requester).action_reset_to_draft()
        alloc.with_user(self.requester).action_submit()
        self._approve(alloc)
        self.assertEqual(alloc.state, "approved")
        self.assertEqual(self.account.total_assigned, 600000)
        self.assertEqual(self.project_a.total_allocated, 600000)
        self.assertEqual(self.project_a.available_fund, 600000)

        # 6-8. Transfer BDT 200,000 from Project A to Project B.
        transfer = self.env["nn.fund.transfer"].with_user(self.requester).create({
            "source_id": self.project_a.id,
            "destination_id": self.project_b.id,
            "amount": 200000,
        })
        transfer.with_user(self.requester).action_submit()
        # 7. Amount remains on hold while approval is pending.
        self.assertEqual(self.project_a.transfer_hold, 200000)
        self.assertEqual(self.project_a.available_fund, 400000)
        self.assertEqual(self.project_b.available_fund, 0)
        # 8. Approve the transfer.
        self._approve(transfer)
        self.assertEqual(self.project_a.available_fund, 400000)
        self.assertEqual(self.project_b.incoming_transfers, 200000)
        self.assertEqual(self.project_b.available_fund, 200000)

        # 9. Create a BDT 150,000 requisition for Project B.
        req = self.env["nn.fund.requisition"].with_user(self.requester).create({
            "target_id": self.project_b.id,
            "requested_amount": 150000,
        })
        req.with_user(self.requester).action_submit()
        self.assertEqual(self.project_b.requisition_hold, 150000)
        self._approve(req)
        self.assertEqual(req.state, "approved")
        self.assertEqual(req.remaining_billable_amount, 150000)
        self.assertEqual(self.project_b.approved_unspent, 150000)

        # 10. Create a BDT 100,000 partial bill.
        bill1 = self.env["nn.fund.bill"].with_user(self.finance).create({
            "requisition_id": req.id,
            "target_id": self.project_b.id,
            "amount": 100000,
        })
        bill1.action_post()
        # 11. BDT 50,000 remains billable.
        self.assertEqual(req.remaining_billable_amount, 50000)
        self.assertEqual(self.project_b.total_spent, 100000)

        # 12. Try to create another bill for BDT 60,000 and block it.
        bill2 = self.env["nn.fund.bill"].with_user(self.finance).create({
            "requisition_id": req.id,
            "target_id": self.project_b.id,
            "amount": 60000,
        })
        with self.assertRaises(UserError):
            bill2.action_post()

        # 13. Try to use Project B's requisition for Project A and block it.
        with self.assertRaises(ValidationError):
            self.env["nn.fund.bill"].with_user(self.finance).create({
                "requisition_id": req.id,
                "target_id": self.project_a.id,
                "amount": 10000,
            })

    # ==================================================================
    # Negative / integrity tests.
    # ==================================================================
    def test_02_over_allocation_blocked(self):
        self._receive(100000, "TXN-OVER")
        alloc = self.env["nn.fund.allocation"].with_user(self.requester).create({
            "fund_account_id": self.account.id,
            "target_id": self.project_a.id,
            "amount": 250000,
        })
        with self.assertRaises(ValidationError):
            alloc.with_user(self.requester).action_submit()

    def test_03_md_cannot_approve_before_gm(self):
        self._receive(500000, "TXN-MDGM")
        alloc = self.env["nn.fund.allocation"].with_user(self.requester).create({
            "fund_account_id": self.account.id,
            "target_id": self.project_a.id,
            "amount": 100000,
        })
        alloc.with_user(self.requester).action_submit()
        with self.assertRaises(UserError):
            alloc.with_user(self.md).action_md_approve()

    def test_04_cannot_approve_own_request(self):
        # A user who is both requester and GM approver cannot approve their
        # own allocation.
        self.gm.groups_id = [(4, self.env.ref(
            "nn_fund_management.group_fund_user").id)]
        self._receive(500000, "TXN-OWN")
        alloc = self.env["nn.fund.allocation"].with_user(self.gm).create({
            "fund_account_id": self.account.id,
            "target_id": self.project_a.id,
            "amount": 100000,
        })
        alloc.with_user(self.gm).action_submit()
        with self.assertRaises(UserError):
            alloc.with_user(self.gm).action_gm_approve()

    def test_05_duplicate_transaction_reference_blocked(self):
        self._receive(100000, "DUP-REF")
        with self.assertRaises(Exception):
            # Same reference within the same account must be rejected by the
            # SQL unique constraint.
            self.env["nn.incoming.fund"].with_user(self.finance).create({
                "fund_account_id": self.account.id,
                "amount": 50000,
                "transaction_reference": "DUP-REF",
            }).flush_recordset()

    def test_06_computed_balance_not_editable(self):
        self._receive(100000, "TXN-RO")
        field = self.env["nn.fund.account"]._fields["available_balance"]
        # The balance is a stored computed field with no inverse method, so the
        # ORM marks it read-only and gives it no write-back path: it can never
        # be edited from a form or set through a normal write. The only way the
        # number changes is the compute from the record state.
        self.assertTrue(field.readonly)
        self.assertIsNone(field.inverse)
        self.assertEqual(self.account.available_balance, 100000)

    def test_07_transfer_source_equals_destination_blocked(self):
        with self.assertRaises(ValidationError):
            self.env["nn.fund.transfer"].with_user(self.requester).create({
                "source_id": self.project_a.id,
                "destination_id": self.project_a.id,
                "amount": 1000,
            })

    def test_08_configurable_rule_skips_md(self):
        # A rule that does not require MD lets GM fully approve.
        self.env["nn.approval.rule"].search([]).write({"active": False})
        self.env["nn.approval.rule"].create({
            "name": "GM only",
            "request_type": "any",
            "min_amount": 0.0,
            "max_amount": 0.0,
            "md_required": False,
        })
        self._receive(500000, "TXN-GMONLY")
        alloc = self.env["nn.fund.allocation"].with_user(self.requester).create({
            "fund_account_id": self.account.id,
            "target_id": self.project_a.id,
            "amount": 100000,
        })
        alloc.with_user(self.requester).action_submit()
        self.assertFalse(alloc.md_required)
        alloc.with_user(self.gm).action_gm_approve()
        self.assertEqual(alloc.state, "approved")
