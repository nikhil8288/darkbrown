# Single-page forms + HR module

Repo-root overlay. **This supersedes `darkbrown_single_page_forms.zip`** — the same
shell change is in here, plus the HR module on top. Apply this one, not both.

## Files

New:

    darkbrown/api/people.py
    darkbrown/darkbrown/doctype/staff_member/{__init__.py,staff_member.json,staff_member.py}

Changed:

    darkbrown/shell/index.html                                (forms engine + staff screens)
    darkbrown/api/command.py                                  (bridge + runway)
    darkbrown/api/app.py                                      (boot payload)
    darkbrown/darkbrown/doctype/dbr_settings/dbr_settings.json (staff pay day)

## Deploying

This one **does** need a migrate — there is a new doctype and a new settings field:

    bench --site <site> migrate
    bench --site <site> clear-cache

Then hard-refresh the browser.

After migrating, set **DBR Settings → People → Staff Pay Day**. It defaults to the
5th. This was never confirmed, so the default is an assumption and it decides which
week of the runway carries payroll.

---

# Part one — every form is one page

The engine reads the same step definitions and renders them together instead of one
at a time. Steps became numbered sections down the page, the step rail became a jump
rail, Back and Continue went, and there is one save button carrying the form's own
wording. All 17 multi-step forms convert; the single-step forms are untouched.

**Clicking outside no longer closes anything.** A form closes on the X, on Cancel, or
on Escape. If there is anything in it, a sheet asks first, and leaving keeps what was
entered — including chosen files — restored next time that form opens, with a strip
saying so and a "Start fresh" button. Drafts are per form, held for the browser
session, dropped once the record saves.

**Validation runs once, on save.** Every section is checked. What comes back is a list
of what is outstanding, each entry a link that scrolls to and focuses the field, with
the sections and rail chips concerned marked red.

Two things behind that:

*Derived sections refresh on change.* A section may read a field defined in another —
the payment schedule from the lease value, the unit list from the building. Redrawing
on every change was the first attempt and it was too blunt: the whole form is
replaced, so the field the cursor was moving to gets torn out from under it. The
engine now works out per form which keys are read outside the section that defines
them, and redraws only on those. For onboard-building that is three fields, not
twenty-eight. It is read off the step definitions, so new forms need no annotation.

*The confirm sheet renders into a new `#modal2`,* not into `#modal`. Leaving a field
fires a change, a change can redraw the form, and a redraw replaces `#modal` wholesale
— which took the sheet with it before the click on it had landed.

---

# Part two — HR

Scope is deliberately small. The point is the money: salaries are a fixed monthly
operating cost that this system recorded nowhere, so the bridge, the runway and every
cost base read better than the business was.

## Decisions this implements

- **D74** Staff cost is portfolio overhead. It does not touch building margin, which
  stays the spread after head-lease. It does hit total operating cost, so it reaches
  the reserve floor and the distribution gate.
- **D75** No gratuity accrual in v1. Basic and allowances are stored separately anyway,
  so it can be added without revisiting records.
- **D76** Pay visible to Accounts and the MD. GM sees headcount, names, departments.
- **D77 (proposed, overturn if you disagree)** The headline `spread` KPI is left alone.
  It is billed minus head-lease, compared period-on-period, and feeds several panels;
  netting overhead into it would change what the number means without renaming it.
  Staff appears in the bridge and the runway instead.

## What is in it

`Staff Member` doctype — not named `Employee`, because ERPNext already has one.
Name, job title, department, status, QID, joining date, and pay as basic +
allowances with monthly cost derived. Pay fields sit at `permlevel: 1`, so Frappe
itself withholds them rather than the screen doing it.

`api/people.py` — list, record, save, cost total, summary. Two points worth knowing:

- `monthly_staff_cost` is **not** whitelisted. A whitelisted total salary bill is a
  total salary bill available to anyone who can call it. Screens reach it through
  `staff_summary`, which applies the pay rule.
- `save_staff` refuses to write pay when the caller cannot see it. Otherwise a GM
  editing a job title would silently blank a real salary.

The cost total respects dates — joined after the month, or left before it, is out.

## Where it lands

`_waterfall()` gains a Staff bar, its own rather than folded into maintenance.
Bar geometry now follows the bar count; the old fixed widths ran a sixth bar off
the canvas.

`_runway_flows()` gains payroll, which was absent entirely — the most reliable
outflow this business has, missing from thirteen weeks of cash. It falls in the week
containing pay day rather than being spread across weeks, because smoothing would
erase the one thing the runway exists to show.

Shell: People → Staff nav group, list and detail screens, and a two-section
`add-staff` form.

## Not in it

Payroll runs, the WPS file, attendance, leave, employee documents and their expiry,
gratuity accrual, approvals. Document expiry is the cheapest thing to add back — the
lease-expiry alerting already exists and employee documents would ride on it.

---

## Tested, and not

Verified against the prototype's seeded data: 39 forms open with all sections
rendered, 68 routes clean across MD/GM/ACC/DOC/MNT, draft persistence and the confirm
sheet behave, `add-staff` saves end to end, the bridge renders six bars with no
overflow, and masking is right per role — MD and Accounts see pay, the other three
get a tile saying it is not shown for their role.

**Not verified:** anything against a real database. The doctype has never been through
`bench migrate`, and `_staff_seed` in the boot payload is untested against real
records. Run it on a test site before it goes near live data.

Two known items, neither introduced here:

- Bar labels truncate at 18 characters, so "Spread after recorded costs" was already
  being clipped before the Staff bar joined it.
- `classify-line` throws when opened without a context. It always has; it is only ever
  called as `openForm('classify-line',{id})`.

## Testing note

Redraws replace the form DOM, so a test calling `fill()` on several fields back to
back can write into a detached node. Drive it as a person would: click the field,
fill it, then move on.
