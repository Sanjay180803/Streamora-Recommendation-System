"""Check that the model and data artifacts listed in configs/artifacts.json exist.

    python scripts/check_artifacts.py            # verify presence and recorded checksums
    python scripts/check_artifacts.py --record   # store checksums and sizes of the present files

Exit status is 1 if a required file is missing or any checksum does not match.
"""

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MANIFEST = ROOT / "configs" / "artifacts.json"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def check(manifest: dict, root: Path, record: bool) -> list[str]:
    problems = []
    for entry in manifest["files"]:
        path = root / entry["path"]
        if not path.exists():
            if entry["required"]:
                problems.append(f"missing required file: {entry['path']}")
            else:
                print(f"optional file absent: {entry['path']}")
            continue

        if record:
            entry["size_bytes"] = path.stat().st_size
            entry["sha256"] = sha256(path)
            print(f"recorded {entry['path']}")
        elif entry.get("sha256") is None:
            print(f"present (no checksum recorded): {entry['path']}")
        elif entry.get("size_bytes") not in (None, path.stat().st_size):
            problems.append(f"size mismatch: {entry['path']}")
        elif entry["sha256"] != sha256(path):
            problems.append(f"checksum mismatch: {entry['path']}")
        else:
            print(f"ok: {entry['path']}")
    return problems


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--record", action="store_true", help="store checksums of present files")
    parser.add_argument("--manifest", type=Path, default=MANIFEST)
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args(argv)

    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    problems = check(manifest, args.root, args.record)
    if args.record:
        args.manifest.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    for problem in problems:
        print(f"ERROR: {problem}", file=sys.stderr)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
