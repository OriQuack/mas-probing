#!/usr/bin/env python
"""Render a run directory as one readable transcript, in time order, for trace labelling.

  python scripts/render_trace.py RUN_DIR [RUN_DIR ...] [--out-dir DIR] [--max-chars 20000]

For each run: the run header (task, condition, status, final answer, cost), then every orchestrator action,
checkpoint, refinement step and worker call, with each model request's new input messages (system prompts,
instructions, tool results) and its output (text and tool calls). Image data is replaced by a placeholder.
Page-reader calls inside `read_url` (tools v3) are shown short: the start and end of the request (the end holds
the question) and the reader's answer; the full page text is in messages.jsonl (hash given).
Reads only the run directory (never ground truth), so it is safe to give its output to labellers.
"""


from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

READER_HEAD, READER_TAIL = 600, 400  # characters of a page-reader request shown in the transcript


def _load(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.open() if line.strip()]


def _clip(s: str, n: int) -> str:
    s = s or ""
    return s if len(s) <= n else s[:n] + f"\n[... {len(s) - n} more characters not shown in this transcript ...]"


def _content_text(content, n: int) -> str:
    if isinstance(content, str):
        return _clip(content, n)
    parts = []
    for p in content or []:
        if p.get("type") == "text":
            parts.append(_clip(p.get("text", ""), n))
        elif p.get("type") == "image_url":
            url = (p.get("image_url") or {}).get("url", "")
            parts.append("[image: data URL]" if url.startswith("data:") else f"[image: {url}]")
        else:
            parts.append(f"[{p.get('type')}]")
    return "\n".join(parts)


def _turn_key(content, tool_calls) -> str:
    calls = [(tc["function"]["name"], tc["function"]["arguments"]) for tc in tool_calls or []]
    return json.dumps([content or "", calls], ensure_ascii=False)


def _where(r: dict) -> str:
    keys = ("stage", "delegation", "role", "worker", "scratch")
    return " ".join(f"{k}={r[k]}" for k in keys if r.get(k) is not None)


def render(run_dir: Path, max_chars: int) -> str:
    info = json.loads((run_dir / "run.json").read_text())
    msgs = {r["h"]: r["m"] for r in _load(run_dir / "messages.jsonl")}
    items = []
    for r in _load(run_dir / "events.jsonl"):
        items.append((r["ts"], 0, "event", r))
    for r in _load(run_dir / "llm_calls.jsonl"):
        if r.get("status") != "started":
            items.append((r["ts"], 1, "llm", r))
    items.sort(key=lambda x: (x[0], x[1]))

    out = [f"# Run {run_dir.name}", ""]
    out.append(f"- task_id: {info['task_id']} (level {info.get('level')})")
    out.append(f"- mode: {info.get('mode')}, label: {info.get('label')}, condition: {info.get('condition')}, "
               f"refine_at: {info.get('refine_at')}")
    if info.get("restored_from"):
        out.append(f"- restored from: {info['restored_from']} (delegation {info.get('restored_delegation')}); "
                   f"override: {info.get('override')} ({info.get('override_source')})")
    cfg = info.get("config") or {}
    out.append(f"- pool: {(cfg.get('pool') or {}).get('name')}; orchestrator: {cfg.get('orchestrator_model')}; "
               f"refiner model: {cfg.get('refiner_model')}")
    out.append(f"- status: {info.get('status')}; delegations: {info.get('n_delegations')}; "
               f"forced finish: {info.get('forced_finish')}")
    c = info.get("counters") or {}
    out.append(f"- counters: llm_calls={c.get('llm_calls')} tool_calls={c.get('tool_calls')} "
               f"worker_calls={c.get('worker_calls')} cost_usd={c.get('cost_usd')} wall_s={c.get('wall_s')}")
    if info.get("error"):
        out.append(f"- error: {info['error']}")
    out.append(f"- FINAL ANSWER: {info.get('final_answer')!r}")
    out.append("")

    shown: set[str] = set()
    outputs: set[str] = set()
    for _, _, kind, r in items:
        if kind == "event":
            ev = r["event"]
            if ev == "action":
                out.append(f"## [event] orchestrator action at delegation {r.get('delegation')}: {r.get('action')}"
                           + (" (forced finish)" if r.get("forced") else ""))
                if r.get("invalid_before"):
                    out.append(f"(invalid replies before this action, each answered with error feedback: "
                               f"{r['invalid_before']})")
                if r.get("rationale"):
                    out.append(f"rationale: {_clip(r['rationale'], max_chars)}")
                if r.get("action") == "delegate":
                    out.append(f"role: {r.get('worker_id')}")
                    out.append(f"instruction:\n<<<\n{r.get('instruction')}\n>>>")
                else:
                    out.append(f"answer: {r.get('answer')!r}")
            elif ev == "delegation":
                out.append(f"## [event] delegation {r.get('delegation')} -> {r.get('worker')} (role {r.get('role')}); "
                           f"refiner {r.get('refiner')}: {r.get('refine_status')}, changed={r.get('changed')}, "
                           f"connected={r.get('connected')}")
                if r.get("changed"):
                    out.append(f"FINAL instruction sent to the worker:\n<<<\n{r.get('final')}\n>>>")
            elif ev in ("report", "refine_worker_call"):
                out.append(f"## [event] {ev} {_where(r)}: status={r.get('status')}, tool calls={r.get('n_tool_calls')}")
            elif ev == "checkpoint":
                out.append(f"## [event] checkpoint d{r.get('delegation')}")
            else:
                rest = {k: v for k, v in r.items() if k not in ("ts", "event")}
                out.append(f"## [event] {ev}: {_clip(json.dumps(rest, ensure_ascii=False, default=str), 3000)}")
            out.append("")
            continue
        if r.get("component") == "reader":
            out.append(f"### page-reader call {r.get('call_id')} inside tool call #{r.get('tool_call')} "
                       f"[{_where(r)}] model={r.get('model_key')} status={r.get('status')} "
                       f"finish={r.get('finish_reason')}")
            for h in r.get("messages") or []:
                text = _content_text(msgs.get(h, {}).get("content"), 10**9)
                if len(text) > READER_HEAD + READER_TAIL:
                    text = (text[:READER_HEAD] + f"\n[... {len(text) - READER_HEAD - READER_TAIL} characters of page "
                            f"text not shown; full request: messages.jsonl h={h} ...]\n" + text[-READER_TAIL:])
                out.append("--- request (page text + question):")
                out.append(text)
            out.append(f"--- ERROR: {r.get('error')}" if r.get("status") == "error" else "--- output:")
            if r.get("status") != "error":
                out.append(_clip(r.get("output") or "", max_chars))
            u = r.get("usage") or {}
            out.append(f"(tokens in/out {u.get('prompt_tokens')}/{u.get('completion_tokens')}, cost {u.get('cost')})")
            out.append("")
            continue
        out.append(f"### LLM call {r.get('call_id')} [{_where(r)}] model={r.get('model_key')} "
                   f"status={r.get('status')} finish={r.get('finish_reason')}")
        for h in r.get("messages") or []:
            if h in shown:
                continue
            shown.add(h)
            m = msgs.get(h, {})
            role = m.get("role")
            if role == "assistant" and _turn_key(m.get("content"), m.get("tool_calls")) in outputs:
                continue  # this model's own earlier output, printed above
            head = f"--- input message ({role}"
            if role == "tool":
                head += f", tool_call_id={m.get('tool_call_id')}"
            out.append(head + ")")
            out.append(_content_text(m.get("content"), max_chars))
            for tc in m.get("tool_calls") or []:
                out.append(f"[tool call] {tc['function']['name']}({tc['function']['arguments']})")
        if r.get("status") == "error":
            out.append(f"--- ERROR: {r.get('error')}")
        else:
            if r.get("reasoning"):
                out.append("--- reasoning (as returned by the API):")
                out.append(_clip(r["reasoning"], max_chars))
            out.append("--- output:")
            if r.get("output"):
                out.append(_clip(r["output"], max_chars))
            for tc in r.get("tool_calls") or []:
                out.append(f"[tool call] {tc['function']['name']}({_clip(tc['function']['arguments'], 4000)})")
            outputs.add(_turn_key(r.get("output"), r.get("tool_calls")))
        u = r.get("usage") or {}
        out.append(f"(tokens in/out {u.get('prompt_tokens')}/{u.get('completion_tokens')}, cost {u.get('cost')})")
        out.append("")
    tools = [t for t in _load(run_dir / "tool_calls.jsonl") if t.get("status") != "started"]
    if tools:
        out.append("## Tool call summary (tool_calls.jsonl)")
        for t in tools:
            extra = ""
            if t.get("error"):
                extra = f" error={_clip(str(t['error']), 300)}"
            if t.get("sandbox_denied"):
                extra += f" sandbox_denied={t['sandbox_denied']}"
            if rd := t.get("reader"):
                extra += (f" reader(parts={rd.get('n_parts')}, source_chars={rd.get('source_chars')}, "
                          f"usd={rd.get('usd')})")
            out.append(f"- [{_where(t)}] {t.get('tool')} #{t.get('call_no')} {json.dumps(t.get('args'), ensure_ascii=False)[:300]}"
                       f" -> {t.get('status')} backend={t.get('backend')}{extra}")
    refine_dir = run_dir / "refine"
    for f in sorted(refine_dir.glob("d*.json")) if refine_dir.exists() else []:
        out.append("")
        out.append(f"## Refinement record {f.name}")
        out.append(_clip(f.read_text(), max_chars * 2))
    return "\n".join(out) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("run_dirs", nargs="+")
    ap.add_argument("--out-dir", default=None, help="write <out-dir>/<name>.md instead of stdout")
    ap.add_argument("--name", default=None, help="file name (single run only); default: the run dir name")
    ap.add_argument("--max-chars", type=int, default=60000)
    a = ap.parse_args()
    for d in map(Path, a.run_dirs):
        text = render(d, a.max_chars)
        if a.out_dir:
            o = Path(a.out_dir)
            o.mkdir(parents=True, exist_ok=True)
            (o / f"{a.name or d.name}.md").write_text(text)
        else:
            sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
