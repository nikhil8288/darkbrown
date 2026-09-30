"""Offline cleanup rehearsal: dependency order only, never ERP writes.

Children and generated ledger rows belong to a native document lifecycle. They
are not independent delete operations. Every unresolved relationship blocks the
review. This module intentionally does not relax plan.py's execution guards.
"""
from collections import Counter, defaultdict
import heapq

from darkbrown.migration.evidence import digest
from darkbrown.migration.inventory import PROTECTED, snapshot_checksum

LEDGERS = {"GL Entry", "Payment Ledger Entry", "Stock Ledger Entry"}



def cyclic_components(nodes, edges):
    """Iterative SCC discovery; downstream nodes are not labelled cycles."""
    forward, reverse = defaultdict(set), defaultdict(set)
    for source, target in edges:
        forward[source].add(target)
        reverse[target].add(source)
    seen, finish = set(), []
    for root in sorted(nodes):
        if root in seen:
            continue
        seen.add(root)
        stack = [(root, iter(sorted(forward[root])))]
        while stack:
            node, children = stack[-1]
            child = next(children, None)
            if child is None:
                finish.append(node)
                stack.pop()
            elif child not in seen:
                seen.add(child)
                stack.append((child, iter(sorted(forward[child]))))
    seen, components = set(), []
    for root in reversed(finish):
        if root in seen:
            continue
        group, stack = [], [root]
        seen.add(root)
        while stack:
            node = stack.pop()
            group.append(node)
            for child in sorted(reverse[node]):
                if child not in seen:
                    seen.add(child)
                    stack.append(child)
        if len(group) > 1 or root in forward[root]:
            components.append(sorted(group))
    return sorted(components)


def rehearse(snapshot, selection, expected_site, company):
    if snapshot.get("schema_version") != 2 or snapshot.get("snapshot_checksum") != snapshot_checksum(snapshot):
        raise ValueError("Modified or unsupported inventory")
    if snapshot.get("site") != expected_site or snapshot.get("company") != company or not company:
        raise ValueError("Wrong site/company")
    rows = {}
    for dt, data in snapshot["records"].items():
        if data["count"] != len(data["rows"]):
            raise ValueError("Invalid record count")
        for row in data["rows"]:
            key = (dt, row["name"])
            if key in rows or row.get("content_checksum") != digest({k: v for k, v in row.items() if k != "content_checksum"}):
                raise ValueError("Duplicate or modified record")
            rows[key] = row
    chosen = {}
    for decision in selection:
        key = (decision["doctype"], decision["name"])
        if key in chosen or key not in rows or not decision.get("reason"):
            raise ValueError("Duplicate, missing or unexplained selection")
        if decision.get("source_record_checksum") != rows[key]["content_checksum"]:
            raise ValueError("Stale selection")
        chosen[key] = decision
    blockers = []
    def block(code, key=None, target=None):
        blockers.append({"code": code, "record": key, "target": target})
    for error in snapshot.get("errors", []):
        blockers.append({"code": "inventory_error", "detail": error})
    links = defaultdict(list)
    for link in snapshot["relationships"]:
        links[link["doctype"]].append(link)
    owners = {}
    def owner(key, trail=()):
        if key in owners:
            return owners[key]
        if key in trail:
            block("ownership_cycle", key)
            return None
        row = rows[key]
        data = snapshot["records"][key[0]]
        parent = None
        if data.get("istable"):
            parent = (row.get("parenttype"), row.get("parent"))
            if parent not in rows:
                block("missing_parent", key, parent)
                owners[key] = None
                return None
            if not any(l["type"] in {"Table", "Table MultiSelect"} and l["field"] == row.get("parentfield") and l["target"] == key[0] for l in links[parent[0]]):
                block("invalid_parentfield", key, parent)
        elif key[0] in LEDGERS:
            parent = (row.get("voucher_type"), row.get("voucher_no"))
            if parent not in rows:
                block("missing_native_voucher", key, parent)
                owners[key] = None
                return None
        if parent:
            if parent not in chosen:
                block("lifecycle_owner_not_selected", key, parent)
            result = owner(parent, trail + (key,))
        else:
            result = key
        owners[key] = result
        return result
    for key in sorted(chosen):
        owner(key)
        row = rows[key]
        if key[0] in PROTECTED or snapshot["records"][key[0]].get("issingle"):
            block("protected_setup", key)
        if row.get("company") and row["company"] != company:
            block("cross_company", key)
        if str(row.get("posting_date") or "")[:10] >= "2026-10-01":
            block("post_cutover_exact_exception_required", key)
    groups = defaultdict(list)
    for key in sorted(chosen):
        root = owners[key]
        if root in chosen:
            groups[root].append(key)
    edges = set()
    edge_evidence = []
    for key, row in sorted(rows.items()):
        included = key in chosen
        if not included:
            parent = (row.get("parenttype"), row.get("parent"))
            voucher = (row.get("voucher_type"), row.get("voucher_no")) if key[0] in LEDGERS else None
            if parent in chosen or voucher in chosen:
                block("unselected_lifecycle_member", key, parent if parent in chosen else voucher)
        for link in links[key[0]]:
            if link["type"] not in {"Link", "Dynamic Link"}:
                continue
            value = row.get(link["field"])
            if not value:
                continue
            target_type = row.get(link["target"]) if link["type"] == "Dynamic Link" else link["target"]
            if not isinstance(value, str) or not isinstance(target_type, str):
                if included:
                    block("invalid_relationship_value", key)
                continue
            target = (target_type, value)
            if not included and target in chosen:
                block("retained_incoming_link", key, target)
            elif included and target not in rows:
                block("missing_link_target", key, target)
            elif included and target in chosen:
                source_owner, target_owner = owners.get(key), owners.get(target)
                if source_owner in groups and target_owner in groups and source_owner != target_owner:
                    edges.add((source_owner, target_owner))
                    edge_evidence.append({"source_owner": source_owner, "target_owner": target_owner,
                        "record": key, "field": link["field"], "target": target})
    outgoing = defaultdict(set)
    indegree = {key: 0 for key in groups}
    for source, target in sorted(edges):
        outgoing[source].add(target)
        indegree[target] += 1
    ready = [key for key, degree in indegree.items() if degree == 0]
    heapq.heapify(ready)
    ordered = []
    while ready:
        key = heapq.heappop(ready)
        ordered.append(key)
        for target in sorted(outgoing[key]):
            indegree[target] -= 1
            if indegree[target] == 0:
                heapq.heappush(ready, target)
    unresolved = sorted(set(groups) - set(ordered))
    if unresolved:
        # Includes cycle members and downstream nodes: never claim all are cyclic.
        blockers.append({"code": "cyclic_or_cycle_dependent_groups", "records": unresolved})
    unresolved_set = set(unresolved)
    result = {
        "status": "OFFLINE REHEARSAL ONLY", "execution_enabled": False,
        "site": expected_site, "company": company,
        "snapshot_checksum": snapshot["snapshot_checksum"],
        "selection_checksum": digest([chosen[key] for key in sorted(chosen)]),
        "selected_records": len(chosen),
        "lifecycle_groups": [{"owner": key, "owner_record_checksum": rows[key]["content_checksum"],
            "docstatus": rows[key].get("docstatus"),
            "proposed_route": "native_cancel_then_delete_rehearsal" if rows[key].get("docstatus") == 1 else "native_delete_rehearsal",
            "members": groups[key]} for key in sorted(groups)],
        "dependency_order_prefix": ordered,
        "cyclic_groups": cyclic_components(groups, edges),
        "unresolved_dependency_edges": [e for e in edge_evidence if e["source_owner"] in unresolved_set and e["target_owner"] in unresolved_set],
        "order_complete": len(ordered) == len(groups),
        "blockers": blockers,
        "blocker_counts": dict(sorted(Counter(b["code"] for b in blockers).items())),
        "remaining_gates": ["native lifecycle integration tests", "exact scope approval",
            "database and files restore proof", "quiesced site and queue evidence",
            "completed financial reconstruction and import validation"],
    }
    result["rehearsal_checksum"] = digest(result)
    return result


def main():
    import argparse
    import json
    from pathlib import Path
    from darkbrown.migration.evidence import outside_repo
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("snapshot")
    parser.add_argument("selection")
    parser.add_argument("--site", required=True)
    parser.add_argument("--company", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    snapshot_path, selection_path = outside_repo(args.snapshot), outside_repo(args.selection)
    output = outside_repo(args.output)
    selection = json.loads(selection_path.read_text())
    if isinstance(selection, dict):
        selection = selection["selection"]
    result = rehearse(json.loads(snapshot_path.read_text()), selection, args.site, args.company)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, indent=2, ensure_ascii=False)
    # No operational identifiers in console output.
    print(json.dumps({"execution_enabled": False, "selected_records": result["selected_records"],
                      "blocker_counts": result["blocker_counts"]}))


if __name__ == "__main__":
    main()
