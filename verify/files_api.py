"""documents.save_files and documents.files, against a stubbed Frappe holding
the REAL Document Register and Document Archive schemas.

What is being checked is what the browser cannot check: that a file lands with
the right building and unit on it, that a unit file is a building file too,
that a type nobody recognises does not write an invalid Select value, and that
the building query is genuinely scoped rather than returning the site.
"""
import sys, os, json, glob

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import stub_frappe as S
sys.path.insert(0, os.path.join(HERE, '..'))
REPO = os.path.join(HERE, '..')

for f in glob.glob(REPO + '/darkbrown/darkbrown/doctype/*/*.json'):
    d = json.load(open(f))
    if d.get('doctype') != 'DocType':
        continue
    S.SCHEMA[d['name']] = {x['fieldname']: (x['fieldtype'], x.get('options'),
                                            x.get('default'))
                           for x in d.get('fields', [])}
S.SCHEMA['User'] = {'name': ('Data', None, None), 'full_name': ('Data', None, None)}
S.SCHEMA['File'] = {'name': ('Data', None, None), 'file_url': ('Data', None, None),
                    'file_size': ('Int', None, None)}

from darkbrown.api import documents

PASS, FAIL = [], []


def check(name, fn):
    try:
        fn()
        PASS.append(name)
    except AssertionError as e:
        FAIL.append((name, "ASSERT: %s" % e))
    except Exception as e:
        FAIL.append((name, "%s: %s" % (type(e).__name__, e)))


def reset():
    S.DB.clear()
    S.DB.update({
        'Building': [{'name': 'AK-12'}, {'name': 'AK-13'}],
        'Unit': [{'name': 'AK-12-F-01', 'building': 'AK-12'},
                 {'name': 'AK-12-F-02', 'building': 'AK-12'},
                 {'name': 'AK-13-G-01', 'building': 'AK-13'}],
        'Document Register': [],
        'Document Archive': [],
        'User': [{'name': 'Administrator', 'full_name': 'System'}],
        'File': [{'name': 'F1', 'file_url': '/private/files/a.pdf',
                  'file_size': 1048576}],
    })


def rows():
    return S.DB['Document Register']


print("=" * 72)
print("FILES ON A RECORD")
print("=" * 72)


def t_building():
    reset()
    r = documents.save_files(json.dumps({
        'files': ['/private/files/a.pdf', '/private/files/b.pdf'],
        'type': 'Title Deed', 'building': 'AK-12'}))
    assert r['filed'] == 2, r
    assert len(rows()) == 2, rows()
    for d in rows():
        assert d['building'] == 'AK-12', d
        assert not d.get('unit'), d
        assert d['status'] == 'Confirmed', d
        assert d['document_type'] == 'Title Deed', d
        # No extraction happened, so nothing may claim one did.
        assert not d.get('extractor_model'), d
        assert not d.get('extraction_confidence'), d
        assert not d.get('extracted_json'), d
check("two files against a building file as Confirmed, with no extraction claimed",
      t_building)


def t_unit_derives_building():
    reset()
    r = documents.save_files(json.dumps({
        'files': ['/private/files/ta.pdf'], 'type': 'Tenancy Agreement',
        'unit': 'AK-12-F-01'}))
    assert r['building'] == 'AK-12', r
    d = rows()[0]
    assert d['unit'] == 'AK-12-F-01' and d['building'] == 'AK-12', d
check("a unit file is a building file too - the building is derived, not asked for",
      t_unit_derives_building)


def t_unit_wins_over_a_wrong_building():
    reset()
    r = documents.save_files(json.dumps({
        'files': ['/private/files/x.pdf'], 'unit': 'AK-12-F-01',
        'building': 'AK-13'}))
    assert r['building'] == 'AK-12', "the unit's own building must win: %s" % r
check("a unit sent with the wrong building files under the unit's own building",
      t_unit_wins_over_a_wrong_building)


def t_unknown_type():
    reset()
    documents.save_files(json.dumps({
        'files': ['/private/files/a.pdf'], 'type': 'Landlord bank letter',
        'building': 'AK-12'}))
    d = rows()[0]
    opts = [o for o in S.SCHEMA['Document Register']['document_type'][1].split('\n') if o]
    assert d['document_type'] == 'Other', d
    assert d['document_type'] in opts, "wrote a value the Select does not hold"
check("a type the register does not hold becomes Other rather than an invalid value",
      t_unknown_type)


def t_refusals():
    reset()
    for payload, why in (
            ({'files': [], 'building': 'AK-12'}, 'no file'),
            ({'files': ['/f/a.pdf']}, 'neither building nor unit'),
            ({'files': ['/f/a.pdf'], 'building': 'NOPE'}, 'unknown building'),
            ({'files': ['/f/a.pdf'], 'unit': 'NOPE'}, 'unknown unit')):
        try:
            documents.save_files(json.dumps(payload))
            assert False, "accepted %s" % why
        except S.ValidationError:
            pass
    assert not rows(), "a refused call still wrote: %s" % rows()
check("nothing is filed on no file, no record, an unknown building or an unknown unit",
      t_refusals)


def t_files_building_scope():
    reset()
    documents.save_files(json.dumps({'files': ['/f/deed.pdf'],
                                     'type': 'Title Deed', 'building': 'AK-12'}))
    documents.save_files(json.dumps({'files': ['/f/ta.pdf'],
                                     'type': 'Tenancy Agreement',
                                     'unit': 'AK-12-F-01'}))
    documents.save_files(json.dumps({'files': ['/f/other.pdf'],
                                     'building': 'AK-13'}))
    out = documents.files(building='AK-12')
    got = sorted(r['f'] for r in out['rows'])
    assert got == ['deed.pdf', 'ta.pdf'], got
    assert out['on_units'] == 1, out['on_units']
    on = {r['f']: r['on'] for r in out['rows']}
    assert on['ta.pdf'] == 'AK-12-F-01' and on['deed.pdf'] == 'Building', on
check("a building shows its own files and its units', and says which door each came from",
      t_files_building_scope)


def t_files_unit_scope():
    reset()
    documents.save_files(json.dumps({'files': ['/f/deed.pdf'], 'building': 'AK-12'}))
    documents.save_files(json.dumps({'files': ['/f/ta.pdf'], 'unit': 'AK-12-F-01'}))
    documents.save_files(json.dumps({'files': ['/f/two.pdf'], 'unit': 'AK-12-F-02'}))
    out = documents.files(unit='AK-12-F-01')
    got = [r['f'] for r in out['rows']]
    assert got == ['ta.pdf'], got
check("a unit shows only its own files, not its neighbours' and not the building's",
      t_files_unit_scope)


def t_archive_wins():
    reset()
    documents.save_files(json.dumps({'files': ['/f/deed.pdf'], 'building': 'AK-12'}))
    reg = rows()[0]['name']
    S.DB['Document Archive'].append({
        'name': 'ARCH-001', 'file': '/f/deed.pdf', 'document_type': 'Title Deed',
        'building': 'AK-12', 'unit': None, 'archived_on': '2026-09-01',
        'archived_by': 'Administrator', 'source_register': reg,
        'original_filename': 'deed.pdf', 'owner': 'Administrator',
        'modified': '2026-09-01'})
    out = documents.files(building='AK-12')
    assert len(out['rows']) == 1, "the same document twice: %s" % out['rows']
    assert out['rows'][0]['src'] == 'Archive', out['rows'][0]
check("an archived document is not listed twice - the archive copy wins",
      t_archive_wins)


def t_no_record_named():
    reset()
    try:
        documents.files()
        assert False, "read the whole register with no record named"
    except S.ValidationError:
        pass
check("files() refuses to answer without a building or a unit", t_no_record_named)


def t_types_from_meta():
    reset()
    opts = [o for o in S.SCHEMA['Document Register']['document_type'][1].split('\n') if o]
    assert documents.file_types() == opts, "the type list is not the register's own"
    assert 'Other' in opts
check("the type list is read off the DocType, not repeated in code", t_types_from_meta)


print()
for n in PASS:
    print("  PASS  %s" % n)
for n, e in FAIL:
    print("  FAIL  %s\n          %s" % (n, e))
print()
print("%d passed, %d failed" % (len(PASS), len(FAIL)))
sys.exit(1 if FAIL else 0)
