# Onboarding extraction — round 2

Supersedes `darkbrown_wizard_ocr.zip`. Same four files; unzip over the repo
root, commit, push, then:

    bench --site erp.darkbrown.qa migrate
    bench build
    bench clear-cache
    bench restart

## What was broken

`api/doc_intake.py` is V1 code running against the V2 Document Register.
The two schemas do not match.

1. `create_intake()` inserted without `document_type`, which is mandatory.
   That is the `[Document Register, DOC-2026-0078]: document_type` on screen.
   All five files died there, before a single page was sent to the model.
2. The model's `document_type` vocabulary and the field's Select options are
   different lists. `Owner Contract`, `Tenant Agreement`, `QID / National ID`
   and `Utility / Other` are not options, so writing one is a validation
   error. `REG_TYPE` now translates; an owner contract files as Head Lease.
3. `_apply_extraction()` wrote to about twenty fields the doctype does not
   have — including `raw_json` instead of `extracted_json`. Frappe absorbs an
   unknown fieldname silently, so a "successful" extraction would have
   persisted almost nothing and the wizard would have read an empty JSON.
   It now writes `extracted_json` as the record, guards every flat write with
   `meta.has_field`, and maps what does exist: `document_no`, `issue_date`,
   `expiry_date`, `extraction_confidence`.
4. `_rehydrate()` puts the flat names back on a loaded doc from the JSON, so
   the 43 downstream reads of `reg.party_name`, `reg.cheques` and the rest
   keep working without the doctype growing twenty columns.

## Still to do

- The intake queue's own screen and `confirm_and_push()` have not been
  exercised against V2 end to end. Rehydration should carry them, but that
  path deserves its own pass before anyone relies on it.
- Tenant and cheque wizards still only attach; no field map is written.
