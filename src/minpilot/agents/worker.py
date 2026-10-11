"""A worker: a registered (model, system prompt, tools) setting that answers one request with a tool loop.

Workers keep no state between calls: each call starts from the system prompt, unless the caller passes an earlier
conversation (`history`) to continue (probe follow-ups; the "connected" condition, where execution continues the
executor's probe conversation). Files are a separate matter: they live in the workspace the caller's toolbox is
bound to. The active system prompt follows the request kind, including when continuing a conversation.

Tool loop: the model may call tools until it answers without a tool call (the report) or reaches
`max_tool_calls`; then it is told to report now and called once more with `tool_choice="none"`. Images returned
by tools are shown in one user message after the tool results of that turn.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from minpilot import prompts
from minpilot.config import WorkerSpec
from minpilot.llm.client import LLMClient
from minpilot.tools.toolbox import Toolbox, tool_schemas


@dataclass
class WorkerCall:
    report: str
    messages: list[dict]
    status: str                 # ok | tool_limit | empty
    n_tool_calls: int = 0
    tools_used: list[str] = field(default_factory=list)


class Worker:
    def __init__(self, spec: WorkerSpec, client: LLMClient):
        self.spec = spec
        self.client = client

    @property
    def id(self) -> str:
        return self.spec.id

    def system_message(self, kind: str = "task") -> dict:
        render = prompts.probe_system if kind == "probe" else prompts.worker_system
        return {"role": "system", "content": render(self.spec.system_prompt, self.spec.tools)}

    def run(self, original_task: str, instruction: str, toolbox: Toolbox, *, allow_tools: bool = True,
            max_tool_calls: int | None = None, history: list[dict] | None = None,
            user_message: str | None = None, kind: str = "task", context: str = "") -> WorkerCall:
        """One request. `kind` is "task" (execution, checks: the request states this call's tool-call limit) or
        "probe" (review questions). `user_message` replaces the standard request text (used for follow-up
        questions, which continue a probe conversation). `context`: the delegation's context (F21), shown between
        the original task and the instruction."""
        limit = self.spec.max_tool_calls if max_tool_calls is None else max_tool_calls
        tools = tool_schemas(self.spec.tools) if allow_tools and self.spec.tools else None
        msgs = list(history) if history else [self.system_message(kind)]
        # Follow-ups retain probe policy; connected execution switches policy while retaining prior turns.
        if history:
            msgs[0] = self.system_message(kind)
        msgs.append({"role": "user", "content": user_message or prompts.worker_request(
            original_task, instruction, context=context, kind=kind, tool_limit=limit if tools is not None else None)})
        n, used, status = 0, [], "ok"
        for _ in range(limit + 2):
            forced = tools is not None and n >= limit
            if forced:
                limit_message = prompts.PROBE_TOOL_LIMIT_REACHED if kind == "probe" else prompts.TOOL_LIMIT_REACHED
                msgs.append({"role": "user", "content": limit_message})
                status = "tool_limit"
            res = self.client.chat(msgs, tools=tools, tool_choice="none" if forced else None)
            message = dict(res.message)
            if not res.tool_calls or forced or tools is None:
                message.pop("tool_calls", None)  # a forced/no-tool turn is the report; drop stray calls
                msgs.append(message)
                report = (message.get("content") or "").strip()
                return WorkerCall(report or "(the worker returned an empty report)", msgs,
                                  status if report else "empty", n, used)
            msgs.append(message)
            images: list[str] = []
            for tc in res.tool_calls:
                name = tc["function"]["name"]
                if n >= limit:
                    out_text = "Error: tool-call limit reached; this call was not executed."
                else:
                    n += 1
                    used.append(name)
                    out = toolbox.call(name, tc["function"].get("arguments") or "{}", self.spec.tools)
                    out_text = out.text
                    images += out.images
                msgs.append({"role": "tool", "tool_call_id": tc["id"], "content": out_text})
            if images:
                msgs.append({"role": "user", "content": [{"type": "text", "text": prompts.IMAGES_FOLLOW}]
                             + [{"type": "image_url", "image_url": {"url": u}} for u in images]})
        raise RuntimeError("worker loop did not terminate")  # unreachable: the forced turn always returns
