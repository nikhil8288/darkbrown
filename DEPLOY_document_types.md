# Renaming the document types

Supersedes `darkbrown_files_panel_20260903b.zip`. Unzip over the repo root:

    bench migrate      # REQUIRED this time - it runs the rename patch
    bench build
    bench clear-cache
    bench restart

`bench migrate` is not optional here. The Select options move in the JSON and
the existing rows move with them in `patches/rename_document_types.py`. Renaming
an option without the data would leave every old row holding a value the field
no longer offers: blank on the form, missing from a filter, and silently
rewritten on the next save.

## What you asked for, and what the audit changed

| you said | shipped |
|---|---|
| Head Lease -> Building Agreement | done, everywhere |
| Tenancy Agreement -> Tenant Agreement | done, everywhere |
| remove Cheque Batch | **removed from the form, kept in storage** - see below |
| add Security Cheque, Advance Cheque etc | Security Cheque, Advance Cheque, Rent Cheque |

**Cheque Batch could not simply be deleted.** It is load-bearing in intake:
`doc_intake._push_cheques` runs on it, `doc_intake_phase2` blocks a push when a
confirmed cheque in the batch has no date, and both compare the stored value
literally. Deleting the option would have left those branches matching nothing -
one scan of six cheques would archive silently and create no Cheque records, and
nothing would have said so.

So there are now two lists rather than one:

- **Stored vocabulary** - the DocType Select. Everything the register can hold,
  including `Cheque Batch` and `Unknown`, both written by intake.
- **Form vocabulary** - `documents._form_types()`, which is the stored list
  minus `documents.FORM_HIDDEN`. This is what the Add files dropdown shows, and
  `save_files` will only write from it: a hand-filed `Cheque Batch` lands as
  `Other`.

`Unknown` is hidden for the same class of reason - it is what the extractor
writes when it could not tell, so a person choosing it by hand would be
recording that they did not look.

The three cheque kinds are **filing labels for the paper**, not a new state on
the Cheque doctype. A security cheque is still identified the way it always
was - by a Security Deposit pointing at it through `receipt_cheque` - and
`is_security_cheque()` is untouched. Filing a scan as Security Cheque changes
nothing in the ledger.

## Every place the old values were written

Audited before anything was touched, because a missed writer does not fail a
test - it quietly files one document a month under a dead value.

| file | was | now |
|---|---|---|
| `document_register.json` | the Select | renamed, three cheque kinds added |
| `document_archive.json` | `Head Lease` | `Building Agreement` - the archive copies the register's value, so its list had to carry it |
| `doc_intake.REG_TYPE` | model label -> Select | maps onto the new values |
| `doc_intake.PARTY_DOC_TYPE_MAP` | keyed `Head Lease` | keyed `Building Agreement` |
| `doc_intake` push gate | a 3-value tuple | `== "Building Agreement"` |
| `agreements.py` | `Tenancy Agreement` | `Tenant Agreement` |
| `utils/handoffs.py` | `Head Lease` | `Building Agreement` |
| shell `W_DOCTYPE`, `FILE_KINDS_FALLBACK` | old values | new values |

Deliberately **not** touched: `create_role_workspaces.py`,
`create_collections_workflow.py` and `demo/seed.py` also have a `document_type`,
but theirs names a DocType, not a register value. `doc_intake_prompts.py` says
"Head Lease" because that is what the paper is called - it is the model's label
and `_reg_type` maps it before anything is saved.

`verify/files_api.py` now greps the whole tree for the retired spellings and
fails on any hit outside that named exclusion list. It caught the prompts file
on the first run, which is how the distinction above got made explicit.

## Two pre-existing faults the audit turned up

Neither is caused by this change and neither is fixed by it. Both are one-line
decisions that belong to you, not to a rename.

**1. The tenancy cross-check has never run.** `_diff_agreement` is gated on the
register's `document_type`, and the gate asked for `"Tenant Agreement"` while
the register stored `"Tenancy Agreement"`. They never met, so a scanned tenancy
contract has never been compared against the live agreement - no rent mismatch,
no date mismatch, nothing. After the rename those two strings *would* have met,
which would have switched the check on as a side effect of renaming a label. I
refused that: the gate is now explicitly `== "Building Agreement"`, which is the
only thing it has ever admitted. Say the word and it becomes
`in ("Building Agreement", "Tenant Agreement")`.

**2. A scanned QID has never filed as a Party Document.**
`PARTY_DOC_TYPE_MAP` is keyed on model labels - `"QID / National ID"`,
`"Utility / Other"` - but `_reg_type` normalises those to `"QID"` and
`"Utility Bill"` before the row is saved. The lookup is guarded by
`if reg.document_type in PARTY_DOC_TYPE_MAP`, so there is no crash; the row is
simply never written, and the party's document list stays empty. Same shape of
fault as the one above. Fixing it means re-keying the map onto stored values,
which changes what gets written to Customers and Suppliers - a behaviour change
that wants your say-so.

## Verification

    python3 -m compileall darkbrown        # clean
    JSON parse sweep, 55 files             # clean
    python3 verify/harness.py              # 32 passed, 1 failed *
    python3 verify/files_api.py            # 19 passed, 0 failed
    node verify/routes.js                  # 1,650 renders, 25/25
    node verify/files_panel.js             # 26 passed, 0 failed

\* `only System Manager can delete a financial record` fails identically on a
clean clone of `main`. Stub limitation in the harness, not a regression.
