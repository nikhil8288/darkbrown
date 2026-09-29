"""Pure, deterministic migration review controls. No ERP posting/deletion code."""
from collections import Counter
from datetime import date
from decimal import Decimal, InvalidOperation

from darkbrown.migration.evidence import digest
from darkbrown.migration.inventory import PROTECTED, snapshot_checksum

CUTOVER = date(2026, 10, 1)


def money(value):
    if value is None or value == "" or isinstance(value, bool):
        raise ValueError("Missing amount is not zero")
    try:
        number = Decimal(str(value))
    except InvalidOperation as exc:
        raise ValueError("Invalid financial input") from exc
    if not number.is_finite():
        raise ValueError("Non-finite financial input")
    return number.quantize(Decimal("0.01"))


def event_key(kind, identity, original_period, charge_type):
    if not all((kind, identity, original_period, charge_type)):
        raise ValueError("Economic identity, period and charge type required")
    # Source hash/row and amounts deliberately excluded. A revision is a change
    # to the same event, never a new economic event merely because bytes changed.
    return digest([kind, identity, original_period, charge_type])


def change_plan(old, new):
    def index(rows):
        result = {}
        for row in rows:
            key = row["economic_event_key"]
            if key in result:
                raise ValueError("Duplicate economic event; resolve aggregation explicitly")
            result[key] = row
        return result
    before, after = index(old), index(new)
    return {"new": sorted(after.keys() - before.keys()),
            "removed_review_only": sorted(before.keys() - after.keys()),
            "changed_review_only": sorted(k for k in before.keys() & after.keys() if digest(before[k]) != digest(after[k])),
            "unchanged": sorted(k for k in before.keys() & after.keys() if digest(before[k]) == digest(after[k]))}


def cleanup_plan(snapshot, decisions, expected_site, company, pack_checksum):
    if snapshot.get("schema_version") != 2:
        raise ValueError("Fresh schema v2 inventory with singleton values required")
    if snapshot.get("snapshot_checksum") != snapshot_checksum(snapshot):
        raise ValueError("Inventory content changed; recapture before planning")
    if snapshot["site"] != expected_site or snapshot["company"] != company or not company:
        raise ValueError("Wrong or unselected site/company")
    if snapshot["errors"]:
        raise ValueError("Incomplete inventory; resolve unreadable tables before cleanup planning")
    selected, retained, blockers = [], [], []
    by_id = {(dt, row["name"]): row for dt, data in snapshot["records"].items() for row in data["rows"]}
    scope = set()
    for decision in decisions:
        key = (decision["doctype"], decision["name"])
        if key in scope or key not in by_id:
            raise ValueError("Duplicate or missing record in cleanup decision")
        scope.add(key)
        row = by_id[key]
        if decision.get("action") not in {"preserve", "delete"} or not decision.get("reason"):
            raise ValueError("Explicit disposition and reason required")
        if decision["action"] == "delete":
            if key[0] in PROTECTED or snapshot["records"][key[0]].get("issingle"):
                raise ValueError("Protected setup cannot be selected for business cleanup")
            if row.get("company") and row["company"] != company:
                raise ValueError("Cross-company deletion refused")
            if row.get("posting_date") and str(row["posting_date"])[:10] >= CUTOVER.isoformat():
                raise ValueError("Post-go-live data cannot enter migration cleanup")
            selected.append({**decision, "record_checksum": digest(row)})
        else:
            retained.append(decision)
    delete_ids = {(r["doctype"], r["name"]) for r in selected}
    relationships = snapshot["relationships"]
    links_by_type = {}
    for link in relationships:
        links_by_type.setdefault(link["doctype"], []).append(link)

    def block(key, reason, **details):
        entry = {"record": key, "reason": reason, **details}
        if entry not in blockers:
            blockers.append(entry)

    def parent_of(key):
        row = by_id[key]
        is_child = snapshot["records"][key[0]].get("istable") or row.get("parent") or row.get("parenttype")
        if not is_child:
            return None
        parent = (row.get("parenttype"), row.get("parent"))
        if not all(parent) or parent not in by_id:
            block(key, "missing parent; ownership cannot be established")
            return None
        if not row.get("parentfield") or not any(
            link["type"] in {"Table", "Table MultiSelect"} and
            link["field"] == row["parentfield"] and link["target"] == key[0]
            for link in links_by_type.get(parent[0], [])):
            block(key, "invalid parentfield or parent table ownership")
        return parent

    def inherit(key, origin, seen):
        if key in seen:
            return
        seen.add(key)
        row = by_id[key]
        if row.get("company") and row["company"] != company:
            block(origin, "linked or parent record belongs to another company", dependency=key)
        if row.get("posting_date") and str(row["posting_date"])[:10] >= CUTOVER.isoformat():
            block(origin, "linked or parent record is post-cutover", dependency=key)
        parent = parent_of(key)
        if parent:
            if parent[0] in PROTECTED or snapshot["records"][parent[0]].get("issingle"):
                block(origin, "child of protected parent", dependency=parent)
            if parent not in delete_ids:
                block(origin, "parent retained; explicit parent deletion required", dependency=parent)
            inherit(parent, origin, seen)
        # Shared setup may be referenced by deleted vouchers, but ownership
        # still matters. Do not recursively walk a retained setup's entire graph.
        if key != origin and (key[0] in PROTECTED or snapshot["records"][key[0]].get("issingle")):
            return
        for link in links_by_type.get(key[0], []):
            if link["type"] not in {"Link", "Dynamic Link"}:
                continue
            name = row.get(link["field"])
            if not name:
                continue
            target = row.get(link["target"]) if link["type"] == "Dynamic Link" else link["target"]
            dependency = (target, name)
            if dependency not in by_id:
                block(origin, "linked record missing from inventory", dependency=dependency)
            else:
                inherit(dependency, origin, seen)

    for key in sorted(delete_ids):
        inherit(key, key, set())
    # All unselected records are preserved. Incoming links from those records
    # block deletion, including dynamic links and child-table parent pointers.
    links = snapshot["relationships"]
    for key, row in by_id.items():
        if key in delete_ids:
            continue
        if (row.get("parenttype"), row.get("parent")) in delete_ids:
            blockers.append({"record": key, "reason": "child needs explicit inclusion"})
        for link in links:
            if link["doctype"] != key[0] or link["type"] not in {"Link", "Dynamic Link"}:
                continue
            target = row.get(link["target"]) if link["type"] == "Dynamic Link" else link["target"]
            if (target, row.get(link["field"])) in delete_ids:
                blockers.append({"record": key, "field": link["field"], "reason": "retained incoming link"})
    plan = {"site": expected_site, "company": company, "pack_checksum": pack_checksum,
            "snapshot_checksum": snapshot["snapshot_checksum"], "delete": selected,
            "explicit_preserve": retained, "preserved_total": len(by_id) - len(selected),
            "deletion_counts": dict(Counter(r["doctype"] for r in selected)),
            "blockers": blockers, "execution_enabled": False,
            "remaining_gates": ["installed lifecycle/dependency rehearsal", "verified database/files restore",
                                "scheduler/notification pause and restoration", "owner execution approval",
                                "fresh inventory comparison with writes quiesced"]}
    plan["plan_checksum"] = digest(plan)
    return plan


def validate_approval(plan, approval, current_snapshot):
    if current_snapshot.get("schema_version") != 2 or current_snapshot.get("snapshot_checksum") != snapshot_checksum(current_snapshot):
        raise ValueError("Current inventory is incomplete or modified")
    if plan["plan_checksum"] != digest({k: v for k, v in plan.items() if k != "plan_checksum"}):
        raise ValueError("Reviewed plan was modified")
    for field in ("site", "company", "pack_checksum", "snapshot_checksum", "plan_checksum"):
        if approval.get(field) != plan.get(field):
            raise ValueError("Approval does not bind to " + field)
    if current_snapshot["snapshot_checksum"] != plan["snapshot_checksum"]:
        raise ValueError("Site changed after inventory; rebuild the plan")
    if plan["blockers"] or not approval.get("backup_restore_verified"):
        raise ValueError("Cleanup dependencies or recovery remain unverified")
    # Validation is not execution authorization. No one-time destructive
    # capability is exposed by this preparation release.
    return {"binding_valid": True, "execution_enabled": False}
