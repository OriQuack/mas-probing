#!/usr/bin/env python
"""List retained experiments, locate historical paths, or verify immutable execution evidence. No model calls."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from minpilot.artifacts import find_run_records


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    listing = sub.add_parser("list", help="show purpose, run count and prompt versions")
    listing.add_argument("--root", type=Path, default=REPO / "outputs/experiments")
    resolve = sub.add_parser("resolve", help="map a stored pre-cleanup path to its current location")
    resolve.add_argument("path")
    verify = sub.add_parser("verify", help="verify retained canonical run files against SHA-256 inventories")
    verify.add_argument("--root", type=Path, default=REPO / "outputs/experiments")
    args = parser.parse_args()
    if args.command == "resolve":
        mapping = json.loads((REPO / "docs/reports/retention.json").read_text())["path_migrations"]
        value = args.path
        if value.startswith(str(REPO) + "/"):
            value = str(Path(value).relative_to(REPO))
        for old, new in sorted(mapping.items(), key=lambda item: -len(item[0])):
            if value == old or value.startswith(old + "/"):
                target = REPO / (new + value[len(old):])
                print(target)
                return 0 if target.exists() else 1
        target = Path(value) if Path(value).is_absolute() else REPO / value
        print(target)
        return 0 if target.exists() else 1
    checked = 0
    for path in sorted(args.root.glob("*/manifest.json")):
        manifest = json.loads(path.read_text())
        if args.command == "list":
            print(f"{path.parent.name}: {len(find_run_records(path.parent))} runs — {manifest['purpose']}")
            print(f"  execution prompts: {manifest.get('execution_prompt_versions', '?')}; "
                  f"refiner prompts: {manifest.get('refiner_prompt_versions', '?')}")
        else:
            inventory = path.parent / "checksums.json"
            if not inventory.exists():
                print(f"{path.parent.name}: no frozen evidence inventory", file=sys.stderr)
                continue
            for name, expected in json.loads(inventory.read_text()).items():
                target = (path.parent / name).resolve()
                if not target.is_relative_to(path.parent.resolve()):
                    raise ValueError(f"inventory path escapes experiment: {name}")
                if not target.is_file() or hashlib.sha256(target.read_bytes()).hexdigest() != expected:
                    print(f"FAIL: {target}", file=sys.stderr)
                    return 1
                checked += 1
    if args.command == "verify":
        print(f"Verified {checked} canonical files.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
