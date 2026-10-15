"""Instruction selection by cross-worker answer agreement on MoNaCo, oracle setting (standalone experiment).

Each worker answers the whole question from the oracle documents in free text ending in an `Answers:` line; there
are no nodes and no gold decomposition. Candidates are naive and three method-grounded instructions per question,
authored from the question text only and imported (no generation model): decompose (Least-to-Most), clarify
(Metacognitive Prompting, interpretation only) and structured (Tab-CoT). Workers, repeats, the selection rule and its
seeded tie break are those of `instruction_selection`. Per question, one `luna-low` call splits the answer lines of
all its probes into items (each item checked by code to be a verbatim piece of its line), one more groups the items,
and agreement is item F1 between answers (exact normalized item sets are kept as a diagnostic); scoring uses the
published MoNaCo judge prompts on the answer line instead of exact gold comparison.
"""
from __future__ import annotations

import hashlib
import random
import re
import statistics
import unicodedata
from decimal import Decimal

from minpilot.llm.client import LLMClient, json_schema_format
from minpilot.runtime.trace import BudgetExceeded
from perturbation_consistency import instruction_selection as ins

VERSION = "monaco-instruction-selection-v7"
NORMALIZATION_VERSION = 1
CLUSTER_VERSION = 3
SPLIT_VERSION = 1
CANDIDATES = ("naive", "decompose", "clarify", "structured")
WORKERS, REPEATS, EXECUTOR, MAX_WORDS = ins.WORKERS, ins.REPEATS, ins.EXECUTOR, ins.MAX_WORDS
JUDGE = "luna-high"
CLUSTERER = SPLITTER = "luna-low"
ERRORS = ins.ERRORS
# Judge, split and cluster calls matter for every slot: up to 3 retries both for an invalid reply within a call
# (TRIES) and for an errored call on rerun (MAX_ATTEMPTS). A probe that errored, hit the length limit or gave no
# answer line is retried once (PROBE_RETRY, PROBE_ATTEMPTS). Executions keep "length" and "no_answer" as results.
TRIES = MAX_ATTEMPTS = 4
PROBE_RETRY, PROBE_ATTEMPTS = ("error", "length", "no_answer"), 2


def validate_candidates(value: object) -> dict[str, str]:
    """Exactly the three non-naive candidates, each 1..MAX_WORDS words, all distinct; naive is the empty
    instruction."""
    if not isinstance(value, dict) or set(value) != set(CANDIDATES[1:]):
        raise ValueError(f"expected exactly {', '.join(CANDIDATES[1:])}")
    out = {"naive": ""}
    for key in CANDIDATES[1:]:
        text = value[key]
        if not isinstance(text, str) or not 1 <= len(text.split()) <= MAX_WORDS:
            raise ValueError(f"{key}: expected 1..{MAX_WORDS} words")
        out[key] = text.strip()
    if len(set(out.values())) != len(out):
        raise ValueError("candidate instructions must be distinct")
    return out


TASK_PROMPT = """Use the documents below to answer the question.

Documents:

{documents}

Question: {question}"""
ANSWER_FORMAT = """End your response with one final line in this form:
Answers: <your final answer>
Put only the final answer on that line, without explanation. If nothing qualifies, write "Answers: none"."""


def task_prompt(documents: list[str], question: str, instruction: str) -> str:
    body = TASK_PROMPT.format(documents="\n\n".join(documents), question=question)
    return f"{body}\n\n{instruction}\n\n{ANSWER_FORMAT}" if instruction else f"{body}\n\n{ANSWER_FORMAT}"


# ---- answers and equivalence ----

ANSWER_MARKER = re.compile(r"(?im)^\W*(?:final\s+)?answers?\W*:")
BULLET = re.compile(r"^\s*(?:[-*•]|\d+[.)])\s+")
NUMBER = re.compile(r"^[+-]?(\d{1,3}(,\d{3})+|\d+)(\.\d+)?%?$")
TRUE, FALSE = {"yes", "true"}, {"no", "false"}


def answer_line(content: str) -> str | None:
    """Text of the last `Answers:` line, without markdown emphasis and with whitespace collapsed. When the marker
    line is otherwise empty, the following lines up to a blank line (bullets removed) are joined with "; ".
    None if there is no marker or no text after it."""
    hits = list(ANSWER_MARKER.finditer(content or ""))
    if not hits:
        return None
    first, _, after = content[hits[-1].end():].partition("\n")
    text = first.strip().strip("*").strip()
    if not text:
        block = []
        for line in after.splitlines():
            if not line.strip():
                if block:
                    break
                continue
            block.append(BULLET.sub("", line).strip().strip("*").strip())
        text = "; ".join(b for b in block if b)
    return " ".join(text.split()) or None


def normalize_value(v) -> tuple:
    """Numbers keep sign and decimal point; only thousands commas are dropped and `%` is kept as a marker.
    Strings are NFKC, casefolded and whitespace-collapsed; inner punctuation is kept."""
    if isinstance(v, bool):
        return ("bool", v)
    if isinstance(v, (int, float)):
        return ("num", Decimal(str(v)).normalize(), False)
    s = " ".join(unicodedata.normalize("NFKC", v).split()).casefold()
    if s in TRUE or s in FALSE:
        return ("bool", s in TRUE)
    if NUMBER.match(s):
        return ("num", Decimal(s.rstrip("%").replace(",", "")).normalize(), s.endswith("%"))
    return ("str", s)


def answer_key(answer: list) -> frozenset:
    """An answer is the set of its items; a multi-value item is a tuple, a one-value item is that value."""
    def item(x):
        if isinstance(x, list):
            return normalize_value(x[0]) if len(x) == 1 else tuple(normalize_value(y) for y in x)
        return normalize_value(x)
    return frozenset(item(x) for x in answer)


def probe_answers(records: list[dict]) -> list[dict | None]:
    """Nine slot records in worker registration order, then sample order; absent slots are None."""
    by = {}
    for r in records:
        key = (r["worker"], r["sample"])
        if key in by or key[0] not in WORKERS or key[1] not in range(REPEATS):
            raise ValueError(f"invalid or duplicate probe slot: {key}")
        by[key] = r
    return [by.get((w, k)) for w in WORKERS for k in range(REPEATS)]


def item_text(x: str) -> str:
    """One answer item as clusterer input, whitespace collapsed."""
    return " ".join(x.split())


def slot_items(record: dict | None, lines: dict[str, dict]) -> list[str] | None:
    """Items of a completed probe from the split of its answer line (`lines`: line -> split entry); [] when the
    line says nothing qualifies; None for a failed slot, a line without an answer or a split that failed the check."""
    if not record or record.get("status") != "ok" or not record.get("answer_line"):
        return None
    entry = lines[record["answer_line"]]
    if entry["status"] == "empty":
        return []
    return [item_text(x) for x in entry["items"]] if entry["status"] == "answer" else None


def agreement(keys: list) -> dict:
    """Exact-match diagnostic (LongCoT's rule): largest equal-answer group over nine; None is a failed slot."""
    n = len(WORKERS) * REPEATS
    if len(keys) != n:
        raise ValueError(f"expected {n} probe slots")
    groups: dict = {}
    for k in keys:
        if k is not None:
            groups[k] = groups.get(k, 0) + 1
    support = max(groups.values(), default=0)
    matches = sum(keys[i] is not None and keys[i] == keys[j]
                  for i in range(n) for j in range(i + 1, n) if i // REPEATS != j // REPEATS)
    cross_pairs = n * (n - REPEATS) // 2
    return {"support": support, "of": n, "agreement": support / n,
            "cross_worker_agreement": matches / cross_pairs, "valid_answers": sum(k is not None for k in keys),
            "distinct_answers": len(groups)}


def rule_agreement(records: list[dict], lines: dict[str, dict]) -> dict:
    """Diagnostic only: exact agreement over normalized item sets (version NORMALIZATION_VERSION)."""
    return agreement([None if (items := slot_items(r, lines)) is None else answer_key(items)
                      for r in probe_answers(records)])


def item_sets(records: list[dict], lines: dict[str, dict], labels: dict[str, str | None]) -> list[frozenset | None]:
    """Nine slots as sets of item groups. Items marked as no answer are dropped; a slot whose items are all
    no answer, like a failed slot, is None. An empty answer is the empty set."""
    out = []
    for r in probe_answers(records):
        items = slot_items(r, lines)
        groups = None if items is None else {labels[t] for t in items}
        out.append(None if groups is None or (items and groups == {None}) else frozenset(groups - {None}))
    return out


def f1(a: frozenset | None, b: frozenset | None) -> float:
    """Item F1 between two answers; a failed slot agrees with nothing, two empty answers agree."""
    if a is None or b is None:
        return 0.
    if not a and not b:
        return 1.
    return 2 * len(a & b) / (len(a) + len(b))


def set_agreement(sets: list[frozenset | None]) -> dict:
    """Primary: the most central answer's mean item F1 with all nine slots, itself included, so a one-item
    answer reduces to LongCoT's largest equal-answer group over nine. Cross-worker: mean item F1 over pairs from
    different workers. Failed slots count as zero."""
    n = len(WORKERS) * REPEATS
    if len(sets) != n:
        raise ValueError(f"expected {n} probe slots")
    central = max((sum(f1(a, b) for b in sets) / n for a in sets if a is not None), default=0.)
    cross = [f1(sets[i], sets[j]) for i in range(n) for j in range(i + 1, n) if i // REPEATS != j // REPEATS]
    valid = [a for a in sets if a is not None]
    return {"agreement": round(central, 12), "cross_worker_agreement": round(sum(cross) / len(cross), 12),
            "support": max((valid.count(a) for a in valid), default=0), "of": n,
            "valid_answers": len(valid), "distinct_answers": len(set(valid))}


# ---- equivalence: one clusterer call per question over the distinct items of all of its probe answers ----

ITEM_CLUSTER_PROMPT = """Below are answer items that several solvers gave to the same question; each solver's
answer is a list of such items. Group the items that refer to the same thing.

Two items are the same when they name the same entity, value or yes/no outcome, even if they differ in wording,
spelling, abbreviation, number formatting or units, or if one adds details such as dates, figures or
explanations. Two items are different when one is broader or narrower than the other (for example a category and
one member of it, or a general term and one specific instance of it), or when they give different values. Numbers
are the same only when they denote the same value, not when they are merely close. An item that holds several
values (such as a name together with a date) is the same as another item only when all of its values are the
same. Use general knowledge only to recognize that two names refer to the same thing. Do not judge which item is
correct. Put items that are not answers (such as "unknown", "none found" or a refusal) under no_answer.

Return JSON: "groups" is a list of groups, each a list of item ids; "no_answer" lists the ids that are not
answers. Every item id must appear exactly once.

Question: {question}

Items:
{entries}"""
# Whole-answer grouping of cluster version 1, kept for scripts/validate_monaco_answer_clustering.py.
ANSWER_CLUSTER_PROMPT = """Below are final answers that several solvers gave to the same question. Group the answers that
give the same final answer to the question.

Two answers are the same when they name the same entities, values or yes/no outcome, even if they differ in
wording, spelling, abbreviation, item order, list or JSON formatting, number formatting or units, or if one adds
supporting details the question does not ask for (such as figures, dates or explanations). Two answers are
different when, ignoring such details, they contain a different set of items, or a different count, value or
yes/no outcome. Numbers are the same only when they denote the same value, not when they are merely close.
Use general knowledge only to recognize that two names refer to the same entity. Do not judge which answer is
correct. An empty list ([]) is an answer meaning that nothing qualifies. Put answers that decline to answer, say
the information is unavailable, or give no definite answer under no_answer.

Return JSON: "groups" is a list of groups, each a list of answer ids; "no_answer" lists the ids that give no
definite answer. Every answer id must appear exactly once.

Question: {question}

Answers:
{entries}"""
CLUSTER_SCHEMA = {
    "type": "object",
    "properties": {"groups": {"type": "array", "items": {"type": "array", "items": {"type": "string"}}},
                   "no_answer": {"type": "array", "items": {"type": "string"}}},
    "required": ["groups", "no_answer"], "additionalProperties": False,
}


def cluster_prompt(question: str, texts: list[str], seed: str,
                   template: str = ITEM_CLUSTER_PROMPT) -> tuple[str, dict[str, str]]:
    """Distinct texts in seeded order with neutral ids; solver, worker and candidate are not shown."""
    unique = sorted(set(texts))
    random.Random(seed).shuffle(unique)
    ids = {f"A{i + 1}": t for i, t in enumerate(unique)}
    return template.format(question=question, entries="\n".join(f"{i}: {t}" for i, t in ids.items())), ids


def parse_clusters(value: object, ids: dict[str, str]) -> dict[str, str | None]:
    """Text -> group label (`g0`, `g1`, ...), or None for no answer; the reply must partition the ids."""
    if not isinstance(value, dict) or not isinstance(value.get("groups"), list) \
            or not isinstance(value.get("no_answer"), list):
        raise ValueError("cluster reply is not the requested object")
    listed = [i for g in value["groups"] for i in g] + list(value["no_answer"])
    if sorted(listed) != sorted(ids) or any(not g for g in value["groups"]):
        raise ValueError("cluster reply does not list every id exactly once")
    labels = {ids[i]: f"g{n}" for n, g in enumerate(value["groups"]) for i in g}
    return labels | {ids[i]: None for i in value["no_answer"]}


def cluster(client: LLMClient, question: str, texts: list[str], seed: str, tries: int = TRIES,
            template: str = ITEM_CLUSTER_PROMPT) -> dict:
    """Group texts; an invalid reply is asked again, `tries` calls in all. No call when there is no text."""
    prompt, ids = cluster_prompt(question, texts, seed, template)
    if not ids:
        return {"status": "ok", "attempts": 0, "ids": {}, "labels": {}}
    last = None
    for attempt in range(tries):
        try:
            reply = client.chat([{"role": "user", "content": prompt}],
                                response_format=json_schema_format("answer_groups", CLUSTER_SCHEMA))
            if reply.finish_reason == "length":
                raise ValueError("truncated cluster reply")
            return {"status": "ok", "attempts": attempt + 1, "ids": ids, "reply": reply.parsed,
                    "labels": parse_clusters(reply.parsed, ids)}
        except ERRORS as exc:
            last = exc
            if isinstance(exc, BudgetExceeded):
                break
    return {"status": "budget" if isinstance(last, BudgetExceeded) else "error", "ids": ids, "error": str(last)[:300]}


# ---- items: one splitter call per question over the distinct answer lines of all of its probes ----

SPLIT_PROMPT = """Below are final answer lines that several solvers gave to the same question. Split each line into
its answer items.

An item is one answer to the question: one entity, value or yes/no outcome. When the question asks for several
values per answer (for example a name and a date), an item is the whole group of those values. Copy every item
exactly as it is written in the line, as one unbroken piece of the line, and keep the details that belong to it
(such as a note in parentheses) inside the item. Every part of the line must be inside an item except the
separators between items: punctuation such as commas, semicolons and slashes, and the words "and" or "or". Do not
split a single name that contains a comma or "and". Do not judge which items are correct.

For each line give a status: "answer" when the line gives items, "empty" when it says that nothing qualifies, and
"no_answer" when it declines to answer or says the information is unavailable. Lines with status "empty" or
"no_answer" have no items.

Return JSON: "lines" is a list with one object per line id, each with "id", "status" and "items".

Question: {question}

Lines:
{entries}"""
SPLIT_SCHEMA = {
    "type": "object",
    "properties": {"lines": {"type": "array", "items": {
        "type": "object",
        "properties": {"id": {"type": "string"}, "status": {"type": "string", "enum": ["answer", "empty", "no_answer"]},
                       "items": {"type": "array", "items": {"type": "string"}}},
        "required": ["id", "status", "items"], "additionalProperties": False}}},
    "required": ["lines"], "additionalProperties": False,
}
SEPARATOR = re.compile(r"[\s,;:/|.·•()\[\]{}\"'*&+\-–—]+")
SEPARATOR_WORDS = {"and", "or"}


def items_cover(line: str, items: list[str]) -> bool:
    """Code check of a split: the items occur in the line in order, as verbatim pieces (whitespace collapsed),
    and what they leave uncovered is only punctuation and the words "and" or "or"."""
    text, pos, rest = " ".join(line.split()), 0, []
    for item in items:
        item = " ".join(item.split())
        at = text.find(item, pos) if item else -1
        if at < 0:
            return False
        rest.append(text[pos:at])
        pos = at + len(item)
    rest.append(text[pos:])
    words = [w for piece in rest for w in SEPARATOR.sub(" ", piece).split()]
    return bool(items) and all(w.casefold() in SEPARATOR_WORDS for w in words)


def parse_split(value: object, ids: dict[str, str]) -> dict[str, dict]:
    """Line -> {"status", "items"}. The reply must give each id once; a line whose items fail `items_cover`, or
    an empty or no-answer line with items, gets status "invalid"."""
    if not isinstance(value, dict) or not isinstance(value.get("lines"), list):
        raise ValueError("split reply is not the requested object")
    entries = value["lines"]
    if sorted(e.get("id") for e in entries if isinstance(e, dict)) != sorted(ids) or len(entries) != len(ids):
        raise ValueError("split reply does not list every id exactly once")
    out = {}
    for e in entries:
        status, items = e.get("status"), e.get("items")
        if status not in ("answer", "empty", "no_answer") or not isinstance(items, list) \
                or not all(isinstance(x, str) for x in items):
            raise ValueError(f"invalid split entry: {e.get('id')}")
        line = ids[e["id"]]
        valid = items_cover(line, items) if status == "answer" else not items
        out[line] = {"status": status if valid else "invalid", "items": items}
    return out


def split(client: LLMClient, question: str, lines: list[str], seed: str, tries: int = TRIES) -> dict:
    """Split answer lines into items; a malformed reply or a line failing the code check is asked again, `tries`
    calls in all. After the last try, lines still failing the check stay "invalid" (their slots count as failed).
    No call without lines."""
    prompt, ids = cluster_prompt(question, lines, seed, SPLIT_PROMPT)
    if not ids:
        return {"status": "ok", "attempts": 0, "ids": {}, "lines": {}, "invalid": 0}
    last, best = None, None
    for attempt in range(tries):
        try:
            reply = client.chat([{"role": "user", "content": prompt}],
                                response_format=json_schema_format("answer_items", SPLIT_SCHEMA))
            if reply.finish_reason == "length":
                raise ValueError("truncated split reply")
            parsed = parse_split(reply.parsed, ids)
            best = {"status": "ok", "attempts": attempt + 1, "ids": ids, "reply": reply.parsed, "lines": parsed,
                    "invalid": sum(v["status"] == "invalid" for v in parsed.values())}
            if not best["invalid"]:
                return best
        except ERRORS as exc:
            last = exc
            if isinstance(exc, BudgetExceeded):
                break
    if best is not None:
        return best
    return {"status": "budget" if isinstance(last, BudgetExceeded) else "error", "ids": ids, "error": str(last)[:300]}


# ---- retries: append-only records, the last record of a slot counts ----



def latest(rows: list[dict], key) -> dict:
    """The last record per slot."""
    return {key(r): r for r in rows}


def pending(planned: list, rows: list[dict], key, retry: tuple = ("error",), attempts: int = MAX_ATTEMPTS) -> list:
    """Planned slots without a record, or whose last record has a `retry` status with attempts left. Budget stops
    are always retried; records with a `retry` status count toward `attempts`."""
    last, failed = latest(rows, key), {}
    for r in rows:
        if r.get("status") in retry:
            failed[key(r)] = failed.get(key(r), 0) + 1
    return [k for k in planned if k not in last or last[k].get("status") == "budget"
            or (last[k].get("status") in retry and failed.get(k, 0) < attempts)]


def pending_probes(planned: list, rows: list[dict], key) -> list:
    return pending(planned, rows, key, PROBE_RETRY, PROBE_ATTEMPTS)


def select(target_id: str, scores: dict[str, dict], seed: int = 0, *, cross: bool = False) -> dict:
    """`instruction_selection.select` over this module's candidates: the top score, ties broken uniformly by a
    seed derived from the version, the seed and the target."""
    field = "cross_worker_agreement" if cross else "agreement"
    top = max(scores[c][field] for c in CANDIDATES)
    tied = [c for c in CANDIDATES if scores[c][field] == top]
    rng = random.Random(hashlib.sha256(f"{VERSION}:{seed}:{target_id}".encode()).digest())
    return {"candidate": rng.choice(tied), "tied_candidates": tied, "score": top, "metric": field}


def solve(client: LLMClient, prompt: str) -> dict:
    try:
        reply = client.chat([{"role": "user", "content": prompt}])
        line = answer_line(reply.content)
        status = "length" if reply.finish_reason == "length" else "ok" if line is not None else "no_answer"
        return {"answer_line": line if status == "ok" else None, "content": reply.content, "status": status,
                "finish_reason": reply.finish_reason}
    except ERRORS as exc:
        return {"answer_line": None, "status": "budget" if isinstance(exc, BudgetExceeded) else "error",
                "error": str(exc)[:300]}


# ---- judging: the published MoNaCo judge prompts, verbatim ----

_JUDGE_HEAD = """Judge whether the following [response] to [question] is correct or not based on the precise and unambiguous [correct_answer] below.
[question]: {question}
[response]: '{response}'

Your judgment must be in the format and criteria specified below:

extracted_final_answer: The final exact answer extracted from the [response]. Put the extracted answer as ’None’ if there is no exact, final answer to extract from the response.

[correct_answer]: {correct_answer}

"""
_JUDGE_REASONING = """reasoning: Explain why the extracted_final_answer is correct or incorrect based on [correct_answer], focusing only on if there are meaningful differences between [correct_answer] and the extracted_final_answer. Do not comment on any background to the problem, do not attempt to solve the problem, do not argue for any answer different than [correct_answer], focus only on whether the answers match.

"""
SINGLE_JUDGE_PROMPT = _JUDGE_HEAD + _JUDGE_REASONING + """correct: Answer ’yes’ if extracted_final_answer matches the [correct_answer] given above, or is within a small margin of error for numerical problems, a margin of 1 to 3.5 percentage points is acceptable. Answer ’no’ otherwise, i.e. if there is any inconsistency, ambiguity, non-equivalency, or if the extracted answer is incorrect.

precision: Answer ’1’ if extracted_final_answer matches the [correct_answer] given above. Answer ’0’ otherwise, i.e. if there is any inconsistency, ambiguity, non-equivalency, or if the extracted answer is incorrect. In the case where [correct_answer] is a number or percentage, then answer with the following formula to compute the normalized similarity score: [1 - (abs([correct_answer] - extracted_final_answer) / max(abs([correct_answer]), abs(extracted_final_answer)))]

final precision: Extract the precision score from above, just the final score (number).
"""
# The published line ends in a space; it is written out so whitespace cleanup cannot drop it.
LIST_JUDGE_PROMPT = _JUDGE_HEAD + """final answer length: Provide the overall number of unique answers that appear in [response], not just the correct ones. Be sure to provide a number, not an estimate!""" + " \n\n" + _JUDGE_REASONING + """correct: Answer ’yes’ if extracted_final_answer matches the [correct_answer] given above, or is within a small margin of error for numerical problems, a margin of 1 to 5.5 percentage points is acceptable. Answer ’no’ otherwise, i.e. if there is any inconsistency, ambiguity, non-equivalency, or if the extracted answer is incorrect.

overlapping answers: List all of the answers in [response] that also appear in [correct_answer]. You can consider an answer from [response] to match with an answer in [correct_answer] if it is equivalent or is within a small margin of error for numerical problems, a margin of 1 to 5.5 percentage points is acceptable. List all of the [response] answer appearing in [correct_answer] with each answer delimited by '###'. If the number of overlapping answers is zero, output 'NULL'.
"""


def judge_kind(gold: list) -> str:
    """The published runs use the single-answer prompt exactly when the gold is one non-list value."""
    return "single" if len(gold) == 1 and not isinstance(gold[0], list) else "list"


def gold_text(gold: list) -> str:
    """As rendered in the published prompts: Python repr, a lone boolean as ['Yes'] / ['No']."""
    if judge_kind(gold) == "single" and isinstance(gold[0], bool):
        return "['Yes']" if gold[0] else "['No']"
    return str(gold)


def judge_response(record: dict) -> str:
    """What the judge reads of an execution: its final `Answers:` line, so items that the reasoning mentions or
    excludes are not counted; the full content only when there is no answer line."""
    if record.get("answer_line"):
        return "Answers: " + record["answer_line"]
    return record["content"]


def judge_prompt(question: str, response: str, gold: list) -> str:
    template = SINGLE_JUDGE_PROMPT if judge_kind(gold) == "single" else LIST_JUDGE_PROMPT
    return template.format(question=question, response=response, correct_answer=gold_text(gold))


FIELDS = ("extracted_final_answer", "final answer length", "reasoning", "correct", "precision",
          "final precision", "overlapping answers")
_FIELD = re.compile(r"(?im)^\s*\**(" + "|".join(re.escape(f) for f in FIELDS) + r")\**\s*:\s*")
_FLOAT = re.compile(r"[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?")


def _field(text: str, name: str) -> str | None:
    hits = list(_FIELD.finditer(text))
    for i in range(len(hits) - 1, -1, -1):
        if hits[i].group(1).lower() == name:
            end = hits[i + 1].start() if i + 1 < len(hits) else len(text)
            return text[hits[i].end():end]
    return None


def gold_length(gold: list) -> int:
    """The published recall denominator counts every value, so a row of k values counts k."""
    return sum(len(x) if isinstance(x, list) else 1 for x in gold)


def parse_judgement(text: str, gold: list) -> dict:
    """Scores as published: single = the judge's final precision; list = F1 with precision = overlaps /
    max(judged answer count, overlaps) and recall = min(overlaps, gold_length) / gold_length. Empty `###` items are
    not counted (the published scores counted a leading empty item as a match in 138 of 16,119 list judgements)."""
    if judge_kind(gold) == "single":
        n = _FLOAT.search(_field(text, "final precision") or "")
        if n is None:
            raise ValueError("judge reply without final precision")
        raw = float(n.group())
        return {"kind": "single", "raw_score": raw, "score": min(1., max(0., raw))}
    n = _FLOAT.search(_field(text, "final answer length") or "")
    overlap = _field(text, "overlapping answers")
    if n is None or overlap is None:
        raise ValueError("judge reply without answer length or overlapping answers")
    items = [x.strip() for x in overlap.split("###")]
    items = [x for x in items if x and x.upper() != "NULL"]
    correct = len(items)
    predicted = max(int(float(n.group())), correct)
    precision = correct / predicted if predicted else 0.
    recall = min(correct, gold_length(gold)) / gold_length(gold) if gold else 0.
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.
    return {"kind": "list", "num_correct": correct, "predicted": predicted, "gold_length": gold_length(gold),
            "precision": precision, "recall": recall, "score": f1}


def judge(client: LLMClient, question: str, response: str, gold: list, tries: int = TRIES) -> dict:
    """An unparsable judge reply is asked again, `tries` calls in all; the judge sees the gold, no model under test
    ever does."""
    prompt = judge_prompt(question, response, gold)
    last = None
    for attempt in range(tries):
        try:
            reply = client.chat([{"role": "user", "content": prompt}])
            return {"status": "ok", "attempts": attempt + 1, "judge_text": reply.content,
                    **parse_judgement(reply.content, gold)}
        except ERRORS as exc:
            last = exc
            if isinstance(exc, BudgetExceeded):
                break
    return {"status": "budget" if isinstance(last, BudgetExceeded) else "error", "score": None,
            "error": str(last)[:300]}


# ---- analysis ----

def analyze(targets: list[dict], selections: list[dict], executions: list[dict], judgements: list[dict],
            kinds: dict[str, str] | None = None, reps: int = REPEATS, candidates: tuple = CANDIDATES) -> dict:
    """Equal-weight tasks. A planned execution that is missing, failed or unjudged scores 0.
    `kinds` (target -> judge prompt kind) is derived from the gold at analysis time, for the per-kind breakdown.
    `candidates` defaults to this version's; v1-v6 records use `instruction_selection.CANDIDATES`."""
    tids = [t["target_id"] for t in targets]
    seen = set()
    for r in executions:
        key = (r["target_id"], r["candidate"], r["rep"])
        if key in seen:
            raise ValueError(f"duplicate execution: {key}")
        if key[0] not in tids or key[1] not in candidates or key[2] not in range(reps):
            raise ValueError(f"unplanned execution: {key}")
        seen.add(key)
    scored = {}
    for j in judgements:
        key = (j["target_id"], j["candidate"], j["rep"])
        if key in scored:
            raise ValueError(f"duplicate judgement: {key}")
        if key not in seen:
            raise ValueError(f"judgement without execution: {key}")
        scored[key] = j.get("score") if j.get("status") == "ok" else None
    kinds = kinds or {}
    per_task = {}
    for tid in tids:
        per_task[tid] = {}
        for c in candidates:
            vals = [scored.get((tid, c, k)) or 0. for k in range(reps)]
            per_task[tid][c] = {"score": statistics.mean(vals), "perfect": statistics.mean(v == 1. for v in vals)}
    selection = {s["target_id"]: s for s in selections}
    oracle = {tid: max(candidates, key=lambda c: per_task[tid][c]["score"]) for tid in tids}

    def chosen(tid, policy):
        if policy in candidates:
            return [policy]
        if policy == "random":
            return list(candidates)
        if policy == "best_in_hindsight":
            return [oracle[tid]]
        s = selection.get(tid)
        if s is None:
            return []
        if policy == "tie_average":
            return s["primary"]["tied_candidates"]
        return [s["cross" if policy == "cross_selected" else "primary"]["candidate"]]

    policies = ["selected", "cross_selected", *candidates, "random", "best_in_hindsight", "tie_average"]
    out = {"targets": len(tids), "planned_executions": len(tids) * len(candidates) * reps,
           "recorded_executions": len(executions), "judged_ok": sum(v is not None for v in scored.values()),
           "per_task": per_task, "selection": {}, "by_kind": {}}

    def summarize(ids, metric):
        tables = {p: {tid: statistics.mean(per_task[tid][c][metric] for c in cs) if (cs := chosen(tid, p)) else 0.
                      for tid in ids} for p in policies}
        res = {}
        for p, table in tables.items():
            vals = [table[t] for t in ids]
            d_naive = [table[t] - tables["naive"][t] for t in ids]
            d_random = [table[t] - tables["random"][t] for t in ids]
            res[p] = {"mean": statistics.mean(vals), "ci95": ins.interval(vals),
                      "delta_vs_naive": statistics.mean(d_naive), "delta_ci95": ins.interval(d_naive),
                      "delta_vs_random": statistics.mean(d_random), "delta_vs_random_ci95": ins.interval(d_random)}
        return res

    for metric in ("score", "perfect"):
        out["selection"][metric] = summarize(tids, metric)
    out["hindsight_null"] = hindsight_null({tid: [scored.get((tid, c, k)) or 0. for c in candidates for k in range(reps)]
                                            for tid in tids}, reps)
    for kind in sorted(set(kinds.values())):
        ids = [t for t in tids if kinds.get(t) == kind]
        out["by_kind"][kind] = {"targets": len(ids), "score": summarize(ids, "score")}
    return out


def hindsight_null(scores: dict[str, list[float]], reps: int = REPEATS, draws: int = 2000, seed: int = 0) -> dict:
    """best_in_hindsight - naive when candidates are exchangeable: each task's execution scores are shuffled into
    candidate groups of `reps`, the first group standing for naive. The gap that noise alone produces."""
    rng = random.Random(seed)
    gaps = []
    for _ in range(draws):
        per = []
        for vals in scores.values():
            v = list(vals)
            rng.shuffle(v)
            means = [statistics.mean(v[i:i + reps]) for i in range(0, len(v), reps)]
            per.append(max(means) - means[0])
        gaps.append(statistics.mean(per))
    gaps.sort()
    return {"mean": statistics.mean(gaps), "q025": gaps[int(0.025 * draws)], "q975": gaps[int(0.975 * draws) - 1],
            "draws": draws, "seed": seed}
