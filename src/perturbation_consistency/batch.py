"""OpenRouter Batch API as an `LLMClient` transport (about half the per-token price, results within 24 h).

`BatchDispatcher.transport` has the synchronous transport signature `(body, timeout) -> response JSON`, so the
runner and `LLMClient` (budget reservation, validation, trace records) are unchanged. Each call is queued and its
thread blocks; once no new request has arrived for `quiet_s` seconds (all pipelines are waiting) the queue is
submitted as one batch per (model, provider pin), polled every `poll_s` seconds, and every waiting call gets its
own result body. A chain of N dependent nodes therefore takes N batch round trips.

Batch requests take only `provider.only` and `allow_fallbacks` (no `require_parameters`, no `data_collection`), so
the pin is sent at batch level and the per-request `provider` field is dropped. Two fields the client validates may
be missing from a batch result body; when they are, they are filled and flagged rather than invented silently:
- `usage.cost`: estimated from the result's token counts at `price_factor` x the spec's list prices
  (`usage.cost_estimated = true`); the batch-level `usage.cost` actually charged is logged in `batches.jsonl`;
- `provider`: the batch's pinned provider (`provider_from_batch_pin = true`; the pin allows no fallbacks).

`batches.jsonl` (one line per submit and per finished batch) records ids, models, request counts, status and the
charged batch usage. It never contains the API key.
"""

from __future__ import annotations

import json
import threading
import time
import uuid
from concurrent.futures import Future
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from minpilot.llm.client import HTTPError, TransientError
from minpilot.llm.specs import ModelSpec
from minpilot.runtime.trace import InfraError

BASE_URL = "https://openrouter.ai/api/v1"
TERMINAL = {"completed", "failed", "expired", "cancelled"}

# http(method, path, json_body | None) -> (status_code, response JSON)
HTTP = Callable[[str, str, dict | None], tuple[int, dict]]


def requests_http(api_key: str, base_url: str = BASE_URL) -> HTTP:
    import requests

    def call(method: str, path: str, body: dict | None) -> tuple[int, dict]:
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        try:
            # json.dumps keeps key order: endpoint, model and provider must precede requests (else HTTP 400).
            r = requests.request(method, f"{base_url}{path}", headers=headers, timeout=120,
                                 data=None if body is None else json.dumps(body))
        except (requests.Timeout, requests.ConnectionError) as e:
            return 0, {"error": {"message": repr(e)}}
        try:
            return r.status_code, r.json()
        except ValueError:
            return r.status_code, {"error": {"message": r.text[:300]}}

    return call


@dataclass
class _Pending:
    custom_id: str
    body: dict
    spec: ModelSpec
    future: Future = field(default_factory=Future)


class BatchDispatcher:
    def __init__(self, http: HTTP, log_path: Path, specs: dict[str, ModelSpec], *, quiet_s: float = 20.0,
                 poll_s: float = 30.0, price_factor: float = 0.5, max_cost_usd: float | None = None,
                 sleep: Callable[[float], None] = time.sleep, clock: Callable[[], float] = time.monotonic):
        self.http = http
        self.log_path = log_path
        self.by_model = {s.model: s for s in specs.values()}
        self.quiet_s, self.poll_s, self.price_factor = quiet_s, poll_s, price_factor
        self.max_cost_usd = max_cost_usd
        self.sleep, self.clock = sleep, clock
        self._lock = threading.Lock()
        self._queue: list[_Pending] = []
        self._last_put = 0.0
        self._active: dict[str, list[_Pending]] = {}  # batch id -> its requests
        self.charged_usd = 0.0
        self.estimated_usd = 0.0
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._loop, name="batch-dispatcher", daemon=True)
        self._thread.start()

    # -- transport -------------------------------------------------------------------------------
    def transport(self, body: dict, timeout: float | None) -> dict:  # noqa: ARG002 - batches ignore the timeout
        spec = self.by_model.get(body.get("model"))
        if spec is None:
            raise InfraError(f"batch dispatcher has no spec for model {body.get('model')!r}")
        p = _Pending(f"r-{uuid.uuid4().hex[:16]}", body, spec)
        with self._lock:
            if self.max_cost_usd is not None and self.charged_usd >= self.max_cost_usd:
                raise InfraError(f"batch session cap reached (${self.charged_usd:.3f} >= ${self.max_cost_usd})")
            self._queue.append(p)
            self._last_put = self.clock()
        return p.future.result()

    def close(self) -> None:
        self._stop.set()
        self._thread.join()

    # -- loop ------------------------------------------------------------------------------------
    def _loop(self) -> None:
        last_poll = 0.0
        while not self._stop.is_set():
            with self._lock:
                due = self._queue and self.clock() - self._last_put >= self.quiet_s
                batch, self._queue = (self._queue, []) if due else ([], self._queue)
            if batch:
                self._submit(batch)
            if self._active and self.clock() - last_poll >= self.poll_s:
                last_poll = self.clock()
                for bid in list(self._active):
                    self._poll(bid)
            self.sleep(1.0)
        with self._lock:
            left = self._queue + [p for ps in self._active.values() for p in ps]
            self._queue = []
        for p in left:
            if not p.future.done():
                p.future.set_exception(InfraError("batch dispatcher closed before the result arrived"))

    def _log(self, rec: dict) -> None:
        with self._lock, self.log_path.open("a") as f:
            f.write(json.dumps({"ts": time.time(), **rec}) + "\n")

    def _submit(self, batch: list[_Pending]) -> None:
        groups: dict[tuple[str, str], list[_Pending]] = {}
        for p in batch:
            groups.setdefault((p.spec.model, p.spec.provider), []).append(p)
        for (model, provider), ps in groups.items():
            requests_ = []
            for p in ps:
                body = {k: v for k, v in p.body.items() if k not in ("model", "provider")}
                requests_.append({"custom_id": p.custom_id, "body": body})
            payload = {"endpoint": "/v1/chat/completions", "model": model,
                       "provider": {"only": [provider], "allow_fallbacks": False},
                       "completion_window": "24h", "requests": requests_}
            status, data = self.http("POST", "/batches", payload)
            if status in (200, 201, 202) and data.get("id"):
                with self._lock:
                    self._active[data["id"]] = ps
                self._log({"event": "submitted", "batch_id": data["id"], "model": model, "provider": provider,
                           "n": len(ps), "custom_ids": [p.custom_id for p in ps]})
                continue
            self._log({"event": "submit_failed", "model": model, "n": len(ps), "status": status,
                       "error": (data.get("error") or {}).get("message", "")[:300]})
            err = (TransientError(f"batch submit HTTP {status}: {data.get('error')}") if status in (0, 429)
                   or status >= 500 else HTTPError(status, json.dumps(data.get("error"))[:300]))
            for p in ps:
                p.future.set_exception(err)

    def _poll(self, bid: str) -> None:
        status, data = self.http("GET", f"/batches/{bid}", None)
        if status != 200 or data.get("status") not in TERMINAL:
            return
        with self._lock:
            ps = self._active.pop(bid)
        usage = data.get("usage") or {}
        with self._lock:
            self.charged_usd += float(usage.get("cost") or 0.0)
        self._log({"event": "finished", "batch_id": bid, "status": data["status"],
                   "request_counts": data.get("request_counts"), "usage": usage, "error": data.get("error")})
        results = {r.get("custom_id"): r for r in data.get("results") or []}
        for p in ps:
            r = results.get(p.custom_id)
            if data["status"] != "completed" or r is None:
                p.future.set_exception(TransientError(f"batch {bid} {data['status']}: no result for {p.custom_id}"))
            elif r.get("error") or not r.get("response"):
                err = r.get("error") or {}
                code = int(err.get("code") or (r.get("response") or {}).get("status_code") or 0)
                p.future.set_exception(TransientError(f"batch request error {code}: {err}") if code in (0, 429)
                                       or code >= 500 else HTTPError(code, json.dumps(err)[:300]))
            else:
                p.future.set_result(self._complete(r["response"].get("body") or {}, p.spec))

    def _complete(self, body: dict, spec: ModelSpec) -> dict:
        body = dict(body)
        usage = dict(body.get("usage") or {})
        if usage.get("cost") is None and usage:
            usage["cost"] = self.price_factor * (spec.price_prompt * float(usage.get("prompt_tokens") or 0)
                                                 + spec.price_completion * float(usage.get("completion_tokens") or 0))
            usage["cost_estimated"] = True
            with self._lock:
                self.estimated_usd += usage["cost"]
        body["usage"] = usage
        if not body.get("provider"):
            body["provider"] = spec.provider
            body["provider_from_batch_pin"] = True
        return body
