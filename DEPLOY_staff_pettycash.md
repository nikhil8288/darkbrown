# Single-page forms · Staff · Petty cash

Repo-root overlay. **Supersedes both earlier zips** (`darkbrown_single_page_forms.zip`
and `darkbrown_forms_and_hr.zip`). Apply this one only.

Needs a migrate — two new doctypes and a new settings field:

    bench --site <site> migrate
    bench --site <site> clear-cache

Then hard-refresh, and set **DBR Settings → People → Staff Pay Day**. It defaults to
the 5th, which is an assumption that was never confirmed and decides which week of
the runway carries payroll.

## Files

New:

    darkbrown/api/people.py
    darkbrown/api/pettycash.py
    darkbrown/darkbrown/doctype/staff_member/…
    darkbrown/darkbrown/doctype/petty_cash_entry/…

Changed:

    darkbrown/shell/index.html
    darkbrown/api/command.py
    darkbrown/api/charts.py
    darkbrown/api/app.py
    darkbrown/darkbrown/doctype/dbr_settings/dbr_settings.json

---

# 1 — Every form is one page

The engine reads the same step definitions and renders them together instead of one
at a time. Steps became numbered sections down the page, the step rail became a jump
rail, Back and Continue went, and there is one save button carrying the form's own
wording. All 17 multi-step forms convert; the 24 single-step forms are untouched.

**Clicking outside no longer closes anything.** X, Cancel or Escape only. If there is
anything in the form, a sheet asks first, and leaving keeps what was entered —
including chosen files — restored next time that form opens, with a "Start fresh"
button. Drafts are per form, held for the browser session, dropped once the record
saves.

**Validation runs once, on save.** Every section is checked. What comes back is a list
of what is outstanding, each entry a link that scrolls to and focuses the field, with
the sections and rail chips concerned marked red.

Three things behind that, each of which was a bug found by building this:

*Derived sections refresh on change.* A section may read a field defined in another —
the payment schedule from the lease value. Redrawing on every change was the first
attempt and it was too blunt: the whole form is replaced, so the field the cursor was
moving to gets torn out from under it. The engine now works out per form which keys
are read outside the section that defines them, and redraws only on those. Read off
the step definitions, so new forms need no annotation.

*Redraws are deferred to the end of the turn.* Typing in a live field and then
clicking Save ran blur, change, redraw — and the redraw replaced the button between
mousedown and mouseup, so no click was ever dispatched. The button looked dead; it had
been rebuilt underneath the finger. **This affected the existing forms too, before any
of this work.**

*On save: check, then redraw, then check again.* A step's own check is what commits
editor state that is not a plain field — the unit editor reads its rows out of the DOM
when asked — so redrawing first threw that work away and onboard-building stopped
saving. Redrawing after is safe and is needed, or a conditional field like the petty
cash reason box is demanded by an error message but never shown.

*The confirm sheet renders into a new `#modal2`,* not `#modal`, or a redraw takes it
with it before the click on it lands.

---

# 2 — Staff

Scope is small on purpose. The point is the money: salaries are a fixed monthly
operating cost that this system recorded nowhere.

- **D74** Portfolio overhead. Does not touch building margin, which stays the spread
  after head-lease.
- **D75** No gratuity accrual. Basic and allowances stored separately so it can be
  added without revisiting records.
- **D76** Pay visible to Accounts and the MD. GM sees headcount, names, departments.

`Staff Member` — not named `Employee`, ERPNext already has one. Pay fields sit at
`permlevel: 1`, so Frappe withholds them rather than the screen doing it.
`monthly_staff_cost` is **not** whitelisted: a whitelisted total salary bill is one
available to anyone who can call it. `save_staff` refuses to write pay when the caller
cannot see it, or a GM editing a job title would silently blank a salary.

Not in it: payroll runs, WPS, attendance, leave, employee documents and expiry,
gratuity, approvals. Document expiry is the cheapest to add back — the lease-expiry
alerting already exists and employee documents would ride on it.

---

# 3 — Petty cash

- **D78** A float with a running balance, not an expense log.
- **D79** Portfolio overhead, no building tag. Same reasoning as D74.

An expense log says what was spent. Only a float says whether the money that should be
in the box still is, which in a business this cash-heavy is the question worth being
able to answer. Three movements: top-up, expense, and the adjustment when a physical
count disagrees.

The balance is derived from the movements every time and never stored, because a
stored balance and a movement history can disagree and there is then no way to tell
which one lied. Running balances compute forward from the beginning, so a back-dated
entry reshapes everything after it.

Adjustments carry a mandatory reason and their own direction. Both matter: a count
that does not agree is a fact about the cash and possibly about a person, and writing
the book silently down to the box destroys the only evidence. The direction is
explicit because assuming one meant a shortfall *increasing* the book — that was a
real bug in the first draft of this module.

**Partly answers Q24.** Top-ups name the account they came from, so an ATM withdrawal
that funds the float stops being an unclassified cash movement. Not all of Q24 — cash
leaves the accounts for other reasons — but a real piece of it.

---

# 4 — Where the money actually lands

This was the question that prompted the batch, and the honest answer had been "two of
four". Now:

| | payroll | petty cash |
|---|---|---|
| Spread bridge `_waterfall` | yes, one **Overhead** bar | yes, same bar |
| 13-week runway `_runway_flows` | yes, in the pay-day week | expected line only |
| 12-month projection `get_projection` | **yes, new (D80)** | yes, trailing average |
| Headline `spread` KPI | no — **D77**, unconfirmed | no |

The projection was the one that mattered. Its whole purpose is finding the month the
cumulative line goes under, and it modelled rent in against head-lease out and nothing
else — so it was reporting a danger month later than the truth. Payroll enters at
today's figure; petty cash as a trailing three-month average, because a one-off last
March says nothing about next March. The runway keeps actual dated movements and gets
the average only on its *expected* line, never the confirmed one — the confirmed line
answers "what is certain", and an average is not.

The bridge shows staff and petty cash as one **Overhead** bar rather than two. Petty
cash is small beside payroll and a seventh bar would be a sliver against labels the
box cannot fit; the split is returned alongside for the panel to name.

**D77 still needs your call.** The headline `spread` KPI is billed minus head-lease,
compared period-on-period, and feeds several panels. Netting overhead into it would
change what the number means without renaming it, so it was left alone.

## A correction

Earlier notes said staff cost reaches the reserve floor and the distribution gate.
**It does not, because they do not exist in the code.** Stage 2I is in the Product
Bible and the Design Working Document, not in `api/`. Nothing enforces a reserve gate
today. The `people.py` docstring has been corrected.

---

## Tested, and not

Against the prototype's seeded data: 41 forms open with all sections rendered, 69
routes clean across MD/GM/ACC/DOC/MNT, drafts and the confirm sheet behave,
onboard-building and add-staff save end to end, the bridge renders six bars with no
overflow, staff masking is right per role, and the float arithmetic is verified —
including that a shortfall decreases the book and a count that agrees writes nothing.

**Not verified:** anything against a real database. Neither doctype has been through
`bench migrate`; `_staff_seed` and `_petty_seed` are untested against real records.
Run it on a test site first.

Known, neither introduced here:

- Bridge bar labels truncate at 18 characters, so "Spread after recorded costs" was
  already clipped.
- `classify-line` throws when opened without a context. It always has; it is only ever
  called as `openForm('classify-line',{id})`.

## Testing note

`fill()` does not blur, and `change` fires on blur — so a test that fills and clicks
Save without tabbing out will not trigger the live redraw and will not reproduce what
a person sees. Click the field, fill it, tab out, then move on.
