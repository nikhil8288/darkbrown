# Invoice register completeness

Removed the 1,000 Sales Invoice cutoff from the existing scoped boot feed.
All authorised invoices remain available to search, detail and collection flows.
The invoice list renders 100 rows per page, and headline outstanding excludes
Draft and Cancelled documents. Batched child-item reads replace per-invoice
queries. Existing role/field/building filtering remains unchanged.

Verification: synthetic Python check covers 2,313 records, complete amounts,
item lines and building scope. Node VM executes the actual invoice route for
full totals, search beyond the old cutoff, final-page and empty-page behavior.
Existing security boundary suite passes eight checks. This is source/stub
coverage; production display verification follows deployment.
