"""Offline fakes: a scripted OpenRouter transport and model-free web tools."""

from __future__ import annotations

import json
from collections import defaultdict
from typing import Callable

from minpilot.tools.backends import Page, SearchHit
from minpilot.tools.cache import ToolCache
from minpilot.tools.config import ToolConfig
from minpilot.tools.web import WebTools

PROVIDERS = {"openai": "OpenAI", "google-ai-studio": "Google AI Studio"}


def kind_of(body: dict) -> str:
    """Which caller sent this request: orchestrator | analyze | rewrite | simulate | worker:<model>."""
    rf = (body.get("response_format") or {}).get("json_schema", {}).get("name")
    if rf == "orchestrator_action":
        return "orchestrator"
    if rf == "review_analysis":
        return "analyze"
    if rf == "rewrite":
        return "rewrite"
    sys_msg = body["messages"][0].get("content", "")
    if isinstance(sys_msg, str) and sys_msg.startswith("You are the orchestrator") and "predicting" in sys_msg:
        return "simulate"
    return "worker"


class Raw:
    """A reply given verbatim (not JSON-encoded), with a chosen finish_reason, e.g. a truncated JSON reply."""

    def __init__(self, content: str, finish_reason: str = "stop"):
        self.content = content
        self.finish_reason = finish_reason


class ScriptedLLM:
    """`transport(body, timeout)`. `script[kind]` is a list of replies (consumed in order) or a callable
    (body -> reply). A reply is a str (content), a dict (JSON content for schema calls, or a message with
    `tool_calls`), or an Exception to raise. Every request body is kept in `self.bodies`."""

    def __init__(self, script: dict[str, list | Callable], cost: float = 1e-6, provider: str | None = None,
                 served_model: str | None = None):
        self.script = {k: (v if callable(v) else list(v)) for k, v in script.items()}
        self.cost = cost
        self.provider = provider
        self.served_model = served_model
        self.bodies: list[dict] = []
        self.by_kind: dict[str, list[dict]] = defaultdict(list)
        self._n = 0

    def __call__(self, body: dict, timeout) -> dict:
        body = json.loads(json.dumps(body))
        self.bodies.append(body)
        k = kind_of(body)
        self.by_kind[k].append(body)
        src = self.script.get(f"{k}:{body['model']}", self.script.get(k))
        if src is None:
            raise AssertionError(f"no script for {k} ({body['model']})")
        reply = src(body) if callable(src) else src.pop(0)
        if isinstance(reply, Exception):
            raise reply
        finish = "stop"
        if isinstance(reply, Raw):
            msg, finish = {"role": "assistant", "content": reply.content}, reply.finish_reason
        elif isinstance(reply, str):
            msg = {"role": "assistant", "content": reply}
        elif "tool_calls" in reply:
            self._n += 1
            msg = {"role": "assistant", "content": reply.get("content", ""),
                   "tool_calls": [{"id": f"call_{self._n}_{i}", "type": "function",
                                   "function": {"name": n, "arguments": json.dumps(a)}}
                                  for i, (n, a) in enumerate(reply["tool_calls"])]}
        else:
            msg = {"role": "assistant", "content": json.dumps(reply)}
        slug = body["provider"]["only"][0]
        return {"id": f"gen-{len(self.bodies)}", "provider": self.provider or PROVIDERS.get(slug, slug),
                "model": self.served_model or body["model"], "choices": [{"message": msg, "finish_reason": finish}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5, "cost": self.cost}}


def delegate(worker_id: str, instruction: str) -> dict:
    return {"rationale": "r", "action": "delegate", "worker_id": worker_id, "instruction": instruction, "answer": None}


def finish(answer: str) -> dict:
    return {"rationale": "r", "action": "finish", "worker_id": None, "instruction": None, "answer": answer}


class FakeSearch:
    """Default: one hit per query. `results` (query -> hits) overrides it for specific queries."""
    name = "serper"
    paid = False

    def __init__(self):
        self.results: dict[str, list] = {}

    def available(self):
        return True

    def search(self, query):
        if query in self.results:
            return list(self.results[query])
        return [SearchHit(f"Result for {query}", "https://example.org/a", "a snippet")]


class FakeReader:
    name = "direct"
    paid = False

    def available(self):
        return True

    def fetch(self, url):
        return Page(url, "Example", f"Text of {url}. " * 50, "html")


def fake_web(tmp_path, question: str = "q") -> WebTools:
    cfg = ToolConfig(cache_path=tmp_path / "cache.sqlite")
    return WebTools(cfg, cache=ToolCache(cfg.cache_path), question=question, search_backends=[FakeSearch()],
                    read_backends=[FakeReader()])
