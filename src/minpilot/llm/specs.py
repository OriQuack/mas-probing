"""Model keys. A key names one model with fixed settings; everything a key sends is its `identity()`, which is
recorded per run and stored in checkpoints (a restore refuses if it differs).

Ported from the previous pilot's `models/openrouter.py` (the OpenRouter part only; no camel). What one key fixes:
- a dated model id where one exists;
- exactly one provider, no fallbacks, `require_parameters`, `data_collection: deny` (a base provider slug matches
  the provider's default endpoints, never its service tiers);
- the generation cap (`max_tokens`), sampling, and for reasoning models a fixed `reasoning` setting;
- `tools_allowed`: whether requests may carry tools. On OpenAI's own Chat Completions API, GPT-6 Luna allows
  function calling only at effort `none` (reasoning with tools needs the Responses API). Through OpenRouter's Chat
  Completions, tools + effort high work (checked live 2026-10-09: reasoning tokens > 0 with tools at medium/high,
  multi-turn tool loops with encrypted reasoning re-sent); the responses look like OpenAI Responses API output
  (`native_finish_reason: completed`, `reasoning.encrypted`), i.e. OpenRouter appears to translate the request.
  This is undocumented OpenRouter behaviour: runs record reasoning tokens per stage and warn when an effort-high
  stage shows none (harness, decision M4).
No OpenRouter response caching and no web plugins: reruns must resample, and no uncontrolled search tool.
"""

from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class ModelSpec:
    key: str
    model: str
    provider: str
    max_tokens: int
    context_window: int = 128_000
    sampling: dict[str, Any] = field(default_factory=dict)
    reasoning: dict[str, Any] | None = None
    preserve_reasoning: bool = False  # keep `reasoning_details` on assistant messages (Gemini 3 needs them back)
    tools_allowed: bool = True
    # Not part of the identity (they do not change requests): list prices (USD per token) for the cost
    # reservation, and how the model counts image tokens.
    price_prompt: float = 0.0
    price_completion: float = 0.0
    image_tokens: str = "fixed:2000"
    note: str = ""

    def routing(self) -> dict:
        return {"only": [self.provider], "allow_fallbacks": False, "require_parameters": True,
                "data_collection": "deny"}

    def identity(self) -> dict:
        d = asdict(self)
        for k in ("note", "price_prompt", "price_completion", "image_tokens"):
            d.pop(k)
        return {"platform": "openrouter", **d, "routing": self.routing()}


MAX_TOKENS = 8192
MAX_TOKENS_REASONING = 32768

SPECS: dict[str, ModelSpec] = {
    "luna-high": ModelSpec(
        key="luna-high", model="openai/gpt-6-luna-20260922", provider="openai", max_tokens=MAX_TOKENS_REASONING,
        reasoning={"effort": "high"}, preserve_reasoning=True, price_prompt=1e-7, price_completion=5e-7,
        image_tokens="patch:1.2",
        note="GPT-6 Luna at effort high: every role since 2026-10-09 (orchestrator, refiner, workers, page reader; "
             "decision M1). Tools allowed through OpenRouter (see tools_allowed above). Workers re-send the "
             "encrypted reasoning of their earlier turns; the orchestrator keeps only its action JSON."),
    "luna": ModelSpec(
        key="luna", model="openai/gpt-6-luna-20260922", provider="openai", max_tokens=MAX_TOKENS,
        reasoning={"effort": "none"}, preserve_reasoning=True, price_prompt=1e-7, price_completion=5e-7,
        image_tokens="patch:1.2",
        note="GPT-6 Luna at effort none (0 reasoning tokens). The worker default until 2026-10-09 (it was believed "
             "to be the only effort with function calling); kept for comparisons. Sampling fixed by OpenAI "
             "(stochastic). Knowledge cutoff 2026-05-18."),
    "gpt4o": ModelSpec(
        key="gpt4o", model="openai/gpt-4o-2024-08-06", provider="openai", max_tokens=MAX_TOKENS,
        context_window=128_000 - MAX_TOKENS - 8192, sampling={"temperature": 1.0, "top_p": 1.0},
        price_prompt=2.5e-6, price_completion=1e-5, image_tokens="tile",
        note="GPT-4o 2024-08-06 (knowledge cutoff 2023-10, before GAIA's release)."),
    "gemini": ModelSpec(
        key="gemini", model="google/gemini-3.1-flash-lite", provider="google-ai-studio", max_tokens=MAX_TOKENS,
        sampling={"temperature": 1.0, "top_p": 0.95}, reasoning={"effort": "minimal"}, preserve_reasoning=True,
        price_prompt=2.5e-7, price_completion=1.5e-6, image_tokens="fixed:1500",
        note="Gemini 3.1 Flash-Lite at effort minimal; reasoning_details are re-sent (thought signatures)."),
}


def get_spec(key: str) -> ModelSpec:
    if key not in SPECS:
        raise KeyError(f"unknown model key {key!r}; known: {tuple(SPECS)}")
    return SPECS[key]


# -- cost reservation ---------------------------------------------------------------------------
MESSAGE_OVERHEAD_TOKENS = 16
UNKNOWN_IMAGE_TOKENS = 100_000


def image_size(url: str) -> tuple[int, int] | None:
    if not url.startswith("data:") or "," not in url:
        return None
    import base64
    import io

    from PIL import Image

    try:
        return Image.open(io.BytesIO(base64.b64decode(url.split(",", 1)[1]))).size
    except Exception:
        return None


def image_token_bound(scheme: str, size: tuple[int, int] | None, detail: str = "auto") -> int:
    if scheme.startswith("fixed:"):
        return int(scheme.split(":")[1])
    if size is None:
        return UNKNOWN_IMAGE_TOKENS
    w, h = size
    if scheme.startswith("patch:"):
        if detail == "low":
            w, h = min(w, 512), min(h, 512)
        return math.ceil(math.ceil(w / 32) * math.ceil(h / 32) * float(scheme.split(":")[1])) + 1
    if scheme == "tile":
        if detail == "low":
            return 85
        f = min(1.0, 2048 / max(w, h))
        w, h = w * f, h * f
        f = min(1.0, 768 / min(w, h))
        w, h = w * f, h * f
        return 85 + 170 * math.ceil(w / 512) * math.ceil(h / 512)
    raise ValueError(f"unknown image token scheme {scheme!r}")


def input_token_bound(body: dict, image_scheme: str) -> int:
    """Upper bound of a request's input tokens: UTF-8 bytes of its JSON (every BPE token covers >= 1 byte), with
    each image counted by the model's image scheme instead of its base64 bytes."""
    image_tokens = 0

    def strip(x):
        nonlocal image_tokens
        if isinstance(x, dict):
            if x.get("type") == "image_url":
                iu = x.get("image_url") or {}
                image_tokens += image_token_bound(image_scheme, image_size(iu.get("url", "")), iu.get("detail", "auto"))
                return {"type": "image_url"}
            return {k: strip(v) for k, v in x.items()}
        if isinstance(x, list):
            return [strip(v) for v in x]
        return x

    msgs = strip(body.get("messages") or [])
    text = (json.dumps(msgs, ensure_ascii=False) + json.dumps(body.get("tools") or [], ensure_ascii=False)
            + json.dumps(body.get("response_format") or {}, ensure_ascii=False))
    return len(text.encode()) + image_tokens + MESSAGE_OVERHEAD_TOKENS * (len(msgs) + 1)


def reserve_usd(spec: ModelSpec, body: dict) -> float:
    return input_token_bound(body, spec.image_tokens) * spec.price_prompt + spec.max_tokens * spec.price_completion
