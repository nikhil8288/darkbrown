"""Minimal Frappe stub. Imports the REAL darkbrown modules and executes against
this, so a pass means the shipped file works — not a hand-written replica."""
import sys, types, json as _json, datetime

CALLS = []          # every db mutation
THROWN = []         # every frappe.throw
DB = {}             # doctype -> list[dict]
SESSION = {"user": "acc@darkbrown.qa", "roles": ["Accounts"]}

class ValidationError(Exception): pass
class PermissionError_(Exception): pass
class DoesNotExistError(Exception): pass

def _(s): return s

class _Meta:
    def __init__(self, dt): self.dt = dt
    def get_field(self, f):
        spec = SCHEMA.get(self.dt, {}).get(f)
        if not spec: return None
        return types.SimpleNamespace(fieldtype=spec[0], options=spec[1])
    def has_field(self, f): return f in SCHEMA.get(self.dt, {})

SCHEMA = {}

class Doc(dict):
    def __init__(self, dt, d=None):
        super().__init__(d or {})
        self["doctype"] = dt
        self.flags = types.SimpleNamespace(ignore_permissions=False,
                                           ignore_mandatory=False)
        self.meta = _Meta(dt)
        self._changed = set()
    # attribute access mirrors Frappe: declared fields resolve, others raise
    def __getattr__(self, k):
        if k.startswith("_"): raise AttributeError(k)
        dt = self.get("doctype")
        if k in self or k in SCHEMA.get(dt, {}):
            return self.get(k)
        raise AttributeError(
            "'%s' object has no attribute '%s' (not a field on %s)" % (
                type(self).__name__, k, dt))
    def __setattr__(self, k, v):
        if k in ("flags", "meta", "_changed"): object.__setattr__(self, k, v)
        else:
            self[k] = v
            self._changed.add(k)
    def set(self, k, v): self[k] = v
    def get(self, k, default=None): return dict.get(self, k, default)
    def has_permission(self, p="read"): return True
    def has_value_changed(self, f): return f in self._changed
    def _controller(self):
        """The real doctype controller class, if this app defines one. Running
        it means insert()/save() exercise validate() and on_update() exactly as
        Frappe would - without this, a test that asserts on a controller side
        effect silently asserts on nothing."""
        import importlib, re as _re
        dt = self.get("doctype")
        snake = _re.sub(r"[^a-z0-9]+", "_", (dt or "").lower()).strip("_")
        try:
            mod = importlib.import_module(
                "darkbrown.darkbrown.doctype.%s.%s" % (snake, snake))
        except Exception:
            return None
        cls = getattr(mod, "".join(w.title() for w in snake.split("_")), None)
        if cls is None:
            return None
        inst = cls.__new__(cls)
        object.__setattr__(inst, "_changed", self._changed)
        object.__setattr__(inst, "flags", self.flags)
        object.__setattr__(inst, "meta", self.meta)
        dict.update(inst, self)
        return inst

    def _run_controller(self, *methods):
        c = self._controller()
        if c is None:
            return
        for m in methods:
            fn = getattr(c, m, None)
            if callable(fn):
                fn()
        # copy any values the controller derived back onto this document
        dict.update(self, c)

    def save(self, ignore_permissions=False):
        self._run_controller("validate", "before_save")
        _validate_selects(self)
        # persist, so a test can assert on the stored row and not just the call
        for r in DB.get(self["doctype"], []):
            if r.get("name") == self.get("name"):
                r.update({k: v for k, v in self.items() if k != "doctype"})
                break
        CALLS.append(("save", self["doctype"], dict(self)))
        self._run_controller("on_update")
        return self
    def insert(self, ignore_permissions=False):
        self._run_controller("validate", "before_insert")
        _validate_selects(self)
        self.setdefault("name", "%s-NEW-%d" % (self["doctype"][:4].upper(), len(CALLS)))
        DB.setdefault(self["doctype"], []).append(dict(self))
        CALLS.append(("insert", self["doctype"], dict(self)))
        self._run_controller("after_insert", "on_update")
        # reflect controller-derived values onto the stored row
        for r in DB.get(self["doctype"], []):
            if r.get("name") == self.get("name"):
                r.update({k: v for k, v in self.items() if k != "doctype"})
                break
        return self
    def submit(self): self["docstatus"] = 1; CALLS.append(("submit", self["doctype"], dict(self))); return self
    def cancel(self): self["docstatus"] = 2; CALLS.append(("cancel", self["doctype"], dict(self))); return self
    def delete(self): CALLS.append(("delete", self["doctype"], dict(self)))
    def db_set(self, k, v=None, update_modified=True):
        if isinstance(k, dict): self.update(k)
        else: self[k] = v
        CALLS.append(("db_set", self["doctype"], dict(self)))
    def reload(self): return self
    def append(self, key, row):
        self.setdefault(key, []).append(row); return row
    def add_comment(self, t, txt): CALLS.append(("comment", self["doctype"], txt))
    def as_dict(self): return dict(self)

def _validate_selects(doc):
    dt = doc.get("doctype")
    for f, spec in SCHEMA.get(dt, {}).items():
        if spec[0] == "Select" and doc.get(f) is not None:
            opts = [o.strip() for o in (spec[1] or "").split("\n") if o.strip()]
            if opts and doc.get(f) not in opts:
                raise ValidationError(
                    "%s is not a valid value for %s.%s (options: %s)"
                    % (doc.get(f), dt, f, "/".join(opts)))

# ------------------------------------------------------------------ module
frappe = types.ModuleType("frappe")
frappe.ValidationError = ValidationError
frappe.PermissionError = PermissionError_
frappe.DoesNotExistError = DoesNotExistError
frappe._ = _
frappe.session = types.SimpleNamespace(user=SESSION["user"])
frappe.flags = types.SimpleNamespace(in_test=True)
frappe.local = types.SimpleNamespace(flags=types.SimpleNamespace())

def throw(msg, exc=ValidationError):
    THROWN.append(str(msg))
    raise (exc if isinstance(exc, type) else ValidationError)(str(msg))
frappe.throw = throw
def whitelist(allow_guest=False, methods=None, **kw):
    def deco(fn):
        fn.__wrapped_whitelisted__ = True
        return fn
    return deco
frappe.whitelist = whitelist
frappe.conf = {}
frappe.utils_password = None
frappe.msgprint = lambda *a, **k: None
frappe.get_roles = lambda u=None: SESSION["roles"]
frappe.get_doc = lambda dt, name=None, **kw: (
    Doc(dt["doctype"], dt) if isinstance(dt, dict)
    else Doc(dt, dict(_find(dt, name) or {"name": name})))
frappe.new_doc = lambda dt: Doc(dt, _defaults(dt))
frappe.get_meta = lambda dt: _Meta(dt)
frappe.get_single = lambda dt: Doc(dt, DB.get(dt, [{}])[0])
frappe.get_all = lambda dt, **kw: _get_all(dt, **kw)
frappe.get_list = frappe.get_all
frappe.log_error = lambda *a, **k: CALLS.append(("log_error", a, k))
frappe.get_traceback = lambda: "traceback"
frappe.publish_realtime = lambda *a, **k: None
frappe.parse_json = lambda s: _json.loads(s) if isinstance(s, str) else s
frappe.as_json = lambda o: _json.dumps(o, default=str)
frappe.cache = lambda: _CACHE
frappe.defaults = types.SimpleNamespace(
    get_global_default=lambda k: "DarkBrown RealEstate")

class _Cache:
    def __init__(self): self.d = {}
    def get_value(self, k): return self.d.get(k)
    def set_value(self, k, v, expires_in_sec=None): self.d[k] = v
_CACHE = _Cache()

def _defaults(dt):
    out = {}
    for f, spec in SCHEMA.get(dt, {}).items():
        if len(spec) > 2 and spec[2] is not None: out[f] = spec[2]
    return out

def _find(dt, name):
    for r in DB.get(dt, []):
        if r.get("name") == name: return r
    return None

def _match(row, filters):
    if not filters: return True
    if isinstance(filters, list):
        return all(_match(row, {f[0]: f[1:] if len(f) > 2 else f[1]}) for f in filters)
    for k, v in filters.items():
        rv = row.get(k)
        if isinstance(v, (list, tuple)) and len(v) == 2:
            op, val = v
            if op == "in" and rv not in val: return False
            if op == "not in" and rv in val: return False
            if op == "!=" and rv == val: return False
            if op == "<" and not (rv is not None and rv < val): return False
            if op == "<=" and not (rv is not None and rv <= val): return False
            if op == ">" and not (rv is not None and rv > val): return False
            if op == "is": 
                if val == "set" and not rv: return False
                if val == "not set" and rv: return False
            if op == "like":
                if rv is None: return False
                if val.strip("%") not in str(rv): return False
            if op == "between":
                if rv is None or not (val[0] <= rv <= val[1]): return False
        elif rv != v: return False
    return True

def _match_or(row, or_filters):
    """Frappe's or_filters: any one key matching is enough. The stub used to
    drop them into **kw, which meant a query scoped with or_filters came back
    unscoped and any test of that scoping passed for the wrong reason."""
    if not or_filters:
        return True
    if isinstance(or_filters, list):
        return any(_match(row, {f[0]: f[1:] if len(f) > 2 else f[1]})
                   for f in or_filters)
    return any(_match(row, {k: v}) for k, v in or_filters.items())


def _get_all(dt, filters=None, fields=None, pluck=None, limit=None,
             order_by=None, as_dict=True, or_filters=None, **kw):
    rows = [r for r in DB.get(dt, [])
            if _match(r, filters) and _match_or(r, or_filters)]
    if limit: rows = rows[:limit]
    if pluck: return [r.get(pluck) for r in rows]
    out = []
    for r in rows:
        d = Doc(dt, r) if fields is None else Doc(dt, {f: r.get(f) for f in fields
                                                      if not f.startswith("sum(")})
        out.append(d)
    return out

class _DB:
    def get_value(self, dt, name=None, field=None, as_dict=False, **kw):
        rows = DB.get(dt, [])
        if isinstance(name, dict): rows = [r for r in rows if _match(r, name)]
        else: rows = [r for r in rows if r.get("name") == name]
        if not rows: return None
        r = rows[0]
        if as_dict:
            return Doc(dt, {f: r.get(f) for f in (field or r.keys())})
        if isinstance(field, (list, tuple)): return [r.get(f) for f in field]
        return r.get(field)
    def set_value(self, dt, name, field, value=None, update_modified=True):
        CALLS.append(("db.set_value", dt, name, field, value))
        for r in DB.get(dt, []):
            if r.get("name") == name:
                r.update(field if isinstance(field, dict) else {field: value})
    def exists(self, dt, filters=None):
        if isinstance(filters, dict):
            return next((r["name"] for r in DB.get(dt, []) if _match(r, filters)), None)
        return next((r["name"] for r in DB.get(dt, []) if r.get("name") == filters), None)
    def count(self, dt, filters=None):
        return len([r for r in DB.get(dt, []) if _match(r, filters)])
    def get_single_value(self, dt, f): return (DB.get(dt) or [{}])[0].get(f)
    def sql(self, q, vals=None, as_dict=False): return [[0]]
    def commit(self): CALLS.append(("commit",))
    def rollback(self): pass
frappe.db = _DB()

# frappe.utils
u = types.ModuleType("frappe.utils")
def flt(v, precision=None):
    try: v = float(v or 0)
    except (TypeError, ValueError): v = 0.0
    return round(v, precision) if precision is not None else v
def cint(v):
    try: return int(float(v or 0))
    except (TypeError, ValueError): return 0
def getdate(d=None):
    if isinstance(d, datetime.date): return d
    if not d: return datetime.date.today()
    return datetime.date.fromisoformat(str(d)[:10])
u.flt, u.cint, u.getdate = flt, cint, getdate
u.today = lambda: datetime.date.today().isoformat()
u.nowdate = u.today
u.now = lambda: datetime.datetime.now().isoformat()
u.now_datetime = lambda: datetime.datetime.now()
u.add_days = lambda d, n: (getdate(d) + datetime.timedelta(days=n)).isoformat()
u.add_months = lambda d, n: (getdate(d) + datetime.timedelta(days=30*n)).isoformat()
u.date_diff = lambda a, b: (getdate(a) - getdate(b)).days
u.get_last_day = lambda d: getdate(d).replace(day=28).isoformat()
u.fmt_money = lambda v, currency=None: "%s %s" % (currency or "", flt(v))
u.get_first_day = lambda d: getdate(d).replace(day=1).isoformat()
u.cstr = lambda v: "" if v is None else str(v)
u.get_datetime = lambda d=None: (datetime.datetime.fromisoformat(str(d)) if d
                                 else datetime.datetime.now())
u.formatdate = lambda d=None, f=None: str(d or "")
u.format_datetime = u.formatdate
u.time_diff_in_hours = lambda a, b: 0.0
u.get_url = lambda *a, **k: "https://erp.darkbrown.qa"
u.random_string = lambda n=8: "x" * n
u.escape_html = lambda v: str(v or "")
u.money_in_words = lambda v, c=None: "%s only" % v
u.get_datetime_str = lambda d: str(d)
u.add_to_date = lambda d, **k: u.add_days(d, k.get("days", 0))
pw = types.ModuleType("frappe.utils.password")
pw.get_decrypted_password = lambda *a, **k: "sk-test"
sys.modules["frappe.utils.password"] = pw
u.password = pw
frappe.utils = u
for n in ("flt","cint","getdate","today","nowdate","now","add_days","add_months",
          "date_diff","get_last_day","fmt_money","cstr","now_datetime","get_first_day",
          "get_datetime","formatdate","format_datetime","get_url","escape_html",
          "money_in_words","add_to_date","random_string"):
    setattr(frappe, n, getattr(u, n))

# submodules the app imports
for mod, attrs in {
    "frappe.model": {}, "frappe.model.document": {"Document": Doc},
    "frappe.desk": {}, "frappe.desk.form": {},
    "frappe.desk.form.assign_to": {"add": lambda *a, **k: CALLS.append(("assign", a)),
                                   "DuplicateToDoError": type("DuplicateToDoError",(Exception,),{})},
    "frappe.website": {}, "frappe.website.page_renderers": {},
    "frappe.website.page_renderers.base_renderer": {"BaseRenderer": object},
    "frappe.sessions": {"get_csrf_token": lambda: "csrf"},
    "frappe.custom": {}, "frappe.custom.doctype": {},
    "frappe.custom.doctype.custom_field": {},
    "frappe.custom.doctype.custom_field.custom_field": {
        "create_custom_fields": lambda *a, **k: CALLS.append(("custom_fields", a))},
    "frappe.custom.doctype.property_setter": {},
    "frappe.custom.doctype.property_setter.property_setter": {
        "make_property_setter": lambda *a, **k: None},
    "frappe.core": {}, "frappe.core.doctype": {},
    "frappe.utils.password": {"get_decrypted_password": lambda *a, **k: "sk-test"},
    "erpnext": {}, "erpnext.accounts": {},
    "erpnext.accounts.party": {"get_party_account": lambda *a, **k: "Debtors"},
}.items():
    m = types.ModuleType(mod)
    for k, v in attrs.items(): setattr(m, k, v)
    sys.modules[mod] = m
frappe.model = sys.modules["frappe.model"]
frappe.sessions = sys.modules["frappe.sessions"]
sys.modules["frappe"] = frappe
sys.modules["frappe.utils"] = u

types = __import__("types")
