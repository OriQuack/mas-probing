"""The orchestrator: decides one action per turn (delegate a subtask to a worker role, or finish with the answer).

It has no tools and never sees files: everything goes through workers. Actions come as strict JSON-schema output
(the orchestrator model runs at reasoning effort high, which on Chat Completions allows no function calling).
The conversation is a plain message list owned by the harness (and saved in checkpoints):

    system, user(task), assistant(action JSON), user(report), assistant(action JSON), user(report), ...

An invalid action (unknown worker, missing fields) gets an error message and another turn, up to
`max_invalid` times per step; then the run errors (`invalid_action`).
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from minpilot.agents import prompts
from minpilot.llm.client import LLMClient, json_schema_format


class InvalidAction(Exception):
    pass


@dataclass
class Action:
    kind: str                 # delegate | finish
    rationale: str
    worker_id: str | None = None
    instruction: str | None = None
    answer: str | None = None
    raw: dict | None = None


class Orchestrator:
    def __init__(self, client: LLMClient, roles: list[dict], max_delegations: int, max_invalid: int = 2, *,
                 answer_format: str):
        self.client = client
        self.roles = {r["id"]: r for r in roles}
        self.max_delegations = max_delegations
        self.answer_format = answer_format  # the benchmark's answer rules
        self.max_invalid = max_invalid
        self.format = json_schema_format("orchestrator_action", prompts.orchestrator_action_schema(len(roles)))
        self.last_invalid: list[str] = []

    def initial_messages(self, original_task: str) -> list[dict]:
        return [{"role": "system", "content": prompts.orchestrator_system(list(self.roles.values()),
                                                                           self.max_delegations, self.answer_format)},
                {"role": "user", "content": prompts.orchestrator_task_message(original_task)}]

    def next_action(self, messages: list[dict], must_finish: bool = False) -> Action:
        """Appends the assistant turn(s) (and error feedback) to `messages` and returns a valid action."""
        self.last_invalid = []  # problems of the invalid replies before this action (logged by the harness)
        if must_finish:
            messages.append({"role": "user", "content": prompts.FORCE_FINISH})
        for _ in range(self.max_invalid + 1):
            res = self.client.chat(messages, response_format=self.format)
            messages.append({"role": "assistant", "content": res.content})
            problem, action = self._parse(res.parsed, must_finish)
            if action:
                return action
            self.last_invalid.append(problem)
            messages.append({"role": "user", "content": prompts.invalid_action_message(problem)})
        raise InvalidAction(problem)

    def _parse(self, d, must_finish: bool) -> tuple[str, Action | None]:
        if not isinstance(d, dict):
            return "the reply was not a JSON object.", None
        kind = d.get("action")
        if kind == "finish":
            if not (d.get("answer") or "").strip():
                return "`finish` needs a non-empty `answer`.", None
            return "", Action("finish", d.get("rationale") or "", answer=d["answer"].strip(), raw=d)
        if kind == "delegate":
            if must_finish:
                return "no delegations are left; you must `finish`.", None
            # one role: nothing to choose (the schema has no worker_id); the role is filled in here
            wid = next(iter(self.roles)) if len(self.roles) == 1 else (d.get("worker_id") or "").strip()
            if wid not in self.roles:
                return f"unknown worker_id {wid!r}; choose one of {sorted(self.roles)}.", None
            if not (d.get("instruction") or "").strip():
                return "`delegate` needs a non-empty `instruction`.", None
            return "", Action("delegate", d.get("rationale") or "", worker_id=wid,
                              instruction=d["instruction"].strip(), raw=d)
        return f"unknown action {json.dumps(kind)}.", None
