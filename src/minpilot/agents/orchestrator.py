"""The orchestrator: one conversation per run, acting through tool calls.

The harness opens the conversation with the task, the workers and the budget, asks for the next actions and returns
each action's reports as that tool call's result. One message may carry several `probe`/`execute` calls; they run in
the order given. `finish` runs only as the sole call of its message. A reply without a tool call gets one reminder;
an invalid call gets its error as its tool result while the valid calls of the message still run. A message with no
valid call is chosen again, at most twice in a row. When no executions remain, only `finish` is offered and a tool
call is required.
"""

from __future__ import annotations

import json

from minpilot import prompts
from minpilot.llm.client import LLMClient
from minpilot.prompts.schemas import action_tools

MAX_INVALID_CALLS = 2


class DecisionError(ValueError):
    pass


class Orchestrator:
    def __init__(self, client: LLMClient, trace):
        self.client, self.trace = client, trace
        self.messages: list[dict] = []

    def start(self, first_message: str) -> None:
        self.messages = [{"role": "system", "content": prompts.ORCHESTRATOR},
                         {"role": "user", "content": first_message}]

    def next_actions(self, available: list[str], validate) -> list[dict]:
        """The valid actions of the next message, in order. `validate(name, args, accepted)` returns the resolved
        action or raises ValueError, whose message is returned to the model; `accepted` lists the actions already
        accepted from the same message. Each action carries `tool_call_id`, `args` and the text the model wrote with
        the calls (`note`); `reply` later answers each call."""
        tools = action_tools(available)
        required = available == ["finish"]
        reminded, invalid = False, 0
        while True:
            response = self.client.chat(self.messages, tools=tools, tool_choice="required" if required else None)
            self.messages.append(dict(response.message))
            calls = response.tool_calls
            if not calls:
                if reminded:
                    raise DecisionError("the orchestrator replied twice without a tool call")
                reminded = True
                self.messages.append({"role": "user", "content": prompts.CHOOSE_ACTION})
                continue
            actions, errors = [], []
            for call in calls:
                name = call["function"]["name"]
                try:
                    args = json.loads(call["function"].get("arguments") or "{}")
                    if not isinstance(args, dict):
                        raise ValueError("arguments must be a JSON object")
                    if name not in available:
                        raise ValueError(f"{name!r} is not available; use one of {', '.join(available)}")
                    if name == "finish" and len(calls) > 1:
                        raise ValueError("call `finish` alone in its own message, after the reports you need")
                    action = validate(name, args, actions)
                except ValueError as error:
                    errors.append(str(error))
                    self.trace.event("decision_error", stage="orchestrator", error=str(error), call=call)
                    self.reply(call["id"], f"Error: {error}. This call was not run.")
                    continue
                actions.append({**action, "tool_call_id": call["id"], "args": args, "note": response.content or ""})
            if not actions:
                invalid += 1
                if invalid >= MAX_INVALID_CALLS:
                    raise DecisionError(f"invalid tool call: {errors[-1]}")
                continue
            self.trace.event("decision", stage="orchestrator", output=actions)
            return actions

    def reply(self, tool_call_id: str, text: str) -> None:
        self.messages.append({"role": "tool", "tool_call_id": tool_call_id, "content": text})
