# Run in the authorised pre-live site's System Console with Commit UNCHECKED.
# Synthetic parties only. No email addresses, bank accounts, or external calls.
# Explicit rollback plus absence checks; this is not a backup-restore rehearsal.
assert frappe.session.user == 'Administrator'
assert not frappe.get_all('Webhook', filters={'enabled': 1})
assert not frappe.get_all('Server Script', filters={'disabled': 0})
assert not frappe.db.exists('Customer', 'MIG-TEST-CUSTOMER-20260930')
assert not frappe.db.exists('Supplier', 'MIG-TEST-SUPPLIER-20260930')
migration_test_customer = frappe.get_doc({'doctype': 'Customer', 'customer_name': 'Migration synthetic test', 'customer_type': 'Individual', 'customer_group': 'Tenant', 'territory': 'Qatar', 'db_is_tenant': 1}).insert(set_name='MIG-TEST-CUSTOMER-20260930')
migration_test_supplier = frappe.get_doc({'doctype': 'Supplier', 'supplier_name': 'Migration synthetic owner test', 'supplier_type': 'Company', 'supplier_group': 'Landlord', 'db_is_landlord': 1}).insert(set_name='MIG-TEST-SUPPLIER-20260930')
migration_test_asset = frappe.get_doc({'doctype': 'Account', 'account_name': 'MIG TEST Collections 20260930', 'parent_account': 'Current Assets - DBR', 'company': 'DarkBrown RealEstate', 'is_group': 0, 'account_currency': 'QAR'}).insert()
migration_test_liability = frappe.get_doc({'doctype': 'Account', 'account_name': 'MIG TEST Payments 20260930', 'parent_account': 'Current Liabilities - DBR', 'company': 'DarkBrown RealEstate', 'is_group': 0, 'account_currency': 'QAR'}).insert()
migration_test_si = frappe.get_doc({'doctype': 'Sales Invoice', 'company': 'DarkBrown RealEstate', 'customer': migration_test_customer.name, 'posting_date': '2026-09-01', 'due_date': '2026-09-30', 'set_posting_time': 1, 'currency': 'QAR', 'conversion_rate': 1, 'debit_to': 'Debtors - DBR', 'ignore_pricing_rule': 1, 'items': [{'item_code': 'Rent', 'qty': 1, 'rate': 100, 'income_account': 'Rental Income - DBR', 'cost_center': 'AK-12 - DBR'}]}).insert(set_name='MIG-TEST-INV-20260930')
migration_test_si.submit()
assert migration_test_si.name == 'MIG-TEST-INV-20260930'
assert migration_test_si.grand_total == 100
migration_test_receipt = frappe.get_doc({'doctype': 'Journal Entry', 'company': 'DarkBrown RealEstate', 'posting_date': '2026-09-30', 'voucher_type': 'Journal Entry', 'user_remark': 'Synthetic migration receipt rollback test', 'accounts': [{'account': migration_test_asset.name, 'debit_in_account_currency': 60}, {'account': 'Debtors - DBR', 'party_type': 'Customer', 'party': migration_test_customer.name, 'credit_in_account_currency': 60, 'reference_type': 'Sales Invoice', 'reference_name': migration_test_si.name}]}).insert(set_name='MIG-TEST-RCPT-20260930')
migration_test_receipt.submit()
migration_test_si.reload()
assert migration_test_si.outstanding_amount == 40
migration_test_pi = frappe.get_doc({'doctype': 'Purchase Invoice', 'company': 'DarkBrown RealEstate', 'supplier': migration_test_supplier.name, 'posting_date': '2026-09-01', 'due_date': '2026-09-30', 'set_posting_time': 1, 'currency': 'QAR', 'conversion_rate': 1, 'credit_to': 'Creditors - DBR', 'ignore_pricing_rule': 1, 'items': [{'item_code': 'Landlord Rent', 'qty': 1, 'rate': 100, 'expense_account': 'Head Lease Rent - DBR', 'cost_center': 'AK-12 - DBR'}]}).insert(set_name='MIG-TEST-BILL-20260930')
migration_test_pi.submit()
assert migration_test_pi.grand_total == 100
migration_test_payment = frappe.get_doc({'doctype': 'Journal Entry', 'company': 'DarkBrown RealEstate', 'posting_date': '2026-09-30', 'voucher_type': 'Journal Entry', 'user_remark': 'Synthetic migration owner payment rollback test', 'accounts': [{'account': migration_test_liability.name, 'credit_in_account_currency': 60}, {'account': 'Creditors - DBR', 'party_type': 'Supplier', 'party': migration_test_supplier.name, 'debit_in_account_currency': 60, 'reference_type': 'Purchase Invoice', 'reference_name': migration_test_pi.name}]}).insert(set_name='MIG-TEST-PAY-20260930')
migration_test_payment.submit()
migration_test_pi.reload()
assert migration_test_pi.outstanding_amount == 40
migration_test_gl = frappe.get_all('GL Entry', filters={'voucher_no': ['in', [migration_test_si.name, migration_test_receipt.name, migration_test_pi.name, migration_test_payment.name]]}, fields=['debit', 'credit'])
assert sum(r.debit for r in migration_test_gl) == sum(r.credit for r in migration_test_gl)
print('NATIVE POSTING PASS: invoice 100, receipt 60, receivable 40; bill 100, payment 60, payable 40; GL balanced.')
migration_test_receipt.cancel()
migration_test_si.reload()
assert migration_test_si.outstanding_amount == 100
migration_test_payment.cancel()
migration_test_pi.reload()
assert migration_test_pi.outstanding_amount == 100
print('NATIVE CANCELLATION PASS: invoice and bill outstanding restored to 100.')
frappe.db.rollback()
assert not frappe.db.exists('Sales Invoice', 'MIG-TEST-INV-20260930')
assert not frappe.db.exists('Purchase Invoice', 'MIG-TEST-BILL-20260930')
assert not frappe.db.exists('Customer', 'MIG-TEST-CUSTOMER-20260930')
assert not frappe.db.exists('Supplier', 'MIG-TEST-SUPPLIER-20260930')
assert not frappe.db.exists('Account', migration_test_asset.name)
assert not frappe.db.exists('Account', migration_test_liability.name)
assert not frappe.get_all('GL Entry', filters={'voucher_no': ['in', ['MIG-TEST-INV-20260930', 'MIG-TEST-RCPT-20260930', 'MIG-TEST-BILL-20260930', 'MIG-TEST-PAY-20260930']]})
assert not frappe.get_all('Payment Ledger Entry', filters={'voucher_no': ['in', ['MIG-TEST-INV-20260930', 'MIG-TEST-RCPT-20260930', 'MIG-TEST-BILL-20260930', 'MIG-TEST-PAY-20260930']]})
print('ROLLBACK PASS: synthetic masters, accounts, invoices, bills and ledger rows absent.')
