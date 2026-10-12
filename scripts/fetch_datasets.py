#!/usr/bin/env python
"""Download external benchmarks into ~/data2/datasets at pinned revisions (data stays off the home disk).

  python scripts/fetch_datasets.py monaco longcot [--root ~/data2/datasets] [--workers 8]

- monaco: Hugging Face dataset allenai/MoNaCo_Benchmark via huggingface_hub.snapshot_download (gated: the account of
  the token in $HF_HOME/token, HF_HOME=/data2/dohyun/hf, must have been granted access). Re-running resumes.
- longcot: the official repository github.com/LongHorizonReasoning/longcot, cloned and checked out at the pinned
  commit (its data are plain JSON under src/data/<domain>/<difficulty>.json).

Each dataset directory gets SOURCE.json (origin, revision, file count, bytes, fetch time). MoNaCo asks that its data
not be redistributed online, so the data never enters this repository; loaders read it from the dataset root.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import time
from pathlib import Path

DEFAULT_ROOT = Path.home() / "data2/datasets"
MONACO_REPO = "allenai/MoNaCo_Benchmark"
MONACO_REVISION = "b6382af0b328af154d22cdb38cefcafa909c23a0"
LONGCOT_URL = "https://github.com/LongHorizonReasoning/longcot.git"
LONGCOT_COMMIT = "fb9649423f15f5b0091f8e988b100596cac592ca"


def fetch_monaco(root: Path, workers: int) -> None:
    os.environ.setdefault("HF_HOME", "/data2/dohyun/hf")  # token and cache under /data2, never ~/.cache
    from huggingface_hub import snapshot_download

    dest = root / "MoNaCo"
    snapshot_download(MONACO_REPO, repo_type="dataset", revision=MONACO_REVISION, local_dir=dest,
                      max_workers=workers)
    files = [p for p in dest.rglob("*") if p.is_file() and ".cache" not in p.parts and p.name != "SOURCE.json"]
    _write_source(dest, {"origin": f"https://huggingface.co/datasets/{MONACO_REPO}", "revision": MONACO_REVISION,
                         "files": len(files), "bytes": sum(p.stat().st_size for p in files),
                         "license": "ODC-BY; do not redistribute the data online (dataset card)"})
    print(f"monaco: {len(files)} files at {MONACO_REVISION[:12]} -> {dest}", flush=True)


def fetch_longcot(root: Path) -> None:
    dest = root / "LongCoT" / "repo"
    if not dest.exists():
        dest.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(["git", "clone", "--quiet", LONGCOT_URL, str(dest)], check=True)
    if LONGCOT_COMMIT:
        subprocess.run(["git", "-C", str(dest), "fetch", "--quiet", "origin"], check=True)
        subprocess.run(["git", "-C", str(dest), "checkout", "--quiet", LONGCOT_COMMIT], check=True)
    commit = subprocess.run(["git", "-C", str(dest), "rev-parse", "HEAD"], check=True, capture_output=True,
                            text=True).stdout.strip()
    data = sorted((dest / "src/data").glob("*/*.json"))
    _write_source(dest.parent, {"origin": LONGCOT_URL, "revision": commit, "files": len(data),
                                "bytes": sum(p.stat().st_size for p in data), "license": "MIT",
                                "data_dir": "repo/src/data/<domain>/<difficulty>.json"})
    print(f"longcot: {len(data)} data files at {commit[:12]} -> {dest}", flush=True)


def _write_source(dest: Path, info: dict) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    info["fetched_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    (dest / "SOURCE.json").write_text(json.dumps(info, indent=1) + "\n")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("datasets", nargs="+", choices=("monaco", "longcot"))
    ap.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    ap.add_argument("--workers", type=int, default=8)
    args = ap.parse_args()
    for name in args.datasets:
        fetch_monaco(args.root, args.workers) if name == "monaco" else fetch_longcot(args.root)


if __name__ == "__main__":
    main()
