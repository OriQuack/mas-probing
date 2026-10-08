"""Web tools for workers: `web_search` and `read_url` (with an optional `date` for an archived snapshot).

One `WebTools` per run, shared by every worker and every workspace of the run (it touches no files). It owns the
fallback chains (backends.py), the per-run search-backend pin, the shared result cache (frozen on first success,
so restored runs see identical results for identical queries/URLs), paid-credit accounting and the GAIA-answer
blocklist. The agent never sees which backend served a result; tool records always do.

The machinery (_call, _search, _read, page_issue, _paged) is the previous pilot's tools v3, unchanged in
behaviour. Tool names, signatures and descriptions are new (not OWL's).
"""

from __future__ import annotations

import json
import re
import threading
import time
from typing import Any

from minpilot.tools import antibot, blocklist
from minpilot.tools.backends import (
    RATE_LIMITER, BackendError, Crawl4AIBackend, CreditsExhausted, DDGBackend, DirectFetchBackend, Page,
    PlaywrightBackend, RateLimited, SerperBackend, WaybackBackend,
)
from minpilot.tools.cache import ToolCache
from minpilot.tools.config import ToolConfig

BLOCKED_QUERY_MESSAGE = ("Error: searching for benchmark datasets, leaderboards or their answers is not permitted in "
                         "this environment. Search for the information itself.")
BLOCKED_MESSAGE = "Error: access to this page is not permitted in this environment. Use a different source."
_WAYBACK_SNAPSHOT = re.compile(r"^https?://web\.archive\.org/web/(\d{8,14})(?:[a-z_]*)/(.+)$")


def _snapshot_date(url: str) -> str | None:
    m = _WAYBACK_SNAPSHOT.match(url)
    if not m:
        return None
    ts = m.group(1)
    return f"{ts[:4]}-{ts[4:6]}-{ts[6:8]}"


class WebTools:
    def __init__(self, cfg: ToolConfig | None = None, *, cache: ToolCache | None = None, question: str | None = None,
                 search_backends: list | None = None, read_backends: list | None = None,
                 wayback: WaybackBackend | None = None):
        self.cfg = cfg or ToolConfig()
        self.cache = cache or ToolCache(self.cfg.cache_path)
        self.question = question  # used only for the content blocklist; never sent to backends
        self.search_backends = search_backends or [SerperBackend(self.cfg), DDGBackend(self.cfg)]
        readers = {"crawl4ai": Crawl4AIBackend, "direct": DirectFetchBackend, "playwright": PlaywrightBackend}
        self.read_backends = read_backends or [readers[n](self.cfg) for n in self.cfg.reader_chain]
        self.wayback = wayback or WaybackBackend(self.cfg)
        self.pinned_search: str | None = None
        self._lock = threading.Lock()

    def state_dict(self) -> dict:
        return {"pinned_search": self.pinned_search, "cache": str(self.cache.path.resolve())}

    def load_state_dict(self, state: dict) -> None:
        self.pinned_search = state.get("pinned_search")

    # -- tools -------------------------------------------------------------------------------
    def web_search(self, query: str, allowed: tuple[str, ...] = ()) -> tuple[str, dict]:
        rec = self._new_record()
        try:
            if reason := blocklist.query_block_reason(query):
                rec["blocked"] = reason
                return BLOCKED_QUERY_MESSAGE, rec
            hits = self._search(query.strip(), rec)
            if hits is None:
                return "Error: web search is currently unavailable. Try again later.", rec
            kept, blocked = [], []
            for h in hits:
                reason = blocklist.url_block_reason(h["url"]) or blocklist.content_block_reason(
                    f"{h['title']}\n{h['snippet']}", self.question, allowed=allowed)
                (blocked if reason else kept).append(h if not reason else {"url": h["url"], "reason": reason})
            rec["blocked_results"] = [b["url"] for b in blocked]
            rec["blocked_reasons"] = [b["reason"] for b in blocked]
            if not kept:
                return f'No results found for "{query}".', rec
            lines = [f'Search results for "{query}":']
            for i, h in enumerate(kept, 1):
                lines.append(f"{i}. {h['title']}\n   URL: {h['url']}\n   {h['snippet']}")
            return "\n".join(lines), rec
        except Exception as e:  # tool errors go back to the agent as text, never crash the run
            rec["error"] = repr(e)
            return f"Error: search failed ({type(e).__name__}).", rec

    def read_url(self, url: str, page: int = 1, date: str | None = None,
                 allowed: tuple[str, ...] = ()) -> tuple[str, dict]:
        rec = self._new_record()
        try:
            url = url.strip()
            if not re.match(r"^https?://", url):
                return "Error: url must start with http:// or https://. Use read_file for local files.", rec
            if date:
                date = str(date).strip()
                if not re.fullmatch(r"\d{4}(\d{2}(\d{2})?)?", date):
                    return "Error: date must be in YYYYMMDD format.", rec
                snap = self._snapshot(url, date, rec)
                if isinstance(snap, str):
                    return snap, rec
                url = snap["snapshot_url"]
            doc = self._read(url, rec, allowed)
            if doc is None:
                return "Error: could not retrieve this page. Try a different source.", rec
            if doc.get("blocked"):
                return BLOCKED_MESSAGE, rec
            return self._paged(doc, page, url), rec
        except Exception as e:
            rec["error"] = repr(e)
            return f"Error: reading the page failed ({type(e).__name__}: {e}).", rec

    # -- internals ---------------------------------------------------------------------------
    @staticmethod
    def _new_record() -> dict:
        return {"cache_hit": False, "backend": None, "attempts": [], "fallback": False, "blocked": None,
                "credits": {}}

    def _snapshot(self, url: str, date: str, rec: dict) -> dict | str:
        if reason := blocklist.url_block_reason(url):
            rec["blocked"] = reason
            return BLOCKED_MESSAGE
        key = json.dumps([url, date])
        snap = self.cache.get("wayback", key)
        rec["wayback_cache_hit"] = snap is not None
        if snap is None:
            RATE_LIMITER.wait("wayback", self.cfg.min_interval_s.get("wayback", 0))
            t0 = time.monotonic()
            try:
                found = self.wayback.closest(url, date)
            except BackendError as e:
                rec["attempts"].append({"backend": "wayback", "ok": False, "error": str(e)[:300]})
                return "Error: the Wayback Machine is unavailable right now. Try again later."
            rec["attempts"].append({"backend": "wayback", "ok": True, "latency_s": round(time.monotonic() - t0, 2)})
            if found is None:
                return f"No archived snapshot of {url} was found."
            snap = self.cache.put("wayback", key, {"snapshot_url": found[0], "timestamp": found[1]}, "wayback")
        return snap

    def _has_credits(self, backend) -> bool:
        if not backend.paid:
            return backend.available()
        if not backend.available():
            return False
        state = self.cache.credits(backend.name)
        if state is None or time.time() - state[1] > self.cfg.credit_sync_s:
            try:
                self.cache.sync_credits(backend.name, backend.balance())
            except CreditsExhausted:
                self.cache.sync_credits(backend.name, 0)
            except Exception:
                if state is None:
                    return True  # balance endpoint down: try the call; the call itself reports exhaustion
            state = self.cache.credits(backend.name)
        remaining, _, used = state
        return remaining - used > self.cfg.credit_reserve.get(backend.name, 0)

    def _call(self, backend, method: str, arg: str, rec: dict):
        """One backend call: credit check, optional cross-process slot, one retry on a short HTTP 429 (never
        charged), credit accounting. Every attempt is logged in rec["attempts"]."""
        if not self._has_credits(backend):
            rec["attempts"].append({"backend": backend.name, "ok": False, "error": "no_credits_or_key"})
            return None
        limits = self.cfg.backend_limits.get(backend.name)
        for try_ in range(2):
            token, waited = None, 0.0
            if limits:
                token, waited = self.cache.acquire(backend.name, int(limits["concurrent"]), int(limits["per_min"]),
                                                   self.cfg.limit_max_wait_s, lease_s=self.cfg.http_timeout_s + 60)
                if token is None:
                    rec["attempts"].append({"backend": backend.name, "ok": False, "error": f"{backend.name}_busy",
                                            "waited_s": round(waited, 2)})
                    return None
            RATE_LIMITER.wait(backend.name, self.cfg.min_interval_s.get(backend.name, 0))
            t0 = time.monotonic()
            try:
                result = getattr(backend, method)(arg)
            except RateLimited as e:
                wait = e.retry_after if e.retry_after is not None else self.cfg.rate_limit_default_wait_s
                retry = try_ == 0 and wait <= self.cfg.rate_limit_retry_max_wait_s
                rec["attempts"].append({"backend": backend.name, "ok": False, "error": str(e)[:300],
                                        "rate_limited": True, "retry": retry,
                                        "latency_s": round(time.monotonic() - t0, 2)})
                if retry:
                    if token:
                        self.cache.release(token)
                        token = None
                    time.sleep(wait)
                    continue
                return None
            except CreditsExhausted as e:
                self.cache.sync_credits(backend.name, 0)
                rec["attempts"].append({"backend": backend.name, "ok": False, "error": str(e)[:300]})
                return None
            except BackendError as e:
                if backend.paid:
                    self.cache.charge(backend.name)
                    rec["credits"][backend.name] = rec["credits"].get(backend.name, 0) + 1
                rec["attempts"].append({"backend": backend.name, "ok": False, "error": str(e)[:300],
                                        "latency_s": round(time.monotonic() - t0, 2)})
                return None
            finally:
                if token:
                    self.cache.release(token)
            if backend.paid:
                self.cache.charge(backend.name)
                rec["credits"][backend.name] = rec["credits"].get(backend.name, 0) + 1
            rec["attempts"].append({"backend": backend.name, "ok": True, "latency_s": round(time.monotonic() - t0, 2)})
            return result
        return None

    def _search(self, query: str, rec: dict) -> list[dict] | None:
        key = json.dumps([query, self.cfg.num_results, self.cfg.gl, self.cfg.hl])
        cached = self.cache.get("search", key)
        if cached is not None:
            rec.update(cache_hit=True, backend=cached["backend"])
            return cached["hits"]
        with self._lock:
            pinned = self.pinned_search
        order = sorted(self.search_backends, key=lambda b: b.name != pinned) if pinned else self.search_backends
        for i, backend in enumerate(order):
            hits = self._call(backend, "search", query, rec)
            if hits is None:
                continue
            with self._lock:
                if self.pinned_search is None:
                    self.pinned_search = backend.name
                rec["backend_switched"] = backend.name != self.pinned_search
            rec.update(backend=backend.name, fallback=i > 0)
            value = {"backend": backend.name, "hits": [h.__dict__ for h in hits]}
            return self.cache.put("search", key, value, backend.name)["hits"]
        return None

    @staticmethod
    def page_issue(url: str, title: str, text: str, question: str | None, allowed: tuple[str, ...] = ()) -> str | None:
        """The one validation for page content shown to a model (fresh reads AND cache hits)."""
        if reason := blocklist.url_block_reason(url or ""):
            return reason
        if challenge := antibot.challenge_reason(text or "", title or ""):
            return challenge
        return blocklist.content_block_reason(f"{title or ''}\n{text or ''}", question, allowed=allowed)

    def _read(self, url: str, rec: dict, allowed: tuple[str, ...] = ()) -> dict | None:
        if reason := blocklist.url_block_reason(url):
            rec["blocked"] = reason
            return {"blocked": reason}
        cached = self.cache.get("page", url)
        if cached is not None:
            rec.update(cache_hit=True, backend=cached.get("backend"))
        else:
            fetch_url = _WAYBACK_SNAPSHOT.sub(r"https://web.archive.org/web/\1id_/\2", url)
            for i, backend in enumerate(self.read_backends):
                page: Page | None = self._call(backend, "fetch", fetch_url, rec)
                if page is None:
                    continue
                if challenge := antibot.challenge_reason(page.text, page.title):
                    rec["attempts"][-1].update(ok=False, error=challenge)
                    continue
                rec.update(backend=backend.name, fallback=i > 0)
                final = url if fetch_url != url else page.url
                value = {"url": final, "title": page.title, "text": page.text, "content_type": page.content_type,
                         "backend": backend.name, "fetched_at": time.time()}
                if reason := self.page_issue(page.url, page.title, page.text, None):
                    value = {"blocked": reason, "backend": backend.name, "fetched_at": time.time()}
                cached = self.cache.put("page", url, value, backend.name)
                break
            else:
                return None
        if cached.get("blocked"):
            rec["blocked"] = cached["blocked"]
            return cached
        reason = self.page_issue(cached.get("url", url), cached.get("title", ""), cached.get("text", ""),
                                 self.question, allowed=allowed)
        if reason in antibot.FAILED_READ_REASONS:
            rec["attempts"].append({"backend": "cache", "ok": False, "error": reason})
            return None
        if reason:
            rec["blocked"] = reason
            return {"blocked": reason}
        return cached

    def _paged(self, doc: dict, page: int, ref: str) -> str:
        return paged(doc, page, self.cfg.page_chars, "read_url", ref)


def paged(doc: dict, page: Any, size: int, tool: str, ref: str) -> str:
    text = doc["text"]
    n_pages = max(1, -(-len(text) // size))
    try:
        page = int(page or 1)
    except (TypeError, ValueError):
        return "Error: page must be an integer."
    if page < 1 or page > n_pages:
        return f"Error: page {page} out of range; this document has {n_pages} page(s)."
    start = (page - 1) * size
    header = [f"Source: {doc['url']}"]
    if doc.get("title"):
        header.append(f"Title: {doc['title']}")
    if snap := _snapshot_date(doc["url"]):
        header.append(f"Archived snapshot (Wayback Machine) taken on {snap}; the page may have changed since.")
    header.append(f"Page {page} of {n_pages} (characters {start}-{min(start + size, len(text))} of {len(text)})."
                  + (f" Call {tool} with page={page + 1} for more." if page < n_pages else ""))
    return "\n".join(header) + "\n\n" + text[start:start + size]
