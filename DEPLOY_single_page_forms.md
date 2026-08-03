# Single-page forms + modal dismiss fix

Overlay for the repo root. One file changed:

    darkbrown/shell/index.html

Copy it over, hard-refresh the browser. No `bench migrate` — nothing server-side
moved, and no doctype or field was touched.

## What changed

**Every form is one page.** The engine still reads the same step definitions; it
renders them all together instead of one at a time. Steps became numbered sections
stacked down the page, the step rail at the top became a jump rail, Back and
Continue went away, and there is a single save button carrying the form's own
wording ("Create building, landlord and units").

Applies to all 16 multi-step forms — onboard-building (6), add-tenant (5),
start-moveout (5), log-cheque (5), and the rest. The 22 single-step forms render
exactly as before.

**Clicking outside no longer closes anything.** The overlay's dismiss handler is
gone. A form closes on the X, on Cancel, or on Escape, and nothing else.

**Nothing is lost when it does close.** A form with anything in it raises a sheet
before closing. Leaving keeps what was entered, including chosen files, and it is
restored the next time that form is opened, with a strip at the top saying so and
a "Start fresh" button. Drafts are per form, held for the browser session, and
dropped once the record saves. A form opened against a specific record does not
offer a draft raised against a different one.

**Validation runs once, on save.** Every section is checked, not just the one in
view. What comes back is a list of what is outstanding, each entry a link that
scrolls to and focuses the field; the sections and rail chips concerned are marked
red. Field labels in that list are read off the rendered form, so they match what
is on screen.

## Two things worth knowing

**Derived sections refresh on change.** A section may read a field defined in
another one — the payment schedule is built from the lease value, the unit list
from the building. With no Continue press to trigger that, the engine works out
per form which keys are read outside the section that defines them and redraws
only on those. For onboard-building that is three fields, not twenty-eight. It is
derived from the step definitions at open, so new forms need no annotation.

**The confirm sheet renders into a new `#modal2` element,** not into `#modal`.
Leaving a field fires a change, a change can redraw the form, and a redraw
replaces `#modal` wholesale — which took the sheet with it before the click on it
had landed.

## Testing note

Redraws replace the form DOM, so a test that calls `fill()` on several fields back
to back can write into a detached node. Drive it as a person would: click the
field, fill it, then move on. `classify-line` throws when opened without a context
— it always did, it is only ever called as `openForm('classify-line',{id})`.
