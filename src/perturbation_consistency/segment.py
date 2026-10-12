"""Segment pilot: the first nodes of a linear chain, solved as one problem in one call.

A segment runs from node_0 to the first requested node t in node_1..node_4, so its last answer has gold and no gold
value is ever given as an input (unlike the single-node pilot, decision C32). Each sample answers every node of the
segment in one response; the score is the last node's answer. The segment is perturbed as a whole (decision C33),
with the same five conditions and `SAMPLES` prompts each as the single-node pilot:

- `repeat`: the plain segment;
- `instruction`: step by step / plan the whole chain first / check each value before passing it on;
- `surface`: the whole segment rewritten (paraphrase keeping the node labels; one Given/Dependencies/Find
  restatement) and the plain segment plus a true, topic-related note the solution does not use;
- `methods`: three strategies for working through the segment as a whole, from the rewriter, one per sample;
- `avoid_first`: name the natural way to proceed, then proceed another way.

Every prompt asks for one `node_<i> = ...` line per node, a `method = ...` line and the final `answer = ...` line
(the last node). Rewrites keep every formula, number and dependency placeholder of the segment and pass the
rewriter's same-problem check; the related note must be true, not change the problems and not hint.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from minpilot.llm.client import LLMClient
from perturbation_consistency import perturb
from perturbation_consistency.longcot_nodes import Chain, clean_answer

SAMPLES = perturb.SAMPLES
MAX_LAST = 4  # the segment ends at the first requested node among node_1..node_4
INTRO = ("The following problems form a chain: where a problem says to use the answer from an earlier problem, use "
         "your own answer to that problem.\n\n")
INSTRUCTIONS = (
    ("step_by_step", "Solve the following problems in order, step by step, writing out each step.\n\n"),
    ("plan_chain", "Before solving, write a plan for the whole chain: list the problems, which value flows from each "
                   "problem into which later problem, and the order in which you will solve them. Then carry out the "
                   "plan.\n\n"),
    ("check_each_value", "Solve the following problems in order. Before passing any answer on to a later problem, "
                         "check it by a different route, and correct it if the check fails.\n\n"),
)
STRATEGY_PROMPT = ("Work through the following problems using this strategy: {strategy} If the strategy cannot work "
                   "here, say so in one sentence and proceed another way.\n\n")
AVOID_FIRST = ("First, state in one line how you would most naturally work through these problems. Then solve them "
               "without proceeding that way.\n\n")
_NODE_LINE = re.compile(r"(?im)^[\s*_`>-]*\\?\(?\s*(node_\d+)\s*\\?\)?[\s*_`]*=[\s*_`]*(.+?)[\s*_`]*$")


def format_request(nodes: list[str]) -> str:
    lines = ", ".join(f"`{n} = <exact value>`" for n in nodes)
    return (f"End your response with one line per problem, in this order: {lines}; then a line `method = <a few words "
            f"naming your overall approach>`; then a final line of the form: answer = <exact value of {nodes[-1]}>")


@dataclass(frozen=True)
class Target:
    target_id: str      # <question_id>:<last node>
    question_id: str
    difficulty: str
    template: str
    node: str           # last node of the segment: the scored answer
    kind: str = "segment"
    inputs: dict = field(default_factory=dict)  # none: the segment starts at node_0
    nodes: tuple = ()


def segment_target(chain: Chain, difficulty: str, template: str = "linear") -> Target | None:
    requested = sorted(int(n.split("_")[1]) for n in chain.requested)
    last = next((i for i in requested if 1 <= i <= MAX_LAST), None)
    if last is None:
        return None
    nodes = tuple(f"node_{i}" for i in range(last + 1))
    if any(d not in nodes for n in nodes for d in chain.node(n).deps):
        return None
    return Target(f"{chain.question_id}:node_{last}", chain.question_id, difficulty, template, f"node_{last}",
                  nodes=nodes)


def segment_text(chain: Chain, nodes: tuple) -> str:
    return "\n".join(f"Problem {n}: {chain.node(n).text}" for n in nodes)


# -- prompts to the rewriting model --------------------------------------------------------------------------------
RULES = ("Keep every formula, every number and every bracketed placeholder of the form [For this value use ...] "
         "exactly as written. Do not add hints, solution steps, simplifications or answers, and do not drop or weaken "
         "any condition.")
PARAPHRASE = ("Rewrite the following chain of math problems in different words. Keep each 'Problem node_<i>:' label "
              "and the order of the problems; every problem must keep its mathematical meaning and its answer. "
              + RULES + "\n\nProblems:\n{text}")
STRUCTURED = ("Restate the following chain of math problems as one problem with three labelled parts: 'Given:' (the "
              "facts, definitions and conditions of every problem, each marked with its node label), 'Dependencies:' "
              "(each bracketed placeholder copied exactly, with the node in which it appears), and 'Find:' (what each "
              "problem asks for, by node label). Every problem must keep its meaning and its answer. " + RULES
              + "\n\nProblems:\n{text}")
SAME_CHAIN = ("Do these two texts pose the same chain of math problems with the same answers? Answer false if any "
              "quantity, condition, domain, dependency or the thing asked for differs in any problem, or if B hints at "
              "a solution.\n\nA:\n{a}\n\nB:\n{b}")
RELATED_FACT = ("Write one true sentence of background that is related to the setting or topic of the following math "
                "problems but that a solver would not use: for example a historical note, or a true property of an "
                "object in the problems that answers a different question from the ones asked. It must not mention "
                "any theorem, identity, formula, technique or quantity that could help solve any of these problems, "
                "must not change the problems or their answers, and must not refer to the placeholders. Start it "
                "with 'Note:'.\n\nProblems:\n{text}")
STRATEGIES = ("List three substantially different strategies for working through the following chain of math "
              "problems as a whole: for example different orders of work, different ways of organising and checking "
              "the values passed between problems, or different key techniques for the hardest problem. One or two "
              "sentences each, specific to these problems. Do not solve any problem and do not state or hint at any "
              "answer or intermediate value.\n\n{text}")


def rewrite(client: LLMClient, kind: str, text: str, nodes: tuple, tries: int = 2) -> dict:
    attempts = []
    for _ in range(tries):
        out = perturb._ask(client, (PARAPHRASE if kind == "paraphrase" else STRUCTURED).format(text=text),
                           "rewrite", perturb._REWRITE_SCHEMA)
        new = (out or {}).get("text", "").strip()
        lost = perturb.preserved(text, new) if new else ["<empty>"]
        lost += [n for n in nodes if not re.search(rf"\b{n}\b", new)]
        same = perturb._ask(client, SAME_CHAIN.format(a=text, b=new), "same_problem", perturb._SAME_SCHEMA) \
            if new and not lost else None
        attempts.append({"text": new, "lost": lost, "same_problem": same})
        if new and not lost and same and same.get("same_problem") is True:
            return {"kind": kind, "text": new, "ok": True, "attempts": attempts}
    return {"kind": kind, "text": None, "ok": False, "attempts": attempts}


def related_fact(client: LLMClient, text: str, tries: int = 3) -> dict:
    attempts = []
    for _ in range(tries):
        out = perturb._ask(client, RELATED_FACT.format(text=text), "rewrite", perturb._REWRITE_SCHEMA)
        fact = (out or {}).get("text", "").strip()
        check = perturb._ask(client, perturb.FACT_CHECK.format(text=text, fact=fact), "fact_check",
                             perturb._FACT_CHECK_SCHEMA) if fact else None
        attempts.append({"text": fact, "check": check})
        if fact and "[For this value" not in fact and check and check.get("true") is True \
                and check.get("changes_problem") is False and check.get("hints") is False:
            return {"kind": "related_fact", "text": fact, "ok": True, "attempts": attempts}
    return {"kind": "related_fact", "text": None, "ok": False, "attempts": attempts}


def strategies(client: LLMClient, text: str) -> list[str]:
    out = perturb._ask(client, STRATEGIES.format(text=text), "approaches", perturb._APPROACH_SCHEMA)
    items = [a.strip() for a in (out or {}).get("approaches", []) if isinstance(a, str) and a.strip()]
    return items[:SAMPLES]


def build_prompts(chain: Chain, target: Target, rewrites: dict[str, dict], methods: list[str]) -> list[dict]:
    text = segment_text(chain, target.nodes)
    fmt = format_request(list(target.nodes))
    rows = []

    def add(condition: str, sample: int, prompt: str, detail: str) -> None:
        rows.append({"target_id": target.target_id, "condition": condition, "sample": sample, "detail": detail,
                     "answer_node": target.node, "nodes": list(target.nodes), "prompt": f"{prompt}\n\n{fmt}"})

    for i in range(SAMPLES):
        add("repeat", i, INTRO + text, "plain")
    for i, (name, prefix) in enumerate(INSTRUCTIONS[:SAMPLES]):
        add("instruction", i, prefix + INTRO + text, name)
    for i, kind in enumerate(("paraphrase", "structured", "related_fact")[:SAMPLES]):
        if not rewrites.get(kind, {}).get("ok"):
            continue
        body = f"{text}\n\n{rewrites[kind]['text']}" if kind == "related_fact" else rewrites[kind]["text"]
        add("surface", i, INTRO + body, kind)
    for i, strategy in enumerate(methods[:SAMPLES]):
        add("methods", i, STRATEGY_PROMPT.format(strategy=strategy.rstrip(".") + ".") + INTRO + text, strategy)
    for i in range(SAMPLES):
        add("avoid_first", i, AVOID_FIRST + INTRO + text, "avoid_first")
    return rows


def node_answers(text: str | None) -> dict[str, str]:
    """The last `node_<i> = value` line per node (notation cleaned)."""
    out = {}
    for node, value in _NODE_LINE.findall(text or ""):
        out[node] = clean_answer(value)
    return out
