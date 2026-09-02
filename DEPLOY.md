# Onboarding extraction — round 4: the lease is the base

Supersedes `darkbrown_wizard_ocr_r3.zip`. Unzip over the repo root, commit,
push, then:

    bench --site erp.darkbrown.qa migrate
    bench build
    bench clear-cache
    bench restart

## Why nothing filled

`_fold_building()` only read a contract block when the classifier had labelled
the file "Head Lease" or "Owner Contract". Anything else — and the classifier
had already proved it can be wrong, calling a sanad mulki a tenant agreement —
had its entire contract block thrown away unread. The rent, the term and the
dates were extracted correctly and then discarded on the label.

The fold no longer gates on the label. A document carrying rent, dates or a
cheque count IS a lease, whatever it was called, and it says so on screen when
it overrides a classification.

## Precedence

Documents are now ranked, and the rank wins before confidence does:

1. **Lease / rental agreement** — the base. The only document that states the
   rent, the term, the deposit and the payment schedule.
2. **Title deed, commercial registration** — owner and address only.
3. **QID, passport, utility, cheques** — the party's name and number.

A 99% read of a QID card no longer overwrites the landlord's name as the lease
writes it. Where two documents disagree, the winner is shown with the losing
value and the file it came from underneath it, rather than the disagreement
being silently resolved.

## On screen

- The file used as the base is marked.
- Each file shows how many fields it contributed; one that gave nothing says so.
- The lease's own gaps are named — "does not state the floors, number of units"
  — so it is clear what is left to type rather than looking like a failure.
- With no lease in the batch, the panel says to attach one rather than
  reporting that nothing matched.

## Still to do

- The intake queue screen and `confirm_and_push()` have not been run against
  V2 end to end.
- Tenant and cheque wizards still only attach; no field map is written.
