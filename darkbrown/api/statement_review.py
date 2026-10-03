"""Durable private statement reviews; no accounting or clearing side effects."""
import hashlib
import json

import frappe
from frappe.utils import now_datetime
from darkbrown.guards import guard, MD, ACC
from darkbrown.permissions import require_file_access

PREFIX = 'dbr-statement-review-'
VERSION = 1


def _scope():
    company = frappe.get_single('DBR Settings').default_company
    # Preserve File ownership boundaries: each user has their own saved reviews.
    digest = hashlib.sha256((company + '\0' + frappe.session.user).encode()).hexdigest()[:24]
    return company, PREFIX + digest + '-'


def row_key(row):
    """Balance distinguishes genuine same-date/reference/amount bank movements."""
    return tuple(str(row.get(k) or '') for k in
                 ('date', 'value_date', 'ref', 'amount', 'direction', 'balance'))


def _read(name):
    company, prefix = _scope()
    if not str(name).startswith(prefix):
        frappe.throw('Not permitted to read this statement review.', frappe.PermissionError)
    file = frappe.get_doc('File', name)
    if file.owner != frappe.session.user or not file.is_private:
        frappe.throw('Not permitted to read this statement review.', frappe.PermissionError)
    require_file_access(file.file_url)
    saved = json.loads(file.get_content())
    if saved.get('schema') != VERSION or saved.get('company') != company:
        frappe.throw('Unsupported statement review.')
    return saved


def _files():
    company, prefix = _scope()
    result = []
    while True:
        page = frappe.get_list('File', filters={'name': ['like', prefix + '%'],
            'owner': frappe.session.user, 'is_private': 1}, fields=['name'],
            order_by='creation desc, name desc', start=len(result), page_length=500)
        result.extend(page)
        if len(page) < 500:
            return result


@frappe.whitelist()
def list_reviews():
    guard(MD, ACC)
    result = []
    for file in _files():
        saved = _read(file.name)
        data = saved['review']
        result.append({'id': file.name, 'bank': data['bank'],
            'account_suffix': data['account_suffix'], 'saved_on': saved['saved_on'],
            'from_date': data['rows'][0]['date'], 'to_date': data['rows'][-1]['date'],
            'rows': len(data['rows']), 'historical': data['historical'],
            'closing': data['closing']})
    return result


@frappe.whitelist()
def load_review(name):
    guard(MD, ACC)
    saved = _read(name)
    return dict(saved['review'], saved_id=name, saved_on=saved['saved_on'],
                snapshot=True, duplicate_file=False)


@frappe.whitelist()
def save_review(file_url):
    guard(MD, ACC)
    from darkbrown.api.cashdesk import preview_statement_file
    source = require_file_access(file_url)
    if not source.is_private or not (source.file_name or '').lower().endswith('.pdf'):
        frappe.throw('Upload one private PDF statement.')
    raw = source.get_content()
    raw = raw.encode() if isinstance(raw, str) else raw
    digest = hashlib.sha256(raw).hexdigest()
    company, prefix = _scope()
    name = prefix + digest
    # Serialize validation; the deterministic primary key also prevents duplicate
    # saved reviews if concurrent requests race across the transaction boundary.
    with frappe.cache.lock(name, timeout=180, blocking_timeout=180):
        if frappe.db.exists('File', name):
            result = load_review(name)
            result['duplicate_file'] = True
            return result
        review = preview_statement_file(file_url)
        if not review.get('bank_account'):
            frappe.throw('Resolve the company bank account mapping before saving this review.')
        latest = source.get_content()
        latest = latest.encode() if isinstance(latest, str) else latest
        if hashlib.sha256(latest).hexdigest() != digest:
            frappe.throw('Source changed during validation. Validate the PDF again.')
        prior_keys = set()
        for file in _files():
            old = _read(file.name)['review']
            if old['bank_account'] == review['bank_account']:
                prior_keys.update(row_key(row) for row in old['rows'])
        overlaps = [i for i, row in enumerate(review['rows'], 1) if row_key(row) in prior_keys]
        review['saved_overlap_rows'] = overlaps
        if overlaps:
            review['exceptions'].append(str(len(overlaps)) +
                ' rows also occur in a saved review. They are retained for audit, not imported again.')
        for i, row in enumerate(review['rows'], 1):
            row['source_row_id'] = digest + ':' + str(i)
        saved = {'schema': VERSION, 'company': company, 'source_sha256': digest,
                 'saved_on': str(now_datetime()), 'review': review}
        frappe.get_doc({'doctype': 'File', 'file_name': name + '.json',
            'is_private': 1, 'content': json.dumps(saved, sort_keys=True),
            'folder': 'Home'}).insert(set_name=name)
        return dict(review, saved_id=name, saved_on=saved['saved_on'],
                    snapshot=True, duplicate_file=False)
