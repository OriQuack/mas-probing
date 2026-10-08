"""Search and page-fetch backends. Each does one HTTP job and raises `BackendError` on any failure, so the
caller (`WebTools`) owns fallback order, caching, credits and logging.

Search:  Serper (Google, paid trial)  ->  DuckDuckGo (free, rate-limited)
Reader:  Crawl4AI service (pinned image, local)  ->  direct fetch + local parsing  ->  Playwright
Wayback: snapshot closest to a date (used by read_url when a date is given)

Copied from the previous pilot (tools v3) without behaviour changes; Firecrawl removed.
"""

from __future__ import annotations

import concurrent.futures
import os
import re
import threading
import warnings
import time
from dataclasses import dataclass, field

import requests

from minpilot.tools import documents
from minpilot.tools.config import ToolConfig


class BackendError(Exception):
    pass


class CreditsExhausted(BackendError):
    pass


class RateLimited(BackendError):
    """HTTP 429. `retry_after` in seconds if the server said (None otherwise). Not billed."""

    def __init__(self, msg: str, retry_after: float | None = None):
        super().__init__(msg)
        self.retry_after = retry_after


@dataclass
class SearchHit:
    title: str
    url: str
    snippet: str


@dataclass
class Page:
    url: str  # final URL after redirects
    title: str
    text: str
    content_type: str  # file extension style: html, pdf, docx, ...
    meta: dict = field(default_factory=dict)


class _RateLimiter:
    """Process-wide minimum interval between calls per backend."""

    def __init__(self):
        self._lock = threading.Lock()
        self._next: dict[str, float] = {}

    def wait(self, name: str, interval: float) -> None:
        if interval <= 0:
            return
        with self._lock:
            now = time.monotonic()
            start = max(now, self._next.get(name, now))
            self._next[name] = start + interval
        time.sleep(max(0.0, start - now))


RATE_LIMITER = _RateLimiter()


def _raise_for_status(name: str, r: requests.Response) -> None:
    if r.status_code == 429:  # rate limited: retried once if the wait is short, else next backend (web.py)
        ra = r.headers.get("Retry-After")
        try:
            retry_after = float(ra) if ra is not None else None
        except ValueError:
            retry_after = None
        raise RateLimited(f"{name} rate_limited (HTTP 429, retry-after={ra})", retry_after)
    if r.status_code in (401, 402, 403) and name == "serper":
        raise CreditsExhausted(f"{name} HTTP {r.status_code}: {r.text[:200]}")
    if r.status_code >= 400:
        raise BackendError(f"{name} HTTP {r.status_code}: {r.text[:200]}")


# -- search -------------------------------------------------------------------------------------
class SerperBackend:
    name = "serper"
    paid = True

    def __init__(self, cfg: ToolConfig):
        self.cfg = cfg
        self.key = os.environ.get("SERPER_API_KEY", "")

    def available(self) -> bool:
        return bool(self.key)

    def balance(self) -> int:
        r = requests.get("https://google.serper.dev/account", headers={"X-API-KEY": self.key}, timeout=20)
        _raise_for_status(self.name, r)
        return int(r.json()["balance"])

    def search(self, query: str) -> list[SearchHit]:
        try:
            r = requests.post(
                "https://google.serper.dev/search",
                headers={"X-API-KEY": self.key, "Content-Type": "application/json"},
                json={"q": query, "gl": self.cfg.gl, "hl": self.cfg.hl, "num": self.cfg.num_results},
                timeout=self.cfg.http_timeout_s,
            )
        except requests.RequestException as e:
            raise BackendError(f"serper: {e!r}") from e
        if r.status_code == 400 and "credit" in r.text.lower():
            raise CreditsExhausted(f"serper: {r.text[:200]}")
        _raise_for_status(self.name, r)
        return [SearchHit(o.get("title", ""), o.get("link", ""), o.get("snippet", ""))
                for o in r.json().get("organic", [])]


class DDGBackend:
    name = "ddg"
    paid = False

    def __init__(self, cfg: ToolConfig):
        self.cfg = cfg

    def available(self) -> bool:
        return True

    def search(self, query: str) -> list[SearchHit]:
        from duckduckgo_search import DDGS

        try:
            # Swallow its "renamed to ddgs" notice (it forces simplefilter("always"), so record instead of
            # ignore). The old package name is what the date-capped install resolves to.
            with warnings.catch_warnings(record=True):
                rows = DDGS(timeout=int(self.cfg.http_timeout_s)).text(
                    query, region=self.cfg.ddg_region, max_results=self.cfg.num_results
                )
        except Exception as e:  # the library raises its own rate-limit / timeout exceptions
            raise BackendError(f"ddg: {e!r}") from e
        return [SearchHit(r.get("title", ""), r.get("href", ""), r.get("body", "")) for r in rows]


# -- reader -------------------------------------------------------------------------------------
class Crawl4AIBackend:
    """Local Crawl4AI service (scripts/crawl4ai/serve.sh: unclecode/crawl4ai pinned by digest, Apptainer, CPU
    only, loopback). HTML pages are rendered in its browser and converted to markdown with a deterministic
    rule: the elements in ToolConfig.crawl4ai_excluded_tags (navigation, headers, footers, sidebars) are
    dropped, everything else is kept (`raw_markdown`; no heuristic "fit" pruning, which lost content in the
    reader comparison). PDFs and other downloads fail here by design and fall through to the direct reader."""

    name = "crawl4ai"
    paid = False

    def __init__(self, cfg: ToolConfig, endpoint_path=None):
        self.cfg = cfg
        self.endpoint_path = endpoint_path or cfg.crawl4ai_endpoint

    def endpoint(self) -> dict:
        import json

        p = self.endpoint_path
        if not p.exists():
            raise BackendError("crawl4ai: service not running (scripts/crawl4ai/serve.sh)")
        return json.loads(p.read_text())

    def available(self) -> bool:
        return True  # an unreachable service is reported per call (and runs refuse to start without it)

    def fetch(self, url: str) -> Page:
        ep = self.endpoint()
        body = {"urls": [url], "crawler_config": {"type": "CrawlerRunConfig", "params": {
            "cache_mode": "bypass",  # our own cache decides what is reused
            "excluded_tags": list(self.cfg.crawl4ai_excluded_tags),
            "remove_overlay_elements": True,
            "page_timeout": int(self.cfg.render_timeout_s * 1000),
        }}}
        try:
            r = requests.post(f"{ep['base_url']}/crawl", json=body, timeout=self.cfg.render_timeout_s + 60,
                              headers={"Authorization": f"Bearer {ep['token']}"})
        except requests.RequestException as e:
            raise BackendError(f"crawl4ai: {e!r}") from e
        _raise_for_status(self.name, r)
        res = (r.json().get("results") or [{}])[0]
        if not res.get("success"):
            raise BackendError(f"crawl4ai: {str(res.get('error_message') or 'failed')[:200]}")
        md = res.get("markdown")
        text = (md.get("raw_markdown") if isinstance(md, dict) else md) or ""
        status = res.get("status_code")
        if status and int(status) >= 400:
            raise BackendError(f"crawl4ai: HTTP {status}")
        if len(text.strip()) < self.cfg.min_text_chars:
            raise BackendError("crawl4ai: empty page")
        meta = res.get("metadata") or {}
        return Page(res.get("redirected_url") or url, meta.get("title") or "", text.strip(), "html",
                    {"status": status, "image_digest": ep.get("digest")})


class DirectFetchBackend:
    name = "direct"
    paid = False

    def __init__(self, cfg: ToolConfig):
        self.cfg = cfg

    def available(self) -> bool:
        return True

    def download(self, url: str) -> tuple[bytes, str, str]:
        """(bytes, final_url, content-type header)."""
        try:
            with requests.get(url, headers={"User-Agent": self.cfg.user_agent}, timeout=self.cfg.http_timeout_s,
                              stream=True) as r:
                _raise_for_status(self.name, r)
                buf = bytearray()
                for chunk in r.iter_content(65536):
                    buf += chunk
                    if len(buf) > self.cfg.max_download_bytes:
                        raise BackendError(f"direct: larger than {self.cfg.max_download_bytes} bytes")
                return bytes(buf), r.url, r.headers.get("Content-Type", "")
        except requests.RequestException as e:
            raise BackendError(f"direct: {e!r}") from e

    def fetch(self, url: str) -> Page:
        data, final_url, ctype_header = self.download(url)
        ext = documents.ext_from_content_type(ctype_header, final_url)
        try:
            text = documents.bytes_to_text(data, ext).strip()
        except documents.UnsupportedDocument as e:
            raise BackendError(f"direct: {e}") from e
        except Exception as e:
            raise BackendError(f"direct: could not parse {ext}: {e!r}") from e
        title = ""
        if ext == "html":
            html = data.decode("utf-8", "replace")
            title = documents.html_title(html)
            low = text.lower()
            if len(text) < self.cfg.min_text_chars or "enable javascript" in low or "javascript is disabled" in low:
                raise BackendError("direct: page needs JavaScript rendering")
        return Page(final_url, title, text, ext)


# One thread for Playwright: its sync API refuses to run inside a thread that has an asyncio loop.
_PLAYWRIGHT_POOL = concurrent.futures.ThreadPoolExecutor(max_workers=2, thread_name_prefix="playwright")


class PlaywrightBackend:
    """Renders JavaScript pages in a fresh headless Chromium per call (no state carries across calls)."""

    name = "playwright"
    paid = False

    def __init__(self, cfg: ToolConfig):
        self.cfg = cfg

    def available(self) -> bool:
        return True

    def _render(self, url: str) -> tuple[str, str, str]:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            try:
                page = browser.new_page(user_agent=self.cfg.user_agent)
                page.goto(url, wait_until="networkidle", timeout=int(self.cfg.render_timeout_s * 1000))
                # Proof-of-work interstitials (e.g. Anubis) clear themselves after a few seconds: wait once.
                # If it is still a challenge afterwards, WebTools rejects it (antibot.challenge_reason).
                from minpilot.tools import antibot

                if antibot.challenge_reason(page.inner_text("body") if page.query_selector("body") else "",
                                            page.title()):
                    page.wait_for_timeout(10_000)
                    try:
                        page.wait_for_load_state("networkidle", timeout=15_000)
                    except Exception:
                        pass
                return page.content(), page.url, page.title()
            finally:
                browser.close()

    def fetch(self, url: str) -> Page:
        try:
            html, final_url, title = _PLAYWRIGHT_POOL.submit(self._render, url).result(
                timeout=self.cfg.render_timeout_s + 30)
        except Exception as e:
            raise BackendError(f"playwright: {e!r}") from e
        text = documents.html_to_text(html)
        if not text:
            raise BackendError("playwright: empty page")
        return Page(final_url, title, text, "html")


class WaybackBackend:
    """Finds the snapshot closest to a date.

    Measured from this cluster on 2026-10-06 (see CLAUDE.md "Tools and task scope"):
    - availability API (archive.org/wayback/available): HTTP 429 in <0.5 s for nearly every URL, even with
      requests 3 s apart and no Retry-After header -> a server-side limit on our egress IP. Not used.
    - `web/<date>id_/<url>` redirect: ~1 s, reliable -> primary.
    - CDX API: no 429s but slow and flaky (2-40 s, some timeouts) -> fallback only.
    """

    name = "wayback"
    paid = False
    _SNAPSHOT = re.compile(r"^https?://web\.archive\.org/web/(\d{14})[a-z_]*/(.+)$")

    def __init__(self, cfg: ToolConfig):
        self.cfg = cfg

    def closest(self, url: str, date: str) -> tuple[str, str] | None:
        """(snapshot_url, timestamp YYYYMMDDhhmmss) or None if never archived."""
        try:
            r = requests.head(f"https://web.archive.org/web/{date}id_/{url}", allow_redirects=True,
                              timeout=self.cfg.http_timeout_s)
            if r.status_code == 404:
                return None
            _raise_for_status(self.name, r)
            if m := self._SNAPSHOT.match(r.url):
                return f"https://web.archive.org/web/{m.group(1)}/{m.group(2)}", m.group(1)
        except (requests.RequestException, BackendError):
            pass
        return self._closest_cdx(url, date)

    def _closest_cdx(self, url: str, date: str) -> tuple[str, str] | None:
        try:
            r = requests.get(
                "https://web.archive.org/cdx/search/cdx",
                params={"url": url, "closest": date, "sort": "closest", "limit": 1, "output": "json",
                        "filter": "statuscode:200", "fl": "timestamp,original"},
                timeout=self.cfg.http_timeout_s,
            )
        except requests.RequestException as e:
            raise BackendError(f"wayback cdx: {e!r}") from e
        _raise_for_status(self.name, r)
        try:
            rows = r.json() if r.text.strip() else []
        except ValueError as e:
            raise BackendError(f"wayback cdx: bad response {r.text[:200]!r}") from e
        if len(rows) < 2:
            return None
        ts, original = rows[1]
        return f"https://web.archive.org/web/{ts}/{original}", ts



def crawl4ai_status(endpoint_path=None) -> dict | None:
    """Verified identity of the running Crawl4AI service, or None (see tools/crawl4ai_service.py)."""
    from minpilot.tools.crawl4ai_service import endpoint_file, service_identity

    ident, _ = service_identity(endpoint_path or endpoint_file())
    return ident
