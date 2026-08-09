# Handover

Repo-root overlay. **Supersedes `darkbrown_v1_names.zip`.** Contains that batch
and the guard batch before it.

**Needs a migrate** (carried over from the previous batch — one new DBR Settings
field).

    git pull
    bench --site <site> migrate
    bench --site <site> build
    bench --site <site> clear-cache
    bench --site <site> restart

`DELETE_THESE.txt` in this zip lists two files to `git rm` — an overlay cannot
delete.

---

# 1 — A correction to the audit first

The audit said onboarding creates every unit `Not Ready` and leaves 276 units
unlettable. **That was wrong.** The wizard has sent `status:'Vacant'` since
31 July; I read the default in `portfolio.py` and did not check what the screen
actually sends. Bulk-onboarded units have been lettable the whole time.

What was true:

- **A building never left Onboarding.** The success message said it stays there
  "until handover is recorded", and nothing in the application could record one.
  `handover_date` was a field `portfolio.py` accepted and the screen never sent.
- **`set_unit_status` was unreachable.** Written, whitelisted, correct, called
  from nowhere. Add Unit defaults to `Not Ready` and offers it in its picker, so
  a unit added after onboarding could be created unlettable **with no way out
  of it** short of the desk.
- **The shell could not see a building's state at all.** `app.buildings()`
  queried `status` and then did not pass it on.

# 2 — What this adds

**`portfolio.record_handover(building, handover_date, ready_units=1)`** —
guarded MD/GM. Three things happen together because they are one event: the date
is written, the building goes Onboarding → Active, and any unit still marked
Not Ready becomes Vacant.

Units that are **Occupied, Reserved or Under Maintenance are left alone.**
Handover is a fact about the building and must not overwrite what somebody has
said about a particular door. `ready_units=0` records the date and touches no
unit at all.

Refused: an unknown building, one already Exited or on Notice Period, and a
handover date falling after an exit date already on the record.

**`portfolio.set_unit_status` hardened and wired.** It now checks the unit
exists, and **refuses to set Occupied by hand** — a unit becomes occupied when
its tenancy is activated and stops being occupied through a move-out. Letting
those two disagree is how a unit ends up let on one screen and empty on another.
The existing refusal to vacate a unit with a live tenancy is unchanged.

**`app.buildings()` now sends `st`, `ho` and `nr`** — status, handover date, and
how many units are still Not Ready.

## On screen

Building page: a **Record handover** button, shown only while the building is
Onboarding, and a banner saying why it matters — void days run from nowhere, and
naming the units that cannot be let. Status and handover date join the stat row.
Once Active the button goes; recording it twice is not a thing.

Unit page: a **Change status** button on any unit that is not Occupied. The
picker offers Vacant, Not Ready, Reserved, Under Maintenance — Occupied is
deliberately absent, and the form says so rather than leaving you to wonder.

# 3 — Tested

**jsdom, against the real shipped `index.html`**, calling `router()` directly
rather than through `dispatchEvent`, which swallows exceptions and turns a broken
route into a silent pass. 24 checks, all passing:

- Routes still render across dash, buildings, units, portfolio, and both
  building and both unit states.
- Record handover appears on the Onboarding building and **not** on the Active
  one; the Active one shows its handover date.
- Change status appears on Not Ready and Vacant units and **not** on the
  Occupied one.
- Both forms open with every section rendered; record-handover names the five
  Not Ready units by count; set-unit-status does not offer Occupied.
- Both WIRE payloads carry the right shape, `ready_units` honours No, and both
  guards refuse to run without a context.

**Python, importing the real `portfolio.py`** against a stubbed Frappe. 9 cases:
handover flips only the Not Ready units and leaves Occupied and Under
Maintenance alone, does not reach into another building, `ready_units=0` touches
nothing, unknown and Exited buildings are refused, a handover after the exit date
is refused, Maintenance cannot record one, Occupied is not settable by hand, an
unknown unit is refused.

Guard sweep re-run: 107 endpoints now, still nothing reachable by a user holding
no DarkBrown role.

**Not verified:** anything against a real database.

# 4 — Left alone deliberately

Add Unit still offers `Not Ready`, and still defaults to it. That is the right
default for a unit added mid-refurbishment, and it is no longer a trap now that
Change status exists.

Buildings already on the live site sit in Onboarding with no handover date.
Recording one per building is the migration, and it is a button.

**Next in order:** `patches.txt` runs one patch of thirteen, then rent-free
treatment with Fatima.
