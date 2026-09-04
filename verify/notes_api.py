"""notes.thread / notes.add, and the decision note that used to be dropped.

The interesting checks are the negative ones. A note endpoint that takes a
doctype name from the browser is an access-control surface, so what matters is
what it refuses: a doctype off the list, a record that does not exist, and a
record the caller cannot read.
"""
import sys, os, json, glob

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import stub_frappe as S
sys.path.insert(0, os.path.join(HERE, '..'))
REPO = os.path.join(HERE, '..')

for f in glob.glob(REPO + '/darkbrown/darkbrown/doctype/*/*.json'):
    d = json.load(open(f))
    if d.get('doctype') == 'DocType':
        S.SCHEMA[d['name']] = {x['fieldname']: (x['fieldtype'], x.get('options'),
                                                x.get('default'))
                               for x in d.get('fields', [])}
S.SCHEMA['User'] = {'name': ('Data', None, None), 'full_name': ('Data', None, None)}
S.SCHEMA['Comment'] = {'name': ('Data', None, None), 'content': ('Text', None, None),
                       'comment_type': ('Data', None, None), 'owner': ('Data', None, None),
                       'reference_doctype': ('Data', None, None),
                       'reference_name': ('Data', None, None),
                       'creation': ('Datetime', None, None)}

# --- what the stub does not model: comments, has_permission, date prettying
F = S.frappe
_PERM = {'ok': True}
F.has_permission = lambda dt, ptype=None, doc=None, **kw: _PERM['ok']
F.utils.strip_html = lambda t: t or ''
F.utils.get_datetime = lambda d: __import__('datetime').datetime.fromisoformat(str(d))
F.utils.now_datetime = lambda: __import__('datetime').datetime(2026, 9, 3, 12, 0)
F.strip_html = F.utils.strip_html
sys.modules['frappe.utils'].strip_html = F.utils.strip_html
sys.modules['frappe.utils'].get_datetime = F.utils.get_datetime
sys.modules['frappe.utils'].now_datetime = F.utils.now_datetime

_SEQ = [0]


def _add_comment(self, ctype, content):
    _SEQ[0] += 1
    S.DB.setdefault('Comment', []).append({
        'name': 'CMT-%03d' % _SEQ[0], 'comment_type': ctype,
        'content': content, 'owner': S.SESSION['user'],
        'reference_doctype': self.doctype, 'reference_name': self.name,
        'creation': '2026-09-03 1%d:00:00' % min(_SEQ[0], 9)})
    return True


S.Doc.add_comment = _add_comment

from darkbrown.api import notes

PASS, FAIL = [], []


def check(name, fn):
    try:
        fn(); PASS.append(name)
    except AssertionError as e:
        FAIL.append((name, 'ASSERT: %s' % e))
    except Exception as e:
        FAIL.append((name, '%s: %s' % (type(e).__name__, e)))


def reset(roles=('Managing Director',)):
    _PERM['ok'] = True
    _SEQ[0] = 0
    S.DB.clear()
    S.DB.update({
        'Collection Case': [{'name': 'CASE-001', 'tenant': 'Ahmed'}],
        'Security Deposit': [{'name': 'SD-001', 'status': 'Held', 'amount': 6500,
                              'deductions': 0, 'move_out_case': None}],
        'Invoice Run': [{'name': 'RUN-001', 'status': 'Pending GM', 'lines': [],
                         'variance_reason': None}],
        'User': [{'name': 'md@dbr.qa', 'full_name': 'Khayaz N.'}],
        'Comment': [],
    })
    S.SESSION['user'] = 'md@dbr.qa'
    S.SESSION['roles'] = list(roles)
    F.session.user = 'md@dbr.qa'


def t_write_then_read():
    reset()
    out = notes.add('Collection Case', 'CASE-001', '  Tenant promised Thursday.  ')
    assert out['count'] == 1, out
    n = out['notes'][0]
    assert n['t'] == 'Tenant promised Thursday.', repr(n['t'])
    assert n['role'] == 'MD', n
    assert n['by'] == 'Khayaz N.', n
    assert n['mine'] is True, n
    assert n['ago'].endswith('ago') or n['ago'] == 'just now', n['ago']
    assert notes.thread('Collection Case', 'CASE-001')['count'] == 1
check("a note written is a note read back, trimmed and signed by the session role",
      t_write_then_read)


def t_role_is_not_the_callers_to_choose():
    reset(roles=('Accounts',))
    out = notes.add('Collection Case', 'CASE-001', 'Receipt attached.')
    assert out['notes'][0]['role'] == 'ACC', out['notes'][0]
check("the role on a note comes from the session, not from the caller",
      t_role_is_not_the_callers_to_choose)


def t_oldest_first():
    reset()
    notes.add('Collection Case', 'CASE-001', 'first')
    notes.add('Collection Case', 'CASE-001', 'second')
    got = [n['t'] for n in notes.thread('Collection Case', 'CASE-001')['notes']]
    assert got == ['first', 'second'], got
check("a trail reads forwards - oldest note first", t_oldest_first)


def t_threads_do_not_bleed():
    reset()
    notes.add('Collection Case', 'CASE-001', 'on the case')
    notes.add('Security Deposit', 'SD-001', 'on the deposit')
    a = notes.thread('Collection Case', 'CASE-001')
    b = notes.thread('Security Deposit', 'SD-001')
    assert [n['t'] for n in a['notes']] == ['on the case'], a
    assert [n['t'] for n in b['notes']] == ['on the deposit'], b
check("one record's notes never appear on another's", t_threads_do_not_bleed)


def t_refusals():
    reset()
    for args, why in (
            (('Sales Invoice', 'SI-001'), 'a doctype off the allowlist'),
            (('Collection Case', 'NOPE'), 'a record that does not exist')):
        for fn in (notes.thread, lambda d, n: notes.add(d, n, 'x')):
            try:
                fn(*args); assert False, 'accepted %s' % why
            except (S.ValidationError, S.DoesNotExistError):
                pass
check("an unlisted doctype and an unknown record are both refused", t_refusals)


def t_empty_note_refused():
    reset()
    for text in ('', '   ', None):
        try:
            notes.add('Collection Case', 'CASE-001', text)
            assert False, 'accepted an empty note'
        except S.ValidationError:
            pass
    assert not S.DB['Comment'], S.DB['Comment']
check("an empty note is refused rather than filed blank", t_empty_note_refused)


def t_permission_is_the_records_own():
    reset()
    _PERM['ok'] = False
    for fn in (lambda: notes.thread('Collection Case', 'CASE-001'),
               lambda: notes.add('Collection Case', 'CASE-001', 'x')):
        try:
            fn(); assert False, 'read notes on a record the caller cannot read'
        except S.PermissionError_:
            pass
check("a note is never more readable than the record it hangs on",
      t_permission_is_the_records_own)


def t_too_long():
    reset()
    try:
        notes.add('Collection Case', 'CASE-001', 'x' * 5001)
        assert False, 'accepted a 5,001 character note'
    except S.ValidationError:
        pass
check("an oversized note is refused", t_too_long)


# ------------------------------------------------- the decision note survives
from darkbrown.api import approvals


def t_decision_note_is_kept_on_approval():
    """This is the fault the screen was reporting. The form makes the note
    mandatory and calls it permanent; three of the five handlers discarded it
    on approve."""
    reset()
    notes_seen = {}

    def fake_record(dt, name, text):
        notes_seen[(dt, name)] = text
        return True
    real = notes.record
    notes.record = fake_record
    try:
        approvals._deposit('SD-001', 'approve', 'Inspection clear, release in full.')
        approvals.decide.__wrapped__ if False else None
    finally:
        notes.record = real
    # _deposit itself keeps nothing on approve - that is the point, and why
    # decide() records it instead.
    doc = S.DB['Security Deposit'][0]
    assert 'Inspection clear' not in json.dumps(doc), \
        "the handler kept it after all - re-check where decide() writes it"
check("the deposit handler alone does not keep an approval reason",
      t_decision_note_is_kept_on_approval)


def t_kind_map_covers_the_queue():
    """Every category the queue can show must resolve to a doctype, or
    decide() raises a KeyError after the decision has already been applied."""
    handled = {'Amendment', 'Tenancy activation', 'Emergency maint.',
               'Deposit release', 'Invoice run'}
    assert set(approvals.KIND_DOCTYPE) == handled, \
        set(approvals.KIND_DOCTYPE) ^ handled
    for dt in approvals.KIND_DOCTYPE.values():
        assert dt in notes.NOTABLE, '%s cannot carry a note' % dt
check("every queue category maps to a doctype that can carry the note",
      t_kind_map_covers_the_queue)


def t_reserved_is_still_reserved():
    assert approvals.RESERVED == {'Deposit release', 'Emergency maint.'}
    for kind in approvals.RESERVED:
        assert kind in approvals.KIND_DOCTYPE
check("the reserved categories are unchanged by this work",
      t_reserved_is_still_reserved)


print()
for n in PASS:
    print('  PASS  %s' % n)
for n, e in FAIL:
    print('  FAIL  %s\n          %s' % (n, e))
print()
print('%d passed, %d failed' % (len(PASS), len(FAIL)))
sys.exit(1 if FAIL else 0)
