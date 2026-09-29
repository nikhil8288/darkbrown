"""Build a code-only overlay ZIP from an explicit, reviewable allowlist."""
import argparse
import hashlib
import json
import subprocess
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FILES = [
    "darkbrown/api/admin.py", "darkbrown/install.py",
    "darkbrown/migration/__init__.py", "darkbrown/migration/evidence.py",
    "darkbrown/migration/inventory.py", "darkbrown/migration/plan.py",
    "darkbrown/migration/prepare.py", "verify/migration_preparation.py",
    "darkbrown/migration/owner_review.py", "verify/migration_review_fixes.py",
    "verify/package_migration.py", "verify/harness.py",
    "verify/security_boundaries.py", "verify/notes_api.py", "verify/tenancy_foundation.py",
    "docs/launch/migration-preparation.md", "docs/launch/STATUS.md",
    "docs/launch/evidence/migration-review-fixes.md",
]


def package(output):
    output = Path(output).resolve()
    if output == ROOT or ROOT in output.parents:
        raise ValueError("Write delivery artifacts outside the repository")
    output.mkdir(parents=True, exist_ok=True)
    manifest = {"kind": "code-only overlay; extract at repository root",
                "release": "preparation-review-fixes-2026-09-30",
                "execution_enabled": False,
                "erp_integration_verified": False,
                "branch": subprocess.check_output(["git", "branch", "--show-current"], cwd=ROOT, text=True).strip(),
                "base_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
                "files": []}
    archive = output / "darkbrown-migration-preparation.zip"
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as z:
        for name in FILES:
            content = (ROOT / name).read_bytes()
            manifest["files"].append({"path": name, "sha256": hashlib.sha256(content).hexdigest(), "bytes": len(content)})
            info = zipfile.ZipInfo(name, date_time=(2026, 9, 30, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            z.writestr(info, content)
    with zipfile.ZipFile(archive) as z:
        assert z.namelist() == FILES
        assert z.testzip() is None
        for entry in manifest["files"]:
            assert hashlib.sha256(z.read(entry["path"])).hexdigest() == entry["sha256"]
    manifest["zip_sha256"] = hashlib.sha256(archive.read_bytes()).hexdigest()
    (output / "deployment-manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(json.dumps({"zip": str(archive), "files": len(FILES), "sha256": manifest["zip_sha256"]}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output")
    package(parser.parse_args().output)
