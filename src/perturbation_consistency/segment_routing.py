"""Segment routing: choose a worker by its consistency on the first segment of a linear chain, then see how the
workers do on the rest of the chain (decision C39).

The segment is the segment pilot's (C38): node_0 up to the first requested node, here among node_1..node_k with k by
difficulty (`CAPS`), solved in one call and scored on its last node. Three conditions give `SAMPLES` prompts each,
every variant taken from published prompting work:

- `repeat`: the plain segment;
- `instruction`: one fixed reasoning instruction after the problems: zero-shot chain of thought (Kojima et al.,
  NeurIPS 2022), Plan-and-Solve+ (Wang et al., ACL 2023), step-back (Zheng et al., ICLR 2024), analogical prompting
  (Yasunaga et al., ICLR 2024) and joint chain-of-verification (Dhuliawala et al., Findings of ACL 2024). Step-back
  and chain-of-verification are used zero-shot in a single call; their papers use few-shot demonstrations;
- `surface`: the input changed with the problems kept: a checked paraphrase (SPUQ, Gao et al., EACL 2024), re-reading
  (Re2, Xu et al., EMNLP 2024), a different wrapper around each problem (FormatSpread, Sclar et al., ICLR 2024), the
  problems in another order (the permutation of BatchPrompt's BPE, Lin et al., ICLR 2024) and one irrelevant sentence
  inserted into one problem (GSM-IC, Shi et al., ICML 2023).

The paraphrase and the irrelevant sentence come from a model that is not a worker, pass automatic checks and a manual
review, and get at most `TRIES` candidates in all (automatic or review rejections included); an item without an
accepted candidate is left out. After the probes every worker continues the chain node by node from its own most
frequent segment answer (`continue_chain`); a run stops at the first requested node it gets wrong, and every later
requested node counts as wrong (gold is read only for that check, never shown to a model).
"""

from __future__ import annotations

import random
import re

from minpilot.llm.client import HTTPError, LLMClient, TransientError
from minpilot.runtime.trace import BudgetExceeded, InfraError, Trace
from perturbation_consistency import longcot_math, perturb, segment
from perturbation_consistency.longcot_nodes import _PLACEHOLDER, Chain, extract_answer, node_prompt

CAPS = {"easy": 8, "medium": 6, "hard": 4}  # the segment ends at the first requested node among node_1..node_k
SAMPLES = 5
TRIES = 3
CONDITIONS = ("repeat", "instruction", "surface")
INSTRUCTIONS = (
    ("zero_shot_cot", "Let's think step by step."),
    ("plan_and_solve", "Let's first understand the problems, extract relevant variables and their corresponding "
                       "numerals, and make a plan. Then, let's carry out the plan, calculate intermediate variables "
                       "(pay attention to correct numerical calculation and commonsense), solve the problems step by "
                       "step, and show the answers."),
    ("step_back", "First, step back: state the high-level concepts and principles involved in these problems. Then "
                  "solve them using those principles."),
    ("analogical", "Recall three relevant and distinct problems. For each problem, describe it and explain the "
                   "solution. Then solve the problems above."),
    ("verify", "Solve the problems. Then write verification questions that check your answers, answer them, and give "
               "final answers revised in light of them."),
)
SURFACE = ("paraphrase", "re_read", "format_perturbation", "batch_permutation", "irrelevant_context")
RE_READ = "Read the question again: "
CONTINUATION_VARIANT = 0  # longcot_nodes.VARIANTS[0]: step by step, as the fixed pipelines of C29


def segment_target(chain: Chain, difficulty: str) -> segment.Target | None:
    return segment.segment_target(chain, difficulty, max_last=CAPS[difficulty])


def formatted(chain: Chain, nodes: tuple) -> str:
    """The segment with another wrapper around each problem; the problem texts and node labels are unchanged."""
    return "\n\n---\n\n".join(f"PROBLEM [{n}]\n{chain.node(n).text}" for n in nodes)


def permutation(target_id: str, nodes: tuple) -> tuple:
    """A fixed order other than the original (for two or more nodes)."""
    rng, order = random.Random(f"batch_permutation:{target_id}"), list(nodes)
    while len(nodes) > 1 and tuple(order) == tuple(nodes):
        rng.shuffle(order)
    return tuple(order)


# -- the irrelevant sentence (GSM-IC) --------------------------------------------------------------------------------
IRRELEVANT = ("Here is a chain of math problems. Choose one problem and write one sentence of irrelevant context to "
              "insert into it, as in GSM-IC (Shi et al., 2023): the sentence looks related to that problem (same "
              "topic; if the problem has a character or object, it may mention that one or a related one) and "
              "contains a number of similar magnitude to the problem's numbers, but it is not needed for, and does "
              "not change, the answer of any problem. It must not state or hint at a step, method, theorem, "
              "intermediate value or answer, must not contradict or add a condition, and must not mention the "
              "bracketed placeholders [For this value use ...] or any other problem. Return the label of the chosen "
              "problem, the sentence, and that problem's full text with the sentence inserted at a sentence boundary "
              "before the final question, every other character unchanged.\n\nProblems:\n{text}")
IRRELEVANT_CHECK = ("Here is a chain of math problems, and problem {node} of it with one sentence inserted.\n\n"
                    "Problems:\n{text}\n\nProblem {node} with the sentence:\n{new}\n\nInserted sentence:\n{sentence}"
                    "\n\nAnswer four questions. changes_answer: could the inserted sentence change the answer of any "
                    "problem, by adding, removing or altering a condition or quantity? hints: does it state or point "
                    "to a step, method, theorem, intermediate value or answer? contradicts: does it contradict "
                    "anything in the problems? looks_related: does it look related to the topic of problem {node}?")
_IRRELEVANT_SCHEMA = {"type": "object", "properties": {"node": {"type": "string"}, "sentence": {"type": "string"},
                                                        "text": {"type": "string"}},
                      "required": ["node", "sentence", "text"]}
_IRRELEVANT_CHECK_SCHEMA = {"type": "object", "properties": {
    "changes_answer": {"type": "boolean"}, "hints": {"type": "boolean"}, "contradicts": {"type": "boolean"},
    "looks_related": {"type": "boolean"}, "reason": {"type": "string"}},
    "required": ["changes_answer", "hints", "contradicts", "looks_related", "reason"]}


def insertion_problems(original: str, new: str, sentence: str) -> list[str]:
    """Why `new` is not `original` with `sentence` inserted once (empty when it is)."""
    out = []
    if not sentence.strip() or new.count(sentence) != 1:
        out.append("sentence not found once in the new text")
    elif perturb._squash(new.replace(sentence, "", 1)) != perturb._squash(original):
        out.append("the rest of the problem changed")
    if "[For this value" in sentence or re.search(r"node_\d+", sentence):
        out.append("mentions a placeholder or a problem label")
    return out


def judge_irrelevant(client: LLMClient, chain: Chain, nodes: tuple, node: str, sentence: str, new: str) -> dict:
    """One candidate through the insertion check and the checker model."""
    problems = ["unknown problem label"] if node not in nodes else \
        insertion_problems(chain.node(node).text, new, sentence)
    check = None if problems else perturb._ask(
        client, IRRELEVANT_CHECK.format(node=node, text=segment.segment_text(chain, nodes), new=new,
                                        sentence=sentence), "irrelevant_check", _IRRELEVANT_CHECK_SCHEMA)
    ok = not problems and bool(check) and check.get("changes_answer") is False and check.get("hints") is False \
        and check.get("contradicts") is False
    return {"node": node, "sentence": sentence, "text": new, "problems": problems, "check": check, "ok": ok}


def irrelevant_context(client: LLMClient, chain: Chain, nodes: tuple, tries: int = TRIES) -> dict:
    """Up to `tries` candidates until one passes the insertion check and the checker model."""
    text = segment.segment_text(chain, nodes)
    attempts = []
    for _ in range(max(0, tries)):
        out = perturb._ask(client, IRRELEVANT.format(text=text), "irrelevant_context", _IRRELEVANT_SCHEMA) or {}
        a = judge_irrelevant(client, chain, nodes, *(str(out.get(k, "")).strip() for k in ("node", "sentence", "text")))
        attempts.append(a)
        if a["ok"]:
            return {"kind": "irrelevant_context", "node": a["node"], "sentence": a["sentence"], "text": a["text"],
                    "ok": True, "attempts": attempts}
    return {"kind": "irrelevant_context", "ok": False, "attempts": attempts}


def manual_irrelevant(client: LLMClient, chain: Chain, nodes: tuple, node: str, sentence: str, before: str) -> dict:
    """A sentence written by hand (not by the rewriter), inserted before `before` in `node` and judged as a generated
    one; recorded with `author`."""
    original = chain.node(node).text if node in nodes else ""
    new = original.replace(before, f"{sentence} {before}", 1) if before in original else original
    a = judge_irrelevant(client, chain, nodes, node, sentence, new) | {"author": "claude_manual"}
    out = {"kind": "irrelevant_context", "ok": a["ok"], "attempts": [a], "author": "claude_manual"}
    return out | ({"node": node, "sentence": sentence, "text": new} if a["ok"] else {})


def _numbers(text: str) -> list[str]:
    text = re.sub(r"\\frac\s*(\d)\s*(\d)", r"\\frac{\1}{\2}", _PLACEHOLDER.sub(" ", text))  # \frac 32 = \frac{3}{2}
    return re.findall(r"\d+(?:\.\d+)?", text)


def paraphrase_problems(original: str, new: str, nodes: tuple) -> list[str]:
    """What a segment paraphrase lost: a dependency placeholder (exact up to whitespace and math delimiters), a node
    label, or a number. Formulas are not compared as strings (a paraphrase may split or re-delimit them, and a `$`
    can be a currency sign); the same-chain check and the manual review judge them."""
    flat = perturb._squash(new)
    phs = _PLACEHOLDER.findall(original)
    lost = [ph for ph in dict.fromkeys(phs) if flat.count(perturb._squash(ph)) < phs.count(ph)]
    lost += [n for n in nodes if not re.search(rf"\b{n}\b", new)]
    before, after = _numbers(original), _numbers(new)
    lost += [x for x in dict.fromkeys(before) if before.count(x) > after.count(x)]
    return lost if new.strip() else ["<empty>"]


def judge_paraphrase(client: LLMClient, text: str, new: str, nodes: tuple) -> dict:
    lost = paraphrase_problems(text, new, nodes)
    same = None if lost else perturb._ask(client, segment.SAME_CHAIN.format(a=text, b=new), "same_problem",
                                          perturb._SAME_SCHEMA)
    return {"text": new, "lost": lost, "same_problem": same,
            "ok": not lost and bool(same) and same.get("same_problem") is True}


def paraphrase(client: LLMClient, chain: Chain, nodes: tuple, tries: int = TRIES) -> dict:
    text, attempts = segment.segment_text(chain, nodes), []
    for _ in range(max(0, tries)):
        out = perturb._ask(client, segment.PARAPHRASE.format(text=text), "rewrite", perturb._REWRITE_SCHEMA) or {}
        a = judge_paraphrase(client, text, str(out.get("text", "")).strip(), nodes)
        attempts.append(a)
        if a["ok"]:
            return {"kind": "paraphrase", "text": a["text"], "ok": True, "attempts": attempts}
    return {"kind": "paraphrase", "text": None, "ok": False, "attempts": attempts}


def recheck_paraphrase(client: LLMClient, chain: Chain, nodes: tuple, item: dict) -> dict:
    """Judge an item's stored candidates again with the current checks, in order (no new candidate)."""
    text, attempts = segment.segment_text(chain, nodes), []
    for old in item.get("attempts", []):
        a = judge_paraphrase(client, text, old.get("text") or "", nodes) | {"rechecked": True,
                                                                            "first_check": old}
        attempts.append(a)
        if a["ok"]:
            return {"kind": "paraphrase", "text": a["text"], "ok": True, "attempts": attempts}
    return {"kind": "paraphrase", "text": None, "ok": False, "attempts": attempts}


# -- probe prompts ---------------------------------------------------------------------------------------------------
def build_prompts(chain: Chain, target: segment.Target, items: dict[str, dict]) -> list[dict]:
    """Every (condition, sample) prompt of one target. `items` holds the accepted paraphrase and irrelevant sentence
    (`ok`); a surface sample whose item is missing is left out."""
    nodes = target.nodes
    text = segment.segment_text(chain, nodes)
    fmt = segment.format_request(list(nodes))
    rows = []

    def add(condition: str, sample: int, body: str, detail: str) -> None:
        rows.append({"target_id": target.target_id, "condition": condition, "sample": sample, "detail": detail,
                     "answer_node": target.node, "nodes": list(nodes), "prompt": f"{body}\n\n{fmt}"})

    plain = segment.INTRO + text
    for i in range(SAMPLES):
        add("repeat", i, plain, "plain")
    for i, (name, instruction) in enumerate(INSTRUCTIONS):
        add("instruction", i, f"{plain}\n\n{instruction}", name)
    for i, kind in enumerate(SURFACE):
        if kind == "paraphrase":
            if not items.get("paraphrase", {}).get("ok"):
                continue
            body = segment.INTRO + items["paraphrase"]["text"]
        elif kind == "re_read":
            body = f"{plain}\n\n{RE_READ}{text}"
        elif kind == "format_perturbation":
            body = segment.INTRO + formatted(chain, nodes)
        elif kind == "batch_permutation":
            body = segment.INTRO + segment.segment_text(chain, permutation(target.target_id, nodes))
        else:
            item = items.get("irrelevant_context", {})
            if not item.get("ok"):
                continue
            body = segment.INTRO + "\n".join(
                f"Problem {n}: {item['text'] if n == item['node'] else chain.node(n).text}" for n in nodes)
        add("surface", i, body, kind)
    return rows


# -- the rest of the chain -------------------------------------------------------------------------------------------
def start_answer(answers: list[str | None]) -> dict:
    """The most frequent of a worker's probe answers (ties: the group whose first member comes first)."""
    groups = [g for g in longcot_math.group(answers) if answers[g[0]] is not None]
    if not groups:
        return {"answer": None, "support": 0, "of": len(answers), "tied": False}
    return {"answer": answers[groups[0][0]], "support": len(groups[0]), "of": len(answers),
            "tied": len(groups) > 1 and len(groups[1]) == len(groups[0])}


def continue_chain(client: LLMClient, trace: Trace, chain: Chain, target: segment.Target, start: str | None,
                   gold: dict[str, str]) -> dict:
    """Solve the nodes after the segment one call each, up to the last requested node, each from the previous
    answers. `gold` holds the requested nodes' answers, read only to stop at the first wrong one; it never enters a
    prompt. Returns per requested node from the segment's last on: correct / wrong / not_reached."""
    names = [n.name for n in chain.nodes]
    last = max(names.index(r) for r in chain.requested)
    todo = names[names.index(target.node) + 1:last + 1]
    values, calls, status = {target.node: start} if start is not None else {}, [], "ok"
    scored = {}
    if start is None:
        status = "no_segment_answer"
    elif not longcot_math.same(gold[target.node], start):
        status = f"wrong_at_{target.node}"
    scored[target.node] = status == "ok"
    for name in todo if status == "ok" else []:
        prompt = node_prompt(chain.node(name), values, CONTINUATION_VARIANT)
        with trace.tags(node=name):
            try:
                res = client.chat([{"role": "user", "content": prompt}])
            except (InfraError, BudgetExceeded, HTTPError, TransientError, ValueError) as e:  # ValueError: a body that is not JSON
                calls.append({"node": name, "answer": None, "status": "error", "error": str(e)[:300]})
                status = f"error_at_{name}"
                break
        answer = extract_answer(res.content)
        call_status = "length" if res.finish_reason == "length" else ("ok" if answer is not None else "no_answer")
        calls.append({"node": name, "answer": answer if call_status == "ok" else None, "status": call_status,
                      "completion_tokens": (res.usage or {}).get("completion_tokens"),
                      "cost_usd": float((res.usage or {}).get("cost") or 0.0)})
        if call_status != "ok":
            status = f"{call_status}_at_{name}"
            break
        values[name] = answer
        if name in gold:
            scored[name] = longcot_math.same(gold[name], answer)
            if not scored[name]:
                status = f"wrong_at_{name}"
                break
    requested_after = [r for r in chain.requested if names.index(r) >= names.index(target.node)]
    result = {r: ("correct" if scored.get(r) else "wrong" if r in scored else "not_reached") for r in requested_after}
    return {"status": status, "start": start, "calls": calls, "requested": result,
            "requested_correct": sum(v == "correct" for v in result.values()), "requested_total": len(result)}
