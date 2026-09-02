# Onboarding extraction — round 3

Supersedes `darkbrown_wizard_ocr_r2.zip`. Unzip over the repo root, commit,
push, then:

    bench --site erp.darkbrown.qa migrate
    bench build
    bench clear-cache
    bench restart

No pip install is needed. `bench pip install PyMuPDF` is optional — see below.

## What was broken this round

`No module named 'fitz'`. Every PDF was being rasterised page-by-page with
PyMuPDF before being sent, and PyMuPDF is a native dependency that was dropped
from `pyproject.toml` in the V1 cleanup. The JPEG went straight through as an
image, which is why one file worked and four did not.

PDFs now go to the API as PDFs. The model reads a native PDF's own text layer
instead of a 150 DPI picture of it — more accurate on typed leases, cheaper,
and no native module on the required path. Limits are the API's own: 100 pages
and 30 MB, both refused with a clear message before any spend.

PyMuPDF is kept as a fallback for a PDF the API will not take whole, and is
now declared in `pyproject.toml` so the next deploy has it. Without it that
fallback says what to install rather than raising ImportError.

## Also in this round

`SANAD MULKI.jpeg` came back as "Tenant Agreement" at 45% because neither the
prompt nor the Document Register had a title deed in its vocabulary, so the
model picked the nearest wrong thing. "Title Deed" is now a document type in
both. A deed fills the owner, the area and the address on the wizard, and
never touches rent or term, because it does not carry them.

## Still to do

- The intake queue screen and `confirm_and_push()` have not been run against
  V2 end to end.
- Tenant and cheque wizards still only attach; no field map is written.
