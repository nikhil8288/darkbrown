"""Read-only evidence extraction; outputs MUST live outside the application tree.

Uses sparse XLSX XML so inflated used ranges do not allocate millions of rows.
Formula caches are evidence, not independently verified financial inputs.
Run with python -m darkbrown.migration.evidence PACK --output PRIVATE_DIRECTORY.
"""
import argparse
import hashlib
import json
import posixpath
import zipfile
from collections import Counter
from pathlib import Path
from xml.etree import ElementTree as ET

NS = {"s": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
REL = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"
APP_ROOT = Path(__file__).resolve().parents[2]


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                    separators=(",", ":"), default=str).encode()).hexdigest()


def file_hash(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def outside_repo(path):
    path = Path(path).resolve()
    if path == APP_ROOT or APP_ROOT in path.parents:
        raise ValueError("Private evidence/output cannot be inside the application repository")
    if any((parent / ".git").exists() for parent in (path, *path.parents)):
        raise ValueError("Private evidence/output cannot be inside a Git repository")
    return path


def verify_pack(root):
    root = outside_repo(root)
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8-sig"))
    seen = set()
    for entry in manifest["files"]:
        path = (root / entry["path"]).resolve()
        if root not in path.parents or entry["path"] in seen:
            raise ValueError("Unsafe or repeated manifest path")
        seen.add(entry["path"])
        if file_hash(path) != entry["sha256"] or path.stat().st_size != entry["bytes"]:
            raise ValueError("Source differs from manifest: " + entry["path"])
    return manifest


def workbook_rows(path):
    with zipfile.ZipFile(path) as z:
        strings = []
        if "xl/sharedStrings.xml" in z.namelist():
            for item in ET.fromstring(z.read("xl/sharedStrings.xml")):
                strings.append("".join(x.text or "" for x in item.findall(".//s:t", NS)))
        rels = {r.attrib["Id"]: r.attrib["Target"] for r in
                ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))}
        workbook = ET.fromstring(z.read("xl/workbook.xml"))
        properties = workbook.find("s:workbookPr", NS)
        if properties is not None and properties.get("date1904") in ("1", "true"):
            raise ValueError("1904-date workbook needs an explicit date-system adapter")
        for sheet in workbook.findall("s:sheets/s:sheet", NS):
            target = rels[sheet.attrib[REL]]
            target = target.lstrip("/") if target.startswith("/") else posixpath.normpath("xl/" + target)
            with z.open(target) as stream:
                for _, row in ET.iterparse(stream, events=("end",)):
                    if row.tag != "{" + NS["s"] + "}row":
                        continue
                    cells = []
                    for cell in row.findall("s:c", NS):
                        typ = cell.get("t", "n")
                        value = cell.findtext("s:v", default=None, namespaces=NS)
                        formula = cell.find("s:f", NS)
                        if typ == "s" and value is not None:
                            value = strings[int(value)]
                        elif typ == "inlineStr":
                            value = "".join(t.text or "" for t in cell.findall(".//s:t", NS))
                        if value is None and formula is None:
                            continue
                        cells.append({"cell": cell.get("r"), "type": typ,
                                      "value": value, "style": cell.get("s"),
                                      "formula": formula.text if formula is not None else None,
                                      "formula_attributes": dict(formula.attrib) if formula is not None else None,
                                      "financial_input_status": "reject_error" if typ == "e" else
                                      "verify_formula" if formula is not None else "unmapped"})
                    if cells:
                        yield sheet.attrib["name"], int(row.attrib["r"]), cells
                    row.clear()


def extract(root, output):
    root, output = outside_repo(root), outside_repo(output)
    if root == output or root in output.parents:
        raise ValueError("Keep generated evidence separate from originals")
    manifest = verify_pack(root)  # Verify every original BEFORE parsing any record.
    output.mkdir(parents=True, exist_ok=True)
    if any(output.iterdir()):
        raise ValueError("Use an empty output directory; preserve earlier dry runs")
    summary = {"manifest_sha256": file_hash(root / "manifest.json"),
               "pack_checksum": digest(manifest), "files_verified": len(manifest["files"]),
               "sheets": [], "errors": [], "duplicates": [],
               "site_verified": False, "posting_documents": 0,
               "status": "extracted; mapping and site verification required"}
    by_hash = {}
    with (output / "evidence-rows.jsonl").open("w", encoding="utf-8") as out, \
            (output / "review-text.txt").open("w", encoding="utf-8") as review:
        for entry in manifest["files"]:
            path = root / entry["path"]
            prior = by_hash.get(entry["sha256"])
            if prior:
                summary["duplicates"].append({"path": entry["path"], "identical_to": prior})
            by_hash[entry["sha256"]] = entry["path"]
            if path.suffix.lower() != ".xlsx":
                continue
            counts = Counter()
            for sheet, row, cells in workbook_rows(path):
                counts[sheet] += 1
                record = {"source_file": entry["path"], "source_sha256": entry["sha256"],
                          "worksheet": sheet, "row": row, "role": entry["role"],
                          "evidence_id": digest([entry["sha256"], sheet, row]),
                          "economic_event_key": None, "original_period": None,
                          "posting_period": None, "reconstructed": True,
                          "mapping_decision": "blocked_pending_semantic_mapping",
                          "cells": cells}
                out.write(json.dumps(record, ensure_ascii=False) + "\n")
                for c in cells:
                    if c["type"] == "e":
                        summary["errors"].append({"file": entry["path"], "sheet": sheet, **c})
                if entry["path"].startswith("reviews/") or path.name == "Remaining checks.xlsx":
                    review.write(json.dumps({"file": entry["path"], "sheet": sheet,
                                             "row": row, "values": [c["value"] for c in cells]},
                                            ensure_ascii=False) + "\n")
            summary["sheets"].extend({"file": entry["path"], "sheet": k,
                                       "populated_rows": v} for k, v in counts.items())
    summary["evidence_rows_sha256"] = file_hash(output / "evidence-rows.jsonl")
    (output / "source-manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    (output / "extraction-summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pack")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    result = extract(args.pack, args.output)
    print(json.dumps({"files_verified": result["files_verified"],
                      "sheets": len(result["sheets"]), "error_cells": len(result["errors"]),
                      "status": result["status"]}))
