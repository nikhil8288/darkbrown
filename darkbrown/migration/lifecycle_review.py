"""Build exact, non-executable lifecycle proposals from an offline rehearsal."""
from darkbrown.migration.evidence import digest
from darkbrown.migration.inventory import snapshot_checksum

# Reviewed controllers, not a floating major-version compatibility claim.
REVIEWED_HEADS = {
    'frappe': '8f801ade016078685c3165c96e38f84f249f5309',
    'erpnext': '4aee12e16c664897571457c007aaa95b8364bbbb',
    'darkbrown': 'cc46da34badf1e3ba577ae4efd62772be3ca44d1',
}


def propose(snapshot, rehearsal):
    if snapshot.get('snapshot_checksum') != snapshot_checksum(snapshot):
        raise ValueError('Modified snapshot')
    if rehearsal.get('rehearsal_checksum') != digest({k:v for k,v in rehearsal.items() if k != 'rehearsal_checksum'}):
        raise ValueError('Modified rehearsal')
    if rehearsal.get('snapshot_checksum') != snapshot['snapshot_checksum']:
        raise ValueError('Stale rehearsal')
    rows = {(dt,r['name']):r for dt,data in snapshot['records'].items() for r in data['rows']}
    proposals, holds = [], []
    mismatches = [app for app, head in REVIEWED_HEADS.items() if snapshot.get('versions',{}).get(app,{}).get('head') != head]
    if mismatches:
        return {'execution_enabled':False, 'proposals':[], 'holds':[{'reason':'Controller versions require review','apps':mismatches}]}
    selected = {tuple(member) for group in rehearsal['lifecycle_groups'] for member in group['members']}
    for group in rehearsal['cyclic_groups']:
        keys = [tuple(key) for key in group]
        by_type = {key[0]:key for key in keys}
        if len(keys) != 2 or len(by_type) != 2 or not set(keys).issubset(selected):
            holds.append({'records':keys,'reason':'Unreviewed cycle shape'})
            continue
        action = None
        if set(by_type) == {'Customer','Contact'}:
            customer, contact = by_type['Customer'], by_type['Contact']
            contact_links = [(k,r) for k,r in rows.items() if k[0]=='Dynamic Link' and r.get('parenttype')=='Contact' and r.get('parent')==contact[1]]
            if (len(contact_links)==1 and contact_links[0][1].get('link_doctype')=='Customer'
                and contact_links[0][1].get('link_name')==customer[1]
                and contact_links[0][0] in selected and not rows[contact].get('user')
                and rows[customer].get('customer_primary_contact')==contact[1]):
                action={'kind':'native_customer_on_trash_rehearsal','owner':customer,
                        'owned_contact':contact,'manual_unlink':False,
                        'requirement':'Native on_trash clears primary contact and deletes exclusively linked contact; verify installed hooks and all side effects in integration test.'}
        else:
            rule = {frozenset({'Cheque','Deposit Batch'}):('Cheque','deposit_batch','Deposit Batch'),
                    frozenset({'Move Out Case','Security Deposit'}):('Security Deposit','move_out_case','Move Out Case')}.get(frozenset(by_type))
            if rule:
                source_type, field, target_type = rule
                source, target = by_type[source_type], by_type[target_type]
                if rows[source].get(field)==target[1] and rows[source].get('docstatus')==0 and any(
                    link['doctype']==source_type and link['field']==field and link['type']=='Link' and link['target']==target_type
                    for link in snapshot['relationships']):
                    action={'kind':'exact_backlink_clear_rehearsal','record':source,'field':field,
                            'expected_value':target[1],'proposed_value':None,'target':target,
                            'requirement':'Rehearse permission-checked document save with all other fields/status unchanged. Verify hooks do not repost, recreate links or modify retained records. Never direct SQL.'}
        if action:
            action['source_snapshot_checksum']=snapshot['snapshot_checksum']
            action['bound_records']=[{'doctype':k[0],'name':k[1],'content_checksum':rows[k]['content_checksum']} for k in keys]
            action['execution_enabled']=False
            proposals.append(action)
        else:
            holds.append({'records':keys,'reason':'Reviewed cycle preconditions not satisfied'})
    for key in sorted(selected):
        row=rows[key]
        if key[0]=='Tenancy Agreement' and row.get('status')!='Draft':
            holds.append({'record':key,'reason':'Native on_trash only permits Draft; do not change operational status or bypass hook without a separately approved migration design.'})
        elif key[0]=='Head Lease' and row.get('status') not in {'Draft','Expired','Terminated'}:
            holds.append({'record':key,'reason':'Native on_trash rejects active lease; explicit migration lifecycle design required.'})
        elif key[0]=='Building' and row.get('cost_center'):
            holds.append({'record':key,'reason':'Deployed on_trash deletes protected cost centre; deploy and verify retention fix before cleanup.'})
    result={'execution_enabled':False,'snapshot_checksum':snapshot['snapshot_checksum'],
            'rehearsal_checksum':rehearsal['rehearsal_checksum'],'reviewed_heads':REVIEWED_HEADS,
            'proposals':proposals,'holds':holds,
            'warning':'Proposals do not clear original graph, queue, cutover, recovery or approval blockers.'}
    result['review_checksum']=digest(result)
    return result
