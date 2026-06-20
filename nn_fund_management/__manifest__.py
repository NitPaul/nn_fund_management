# -*- coding: utf-8 -*-
{
    "name": "NN Fund Management",
    "version": "17.0.1.0.0",
    "category": "Accounting/Finance",
    "summary": "Manage incoming funds, allocations, requisitions, bills and "
               "transfers with a configurable multi-level approval workflow.",
    "description": """
NN Fund Management
==================
Custom module for NN Services & Engineering Ltd. that tracks money from the
moment it is received through allocation, approval, requisition, billing and
transfer - while guaranteeing the same money can never be allocated,
transferred or spent more than once.

Key features:
  * Fund accounts (bank / cash / other) with live unassigned, held, assigned
    and received balances.
  * Incoming fund recording with duplicate-reference protection.
  * Fund allocation to projects or expense heads.
  * Reusable GM -> MD approval workflow with full audit history.
  * Fund requisitions and partial bill control.
  * Transfers between projects / expense heads.
  * Configurable approval rules (no hard-coded approvers).
  * Bank-email integration prototype (parse notification emails into pending
    incoming funds, deduplicated and logged).
  * Role based security (groups, ACLs, record rules, server-side checks).
""",
    "author": "Trainee Candidate - NN Services Assessment",
    "website": "https://www.nnse.com",
    "license": "LGPL-3",
    "depends": [
        "base",
        "mail",
    ],
    "data": [
        # Security loaded first: groups must exist before ACLs/rules/views.
        "security/fund_security.xml",
        "security/ir.model.access.csv",
        # Master / config data.
        "data/sequences.xml",
        "data/init_admin_access.xml",
        # Views.
        "views/fund_account_views.xml",
        "views/incoming_fund_views.xml",
        "views/fund_target_views.xml",
        "views/fund_allocation_views.xml",
        "views/fund_requisition_views.xml",
        "views/fund_bill_views.xml",
        "views/fund_transfer_views.xml",
        "views/approval_rule_views.xml",
        "views/dashboard_views.xml",
        "views/menus.xml",
        "views/bank_email_wizard_views.xml",
    ],
    "demo": [
        "demo/demo_data.xml",
    ],
    "application": True,
    "installable": True,
    "auto_install": False,
}
