# Role homes

One `Home`, five readings of it. Everyone lands on their own; the MD keeps the
Command Centre. Shell only — no server change, no schema change.

    bench build
    bench clear-cache
    bench restart

## Shape

`ROUTES.home` is one route with five builders behind it — `homeMD`, `homeGM`,
`homeACC`, `homeDOC`, `homeMNT`. The chrome, the tiles and the "is this panel
actually backed by data" rule are shared; only the panels differ, so adding a
role is a case, not a route. `#/mywork` still resolves, for anything bookmarked
or linked.

Almost all of it reads arrays already in the boot payload, so there is no extra
round trip on login. The one exception is Documentation's expiry panel, which
lazily calls `documents.expiring` — nothing in the payload carries an expiry
date.

## What each role gets

**GM** — approvals split into what they can clear and what is reserved to the
MD (counted, not offered); tenancies pending activation with what is missing on
each; vacant units with the monthly head-lease bleed; tenancies expiring inside
90 days with a note when a head lease ends in the same window; cases that have
broken a promise or gone to legal.

**Accounts** — cheques maturing inside seven days; returned cheques with the
reason; invoice runs drafted but not issued; what is owed, oldest first. Tiles
carry the arrears total and the past-due count.

**Documentation** — the review queue with confidence, flagging anything under
85%; agreements missing their pack, with the note that a short pack is what
routes a tenancy to the GM; documents expiring inside 60 days.

**Maintenance** — open jobs oldest first; jobs over the emergency ceiling, with
the note that those are reserved to the MD and the GM cannot release them; where
the work is by building; units sitting Not Ready.

**MD** — unchanged in substance. The two hardcoded prototype counts are gone.

## The navigation policy

`ROLE_DENY` is new. Until now every ordinary screen was open to every role, so
Maintenance had a Chart of Accounts in its sidebar and Documentation had a Trial
Balance. Roughly: GM loses the MD's own tools; Accounts loses the approval bench
(it can raise an invoice run, it cannot approve one) and maintenance; DOC loses
every money screen; MNT keeps buildings, units, jobs and move-outs.

**This is a navigation rule and nothing more.** The server guards are the
authority and are untouched. Hiding a door that does not open is a courtesy, not
a permission.

Home itself is never denied to anyone — it is where a refused route sends you,
so it cannot be refused.

## Three things this fixed on the way

**`renderDash` ran on a blocked route.** Blocking `dash` for four roles meant
its elements were never drawn, so `renderDash()` threw and replaced the polite
block message with an error page. It is now gated on `roleCan('dash')`.

**The block screen explained the wrong rule.** It described the owner-balance
restriction whatever had been blocked, so a maintenance user refused the Trial
Balance was told about shareholder accounts. It now names the actual rule and
offers a way back that the role can open.

**Two wrong row-click handlers.** `openC` is the cheque opener, not the case
opener — cases are `openCase`. Caught by writing the panels against the real
handler list rather than from memory.

## Verification

    python3 -m compileall darkbrown    # clean
    node verify/home_roles.js          # 30 passed, 0 failed   (new)
    node verify/routes.js              # 1,650 renders, 25/25
    node verify/mywork_notes.js        # 14 passed, 0 failed
    node verify/files_panel.js         # 26 passed, 0 failed
    python3 verify/notes_api.py        # 11 passed, 0 failed
    python3 verify/files_api.py        # 19 passed, 0 failed
    python3 verify/harness.py          # 32 passed, 1 failed *

\* the same pre-existing stub failure as before, identical on a clean clone.

`home_roles.js` checks each role lands where it should, that each home shows
what belongs to it and not what does not, and that hidden and refused agree —
every route absent from a sidebar is one the router also blocks. It also checks
the three-state rule holds per panel: an array the server never sent reads as
NOT WIRED, an array named in `_failed` is not counted, and an array that came
back genuinely empty says so with a zero on the tile.

## Worth deciding

Panels cap at 15–20 rows with no paging. On a portfolio with 43 vacant units the
GM sees 15 of them. Fine for a landing screen that exists to point you at the
full list, but say the word if you want counts-with-drill instead.
