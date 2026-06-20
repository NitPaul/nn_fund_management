# -*- coding: utf-8 -*-
# Import order matters: the approval mixin and base records must be importable
# before the documents that inherit / reference them.
from . import approval_mixin
from . import fund_history
from . import approval_rule
from . import fund_account
from . import fund_target
from . import incoming_fund
from . import fund_allocation
from . import fund_requisition
from . import fund_bill
from . import fund_transfer
from . import bank_email_wizard
