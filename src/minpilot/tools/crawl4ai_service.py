"""Identity and health of the local Crawl4AI page-reader service .

The expected identity is pinned in `scripts/crawl4ai/IMAGE`: image tag, Docker digest (provenance of the pull),
SHA-256 of the SIF file actually executed, and the server version. `serve.sh` refuses to run a SIF whose hash
differs and records the identity in the endpoint file. A service is accepted (`service_identity`) only if:
  - the endpoint file's identity equals the pinned one (tag, digest, SIF hash, version),
  - GET /health answers HTTP 200 with JSON whose version equals the pinned version,
  - an authenticated crawl of an inline page (`raw:` URL, no network) succeeds with the stored token.
Checked when a service is started or reused (`scripts/crawl4ai/ensure.sh`), before every run (`scripts/run_task.py`),
and against the identity stored in a checkpoint when restoring.
"""

from __future__ import annotations

import json
from pathlib import Path

import requests

from minpilot.tools.config import REPO_ROOT, ToolConfig

IMAGE_FILE = REPO_ROOT / "scripts" / "crawl4ai" / "IMAGE"


def endpoint_file() -> Path:
    return ToolConfig().crawl4ai_endpoint
IDENTITY_KEYS = ("tag", "docker_digest", "sif_sha256", "version")


def expected_identity(image_file: Path = IMAGE_FILE) -> dict:
    out = {}
    for line in image_file.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            out[k.strip()] = v.strip()
    missing = [k for k in IDENTITY_KEYS if not out.get(k)]
    if missing:
        raise ValueError(f"{image_file}: missing {missing}")
    return {k: out[k] for k in IDENTITY_KEYS}


def service_identity(endpoint: Path | None = None, image_file: Path = IMAGE_FILE,
                     timeout: float = 30.0) -> tuple[dict | None, str]:
    """(identity, "ok") if the running service is the pinned one and works; (None, reason) otherwise."""
    try:
        want = expected_identity(image_file)
    except Exception as e:
        return None, f"pinned identity unreadable: {e}"
    try:
        ep = json.loads(Path(endpoint or endpoint_file()).read_text())
    except Exception:
        return None, "service not running (no endpoint file)"
    got = {k: ep.get(k) for k in IDENTITY_KEYS}
    if got != want:
        diff = {k: (got[k], want[k]) for k in IDENTITY_KEYS if got[k] != want[k]}
        return None, f"identity differs from the pinned image: {diff}"
    try:
        h = requests.get(f"{ep['base_url']}/health", timeout=timeout)
        if h.status_code != 200:
            return None, f"/health HTTP {h.status_code}"
        version = h.json().get("version")
    except Exception as e:
        return None, f"/health unreachable: {e!r}"[:200]
    if version != want["version"]:
        return None, f"server version {version!r} != pinned {want['version']!r}"
    try:
        r = requests.post(f"{ep['base_url']}/crawl", timeout=timeout,
                          headers={"Authorization": f"Bearer {ep['token']}"},
                          json={"urls": ["raw:<html><body><p>crawl4ai identity probe</p></body></html>"],
                                "crawler_config": {"type": "CrawlerRunConfig", "params": {"cache_mode": "bypass"}}})
        if r.status_code != 200:
            return None, f"authenticated probe HTTP {r.status_code}"
        res = (r.json().get("results") or [{}])[0]
        md = res.get("markdown")
        md = md.get("raw_markdown") if isinstance(md, dict) else md
        if not res.get("success") or "identity probe" not in (md or ""):
            return None, "authenticated probe failed"
    except Exception as e:
        return None, f"authenticated probe error: {e!r}"[:200]
    return {**want, "base_url": ep["base_url"]}, "ok"


def same_identity(a: dict | None, b: dict | None) -> bool:
    return bool(a) and bool(b) and all(a.get(k) == b.get(k) for k in IDENTITY_KEYS)


if __name__ == "__main__":  # used by scripts/crawl4ai/ensure.sh
    import sys

    ident, reason = service_identity()
    print(reason)
    sys.exit(0 if ident else 1)
