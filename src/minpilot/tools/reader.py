"""Question-based page reader behind `read_url` (tools v3): a fixed model answers a question from a page's text.

Adapted from AOrchestra's `ExtractUrlContentAction` (FoundationAgents/AOrchestra @ 14a1a2051d6b,
benchmark/gaia/tools/extract_url_jina.py; Apache License 2.0; that file credits WebExplorer's browse tool).

Kept from the original:
- the extraction prompts, verbatim (the single-text and the per-part prompt differ slightly there, and here);
- the long-document handling: cl100k_base tokens; above 95,000 tokens the text is split into
  max(2, n // 95000 + 1) parts of n // parts tokens, each extended by 1,024 tokens; every part is answered
  separately and the answers are joined under the original header;
- failure when any part fails or the answer is empty.
Changed (the adapter):
- the text comes from min_pilot's fetch chain (cache, blocklist, Crawl4AI -> direct -> Playwright, Wayback by
  date) instead of Jina;
- the model is a fixed min_pilot key (`ToolConfig.reader_model`) called through `LLMClient`: the run's budgets,
  trace records (tagged `component: reader`) and provider/cost checks apply; the original used deepseek-reasoner;
- parts run in a thread pool instead of asyncio; the result is returned as text with the source and question
  (no 2,000-character source preview).
The reader sees only the page text and the question: never the task, the instruction or the worker's history.
"""

from __future__ import annotations

import contextvars
import hashlib
import os
from concurrent.futures import ThreadPoolExecutor

from minpilot.llm.client import HTTPError, LLMClient, TransientError
from minpilot.tools.config import REPO_ROOT, ToolConfig

PROMPT = ("Please read the source content and answer a following question:\n---begin of source content---\n{source}"
          "\n---end of source content---\n\nIf there is no relevant information, please clearly refuse to answer. Now "
          "answer the question based on the above content:\n{question}")
PART_PROMPT = ("Please read the source content and answer a following question:\n--- begin of source content ---\n"
               "{source}\n--- end of source content ---\n\nIf there is no relevant information, please clearly "
               "refuse to answer. Now answer the question based on the above content:\n{question}")
SPLIT_HEADER = ("Since the content is too long, the result is split and answered separately. Please combine the "
                "results to get the complete answer.\n")

_ENCODINGS: dict[str, object] = {}


def get_encoding(name: str):
    """tiktoken encoding, cached on disk under outputs/cache/tiktoken (fetched once, then offline)."""
    if name not in _ENCODINGS:
        os.environ.setdefault("TIKTOKEN_CACHE_DIR", str(REPO_ROOT / "outputs" / "cache" / "tiktoken"))
        import tiktoken

        _ENCODINGS[name] = tiktoken.get_encoding(name)
    return _ENCODINGS[name]


def split_spans(n_tokens: int, part_tokens: int, overlap: int) -> list[tuple[int, int]] | None:
    """Token spans of the parts (AOrchestra's rule), or None when the text fits in one request."""
    if n_tokens <= part_tokens:
        return None
    n = max(2, n_tokens // part_tokens + 1)
    size = n_tokens // n
    return [(i * size, min(i * size + size + overlap, n_tokens)) for i in range(n)]


class ReaderFailed(Exception):
    pass


class PageReader:
    def __init__(self, client: LLMClient, cfg: ToolConfig, encoding=None):
        self.client = client
        self.cfg = cfg
        self._encoding = encoding  # tests pass a stand-in; default: tiktoken's cfg.reader_encoding

    @property
    def encoding(self):
        return self._encoding or get_encoding(self.cfg.reader_encoding)

    def _ask(self, prompt: str) -> tuple[str, dict]:
        try:
            res = self.client.chat([{"role": "user", "content": [{"type": "text", "text": prompt}]}])
        except (TransientError, HTTPError) as e:  # budget and infrastructure errors propagate
            raise ReaderFailed(f"{type(e).__name__}: {e}") from e
        u = res.usage or {}
        return (res.content or "").strip(), {"usd": float(u.get("cost") or 0.0),
                                             "prompt_tokens": u.get("prompt_tokens") or 0,
                                             "completion_tokens": u.get("completion_tokens") or 0,
                                             "truncated": res.finish_reason == "length"}

    def answer(self, text: str, question: str) -> tuple[str | None, dict]:
        """(answer or None, record). The record has the model, sizes, parts, cost and the error if any."""
        enc = self.encoding
        tokens = enc.encode(text)
        spans = split_spans(len(tokens), self.cfg.reader_part_tokens, self.cfg.reader_overlap_tokens)
        info = {"model": self.client.spec.key, "source_chars": len(text), "source_tokens": len(tokens),
                "source_sha256": hashlib.sha256(text.encode()).hexdigest(), "n_parts": len(spans or [0])}
        prompts = ([PROMPT.format(source=text, question=question)] if spans is None else
                   [PART_PROMPT.format(source=enc.decode(tokens[a:b]), question=question) for a, b in spans])
        with self.client.trace.tags(component="reader"):
            if len(prompts) == 1:
                results = [self._run(prompts[0])]
            else:
                with ThreadPoolExecutor(max_workers=min(self.cfg.reader_max_parallel, len(prompts))) as pool:
                    futures = [pool.submit(contextvars.copy_context().run, self._run, p) for p in prompts]
                    results = [f.result() for f in futures]  # budget/infra errors re-raise here
        info.update(calls=len(results), usd=round(sum(r[1].get("usd", 0.0) for r in results), 8),
                    prompt_tokens=sum(r[1].get("prompt_tokens", 0) for r in results),
                    completion_tokens=sum(r[1].get("completion_tokens", 0) for r in results),
                    truncated=any(r[1].get("truncated") for r in results))
        if errors := [r[1]["error"] for r in results if r[1].get("error")]:
            info["error"] = errors[0]
            return None, info
        if spans is None:
            out = results[0][0]
        else:
            out = SPLIT_HEADER + "".join(f"--- begin of result part {i + 1} ---\n{r[0]}\n--- end of result part "
                                         f"{i + 1} ---\n\n" for i, r in enumerate(results))
        if not out.strip() or any(not r[0] for r in results):
            info["error"] = "empty_answer"
            return None, info
        return out.strip(), info

    def _run(self, prompt: str) -> tuple[str, dict]:
        try:
            return self._ask(prompt)
        except ReaderFailed as e:
            return "", {"error": str(e)[:300]}
