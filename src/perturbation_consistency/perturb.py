"""Perturbation pilot: which way of perturbing a single node makes worker consistency informative?

One node is solved on its own (gold values of the nodes it depends on are given as inputs), so there is no chain and
every worker call can go out at once. For each target node five conditions give `SAMPLES` prompts each:

- `repeat`: the plain problem, sent `SAMPLES` times (the resampling baseline every other condition is compared with);
- `instruction`: solving instructions around the unchanged problem (step by step, plan first, principles first);
- `surface`: the problem text rewritten with the same meaning (a paraphrase, a Given/Conditions/Find restatement, and
  the original plus a true, topic-related sentence that the solution does not need);
- `methods`: a separate model lists substantially different approaches; each sample must use one of them;
- `avoid_first`: name the method that comes to mind first, then solve without it.

Every prompt ends with the same format request: a `method = ...` line naming the main technique, then the
`answer = ...` line. Rewrites and approach lists come from a model that is not a worker (`sonnet-medium`). A rewrite
must keep every formula, number and dependency placeholder of the original (`rewrite_problems`) and pass the
model's same-problem check; otherwise it is retried and finally dropped (the condition then has fewer samples).
"""

from __future__ import annotations

import json
import random
import re
from dataclasses import asdict, dataclass

from minpilot.llm.client import LLMClient, json_schema_format
from perturbation_consistency.longcot_nodes import _PLACEHOLDER, VARIANTS, Chain, Node

SAMPLES = 3
CONDITIONS = ("repeat", "instruction", "surface", "methods", "avoid_first")
FORMAT = ("End your response with two lines: first `method = <a few words naming the main technique you used>`, "
          "then a final line of the form: answer = <exact value>")
INSTRUCTIONS = tuple(VARIANTS[i].split("{body}")[0] for i in (0, 1, 3))  # step by step, plan first, principles first
METHOD_PROMPT = ("Solve the following problem using this approach: {approach} If the approach cannot work for this "
                 "problem, say so in one sentence and solve it another way.\n\n")
AVOID_FIRST = ("First, state in one line the method you would most naturally use for this problem. Then solve the "
               "problem without using that method.\n\n")
_MATH = re.compile(r"\$\$.+?\$\$|\$.+?\$|\\\(.+?\\\)|\\\[.+?\\\]", re.S)
_NUMBER = re.compile(r"\d+(?:\.\d+)?")
_METHOD_LINE = re.compile(r"(?im)^[\s*_`]*method[\s*_`]*=[\s*_`]*(.+?)[\s*_`]*$")


@dataclass(frozen=True)
class Target:
    target_id: str      # <question_id>:<node>
    question_id: str
    difficulty: str
    template: str
    node: str
    kind: str           # "first" (no dependency) or "middle" (gold inputs given)
    inputs: dict        # dependency node -> gold value given in the prompt


def eligible_targets(chain: Chain, gold: dict[str, str], difficulty: str, template: str) -> list[Target]:
    """Requested nodes (gold to score) whose dependencies are all requested too (gold to give as inputs)."""
    out = []
    for n in chain.nodes:
        if n.name in gold and all(d in gold for d in n.deps):
            out.append(Target(f"{chain.question_id}:{n.name}", chain.question_id, difficulty, template, n.name,
                              "middle" if n.deps else "first", {d: gold[d] for d in n.deps}))
    return out


def pick_targets(pool: list[Target], quota: dict[tuple[str, str], int], seed: int) -> list[Target]:
    """`quota[(difficulty, kind)]` targets per stratum, seeded, at most one per question."""
    rng = random.Random(f"perturbation-pilot:{seed}")
    picked, used = [], set()
    for (difficulty, kind), k in sorted(quota.items()):
        stratum = sorted((t for t in pool if t.difficulty == difficulty and t.kind == kind), key=lambda t: t.target_id)
        rng.shuffle(stratum)
        chosen = []
        for t in stratum:
            if len(chosen) < k and t.question_id not in used:
                chosen.append(t)
                used.add(t.question_id)
        if len(chosen) < k:
            raise ValueError(f"only {len(chosen)} targets for {difficulty}/{kind}, need {k}")
        picked += chosen
    return picked


def body(node: Node, text: str, inputs: dict) -> str:
    out = f"Problem {node.name}: {text}"
    if node.deps:
        given = "\n".join(f"- {d}: {inputs[d]}" for d in node.deps)
        out += ("\n\nWhere the problem says to use a value from an earlier problem, use that problem's answer "
                f"given here:\n{given}")
    return out


def _squash(s: str) -> str:
    """Whitespace and math delimiters removed; a form feed read as \\f (LongCoT has `\\frac` stored as form feed + rac)."""
    return re.sub(r"\s|\$|\\\(|\\\)|\\\[|\\\]", "", s.replace("\x0c", "\\f"))


def preserved(original: str, rewrite: str) -> list[str]:
    """What a rewrite lost: formulas, dependency placeholders and numbers of the original that it does not contain.
    Formulas and placeholders are compared without whitespace or math delimiters (`$3 x$` = `$3x$`)."""
    flat = _squash(rewrite)
    lost = [m for m in _MATH.findall(original) + _PLACEHOLDER.findall(original) if _squash(m) not in flat]
    numbers = _NUMBER.findall(_PLACEHOLDER.sub(" ", _MATH.sub(" ", original)))
    have = _NUMBER.findall(rewrite)
    lost += [x for x in numbers if numbers.count(x) > have.count(x)]
    return sorted(set(lost))


# -- prompts to the rewriting model (sonnet-medium) --------------------------------------------------------------
REWRITE_RULES = ("Keep every formula, every number and every bracketed placeholder of the form [For this value use "
                 "...] exactly as written. Do not add hints, solution steps, simplifications or the answer, and do not "
                 "drop or weaken any condition.")
PARAPHRASE = ("Rewrite the following math problem statement in different words. The rewritten problem must have the "
              "same mathematical meaning and the same answer. " + REWRITE_RULES + "\n\nProblem:\n{text}")
STRUCTURED = ("Restate the following math problem as three labelled parts, 'Given:', 'Conditions:' and 'Find:'. The "
              "restated problem must have the same mathematical meaning and the same answer. " + REWRITE_RULES
              + "\n\nProblem:\n{text}")
SAME_PROBLEM = ("Do these two statements describe the same mathematical problem with the same answer? Answer false if "
                "any quantity, condition, domain or the thing asked for differs, or if B hints at the solution."
                "\n\nA:\n{a}\n\nB:\n{b}")
RELATED_FACT = ("Write one true sentence of background that is related to the setting or topic of the following "
                "problem but that a solver would not use: for example a historical note about the topic, or a true "
                "property of an object in the problem that answers a different question from the one asked. It must "
                "not mention any theorem, identity, formula, technique or quantity that could help solve this "
                "problem, must not change the problem or its answer, and must not refer to the dependency "
                "placeholder. Start it with 'Note:'.\n\nProblem:\n{text}")
FACT_CHECK = ("Here is a math problem and a sentence that will be appended to it.\n\nProblem:\n{text}\n\nSentence:\n"
              "{fact}\n\nAnswer three questions. true: is the sentence a correct mathematical statement? "
              "changes_problem: does appending it change the problem's meaning, conditions or answer? hints: does it "
              "state or point to the answer, or to a step, lemma or quantity a solution would use?")
APPROACHES = ("List three substantially different approaches to solving the following math problem: different "
              "techniques, representations or algorithms, not different write-ups of the same method. One or two "
              "sentences each, specific to this problem. Do not solve the problem and do not state or hint at its "
              "answer.\n\n{body}")

_REWRITE_SCHEMA = {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]}
_SAME_SCHEMA = {"type": "object", "properties": {"same_problem": {"type": "boolean"}, "reason": {"type": "string"}},
                "required": ["same_problem", "reason"]}
_FACT_CHECK_SCHEMA = {"type": "object", "properties": {"true": {"type": "boolean"},
                                                       "changes_problem": {"type": "boolean"},
                                                       "hints": {"type": "boolean"}, "reason": {"type": "string"}},
                      "required": ["true", "changes_problem", "hints", "reason"]}
_APPROACH_SCHEMA = {"type": "object", "properties": {"approaches": {"type": "array", "items": {"type": "string"},
                                                                    "minItems": 3, "maxItems": 3}},
                    "required": ["approaches"]}


def _ask(client: LLMClient, prompt: str, name: str, schema: dict) -> dict | None:
    res = client.chat([{"role": "user", "content": prompt}], response_format=json_schema_format(name, schema))
    return res.parsed if isinstance(res.parsed, dict) else None


def rewrite(client: LLMClient, kind: str, text: str, tries: int = 2) -> dict:
    """A checked rewrite of a node text: {'text', 'kind', 'attempts': [...], 'ok'}."""
    attempts = []
    for _ in range(tries):
        out = _ask(client, (PARAPHRASE if kind == "paraphrase" else STRUCTURED).format(text=text), "rewrite",
                   _REWRITE_SCHEMA)
        new = (out or {}).get("text", "").strip()
        lost = preserved(text, new) if new else ["<empty>"]
        same = _ask(client, SAME_PROBLEM.format(a=text, b=new), "same_problem", _SAME_SCHEMA) if new and not lost \
            else None
        attempts.append({"text": new, "lost": lost, "same_problem": same})
        if new and not lost and same and same.get("same_problem") is True:
            return {"kind": kind, "text": new, "ok": True, "attempts": attempts}
    return {"kind": kind, "text": None, "ok": False, "attempts": attempts}


def related_fact(client: LLMClient, text: str, tries: int = 3) -> dict:
    """A checked topic-related sentence to append: true, not changing the problem, not hinting at the solution."""
    attempts = []
    for _ in range(tries):
        out = _ask(client, RELATED_FACT.format(text=text), "rewrite", _REWRITE_SCHEMA)
        fact = (out or {}).get("text", "").strip()
        check = _ask(client, FACT_CHECK.format(text=text, fact=fact), "fact_check", _FACT_CHECK_SCHEMA) if fact \
            else None
        attempts.append({"text": fact, "check": check})
        if fact and "[For this value" not in fact and check and check.get("true") is True \
                and check.get("changes_problem") is False and check.get("hints") is False:
            return {"kind": "related_fact", "text": fact, "ok": True, "attempts": attempts}
    return {"kind": "related_fact", "text": None, "ok": False, "attempts": attempts}


def approaches(client: LLMClient, problem: str) -> list[str]:
    out = _ask(client, APPROACHES.format(body=problem), "approaches", _APPROACH_SCHEMA)
    items = [a.strip() for a in (out or {}).get("approaches", []) if isinstance(a, str) and a.strip()]
    return items[:SAMPLES]


def build_prompts(node: Node, target: Target, rewrites: dict[str, dict], methods: list[str]) -> list[dict]:
    """Every (condition, sample) prompt of one target; samples whose rewrite or approach is missing are left out."""
    plain = body(node, node.text, target.inputs)
    rows = []

    def add(condition: str, sample: int, prompt: str, detail: str) -> None:
        rows.append({"target_id": target.target_id, "condition": condition, "sample": sample, "detail": detail,
                     "prompt": f"{prompt}\n\n{FORMAT}"})

    for i in range(SAMPLES):
        add("repeat", i, plain, "plain")
    for i, prefix in enumerate(INSTRUCTIONS[:SAMPLES]):
        add("instruction", i, prefix + plain, ("step_by_step", "plan_first", "principles_first")[i])
    for i, kind in enumerate(("paraphrase", "structured", "related_fact")[:SAMPLES]):
        if not rewrites.get(kind, {}).get("ok"):
            continue
        text = f"{node.text}\n\n{rewrites[kind]['text']}" if kind == "related_fact" else rewrites[kind]["text"]
        add("surface", i, body(node, text, target.inputs), kind)
    for i, approach in enumerate(methods[:SAMPLES]):
        add("methods", i, METHOD_PROMPT.format(approach=approach.rstrip(".") + ".") + plain, approach)
    for i in range(SAMPLES):
        add("avoid_first", i, AVOID_FIRST + plain, "avoid_first")
    return rows


def method_label(text: str | None) -> str | None:
    found = _METHOD_LINE.findall(text or "")
    return found[-1].strip().rstrip(".")[:200] if found else None


def target_record(t: Target) -> str:
    return json.dumps(asdict(t), ensure_ascii=False)
