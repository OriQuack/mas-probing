"""Web tools for workers: `web_search`, and three ways to read a page (each with an optional `date` for an archived
snapshot):
- `read_url(url, question)`: a reader model answers the question from the page's full text (tools v3; reader.py,
  adapted from AOrchestra's reader);
- `read_url_text(url, page)`: the raw text, in fixed-size pages (tools v1-v2 `read_url`);
- `find_in_url(url, text)`: every occurrence of a string, with surrounding text and its page number.
All three get the page through the same path (`_fetch_doc`: cache, blocklist, reader chain, Wayback).

One `WebTools` per run, shared by every worker and every workspace of the run (it touches no files). It owns the
fallback chains (backends.py), the per-run search-backend pin, the shared result cache (frozen on first success,
so restored runs see identical results for identical queries/URLs), paid-credit accounting and the GAIA-answer
blocklist. The agent never sees which backend served a result; tool records always do.

The machinery (_call, _search, _read, page_issue, paged) is the previous pilot's tools v3, unchanged in
behaviour. Tool names, signatures and descriptions are new (not OWL's).
"""

from __future__ import annotations

import copy
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
DATE_RULES = ("on_or_before", "closest")

# Why every reader failed (tools v4, K9): the worker is told the cause, and a cause that will not change within the
# run (PERMANENT) is remembered, so a repeated read of that URL fails at once instead of re-running every reader.
FAILURE_TEXT = {
    "anti_bot_challenge": "the site answered with an anti-bot or human-verification page",
    "rate_limit_page": "the site answered with a rate-limit notice",
    "load_failure_page": "the page only loads with interactive JavaScript",
    "needs_javascript": "the page only loads with interactive JavaScript",
    "access_denied": "access denied (HTTP 401/403; login, paywall or blocking)",
    "not_found": "page not found (HTTP 404/410)",
    "too_large": "the file is too large to download",
    "unparseable": "the document could not be converted to text",
    "empty": "the page has no readable text",
    "rate_limited": "the site is rate-limiting requests (HTTP 429)",
    "server_error": "the site returned a server error (HTTP 5xx)",
    "timeout": "the site did not respond in time",
    "unavailable": "the page readers are unavailable",
    "unknown": "the readers failed for an unknown reason",
}
PERMANENT_FAILURES = frozenset({"anti_bot_challenge", "rate_limit_page", "load_failure_page", "needs_javascript",
                                "access_denied", "not_found", "too_large", "unparseable", "empty"})
_CAUSE_ORDER = ("anti_bot_challenge", "rate_limit_page", "access_denied", "not_found", "load_failure_page",
                "needs_javascript", "too_large", "unparseable", "rate_limited", "timeout", "server_error", "empty",
                "unavailable", "unknown")


def attempt_cause(error: str) -> str:
    e = str(error or "")
    if e in FAILURE_TEXT:
        return e
    low = e.lower()
    if re.search(r"http (401|403)\b", low):
        return "access_denied"
    if re.search(r"http (404|410)\b", low):
        return "not_found"
    if "429" in low or "rate_limited" in low:
        return "rate_limited"
    if re.search(r"http 5\d\d\b", low):
        return "server_error"
    if "timeout" in low or "timed out" in low:
        return "timeout"
    if "javascript" in low:
        return "needs_javascript"
    if "larger than" in low:
        return "too_large"
    if "could not parse" in low or "unsupported" in low:
        return "unparseable"
    if "empty page" in low:
        return "empty"
    if "not running" in low or "no_credits_or_key" in low or "connectionerror" in low:
        return "unavailable"
    return "unknown"


def failure_cause(attempts: list[dict]) -> str:
    causes = {attempt_cause(a.get("error")) for a in attempts if not a.get("ok")}
    return next((c for c in _CAUSE_ORDER if c in causes), "unknown")


def failure_message(cause: str, earlier: bool = False) -> str:
    text = FAILURE_TEXT.get(cause, FAILURE_TEXT["unknown"])
    if cause in PERMANENT_FAILURES:
        hint = ("Retrying will not help; use a different source (another site, or an archived copy with `date`).")
    else:
        hint = "It may work later; otherwise use a different source."
    when = " (it already failed earlier in this run)" if earlier else ""
    return f"Error: could not retrieve this page{when}: {text}. {hint}"
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
        self.blocked_urls: set[str] = set()
        self.failed_urls: dict[str, str] = {}  # URL key -> permanent failure cause (K9; part of the checkpoint)
        self.reader = None  # tools.reader.PageReader, set by the harness (it needs the run's model client)
        self._lock = threading.Lock()

    def fork(self) -> "WebTools":
        """A view for a scratch workspace (probe, verification): the same cache and backends, but its own search
        pin and blocked-URL set, starting from this one's state. Nothing it does changes the main run's web state
        (review 2026-10-09, F9: a probe's first search used to pin the main run's search backend)."""
        other = copy.copy(self)
        other._lock = threading.Lock()
        other.blocked_urls = set(self.blocked_urls)
        other.failed_urls = dict(self.failed_urls)
        return other

    def state_dict(self) -> dict:
        return {"pinned_search": self.pinned_search, "cache": str(self.cache.path.resolve()),
                "blocked_urls": sorted(self.blocked_urls), "failed_urls": dict(sorted(self.failed_urls.items()))}

    def load_state_dict(self, state: dict) -> None:
        self.pinned_search = state.get("pinned_search")
        self.blocked_urls = set(state.get("blocked_urls", []))
        self.failed_urls = dict(state.get("failed_urls", {}))

    # -- sticky blocking (blocklist v5): once any rule blocks a URL, it stays blocked for the rest of the run ---
    @staticmethod
    def _url_key(url: str) -> str:
        return (url or "").split("#", 1)[0].rstrip("/").lower()

    def _block_reason(self, url: str, reason: str | None) -> str | None:
        key = self._url_key(url)
        with self._lock:
            if reason:
                self.blocked_urls.add(key)
                return reason
            return "blocked_earlier_in_run" if key in self.blocked_urls else None

    # -- tools -------------------------------------------------------------------------------
    def web_search(self, query: str, allowed: tuple[str, ...] = ()) -> tuple[str, dict]:
        rec = self._new_record()
        try:
            if reason := blocklist.query_block_reason(query):
                rec["blocked"] = reason
                return BLOCKED_QUERY_MESSAGE, rec
            hits = self._search(query.strip(), rec)
            if hits is None:
                rec["error"] = "all_search_backends_failed"
                return "Error: web search is currently unavailable. Try again later.", rec
            kept, blocked = [], []
            for h in hits:
                rule = blocklist.url_block_reason(h["url"]) or blocklist.content_block_reason(
                    f"{h['title']}\n{h['snippet']}", self.question, allowed=allowed)
                reason = self._block_reason(h["url"], rule)
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

    def read_url_text(self, url: str, page: int = 1, date: str | None = None, allowed: tuple[str, ...] = (),
                      date_rule: str = "on_or_before") -> tuple[str, dict]:
        rec = self._new_record()
        try:
            doc = self._fetch_doc(url, date, rec, allowed, date_rule)
            if isinstance(doc, str):
                return doc, rec
            return paged(doc, page, self.cfg.page_chars, "read_url_text", doc["url"]), rec
        except Exception as e:
            rec["error"] = repr(e)
            return f"Error: reading the page failed ({type(e).__name__}: {e}).", rec

    def read_url(self, url: str, question: str, date: str | None = None, allowed: tuple[str, ...] = (),
                 date_rule: str = "on_or_before") -> tuple[str, dict]:
        """The question-based reader (tools v3). Budget and infrastructure errors of the reader model propagate
        (they end the run like any other model call); everything else comes back to the worker as text."""
        rec = self._new_record()
        question = str(question or "").strip()
        rec["question"] = question
        if not question:
            rec["error"] = "invalid_arguments: empty question"
            return "Error: give a `question` about the page (for the raw text use read_url_text).", rec
        if self.reader is None:
            rec["error"] = "no_reader"
            return "Error: the page reader is not available.", rec
        try:
            doc = self._fetch_doc(url, date, rec, allowed, date_rule)
        except Exception as e:
            rec["error"] = repr(e)
            return f"Error: reading the page failed ({type(e).__name__}: {e}).", rec
        if isinstance(doc, str):
            return doc, rec
        answer, info = self.reader.answer(doc["text"], question)
        rec["reader"] = info
        if answer is None:
            rec["error"] = f"reader_failed: {info.get('error')}"
            return ("Error: the page reader failed on this page. Try again, or use read_url_text / find_in_url.",
                    rec)
        parts = f", in {info['n_parts']} parts" if info["n_parts"] > 1 else ""
        lines = doc_header(doc) + [f"Question: {question}",
                                   f"Answer of the page reader (it read the whole text, {len(doc['text'])} characters"
                                   f"{parts}, and saw only the text and the question):", "", answer]
        return "\n".join(lines), rec

    def find_in_url(self, url: str, text: str, date: str | None = None, allowed: tuple[str, ...] = (),
                    date_rule: str = "on_or_before") -> tuple[str, dict]:
        rec = self._new_record()
        try:
            needle = " ".join(str(text or "").split())
            rec["find"] = needle
            if not needle:
                rec["error"] = "invalid_arguments: empty text"
                return "Error: give the `text` to find.", rec
            doc = self._fetch_doc(url, date, rec, allowed, date_rule)
            if isinstance(doc, str):
                return doc, rec
            return find_text(doc, needle, self.cfg), rec
        except Exception as e:
            rec["error"] = repr(e)
            return f"Error: searching the page failed ({type(e).__name__}: {e}).", rec

    def _fetch_doc(self, url: str, date: str | None, rec: dict, allowed: tuple[str, ...],
                   date_rule: str = "on_or_before") -> dict | str:
        """The page as a cached document dict, or the error text the agent sees (rec is updated either way)."""
        url = str(url or "").strip()
        if not re.match(r"^https?://", url):
            return "Error: url must start with http:// or https://. Use read_file for local files."
        if date and _WAYBACK_SNAPSHOT.search(url):
            date = None  # already a snapshot URL: read it as is (looking up a snapshot of it finds nothing)
        if date:
            date = str(date).strip()
            if not re.fullmatch(r"\d{4}(\d{2}(\d{2})?)?", date):
                return "Error: date must be in YYYYMMDD format."
            date_rule = date_rule or "on_or_before"
            if date_rule not in DATE_RULES:
                return f"Error: date_rule must be one of {', '.join(DATE_RULES)}."
            rec["date_rule"] = date_rule
            snap = self._snapshot(url, date, rec, date_rule)
            if isinstance(snap, str):
                return snap
            url = snap["snapshot_url"]
        doc = self._read(url, rec, allowed)
        if doc is None:
            rec["error"] = "all_readers_failed"
            return failure_message(rec.get("failure_cause", "unknown"), rec.get("failed_earlier", False))
        if doc.get("blocked"):
            return BLOCKED_MESSAGE
        return {**doc, "url": doc.get("url") or url}

    # -- internals ---------------------------------------------------------------------------
    @staticmethod
    def _new_record() -> dict:
        return {"cache_hit": False, "backend": None, "attempts": [], "fallback": False, "blocked": None,
                "credits": {}}

    def _snapshot(self, url: str, date: str, rec: dict, rule: str = "on_or_before") -> dict | str:
        if reason := blocklist.url_block_reason(url):
            rec["blocked"] = reason
            return BLOCKED_MESSAGE
        key = json.dumps([url, date, rule])
        snap = self.cache.get("wayback", key)
        rec["wayback_cache_hit"] = snap is not None
        if snap is None:
            RATE_LIMITER.wait("wayback", self.cfg.min_interval_s.get("wayback", 0))
            t0 = time.monotonic()
            try:
                found = (self.wayback.on_or_before(url, date) if rule == "on_or_before"
                         else self.wayback.closest(url, date))
            except BackendError as e:
                rec["attempts"].append({"backend": "wayback", "ok": False, "error": str(e)[:300]})
                rec["error"] = "wayback_unavailable"
                return "Error: the Wayback Machine is unavailable right now. Try again later."
            rec["attempts"].append({"backend": "wayback", "ok": True, "latency_s": round(time.monotonic() - t0, 2)})
            if found is None:
                if rule == "on_or_before":
                    return (f"No archived snapshot of {url} on or before {date} was found (date_rule='closest' "
                            f"finds the nearest one, which may be later).")
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
        if reason := self._block_reason(url, blocklist.url_block_reason(url)):
            rec["blocked"] = reason
            return {"blocked": reason}
        cached = self.cache.get("page", url)
        if cached is not None:
            rec.update(cache_hit=True, backend=cached.get("backend"))
        elif (earlier := self.failed_urls.get(self._url_key(url))) is not None:
            rec.update(failure_cause=earlier, failed_earlier=True)  # K9: no new attempt for a permanent failure
            return None
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
                cause = rec["failure_cause"] = failure_cause(rec["attempts"])
                if cause in PERMANENT_FAILURES:
                    with self._lock:
                        self.failed_urls[self._url_key(url)] = cause
                return None
        if cached.get("blocked"):
            self._block_reason(url, cached["blocked"])
            rec["blocked"] = cached["blocked"]
            return cached
        reason = self.page_issue(cached.get("url", url), cached.get("title", ""), cached.get("text", ""),
                                 self.question, allowed=allowed)
        if reason in antibot.FAILED_READ_REASONS:
            rec["attempts"].append({"backend": "cache", "ok": False, "error": reason})
            rec["failure_cause"] = reason
            with self._lock:
                self.failed_urls[self._url_key(url)] = reason
            return None
        if reason:
            self._block_reason(url, reason)
            self._block_reason(cached.get("url", url), reason)
            rec["blocked"] = reason
            return {"blocked": reason}
        return cached


def doc_header(doc: dict) -> list[str]:
    header = [f"Source: {doc['url']}"]
    if doc.get("title"):
        header.append(f"Title: {doc['title']}")
    if snap := _snapshot_date(doc["url"]):
        header.append(f"Archived snapshot (Wayback Machine) taken on {snap}; the page may have changed since.")
    return header


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
    header = doc_header(doc)
    header.append(f"Page {page} of {n_pages} (characters {start}-{min(start + size, len(text))} of {len(text)})."
                  + (f" Call {tool} with page={page + 1} for more." if page < n_pages else ""))
    return "\n".join(header) + "\n\n" + text[start:start + size]


def find_text(doc: dict, needle: str, cfg: ToolConfig) -> str:
    """Case-insensitive search for `needle` (any whitespace between its words) in the document's text."""
    text = doc["text"]
    pattern = re.compile(r"\s+".join(re.escape(w) for w in needle.split()), re.IGNORECASE)
    hits = list(pattern.finditer(text))
    n_pages = max(1, -(-len(text) // cfg.page_chars))
    lines = doc_header(doc) + [f'{len(hits)} occurrence(s) of "{needle}" in {len(text)} characters '
                               f"({n_pages} page(s) of read_url_text)."]
    ctx = cfg.find_context_chars
    for i, m in enumerate(hits[:cfg.find_max_matches], 1):
        a, b = max(0, m.start() - ctx), min(len(text), m.end() + ctx)
        snippet = " ".join(text[a:b].split())
        lines.append(f"\n[{i}] page {m.start() // cfg.page_chars + 1}, character {m.start()}:\n"
                     f"{'...' if a else ''}{snippet}{'...' if b < len(text) else ''}")
    if len(hits) > cfg.find_max_matches:
        lines.append(f"\n(Showing the first {cfg.find_max_matches}; search for a longer string to narrow it down.)")
    return "\n".join(lines)
