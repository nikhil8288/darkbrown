# Residual sweeper — 2026-09-07

Unzip over the repo ROOT (the folder containing `darkbrown/`), overwrite.
Delete this .md before committing.

  darkbrown/demo/residuals.py   NEW. Clears what purge cannot see.
  darkbrown/api/admin.py        + residual_preview() and residual_sweep().

## Why purge missed these

purge scopes tenants by `Customer.db_is_tenant`, landlords by
`Supplier.db_is_landlord`, and cost centres by `Building.cost_center`.
Records without those flags, and cost centres whose Building was already
deleted, are invisible to preview() — so the Data screen reported an empty
site while 45,922 records were still on it.

Scoping stays as-is: purge must remain safe on a site holding data this app
did not create. The sweeper is separate and refuses unless the site is
already meant to be empty.

## Guards (all three must pass)

  * no live (uncancelled) GL Entry
  * no Building records
  * confirm == "CLEAR RESIDUAL DATA"

## Run

Deploy, then in the System Console (Python), tick Commit:

    from darkbrown.demo import residuals   # not needed in console
    print(darkbrown.demo.residuals.preview())

Console blocks imports, so call the whitelisted endpoints instead —
see the chat for the exact snippet.
