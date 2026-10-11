"""Split a LongCoT math prompt into its nodes and render one node as a single-problem prompt.

A LongCoT math prompt lists `Problem node_<i>: ...` lines; a node that depends on earlier answers says so inside
`[For this value use ... problem node_<k> ...]`, and the prompt ends by asking for some nodes' answers. The node text is
sent verbatim (placeholders included); the values of the nodes it depends on are given below it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_NODE_LINE = re.compile(r"(?m)^Problem (node_\d+):[ \t]*")
_PLACEHOLDER = re.compile(r"\[For this value[^\[\]]*\]")
_NODE_REF = re.compile(r"node_\d+")
_REQUEST = re.compile(r"(?m)^What are the answers to problem (.+?)\?\s*$")
# `answer = value` anywhere in a line, e.g. `answer = 7`, `**answer = 7**.`, `...so it is 859.answer = 859`,
# `$$\text{answer} = 738$$`, `answer \(= 5\)`; the value runs to the end of the line.
_ANSWER_LINE = re.compile(r"(?i)(?:\\text\{[ \t]*)?\banswer\b[ \t]*\}?[ \t*_`]*(?:\\\([ \t]*)?=[ \t]*([^\n]+)")


@dataclass(frozen=True)
class Node:
    name: str
    text: str
    deps: tuple[str, ...]


@dataclass(frozen=True)
class Chain:
    question_id: str
    nodes: tuple[Node, ...]
    requested: tuple[str, ...]  # nodes whose answers the original prompt asks for, in its order

    def node(self, name: str) -> Node:
        return next(n for n in self.nodes if n.name == name)


def parse_chain(question_id: str, prompt: str) -> Chain:
    request = _REQUEST.search(prompt)
    if not request:
        raise ValueError(f"{question_id}: no 'What are the answers to problem ...?' line")
    parts = _NODE_LINE.split(prompt[:request.start()])
    if len(parts) < 3:
        raise ValueError(f"{question_id}: no 'Problem node_<i>:' lines")
    nodes = []
    for name, body in zip(parts[1::2], parts[2::2]):
        text = body.strip()
        deps = tuple(dict.fromkeys(ref for ph in _PLACEHOLDER.findall(text) for ref in _NODE_REF.findall(ph)))
        nodes.append(Node(name, text, deps))
    names = [n.name for n in nodes]
    for i, n in enumerate(nodes):
        if any(d not in names[:i] for d in n.deps):
            raise ValueError(f"{question_id}: {n.name} depends on a node that does not precede it: {n.deps}")
    requested = tuple(_NODE_REF.findall(request.group(1)))
    if not requested or any(r not in names for r in requested):
        raise ValueError(f"{question_id}: bad requested nodes {requested}")
    return Chain(question_id, tuple(nodes), requested)


# n fixed instructions around the unchanged problem, each asking for a different way of solving it: step-by-step
# chain of thought, plan-and-solve, solve then self-check, step-back prompting (principles first), and no solving
# instruction at all. The problem text, the given values and the required answer line are the same in every variant.
VARIANTS: tuple[str, ...] = (
    "Solve the following math problem step by step, writing out each step.\n\n{body}\n\n"
    "End your response with a final line of the form: answer = <exact value>",
    "Before solving, write a short plan: what is asked, which facts or methods apply, and the order of steps. "
    "Then carry out the plan.\n\n{body}\n\n"
    "End your response with a final line of the form: answer = <exact value>",
    "Solve the following math problem. Then check your result by a different route, such as substituting it back, "
    "testing small cases or computing it another way. If the check fails, find the error and correct the "
    "solution.\n\n{body}\n\n"
    "End your response with a final line of the form: answer = <exact value>",
    "Before working on the specific problem, step back: state the general mathematical principles, theorems or "
    "techniques that this kind of problem relies on. Then solve the problem using them.\n\n{body}\n\n"
    "End your response with a final line of the form: answer = <exact value>",
    "{body}\n\n"
    "End your response with a final line of the form: answer = <exact value>",
)


def node_prompt(node: Node, values: dict[str, str], variant: int = 0) -> str:
    """The node as a standalone problem. `values` holds the answers of the nodes it depends on."""
    missing = [d for d in node.deps if d not in values]
    if missing:
        raise KeyError(f"{node.name} needs values of {missing}")
    body = f"Problem {node.name}: {node.text}"
    if node.deps:
        given = "\n".join(f"- {d}: {values[d]}" for d in node.deps)
        body += ("\n\nWhere the problem says to use a value from an earlier problem, use that problem's answer "
                 f"given here:\n{given}")
    return VARIANTS[variant].format(body=body)


_DELIMITERS = (("\\(", "\\)"), ("\\[", "\\]"), ("$$", "$$"), ("$", "$"))


def clean_answer(value: str) -> str:
    """Strip notation that does not change the value: markdown emphasis, math delimiters (\\( \\), $ $), \\boxed{},
    LaTeX spacing (\\, \\! \\; \\:), \\dfrac/\\tfrac (as \\frac), unbraced \\sqrt2 (as \\sqrt{2}) and a trailing period. LongCoT's own comparison leaves
    these to an LLM fallback judge, which this harness does not use."""
    s = value.strip()
    for _ in range(3):  # wrappers can nest, e.g. **\(52\)**.
        s = re.sub(r"^[*_`]+|[*_`]+$", "", s).strip().rstrip(".").strip()
        for a, b in _DELIMITERS:
            if len(s) >= len(a) + len(b) and s.startswith(a) and s.endswith(b):
                s = s[len(a):len(s) - len(b)].strip()
            elif s.endswith(b) and a not in s[:-len(b)]:  # closer left over from the surrounding line
                s = s[:-len(b)].strip()
        if m := re.fullmatch(r"\\boxed\{(.*)\}", s):
            s = m.group(1).strip()
    s = s.replace("\\dfrac", "\\frac").replace("\\tfrac", "\\frac")
    s = re.sub(r"\\[,!;:]|\\ ", "", s)
    s = re.sub(r"\\sqrt([0-9A-Za-z])", r"\\sqrt{\1}", s)  # LaTeX: \sqrt2 is the root of one token
    return s.rstrip(".").strip()


_BOXED_TEXT_ANSWER = re.compile(r"\\text\{\s*answer\s*(?:=\s*([^{}]*?))?\s*\}\s*(?:=\s*)?(.*)$", re.S)


def _boxed_answers(text: str):
    """(position, value) for every \\boxed{\\text{answer}=...} or \\boxed{\\text{answer = ...}} (balanced braces)."""
    for m in re.finditer(r"\\boxed\{", text):
        depth, i = 1, m.end()
        while i < len(text) and depth:
            depth += {"{": 1, "}": -1}.get(text[i], 0)
            i += 1
        if depth:
            continue
        inner = re.sub(r"^\\displaystyle\s*", "", text[m.end():i - 1].strip())
        if found := _BOXED_TEXT_ANSWER.match(inner):
            yield m.start(), i, (found.group(1) or found.group(2) or "").strip()


def extract_answer(text: str | None) -> str | None:
    """The last answer given as `answer = ...` or as \\boxed{\\text{answer}=...} (luna-high writes the latter),
    notation cleaned; None when there is neither. A line match inside a boxed answer defers to the boxed reading."""
    text = text or ""
    boxed = list(_boxed_answers(text))
    found = [(start, value) for start, _, value in boxed]
    found += [(m.start(), m.group(1)) for m in _ANSWER_LINE.finditer(text)
              if not any(s <= m.start() < e for s, e, _ in boxed)]
    if not found:
        return None
    return clean_answer(max(found)[1]) or None
