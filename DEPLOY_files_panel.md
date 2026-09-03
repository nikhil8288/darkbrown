# Files on a building and on a unit

A second way documents get in. Intake rasterises a document, reads it and asks
Documentation to confirm what it read — right for a QID, heavy for a floor
plan. This path uploads the file against the Building or the Unit and files a
register row saying what it is. Nothing is extracted, so nothing is queued for
review.

Unzip over the repo root, then:

    bench migrate          # no schema change, but the cache holds the shell
    bench build
    bench clear-cache
    bench restart

No files are deleted by this overlay and no DocType changed, so `git rm` is not
needed and `bench migrate` has nothing to apply. It is in the sequence because
`bench build` and `clear-cache` are what actually ship the new shell.

## What changed

### `darkbrown/api/documents.py` — three endpoints, all gated `MD GM ACC DOC`

| endpoint | does |
|---|---|
| `save_files(payload)` | Files already-uploaded URLs against a Building or a Unit. One `Document Register` row per file, status `Confirmed`, no extractor and no confidence recorded. |
| `files(building=None, unit=None)` | Everything on file for one record. Asked for a building it includes the files filed against its units and says which door each came from. |
| `file_types()` | The register's own `document_type` list, read off the DocType meta. |

Three decisions worth knowing about:

**Status is `Confirmed`, not `Needs Review`.** Needs Review means *somebody
claimed something about this document and a human has to check it*. Nothing was
claimed here — a person said what the file is and where it goes. Sending it to
the review queue would ask Documentation to validate a reading nobody made.
These therefore read as **Validated** in the vault. If you want them queued
instead, it is the one word `"status"` in `save_files`.

**A unit file is a building file.** `save_files` derives the building from the
unit rather than trusting the caller, and if a caller sends a unit and a
different building the unit's own building wins. That is what lets the building
screen show everything filed under its doors without the caller sending both.

**An unrecognised type becomes `Other`.** The list comes from the DocType, so a
type added there appears on the form with no code change, and a type removed
cannot be written by this path.

### `darkbrown/shell/index.html`

- `filesCard(scope, id, label)` — one panel, used by both screens, lazy-fetched
  per record and held until a write invalidates it. Loading, server error and
  genuinely-empty stay three distinct states for the usual reason. Rows open
  through `documents.preview`, so Frappe runs its own permission check on the
  file on the way out. Maintenance sees a note instead of the list, and the
  fetch is never made for that role.
- **Building** — *Agreements in this building* is replaced by **Files**, with
  the **Add files** button in the card header. Because that table went, the
  Units table on the same page gained **Tenant** and **Ends**; those are facts
  about the door and they now sit on the door's row.
- **Unit** — *Current agreement* is replaced by **Files**. The tenancy moved up
  onto the tiles: Tenant, Agreement, Started, Ends, Deposit held, Payment,
  beside the existing status, rents and spread. *Open agreement* is now a header
  button. A unit that is Occupied with no agreement on file gets an amber tile
  and a note rather than a row of dashes.
- `add-files` form and its `WIRE` entry.
- One core change: `submitLive` now honours `w.ptarget` on a `pre:1` form, so
  the files upload **attached to the Building or Unit record itself** before the
  register row is written — the bytes hang on the record in Frappe as well as
  being on the register. Existing `pre` forms define no `ptarget` and pass
  `null`, exactly as before.

### `verify/`

- `files_api.py` — 10 checks on the two endpoints against the real DocType JSON.
- `files_panel.js` — 20 checks on the two screens: each panel state, the scoping
  of the call, the replaced panels being gone, the role gate, and the form.
- `stub_frappe.py` — `get_all` now honours `or_filters`. It used to swallow them
  into `**kw`, which meant a query scoped by `or_filters` came back unscoped and
  any test of that scoping would have passed for the wrong reason.

## Verification run before shipping

    python3 -m compileall darkbrown          # clean
    python3 verify/harness.py                # 32 passed, 1 failed *
    python3 verify/files_api.py              # 10 passed, 0 failed
    node verify/routes.js                    # 25 combinations, 1,650 renders, 0 failed
    node verify/files_panel.js               # 20 passed, 0 failed

\* `only System Manager can delete a financial record` fails identically on a
clean clone of `main` — it is a stub limitation in the harness, not a
regression from this change. Confirmed by running the harness against a fresh
clone before touching anything.

`node verify/*.js` needs `npm install jsdom` in the repo root first.

## Still open

- **No per-file title.** `Document Register` has no title field, so a file shows
  as its own filename and its type — `scan_0043.pdf · Title Deed`. If Anoop or
  Aisha will want *Landlord bank letter — Q3*, that needs one `Data` field on
  the DocType JSON and a real `bench migrate`. Left out deliberately: it is a
  schema change and this overlay has none.
