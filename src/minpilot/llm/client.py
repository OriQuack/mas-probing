"""Chat client for OpenRouter (plain HTTP, no SDK, no agent framework).

`LLMClient.chat(messages, tools=..., response_format=..., tool_choice=...)` sends one Chat Completions request
and returns a `ChatResult`. The caller owns the conversation (a list of plain message dicts); the client never
keeps conversation state, so checkpoints only need the callers' message lists.

Per request:
- `trace.before_llm(reserve)`: budget check + worst-case cost reservation; the timeout is capped at the run's
  remaining wall time;
- a `started` record before sending, then `ok` or `error` with latency, usage, cost, provider, generation id;
- the response is validated: it must name the pinned provider and report its cost, and the cost must be within
  the reservation; otherwise `InfraError` (the response is still recorded: it was paid for);
- transient failures (timeout, connection, 429, 5xx) are retried up to `retries` times with backoff, each attempt
  its own record and budget unit; HTTP 401/402/404 are `InfraError` (key, credits, no matching endpoint).

The transport is injectable (`transport(body, timeout) -> response JSON`), so tests run the same code offline.
"""

from __future__ import annotations

import copy
import json
import os
import re
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from minpilot.llm.specs import ModelSpec, get_spec, reserve_usd
from minpilot.runtime.trace import InfraError, Trace

BASE_URL = "https://openrouter.ai/api/v1"
RETRY_BACKOFF_S = (5.0, 20.0)

Transport = Callable[[dict, float | None], dict]


class HTTPError(Exception):
    def __init__(self, status: int, text: str):
        super().__init__(f"HTTP {status}: {text[:300]}")
        self.status = status


class TransientError(Exception):
    pass


@dataclass
class ChatResult:
    message: dict                     # assistant message to append to the caller's conversation
    content: str
    tool_calls: list[dict] = field(default_factory=list)
    parsed: Any = None                # JSON content when response_format was a JSON schema
    usage: dict = field(default_factory=dict)
    finish_reason: str | None = None


def strict_schema(schema: dict) -> dict:
    """JSON schema in OpenAI's strict form: every object closed with all properties required; optional
    properties become nullable; `default` dropped."""
    def fix(node):
        if isinstance(node, list):
            return [fix(v) for v in node]
        if not isinstance(node, dict):
            return node
        node = {k: fix(v) for k, v in node.items() if k != "default"}
        if node.get("type") == "object" and isinstance(node.get("properties"), dict):
            required = set(node.get("required", []))
            node["properties"] = {k: (v if k in required else {"anyOf": [v, {"type": "null"}]})
                                  for k, v in node["properties"].items()}
            node["required"] = list(node["properties"])
            node["additionalProperties"] = False
        return node
    return fix(copy.deepcopy(schema))


def json_schema_format(name: str, schema: dict) -> dict:
    return {"type": "json_schema", "json_schema": {"name": name, "strict": True, "schema": strict_schema(schema)}}


def http_transport(api_key: str, base_url: str = BASE_URL) -> Transport:
    import requests

    def send(body: dict, timeout: float | None) -> dict:
        try:
            r = requests.post(f"{base_url}/chat/completions", json=body, timeout=timeout or 600,
                              headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"})
        except (requests.Timeout, requests.ConnectionError) as e:
            raise TransientError(repr(e)) from e
        if r.status_code == 429 or r.status_code >= 500:
            raise TransientError(f"HTTP {r.status_code}: {r.text[:300]}")
        if r.status_code >= 400:
            raise HTTPError(r.status_code, r.text)
        data = r.json()
        if "error" in data and not data.get("choices"):
            err = data["error"] or {}
            code = int(err.get("code") or 0)
            if code == 429 or code >= 500:
                raise TransientError(f"error {code}: {err.get('message')}")
            raise HTTPError(code or 400, json.dumps(err)[:300])
        return data

    return send


def _provider_slug(name: str | None) -> str | None:
    return name.strip().lower().replace(" ", "-") if name else None


class LLMClient:
    def __init__(self, spec: ModelSpec, trace: Trace, *, transport: Transport | None = None, retries: int = 2,
                 timeout_s: float = 600.0, sleep: Callable[[float], None] = time.sleep):
        self.spec = spec
        self.trace = trace
        if transport is None:
            key = os.environ.get("OPENROUTER_API_KEY")
            if not key:
                raise InfraError("OPENROUTER_API_KEY is not set (.env)")
            transport = http_transport(key)
        self.transport = transport
        self.retries = retries
        self.timeout_s = timeout_s
        self.sleep = sleep

    def build_body(self, messages: list[dict], tools: list[dict] | None, response_format: dict | None,
                   tool_choice: str | None) -> dict:
        spec = self.spec
        if tools and not spec.tools_allowed:
            raise ValueError(f"{spec.key} must not receive tools (reasoning {spec.reasoning}); use structured output")
        body: dict[str, Any] = {"model": spec.model, "messages": messages, "max_tokens": spec.max_tokens,
                                "provider": spec.routing(), **spec.sampling}
        if spec.reasoning is not None:
            body["reasoning"] = spec.reasoning
        if tools:
            body["tools"] = tools
            if tool_choice:
                body["tool_choice"] = tool_choice
        if response_format:
            body["response_format"] = response_format
        return body

    def chat(self, messages: list[dict], *, tools: list[dict] | None = None, response_format: dict | None = None,
             tool_choice: str | None = None) -> ChatResult:
        body = self.build_body(messages, tools, response_format, tool_choice)
        reserve = reserve_usd(self.spec, body)
        hashes = self.trace.message_hashes(messages)
        for attempt in range(self.retries + 1):
            remaining = self.trace.before_llm(reserve)
            timeout = self.timeout_s if remaining is None else max(1.0, min(self.timeout_s, remaining))
            call_id = self.trace.next_id()
            base = {"call_id": call_id, "attempt": attempt, "model_key": self.spec.key, "model": self.spec.model,
                    "messages": hashes, "n_tools": len(tools or []), "tool_choice": tool_choice,
                    "response_format": (response_format or {}).get("json_schema", {}).get("name"),
                    "n_images": _count_images(messages), "reserve_usd": reserve}
            self.trace.llm({**base, "status": "started"})
            t0 = time.monotonic()
            try:
                data = self.transport(body, timeout)
            except TransientError as e:
                self.trace.settle_llm(reserve, 0.0, unknown=True)  # billing unknown: counted, recorded as $0
                self.trace.llm({**base, "status": "error", "error": str(e)[:500], "transient": True,
                                "latency_s": round(time.monotonic() - t0, 3)})
                if attempt < self.retries:
                    self.sleep(RETRY_BACKOFF_S[min(attempt, len(RETRY_BACKOFF_S) - 1)])
                    continue
                raise
            except HTTPError as e:
                self.trace.settle_llm(reserve, 0.0)
                self.trace.llm({**base, "status": "error", "error": str(e)[:500],
                                "latency_s": round(time.monotonic() - t0, 3)})
                if e.status in (401, 402, 404):
                    raise InfraError(f"OpenRouter {e}") from e
                raise
            usage = data.get("usage") or {}
            cost = float(usage.get("cost") or 0.0)
            self.trace.settle_llm(reserve, cost)
            choice = (data.get("choices") or [{}])[0]
            msg = choice.get("message") or {}
            meta = {"generation_id": data.get("id"), "provider": data.get("provider"), "served_model": data.get("model"),
                    "finish_reason": choice.get("finish_reason"),
                    "native_finish_reason": choice.get("native_finish_reason"), "usage": usage,
                    "latency_s": round(time.monotonic() - t0, 3)}
            problem = self._validate(data, reserve)
            if problem:
                self.trace.llm({**base, **meta, "status": "error", "error": problem, "rejected_response": msg})
                raise InfraError(problem)
            out = {"role": "assistant", "content": msg.get("content") or ""}
            if msg.get("tool_calls"):
                out["tool_calls"] = [{"id": tc["id"], "type": "function",
                                      "function": {"name": tc["function"]["name"],
                                                   "arguments": tc["function"].get("arguments") or "{}"}}
                                     for tc in msg["tool_calls"]]
            if self.spec.preserve_reasoning and msg.get("reasoning_details"):
                out["reasoning_details"] = msg["reasoning_details"]
            parsed = None
            if response_format and response_format.get("type") == "json_schema":
                try:
                    parsed = json.loads(out["content"])
                except (TypeError, ValueError):
                    parsed = None
            self.trace.llm({**base, **meta, "status": "ok", "output": out["content"],
                            "tool_calls": out.get("tool_calls"), "reasoning": msg.get("reasoning")})
            return ChatResult(message=out, content=out["content"], tool_calls=out.get("tool_calls", []),
                              parsed=parsed, usage=usage, finish_reason=choice.get("finish_reason"))
        raise RuntimeError("unreachable")

    def _validate(self, data: dict, reserve: float) -> str | None:
        if not data.get("choices"):
            return f"no choices in response: {data.get('error')}"
        served = _provider_slug(data.get("provider"))
        if served is None:
            return "response names no provider (cannot verify the pinned provider)"
        if served != self.spec.provider.split("/")[0]:
            return f"served by provider {served!r}, pinned {self.spec.provider!r}"
        if not same_model(data.get("model"), self.spec.model):
            return f"served model {data.get('model')!r} is not the requested {self.spec.model!r}"
        cost = (data.get("usage") or {}).get("cost")
        if cost is None:
            return "response reports no cost (the cost budget cannot be enforced)"
        if float(cost) > reserve:
            return f"cost ${cost} above the reserved bound ${reserve:.5f}"
        return None


# Served-model check (review 2026-10-09, F7). OpenRouter reports the served model without the dated suffix of a
# pinned snapshot (requested openai/gpt-6-luna-20260922 -> served openai/gpt-6-luna), so ids are compared after
# dropping a trailing date (-YYYYMMDD or -YYYY-MM-DD) and an OpenRouter variant (:free, ...). Exact aliases that
# need more go in SERVED_ALIASES (requested -> accepted served ids).
SERVED_ALIASES: dict[str, set[str]] = {}
_DATE_SUFFIX = re.compile(r"-(\d{8}|\d{4}-\d{2}-\d{2})$")


def _base_model(model: str) -> str:
    return _DATE_SUFFIX.sub("", (model or "").split(":", 1)[0].strip().lower())


def same_model(served: str | None, requested: str) -> bool:
    if not served:
        return False
    return served == requested or served in SERVED_ALIASES.get(requested, set()) \
        or _base_model(served) == _base_model(requested)


def _count_images(messages: list[dict]) -> int:
    n = 0
    for m in messages:
        c = m.get("content")
        if isinstance(c, list):
            n += sum(1 for p in c if isinstance(p, dict) and p.get("type") == "image_url")
    return n


def make_client(key: str, trace: Trace, transport: Transport | None = None) -> LLMClient:
    return LLMClient(get_spec(key), trace, transport=transport)
