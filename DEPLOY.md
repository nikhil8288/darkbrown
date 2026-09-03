# Onboarding extraction — round 6: all four wizards

Supersedes `darkbrown_wizard_ocr_r5.zip`. Unzip over the repo root, commit,
push, then:

    bench --site erp.darkbrown.qa migrate
    bench build
    bench clear-cache
    bench restart

## Reading now runs in four places

| Wizard | Base document | What comes off it |
|---|---|---|
| Onboard a building | head lease / owner contract | landlord, rent, term, schedule, address |
| **Add unit** (new) | tenancy agreement, handover, Kahramaa bill | unit number, type, floor, rooms, sqm, meter, asking rent |
| **Add tenant** | tenancy agreement + QID | tenant, QID and expiry, rent, term, deposit, cheques, building and unit |
| **Log a cheque** | cheque or batch scan | number, amount, date, bank, direction |

`add-unit` had no Documents step at all. It has one now, first, before the
Unit step.

Everything from round 5 applies to all four: the document overwrites the form,
the lease outranks an ID card, and a losing reading is shown rather than
dropped.

## Selects are never written blind

Free text in a select produces a control that looks filled and saves empty.
Every select-bound field is now matched against the real option list before it
is written, and reported if it does not match:

- `2 BHK` becomes `2BR`; `fully-furnished` becomes `Fully Furnished`;
  `Qatar National Bank` becomes `QNB`.
- `Duplex Maisonette` is not a unit type, so it is named and left for you.
- A 6-month term is not rounded up to 12. Six payments a year is not forced
  into a frequency that does not exist.
- Drawer and payee are bound to live tenants and landlords, so a name off a
  cheque is reported rather than written. The number, amount, date and bank
  are filled.

## Judgement worth knowing about

- A **head lease will not set a unit's asking rent** — it prices the whole
  building. It says so instead of dividing.
- **Add tenant matches the building and unit against existing records.** No
  match means no write and a note naming what the document said, never a new
  building invented from a scan.
- **Log a cheque takes only the earliest cheque** from a batch scan and says
  how many others were on it. A whole book belongs on the Cheques screen.

## Still to do

- The intake queue screen and `confirm_and_push()` are not verified against V2.
