# Onboarding extraction — round 5: the document overwrites

Supersedes `darkbrown_wizard_ocr_r4.zip`. Unzip over the repo root, commit,
push, then:

    bench --site erp.darkbrown.qa migrate
    bench build
    bench clear-cache
    bench restart

## The change

Reading a document now writes every value it found into the form, over
whatever was already there. "Kept yours" is gone.

The old rule protected anything already in a field. That was wrong, because
the wizard ships with values in the fields: `2026-08-01` on the dates, four
instalments, Company as the landlord type. Those are placeholders, not
answers, and they were beating the lease. That is why the term, the first
payment date and the instalment count all read "kept yours" against a 95%
lease that stated 12 payments and a June start.

The rule is one function now, `exApply()`, so it is a single place to look:
every field read is written. Correcting a bad reading is done by hand on the
steps below, and that is the only thing that overrules the paper.

## Also

- Where two documents disagreed, the losing value is still shown under the
  winner, and now names the file it came from rather than saying
  "another said".
- The prompt no longer lets a district be copied into the building name.
  `DOHA JADEED` landing in both Building name and Area is that: the lease
  names a district and no building, and the model filled both. It will now
  leave the building name empty for you to type.

## Still to do

- The intake queue screen and `confirm_and_push()` are not verified against V2.
- Tenant and cheque wizards still only attach; no field map is written.
