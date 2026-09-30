"""One-time, exact-record dummy-data reset inside a caller-owned transaction.

This is an exceptional low-level cleanup, NOT normal document cancellation.
It must appear explicitly in the reviewed approval. Never expose it as a general
reset endpoint. Do not call before the entire replacement import has preflighted.
"""
from darkbrown.migration.evidence import digest
from darkbrown.migration.inventory import PROTECTED, snapshot_checksum

BUSINESS_TYPES = {
 'Building','Unit','Customer','Supplier','Head Lease','Tenancy Agreement',
 'Sales Invoice','Purchase Invoice','Payment Entry','Journal Entry','GL Entry','Payment Ledger Entry',
 'Bank Transaction','Bank Statement Import','Bank Balance Declaration',
 'Move Out Case','Collection Case','Security Deposit','Maintenance Request','Utility Bill','Utility Meter',
 'Deposit Batch','Invoice Run','Agreement Amendment','Document Register','Document Archive',
 'Cheque','Cheque Book','Historical Monthly PL','Expense Entry','Petty Cash Entry','Weekly Closing',
 'Building Scenario','MD Alert Dismissal','Contact','Comment','Version','Workflow Action',
}


def reset_plan(snapshot, selected, orphan_exceptions=()):
    if snapshot.get('snapshot_checksum')!=snapshot_checksum(snapshot):raise ValueError('Modified inventory')
    rows={(dt,r['name']):r for dt,v in snapshot['records'].items() for r in v['rows']}
    ids={tuple(k) for k in selected}
    if len(ids)!=len(selected) or not ids.issubset(rows):raise ValueError('Missing or duplicate selection')
    orphan_ids={tuple(k) for k in orphan_exceptions}
    if not orphan_ids.issubset(ids):raise ValueError('Orphan exception outside scope')
    links={}
    for link in snapshot['relationships']:links.setdefault(link['doctype'],[]).append(link)
    for key in sorted(ids):
        dt,name=key;row=rows[key];meta=snapshot['records'][dt]
        if dt in PROTECTED or meta.get('issingle') or dt=='Staff Member':raise ValueError('Protected setup')
        if row.get('company') and row['company']!=snapshot['company']:raise ValueError('Cross-company data')
        if meta.get('istable'):
            parent=(row.get('parenttype'),row.get('parent'))
            if key in orphan_ids:
                if dt!='Document Register Cheque' or parent in rows or parent[0]!='Document Register':raise ValueError('Invalid exact orphan exception')
            elif parent not in ids or not any(l['type'] in {'Table','Table MultiSelect'} and l['field']==row.get('parentfield') and l['target']==dt for l in links.get(parent[0],[])):
                raise ValueError('Unselected or invalid child owner')
        elif dt not in BUSINESS_TYPES:raise ValueError('Doctype outside reset allowlist')
    incoming=[]
    for key,row in rows.items():
        if key in ids:continue
        if (row.get('parenttype'),row.get('parent')) in ids:incoming.append(key)
        if key[0] in {'GL Entry','Payment Ledger Entry'} and (row.get('voucher_type'),row.get('voucher_no')) in ids:incoming.append(key)
        for link in links.get(key[0],[]):
            if link['type'] not in {'Link','Dynamic Link'}:continue
            target=row.get(link['target']) if link['type']=='Dynamic Link' else link['target']
            value=row.get(link['field'])
            if isinstance(target,str) and isinstance(value,str) and (target,value) in ids:incoming.append(key)
    # Security restrictions are not silently deleted to satisfy this check.
    if incoming:raise ValueError('Retained incoming references require resolved scope')
    result={'site':snapshot['site'],'company':snapshot['company'],
        'method':'exact_record_low_level_dummy_reset','snapshot_checksum':snapshot['snapshot_checksum'],
        'business_population_checksum':digest(sorted(k for k in rows if k[0] in BUSINESS_TYPES)),
        'protected_setup_checksum':digest([(k,rows[k]['content_checksum']) for k in sorted(rows) if k[0] in PROTECTED]),
        'rows':[{'doctype':dt,'name':name,'source_record_checksum':rows[(dt,name)]['content_checksum']} for dt,name in sorted(ids)],
        'orphan_exceptions':sorted(orphan_ids),'includes_post_cutover_dummy_records':any(str(rows[k].get('posting_date') or '')[:10]>='2026-10-01' for k in ids),
        'warning':'Bypasses ordinary document lifecycle only for the exact approved dummy records; deletes their recorded ledger rows. Not valid for real transactions.'}
    result['reset_checksum']=digest(result)
    return result


def execute(frappe,plan,approval):
    """Caller must hold migration lock and roll back ANY error; never commits."""
    if frappe.session.user!='Administrator':raise frappe.PermissionError('Bench Administrator execution required')
    if plan.get('reset_checksum')!=digest({k:v for k,v in plan.items() if k!='reset_checksum'}):raise ValueError('Changed reset plan')
    if str(frappe.local.site)!=plan['site']:raise ValueError('Wrong site')
    if not all(frappe.conf.get(k) for k in ['maintenance_mode','pause_scheduler','mute_emails']):raise ValueError('Site not quiesced')
    if approval.get('reset_checksum')!=plan['reset_checksum'] or approval.get('confirmation')!='REMOVE EXACT REVIEWED DUMMY RECORDS':raise ValueError('Exact destructive approval missing')
    if not approval.get('backup_id') or not approval.get('replacement_import_preflight_passed') or not approval.get('queue_drain_verified'):raise ValueError('Backup/import/queue prerequisites missing')
    from darkbrown.migration.runtime_queue import verify_idle_site
    from darkbrown.migration.inventory import capture
    verify_idle_site(frappe)
    current_snapshot=capture(company=plan['company'],expected_site=plan['site'])
    residual=[e for e in current_snapshot.get('errors',[]) if not (
        e.get('doctype') in {'RQ Job','RQ Worker'} and e.get('error')=='runtime queue inventory and drain evidence required')]
    if residual:raise ValueError('Live inventory still has unresolved errors')
    fresh=reset_plan(current_snapshot,[(r['doctype'],r['name']) for r in plan['rows']],plan['orphan_exceptions'])
    if any(fresh[k]!=plan[k] for k in ['rows','business_population_checksum','protected_setup_checksum']):raise ValueError('Records or protected setup changed since approval')
    before={dt:frappe.db.count(dt) for dt in PROTECTED if frappe.db.exists('DocType',dt) and not frappe.get_meta(dt).issingle}
    counts={}
    for row in plan['rows']:
        dt=row['doctype']
        frappe.db.delete(dt,{'name':row['name']})
        if frappe.db.exists(dt,row['name']):raise ValueError('Dummy row survived reset')
        counts[dt]=counts.get(dt,0)+1
    if any(frappe.db.count(dt)!=n for dt,n in before.items()):raise ValueError('Protected setup count changed')
    return {'deleted':counts,'committed':False}
