# The decision trail, and the queue that said it was not read

Unzip over the repo root:

    bench build
    bench clear-cache
    bench restart

No schema change and no patch, so `bench migrate` has nothing to apply here.
Notes are stored on Frappe's own `Comment`, which already exists.

## The screenshot

The queue was not broken. It was read, it came back empty, and the screen
reported that as **NOT WIRED / queue not read**.

    const wired = !live || ((DB_SEED.approvals || []).length > 0);

An empty list and an unread list were the same condition, so a day with nothing
pending looked identical to a server failure. It now checks whether the key came
back at all and whether the seed named `approvals` in `_failed` - the payload
already carries that list, it just was not being used. Nothing waiting now reads
"Nothing is waiting on you" with a zero on the tile; a queue that actually
failed still says NOT WIRED.

## Notes: there was no server side at all

`saveNote()` wrote into `NOTES`, a hardcoded object in the browser. Live, the
composer accepted a note, said "Note added", and lost it on the next render -
which is why the panel had been made to admit that rather than keep pretending.

`darkbrown/api/notes.py` now stores them, on Frappe's `Comment` against the
record itself rather than in a new doctype:

- a note belongs to the record it is about, not to a parallel table that has to
  be kept in step
- what is written here appears in that record's Desk timeline, and what is
  written in the Desk appears here - one trail, not two
- `frappe.has_permission` on the referenced record becomes the whole access
  rule, so **a note can never be more readable than the thing it hangs on**

`thread(doctype, name)` and `add(doctype, name, text)`, both `guard(*APP)` at
the endpoint plus an allowlist of twelve notable doctypes. The role on a note is
read off the session, never sent by the caller - the prototype's role dropdown
is gone from the live composer, because nobody signs their own note as the
Managing Director.

## The mandatory note that was being thrown away

Worth reading twice. The decision form marks the note required and calls it
"permanent in the audit trail". It was not:

| category | approve | reject |
|---|---|---|
| Amendment | **discarded** | kept in `rejection_reason` |
| Tenancy activation | kept | kept |
| Emergency maint. | kept | kept |
| Deposit release | **discarded** | kept in `deduction_reason` |
| Invoice run | **discarded** | kept in `variance_reason` |

Every approval of an amendment, a deposit release or an invoice run took a
mandatory reason and dropped it on the floor. `approvals.decide` now records it
as a comment on the target record after the handler runs - one place, all five
categories, both outcomes. `KIND_DOCTYPE` maps each queue category to the
doctype it lives on, mirroring `APPR_DT` in the shell.

`notes.record()` is the internal path used there. It never raises: a decision
that went through must not report as failed because its note could not be
written. It does log, because a silently missing audit line is the thing this
module exists to stop.

## Two other screens that were inventing things

**Approval detail** showed a four-step chain hardcoded to step 3 regardless of
status, and a "Supporting records" panel reading `Linked documents: 3 validated`
and `Prior approvals: none` - both fixed strings, true of nothing. Replaced with
the real status-driven chain, and a Source record panel naming the actual
doctype and id.

**Approvals list** showed `Approved this month: 2`, hardcoded. The queue only
carries what is still pending, so that number cannot be derived from it. It now
counts what it can honestly count and says so.

## What is still not wired, deliberately

The **Request info** button. `approvals.decide` takes approve or reject only,
and the form already refuses it with an explanation rather than sending
something the server would reject. Making it real means a third status on five
doctypes - a design decision, not a fix.

The **ledger journal** note thread. `JRN` is prototype data with no doctype
behind it, so `noteThread` is called there with no record and renders the honest
panel instead of a composer that would throw on submit.

## Verification

    python3 -m compileall darkbrown      # clean
    python3 verify/harness.py            # 32 passed, 1 failed *
    python3 verify/notes_api.py          # 11 passed, 0 failed   (new)
    python3 verify/files_api.py          # 19 passed, 0 failed
    node verify/routes.js                # 1,650 renders, 25/25
    node verify/mywork_notes.js          # 14 passed, 0 failed   (new)
    node verify/files_panel.js           # 26 passed, 0 failed

\* `only System Manager can delete a financial record` fails identically on a
clean clone of `main`. Stub limitation, not a regression.

Two things the sweeps caught while building this. The guard scanner flagged both
new endpoints as ungated, because `guard(*APP)` was buried in a shared `_check`
helper - an endpoint nobody can prove is gated is one nobody should trust, so
the guard moved to the endpoints themselves. And `frappe.utils.pretty_date` is
not importable on this build, which the module-import test caught before it
could 500 on a live thread; relative times are computed in `_ago` instead.
