"""Native historical document importer. No report totals or direct GL inserts.

The caller owns one database transaction and must supply a reviewed, resolved
batch. This module deliberately never commits and never runs from deploy hooks.
"""
from datetime import date
from decimal import Decimal
from darkbrown.migration.evidence import digest
from darkbrown.migration.plan import money

MASTER_TYPES = {'Supplier','Customer','Building','Unit','Head Lease','Tenancy Agreement'}
EVENT_TYPES = {'rent_invoice','owner_bill','journal','collection','supplier_payment'}


def document_name(kind, key):
    prefix = {'rent_invoice':'MIG-INV','owner_bill':'MIG-BILL','journal':'MIG-JV','collection':'MIG-RCPT','supplier_payment':'MIG-PAY'}.get(kind,'MIG-MASTER')
    return prefix + '-' + digest([kind,key])[:24].upper()


def validate_batch(batch):
    if batch.get('schema_version') != 1 or not batch.get('company') or not batch.get('site'):
        raise ValueError('Explicit schema, site and company required')
    if batch.get('batch_checksum') != digest({k:v for k,v in batch.items() if k!='batch_checksum'}):
        raise ValueError('Batch changed')
    seen=set()
    for event in batch['events']:
        if event.get('kind') not in EVENT_TYPES or not event.get('key') or event['key'] in seen:
            raise ValueError('Invalid or duplicate economic event')
        seen.add(event['key'])
        if not event.get('source') or not event.get('description'):
            raise ValueError('Source lineage and reconstruction description required')
        posting=date.fromisoformat(event['posting_date'])
        if posting >= date(2026,10,1):
            raise ValueError('Historical migration cannot post October/live data')
        if event['kind'] in {'rent_invoice','owner_bill','collection','supplier_payment'} and money(event['amount'])<=0:
            raise ValueError('Positive amount required; credit notes need separate review')
        if event['kind']=='journal':
            debit=sum((money(r.get('debit','0')) for r in event['lines']),Decimal(0))
            credit=sum((money(r.get('credit','0')) for r in event['lines']),Decimal(0))
            if debit<=0 or debit!=credit:
                raise ValueError('Unbalanced journal')
            for line in event['lines']:
                d,c=money(line.get('debit','0')),money(line.get('credit','0'))
                if min(d,c)<0 or (d and c):raise ValueError('Invalid journal line')
    masters=set()
    for master in batch.get('masters',[]):
        key=(master['doctype'],master['name'])
        if key[0] not in MASTER_TYPES or key in masters or not master.get('source'):
            raise ValueError('Invalid/duplicate master or missing provenance')
        masters.add(key)
        if any(k in master.get('values',{}) for k in ['doctype','name','docstatus','owner','flags']):
            raise ValueError('Identity/control override prohibited')
    return True


def _account(frappe, name, company, account_type=None, root_type=None):
    row=frappe.db.get_value('Account',name,['company','is_group','disabled','account_type','root_type','account_currency'],as_dict=True)
    if not row or row.company!=company or row.is_group or row.disabled or (row.account_currency and row.account_currency!='QAR'):
        raise ValueError('Invalid company/QAR posting account')
    if account_type and row.account_type!=account_type:raise ValueError('Wrong account type')
    if root_type and row.root_type!=root_type:raise ValueError('Wrong account root')
    return row


def _remark(batch,event):
    return '\n'.join(['Reconstructed historical record; internal only.',
        'Migration event: '+event['key'], 'Source checksum: '+digest(event['source']),
        'Posting date convention: '+event.get('date_basis','source date'),
        event['description'], 'MIGRATION-CONTENT:'+digest([batch['company'],event])])


def _existing(frappe,doctype,name,remark):
    if not frappe.db.exists(doctype,name):return None
    doc=frappe.get_doc(doctype,name)
    field='remarks' if doctype in {'Sales Invoice','Purchase Invoice'} else 'user_remark'
    expected=remark.split('MIGRATION-CONTENT:')[-1]
    if doc.docstatus!=1 or ('MIGRATION-CONTENT:'+expected) not in (doc.get(field) or ''):
        raise ValueError('Existing migration document differs or is not submitted')
    return doc


def _submit(frappe,values,name):
    doc=frappe.get_doc(values)
    # No ignore_mandatory, ignore_links, ignore_validate or direct ledger writes.
    doc.insert(set_name=name)
    if doc.name!=name:raise ValueError('Installed naming did not preserve deterministic ID')
    doc.submit()
    return doc


def _submit_migration(frappe, values, name, event):
    from darkbrown.migration.metadata import values_for, posting_scope
    values.update(values_for(frappe, values['doctype'], event))
    with posting_scope(frappe, event, values['doctype'], name):
        return _submit(frappe, values, name)


def post_event(frappe,batch,event):
    company=batch['company']; kind=event['kind']; name=document_name(kind,event['key'])
    remark=_remark(batch,event)
    doctype={'rent_invoice':'Sales Invoice','owner_bill':'Purchase Invoice','journal':'Journal Entry','collection':'Journal Entry','supplier_payment':'Journal Entry'}[kind]
    existing=_existing(frappe,doctype,name,remark)
    if existing:return {'doctype':doctype,'name':existing.name,'created':False}
    common={'doctype':doctype,'company':company,'posting_date':event['posting_date']}
    if kind in {'rent_invoice','owner_bill'}:
        selling=kind=='rent_invoice';party_type='Customer' if selling else 'Supplier'
        if not frappe.db.exists(party_type,event['party']):raise ValueError('Unresolved party')
        _account(frappe,event['party_account'],company,'Receivable' if selling else 'Payable')
        _account(frappe,event['account'],company,root_type='Income' if selling else 'Expense')
        values={**common,'set_posting_time':1,'currency':'QAR','conversion_rate':1,
            'due_date':event['due_date'],'remarks':remark,'ignore_pricing_rule':1,
            'customer' if selling else 'supplier':event['party'],
            'debit_to' if selling else 'credit_to':event['party_account'],
            'items':[{'item_code':event['item'],'qty':1,'rate':str(money(event['amount'])),
                      'description':event['description'],'cost_center':event['cost_center'],
                      'income_account' if selling else 'expense_account':event['account']}]}
        if selling:
            values['custom_billing_period']=event['service_period']+'-01'
            if event.get('agreement'):values['custom_rental_agreement']=event['agreement']
        elif event.get('agreement'):
            values['custom_landlord_contract']=event['agreement']
        doc=_submit_migration(frappe,values,name,event)
        if money(doc.grand_total)!=money(event['amount']):raise ValueError('ERP pricing/tax altered source amount')
    else:
        if kind in {'collection','supplier_payment'}:
            receiving = kind == 'collection'
            # Unknown destinations are an ordinary asset clearing dimension,
            # never a fabricated bank/cash account or a Payment Entry to one.
            row=_account(frappe,event['clearing_account'],company,root_type='Asset' if receiving else 'Liability')
            if row.account_type in {'Bank','Cash','Receivable','Payable'}:raise ValueError('Clearing must not pretend to be bank/cash/party control')
            _account(frappe,event['party_account'],company,'Receivable' if receiving else 'Payable')
            party_type = 'Customer' if receiving else 'Supplier'
            if not frappe.db.exists(party_type,event['party']):raise ValueError('Unresolved settlement party')
            amount=str(money(event['amount']))
            lines=[{'account':event['clearing_account'], 'debit_in_account_currency' if receiving else 'credit_in_account_currency':amount},
                   {'account':event['party_account'],'party_type':party_type,'party':event['party'], 'credit_in_account_currency' if receiving else 'debit_in_account_currency':amount}]
            if event.get('invoice_key'):
                inv=document_name('rent_invoice' if receiving else 'owner_bill',event['invoice_key'])
                invoice_type = 'Sales Invoice' if receiving else 'Purchase Invoice'
                invoice=frappe.get_doc(invoice_type,inv)
                if invoice.company!=company or invoice.get('customer' if receiving else 'supplier')!=event['party'] or invoice.docstatus!=1:
                    raise ValueError('Receipt/invoice party mismatch')
                if money(event['amount'])>money(invoice.outstanding_amount):
                    raise ValueError('Receipt excess requires an explicit unallocated split')
                lines[1].update(reference_type=invoice_type,reference_name=inv)
        else:
            lines=[]
            for source in event['lines']:
                _account(frappe,source['account'],company)
                line={'account':source['account'],'debit_in_account_currency':str(money(source.get('debit','0'))),
                      'credit_in_account_currency':str(money(source.get('credit','0')))}
                for field in ['party_type','party','cost_center','reference_type','reference_name']:
                    if source.get(field):line[field]=source[field]
                lines.append(line)
        doc=_submit_migration(frappe,{**common,'voucher_type':'Journal Entry','user_remark':remark,'accounts':lines},name,event)
    return {'doctype':doctype,'name':doc.name,'created':True}


def same_master_value(meta, field, actual, expected):
    definition = meta.get_field(field)
    if definition and definition.fieldtype in {'Currency', 'Float', 'Percent', 'Int', 'Check'}:
        return Decimal(str(actual or 0)) == Decimal(str(expected or 0))
    return str(actual or '') == str(expected or '')


def approved_provisional_scope(batch, approval):
    return bool(approval and approval.get("batch_checksum") == batch["batch_checksum"]
        and approval.get("exception_checksum") == digest([batch.get("exceptions", []), batch.get("contract_review", []), batch.get("blocking_items", [])])
        and approval.get("confirmation") == "IMPORT SUPPORTED HISTORY AS PROVISIONAL")


def import_batch(frappe,batch, approved_scope=None):
    """Run inside caller's approved transaction/lock. Caller MUST rollback errors."""
    validate_batch(batch)
    if batch.get('complete_replacement') is not True and not approved_provisional_scope(batch, approved_scope):
        raise ValueError('Replacement dataset is incomplete; resolve or explicitly approve its remaining scope before posting')
    if str(frappe.local.site)!=batch['site']:raise ValueError('Wrong site')
    if frappe.db.get_value('Company',batch['company'],'default_currency')!='QAR':raise ValueError('Wrong company currency')
    if frappe.session.user!='Administrator':
        raise frappe.PermissionError('Migration requires the authorised Administrator session')
    if not frappe.conf.get('maintenance_mode') or not frappe.conf.get('pause_scheduler') or not frappe.conf.get('mute_emails'):
        raise ValueError('Migration window must suppress writes, scheduling and mail')
    result={'masters_created':0,'events_created':0,'events_reused':0,'documents':[]}
    for master in batch.get('masters',[]):
        if frappe.db.exists(master['doctype'],master['name']):
            doc=frappe.get_doc(master['doctype'],master['name'])
            meta = frappe.get_meta(master['doctype'])
            if any(not same_master_value(meta, k, doc.get(k), v) for k,v in master['values'].items()):
                raise ValueError('Existing master differs; revision review required')
            continue
        doc=frappe.get_doc({'doctype':master['doctype'],**master['values']})
        doc.insert(set_name=master['name'])
        if doc.name!=master['name']:raise ValueError('Master naming differs')
        result['masters_created']+=1
    for event in batch['events']:
        record=post_event(frappe,batch,event)
        result['events_created' if record['created'] else 'events_reused']+=1
        result['documents'].append(record)
    return result
