"""Recognise pages that are not the requested content: anti-bot / human-verification interstitials, rate-limit
notices and "the page could not load" shells (v0 overnight runs: an Anubis challenge page returned by Playwright
as a successful read and frozen in the cache; tools v2: OAPEN's rate-limit notice and JSTOR's "Client
Challenge" shell, cached and served to later runs of 65638e28 and 114d5fd0).

A page is a challenge only if it is SHORT (an interstitial, not an article) AND carries challenge-specific
wording or a challenge title. Single words like "Anubis" or "Cloudflare" never suffice, so an article about
Egyptian mythology or about Cloudflare itself is not flagged. Applied to every reader's result before it is
returned or cached (web.py `_read`) and to cache hits; any reason here counts as a failed read and the next
reader is tried. (Copied unchanged from the previous pilot; min_pilot has no interactive browser.)
Reasons: `anti_bot_challenge`, `rate_limit_page`, `load_failure_page` (all in FAILED_READ_REASONS).
"""

from __future__ import annotations

import re

MAX_CHALLENGE_CHARS = 4000  # interstitials are short; real pages that merely mention a CAPTCHA are not

_PHRASES = re.compile(
    r"(?i)making sure you'?re not a bot"
    r"|checking (if the site connection is secure|your browser before accessing)"
    r"|verify(ing)? you are (a )?human"
    r"|verification required"
    r"|please (complete|solve) (the|this) (security )?(check|captcha|challenge)"
    r"|our systems have detected unusual traffic"
    r"|enable javascript and cookies to continue"
    r"|ddos protection by"
    r"|attention required!?\s*\|\s*cloudflare"
    r"|cf-browser-verification|cf-challenge|challenge-platform"
    r"|calculating\.\.\.\s*difficulty"
    r"|press (and|&) hold"
    r"|are you a robot\??"
    r"|access to this page has been denied"
    r"|please (complete|solve|enter) the (captcha|characters)|type the characters (you see|in the image)"
    r"|i'?m not a robot")
_RATE_LIMIT = re.compile(
    r"(?i)unusually high rate of requests|too many requests|rate limit(ed| exceeded)"
    r"|access has been (temporarily )?(limited|restricted)|please (reduce your usage|slow down|try again later)"
    r"|request(s)? (was|were|has been|have been) (throttled|rate[- ]limited)")
_LOAD_FAILURE = re.compile(
    r"(?i)a required part of this site couldn.?t load|this page (could not|couldn.?t) be loaded"
    r"|please (enable|turn on) javascript|you need to enable javascript to (run|view|use) this"
    r"|javascript is (disabled|required)")
_TITLES = re.compile(r"(?i)^\s*(just a moment\.*|attention required!?.*cloudflare.*|making sure you'?re not a bot!?"
                     r"|verification required!?|security check|captcha|human verification|access denied"
                     r"|client challenge|too many requests|429 too many requests)\s*$")
FAILED_READ_REASONS = frozenset({"anti_bot_challenge", "rate_limit_page", "load_failure_page"})


def challenge_reason(text: str, title: str = "") -> str | None:
    body = text or ""
    if len(body) > MAX_CHALLENGE_CHARS and not _TITLES.match(title or ""):
        return None
    if _TITLES.match(title or ""):
        return "anti_bot_challenge"
    head = body[:MAX_CHALLENGE_CHARS * 2]
    if _PHRASES.search(head):
        return "anti_bot_challenge"
    if _RATE_LIMIT.search(head):
        return "rate_limit_page"
    if _LOAD_FAILURE.search(head):
        return "load_failure_page"
    return None
