"""The four commands.

    bench --site <site> execute darkbrown.demo.run.preview
    bench --site <site> execute darkbrown.demo.run.purge   --kwargs "{'confirm': 'REMOVE ALL DARKBROWN DATA'}"
    bench --site <site> execute darkbrown.demo.run.seed
    bench --site <site> execute darkbrown.demo.run.verify

and the one that does all three in order:

    bench --site <site> execute darkbrown.demo.run.rebuild --kwargs "{'confirm': 'REMOVE ALL DARKBROWN DATA'}"

`rebuild` is destructive and irreversible. `preview` never writes.
"""

import frappe

from darkbrown.demo import purge as purge_mod
from darkbrown.demo import seed as seed_mod
from darkbrown.demo import verify as verify_mod

BAR = "─" * 68


def preview():
    """Count what a purge would remove. Writes nothing."""
    counts = purge_mod.preview()
    print(f"\n{BAR}\n  on this site now\n{BAR}")
    if not counts:
        print("  nothing — the site is already empty")
    for dt, n in sorted(counts.items(), key=lambda x: -x[1]):
        print(f"  {n:>6}  {dt}")
    print(f"\n  to remove all of it:")
    print(f"  bench --site <site> execute darkbrown.demo.run.rebuild \\")
    print(f"        --kwargs \"{{'confirm': '{purge_mod.CONFIRM}'}}\"\n")
    return counts


def purge(confirm=None, wide=False):
    """Remove everything. Requires the confirmation phrase."""
    print(f"\n{BAR}\n  purging\n{BAR}")
    out = purge_mod.run(confirm=confirm, wide=wide)
    print()
    return out


def seed():
    """Lay down the dummy portfolio."""
    print(f"\n{BAR}\n  seeding\n{BAR}")
    r = seed_mod.run(verbose=True)
    _report(r)
    return {"made": r.made,
            "failed": [s for s in r.steps if s[1] != "ok"],
            "findings": r.findings}


def verify():
    """Check the boot payload and the business invariants."""
    print(f"\n{BAR}\n  verifying\n{BAR}")
    out = verify_mod.run(verbose=True)
    print(f"\n{BAR}")
    if out["passed"]:
        print("  everything checks out")
    else:
        if out["missing_modules"]:
            print(f"  modules missing from the boot payload: "
                  f"{', '.join(out['missing_modules'])}")
        if out["failed_checks"]:
            print(f"  checks that failed:")
            for c in out["failed_checks"]:
                print(f"    · {c}")
    print(f"{BAR}\n")
    return out


def rebuild(confirm=None, wide=False):
    """Purge, seed, verify. This is the one to use."""
    purge(confirm=confirm, wide=wide)
    seeded = seed()
    checked = verify()
    return {"seeded": seeded, "verified": checked}


def _report(r):
    print(f"\n{BAR}\n  created\n{BAR}")
    for key, n in sorted(r.made.items(), key=lambda x: -x[1]):
        print(f"  {n:>6}  {key}")

    failed = [s for s in r.steps if s[1] != "ok"]
    print(f"\n  {len(r.steps) - len(failed)} of {len(r.steps)} steps ran clean")

    if failed:
        print(f"\n{BAR}\n  steps that failed\n{BAR}")
        for label, _, msg in failed:
            print(f"  · {label}\n      {msg}")

    if r.findings:
        print(f"\n{BAR}\n  findings\n{BAR}")
        for f in r.findings:
            print(f"  · {f}")
    print()
