"""Unit prices of paid tool calls, for cost accounting (review 2026-10-09, F5). Not tool behaviour: changing a price
changes only the recorded USD, so it is not part of ToolConfig or of restore checks. Recorded in every run.json.

Only backends that bill per call are priced. Local readers (Crawl4AI, direct fetch, Playwright), Wayback and
DuckDuckGo cost nothing per call; their counts and latency are reported instead, never a made-up USD value.

Serper: list price of the smallest paid tier as of 2026-10 (USD 50 per 50,000 queries = USD 0.001 per credit).
The account currently runs on free trial credits; set the actual contract price here (docs/decisions.md K15).
"""

COSTS_VERSION = "c1"
TOOL_USD_PER_CREDIT: dict[str, float] = {"serper": 0.001}
# The most a single tool call can cost (reserved before the call, like LLM requests).
MAX_TOOL_CALL_USD = max(TOOL_USD_PER_CREDIT.values(), default=0.0)


def credits_usd(credits: dict[str, float] | None) -> float:
    return sum(TOOL_USD_PER_CREDIT.get(k, 0.0) * v for k, v in (credits or {}).items())
