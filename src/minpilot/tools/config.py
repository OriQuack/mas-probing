"""Fixed tool settings. Identical across conditions; logged with every run (`ToolConfig.to_dict`).

Values carried over from the previous pilot's tools v3 (search count/region, page size, reader chain, timeouts,
rate limits): they are about the web, not about the agent framework. Firecrawl is not used here.
"""

from __future__ import annotations

import os
from dataclasses import asdict, dataclass, field
from pathlib import Path

from minpilot.tools.blocklist import BLOCKLIST_VERSION

REPO_ROOT = Path(__file__).resolve().parents[3]


def _crawl4ai_endpoint() -> Path:
    """Endpoint file of the Crawl4AI service. CRAWL4AI_ENDPOINT points at another repo's running service (only
    one instance can hold the default port), e.g. ../pilot/outputs/servers/crawl4ai.json."""
    return Path(os.environ.get("CRAWL4AI_ENDPOINT", REPO_ROOT / "outputs" / "servers" / "crawl4ai.json"))


@dataclass(frozen=True)
class ToolConfig:
    # Search
    num_results: int = 10
    gl: str = "us"  # Serper country
    hl: str = "en"  # Serper language
    ddg_region: str = "us-en"
    # Reading: full text is cached; agents see it in fixed-size pages.
    page_chars: int = 20_000
    max_download_bytes: int = 30_000_000
    http_timeout_s: float = 30.0
    render_timeout_s: float = 45.0
    # Direct fetch output shorter than this (after HTML-to-text) is treated as a JS-rendered page.
    min_text_chars: int = 200
    # Minimum seconds between calls per backend (process-wide). Serper allows 5 qps.
    min_interval_s: dict[str, float] = field(default_factory=lambda: {
        "serper": 0.25, "ddg": 2.0, "direct": 0.0, "playwright": 0.0, "wayback": 1.0,
    })
    # Cross-process slot limits per backend (none needed for the current backends).
    backend_limits: dict[str, dict[str, float]] = field(default_factory=dict)
    limit_max_wait_s: float = 15.0
    # HTTP 429: retry the same backend once if it asks to wait at most this long, otherwise fall back at once.
    rate_limit_retry_max_wait_s: float = 10.0
    rate_limit_default_wait_s: float = 6.0
    # Switch to the next backend when the remaining paid credits fall to this reserve.
    credit_reserve: dict[str, int] = field(default_factory=lambda: {"serper": 50})
    credit_sync_s: float = 600.0
    # Tool-behaviour version (recorded with every run and checkpoint); each version gets its own cache file
    # (cached results are frozen on first success and would keep serving the old behaviour).
    # v1 (2026-10-08): the previous pilot's tools v3 behaviour under new tool names (web_search, read_url,
    #     read_file, view_image, run_python); no Wikipedia tools, no browser agent.
    # v2 (2026-10-08): docx order, error statuses, blocklist fixes (docs/decisions.md K6).
    # v3 (2026-10-09): read_url(url, question) = question-based page reader (AOrchestra's, reader.py);
    #     raw pages move to read_url_text; new find_in_url (decisions K17, K7).
    # v4 (2026-10-09): `date_rule` on_or_before (default) | closest for archived snapshots (K8); failed reads say
    #     why and permanent failures are not retried within a run (K9); role-neutral sandbox network message
    #     (K11); language-independent anti-bot markers (K14).
    tools_version: str = "v4"
    blocklist_version: str = BLOCKLIST_VERSION
    cache_path: Path = REPO_ROOT / "outputs" / "cache" / "tools_v4.sqlite"
    # Page readers, in fallback order (names: crawl4ai, direct, playwright).
    reader_chain: tuple[str, ...] = ("crawl4ai", "direct", "playwright")
    crawl4ai_endpoint: Path = field(default_factory=_crawl4ai_endpoint)
    # Crawl4AI markdown: drop these elements, keep everything else (deterministic; see backends.Crawl4AIBackend).
    crawl4ai_excluded_tags: tuple[str, ...] = ("nav", "header", "footer", "aside")
    user_agent: str = (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    )
    # read_url's page reader (K17): a fixed model and AOrchestra's long-text rule (cl100k tokens, parts of at most
    # 95,000 tokens + 1,024 overlap). The same for every condition; its calls count toward the run's budgets.
    reader_model: str = "luna-high"  # effort high like every role (M1); `luna` (none) in v3-check
    reader_encoding: str = "cl100k_base"
    reader_part_tokens: int = 95_000
    reader_overlap_tokens: int = 1_024
    reader_max_parallel: int = 4  # parts answered at once (speed only; answers do not depend on it)
    # find_in_url: characters of context on each side of a match, and matches shown
    find_context_chars: int = 300
    find_max_matches: int = 20
    # run_python
    code_timeout_s: float = 60.0
    max_code_output_chars: int = 40_000

    def to_dict(self) -> dict:
        d = asdict(self)
        d["cache_path"] = str(self.cache_path)
        d["crawl4ai_endpoint"] = str(self.crawl4ai_endpoint)
        return d
