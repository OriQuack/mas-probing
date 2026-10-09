"""Block content that may publish GAIA answers or solutions (CLAUDE.md "Tools and task scope").

BLOCKLIST_VERSION is recorded with every run (ToolConfig). v2 (2026-10-07) closes the gaps found in the v0
overnight runs (labels/SUMMARY.md): a benchmark mirror under another name (huggingface.co/datasets/
kshitijthakkar/smoltrace-benchmark-v1), leaderboard pages, a paper printing agent traces on a task, SEO pages
that restate a task question, and searches aimed at the benchmark.

Copied from the previous pilot (rules v3); v4 is min_pilot's own. In min_pilot it is applied wherever outside text reaches a
model (tools/web.py, tools/sandbox.py): search queries, search results (title + snippet), page reads (live and
cache hits, final URL after redirects), Wayback snapshots, files that did not come with the task, and
run_python output.

- query_block_reason: searches that target the benchmark ("GAIA benchmark", site:huggingface.co datasets).
- url_block_reason: dataset/space/API pages on Hugging Face (any name), GAIA-named repos, the GAIA paper.
- content_block_reason, each rule a specific piece of evidence (never a single generic word):
    contains_gaia_task_id     a GAIA task id (other than the current task's own attachment names)
    quotes_task_question      the first 80 normalised characters of the current question
    restates_task_question    >= 50% of the question's word 6-grams (SEO pages generated from questions)
    gaia_benchmark_marker     a benchmark identifier: "GAIA benchmark", "gaia-benchmark", "gaia_<n>",
                              "General AI Assistants", "GAIA leaderboard/validation/test set"
    agent_trace_on_task       agent-trace wording (multi-agent, agent dialogue/trajectory/trace, smolagents,
                              tool call) AND overlap with the current question (a shared word 6-gram or a
                              distinctive token such as a DOI)
    agent_eval_on_task (v3)   agent-evaluation wording (agentic, LLM/AI/web/research agent(s), auto-eval,
                              agent-as-a-judge, agent benchmark/evaluation, deep research) AND at least 3 of the
                              question's content words (>= 5 letters, not common words; compared by their
                              first 6 letters). v2 gap: arXiv 2508.05508
                              (an agent-judge paper discussing GAIA tasks in prose, no trace wording) reached the
                              model through a search snippet in Qwen v2's bda648d7 run.
v3 (2026-10-08) adds agent_eval_on_task and the URL rule `known_task_discussion` (papers found discussing GAIA
tasks; extended when the audit finds one).
v5 (2026-10-08, min_pilot; v4 was an intermediate never used for recorded results) closes gaps found by labelling
the first min_pilot baseline (outputs/sessions/pilot-base-20261008T155247Z/labels):
  - URL rules for query-echo and Q/A-aggregator pages (`query_echo_page`, `qa_aggregator`) and more known task
    discussions (a blog, two OpenReview agent-trace attachments);
  - quotes_task_question compares letters and digits only, so hyphenation and line breaks ("end- note") do not
    defeat it;
  - agent_trace_on_task also fires on "sub-task N:" trace wording, and on trace wording plus >= 3 of the
    question's content words (a trace snippet that paraphrases the task shares no word 6-gram with it);
  - web.py blocks a URL for the rest of the run once any rule blocked it (decisions used to differ per snippet).
v6 (2026-10-08, from labelling the v5 baseline): URL rules for benchmark/leaderboard pages with a `gaia` path
segment (hal.cs.princeton.edu/reliability/benchmark/gaia/analysis/ passed the content rules in 2 runs whenever its
snippet did not start with the question) and more known task discussions (an AAAI paper quoting a task, an agent log in a GitHub issue).
"""

from __future__ import annotations

import re
from functools import lru_cache

import pandas as pd

from minpilot.data.gaia import GAIA_ROOT

BLOCKLIST_VERSION = "v6"

_URL_RULES = [
    (re.compile(r"gaia[-_]?benchmark", re.I), "gaia_benchmark_url"),
    # v6: benchmark / leaderboard / eval sites with a `gaia` path segment, e.g. .../benchmark/gaia/analysis/,
    # .../suite/gaia/task/<id>
    (re.compile(r"/(benchmarks?|leaderboards?|suites?|evals?|evaluations?|reliability)/gaia(/|$|[?#])", re.I),
     "gaia_benchmark_url"),
    (re.compile(r"/gaia/(analysis|tasks?|leaderboard|results|validation|test)(/|$|[?#])", re.I), "gaia_benchmark_url"),
    # Hugging Face datasets, spaces and their APIs/raw files, under ANY name: benchmark mirrors and agent-eval
    # dumps are published there under names without "gaia" (v0 leak). Model pages stay reachable.
    (re.compile(r"^https?://([a-z0-9-]+\.)*(huggingface\.co|hf\.co)/(api/)?(datasets|spaces)(/|$)", re.I), "hf_dataset_or_space"),
    (re.compile(r"^https?://datasets-server\.huggingface\.co/", re.I), "hf_dataset_or_space"),
    (re.compile(r"^https?://([a-z0-9-]+\.)*(huggingface\.co|hf\.co|hf\.space)/.*gaia", re.I), "hf_gaia"),
    (re.compile(r"^https?://([a-z0-9-]+\.)*(github\.com|githubusercontent\.com|gitlab\.com)/.*gaia", re.I), "git_gaia"),
    # The GAIA paper (shows example questions with answers).
    (re.compile(r"arxiv\.org/(abs|pdf|html)/2311\.12983", re.I), "gaia_paper"),
    # Papers found discussing GAIA tasks (with their content) in prose; audit finds, extended over time.
    (re.compile(r"arxiv\.org/(abs|pdf|html)/2508\.05508", re.I), "known_task_discussion"),
    (re.compile(r"ehudreiter\.com/2023/12/11/what-llms-cannot-do", re.I), "known_task_discussion"),  # v5
    (re.compile(r"openreview\.net/(attachment|pdf|forum)\?id=(YTyfu1bU04|UoM3G7nKr0)\b", re.I),
     "known_task_discussion"),  # v5: agent-trace papers on GAIA tasks
    (re.compile(r"ojs\.aaai\.org/index\.php/AAAI/article/view/40594\b", re.I), "known_task_discussion"),  # v6
    (re.compile(r"github\.com/MeetKai/functionary/issues/223\b", re.I), "known_task_discussion"),  # v6: agent log
    # v5: pages generated from other people's search queries or Q/A "triples": they restate a task as keywords
    # with an answer, and share too few word 6-grams with the question for the content rules (min_pilot
    # pilot-base 2026-10-08: bda648d7 r2 received a nuggetpedia snippet stating the answer).
    (re.compile(r"^https?://([a-z0-9-]+\.)*nuggetpedia\.com/", re.I), "qa_aggregator"),
    (re.compile(r"^https?://([a-z0-9-]+\.)*instagram\.com/popular/", re.I), "query_echo_page"),
]

_QUERY_TARGETING = re.compile(
    r"(?i)(\bgaia\b.*\b(benchmark|leaderboard|dataset|hugging ?face|validation|test set|answers?|solutions?|tasks?|questions?)\b"
    r"|\b(benchmark|leaderboard|dataset|hugging ?face)\b.*\bgaia\b"
    r"|site:\s*(huggingface\.co|hf\.co)"
    r"|gaia[-_]?benchmark|smoltrace)")

_BENCHMARK_MARKER = re.compile(
    r"(?i)gaia[-_ ]benchmark|\bgaia_\d+\b|general ai assistants?\b|\bgaia (leaderboard|validation( set)?|test set)\b")
_TRACE_MARKER = re.compile(
    r"(?i)\bmulti-?agent\b|\bagent'?s?\s+(dialogue|trajector(y|ies)|traces?|logs?)\b|\bsmolagents\b|\btool[- ]calls?\b"
    r"|\bsub-?task\s*\d+\s*:")
_AGENT_EVAL = re.compile(
    r"(?i)\bagentic\b|\b(llm|ai|web|research|language[- ]model|autonomous|generalist)[- ]agents?\b"
    r"|\bauto[- ]?eval|\b(agent|llm)[- ]as[- ]a[- ]judge\b|\bagent (benchmark|evaluation)s?\b"
    r"|\bdeep research\b")
# Common words that do not make a question's content distinctive (>= 5 letters only; shorter words never count).
_COMMON = frozenset("""about above after again against among answer before being below between could
during either every first found given group these those their there where which while
whose would should other others under until using whether without within world years number numbers
include included including later least little might never often order place please point since small
still three total until value where words write written""".split())
_DISTINCTIVE = re.compile(r"[A-Za-z0-9]*\d[A-Za-z0-9./:_-]{6,}[A-Za-z0-9]")  # DOIs, ids, long numbers
_WORD = re.compile(r"[a-z0-9]+")
_WS = re.compile(r"\W+")


@lru_cache(maxsize=1)
def gaia_task_ids() -> frozenset[str]:
    ids: set[str] = set()
    for split in ("validation", "test"):
        path = GAIA_ROOT / split / "metadata.parquet"
        if path.exists():
            ids.update(pd.read_parquet(path, columns=["task_id"])["task_id"])
    return frozenset(ids)


def url_block_reason(url: str) -> str | None:
    for pattern, reason in _URL_RULES:
        if pattern.search(url or ""):
            return reason
    return None


def query_block_reason(query: str) -> str | None:
    return "targets_benchmark" if _QUERY_TARGETING.search(query or "") else None


def _norm(text: str) -> str:
    return _WS.sub(" ", text.lower()).strip()


def _squash(text: str) -> str:
    """Letters and digits only (v5): hyphenation, line breaks and punctuation do not matter."""
    return re.sub(r"[^a-z0-9]", "", text.lower())


def _sixgrams(text: str) -> set[tuple[str, ...]]:
    w = _WORD.findall(text.lower())
    return {tuple(w[i:i + 6]) for i in range(len(w) - 5)}


@lru_cache(maxsize=64)
def _question_features(question: str) -> tuple[frozenset, frozenset]:
    return frozenset(_sixgrams(question)), frozenset(t for t in _DISTINCTIVE.findall(question))


@lru_cache(maxsize=64)
def _question_content_words(question: str) -> frozenset[str]:
    """Distinctive words of the question as 6-letter prefixes (a light stemming: Vietnamese ~ Vietnam)."""
    return frozenset(w[:6] for w in _WORD.findall(question.lower())
                     if len(w) >= 5 and not w.isdigit() and w not in _COMMON)


def _content_overlap(text: str, question: str) -> int:
    return len(_question_content_words(question) & {w[:6] for w in _WORD.findall(text.lower())})


def content_block_reason(text: str, question: str | None = None, allowed: tuple[str, ...] = ()) -> str | None:
    """`allowed`: exact strings exempt from the task-id rule (the current task's own attachment names, which
    are `<task_id>.<ext>`); they are removed before checking, everything else is checked as is."""
    if not text:
        return None
    probe_text = text
    for a in allowed:
        if a:
            probe_text = probe_text.replace(a, "")
    if any(tid in probe_text for tid in gaia_task_ids()):
        return "contains_gaia_task_id"
    if _BENCHMARK_MARKER.search(text):
        return "gaia_benchmark_marker"
    if question:
        probe = _squash(question)[:70]
        if len(probe) >= 35 and probe in _squash(text):
            return "quotes_task_question"
        q_grams, q_tokens = _question_features(question)
        if q_grams or q_tokens:
            t_grams = _sixgrams(text) if q_grams else set()
            shared = len(q_grams & t_grams)
            if len(q_grams) >= 5 and shared / len(q_grams) >= 0.5:
                return "restates_task_question"
            if _TRACE_MARKER.search(text) and (shared or any(tok in text for tok in q_tokens)
                                               or _content_overlap(text, question) >= 3):
                return "agent_trace_on_task"
        if _AGENT_EVAL.search(text) and _content_overlap(text, question) >= 3:
            return "agent_eval_on_task"
    return None
