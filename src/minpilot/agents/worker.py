"""Workers with one conversation per run, a bounded tool loop and preserved partial evidence.

Each worker keeps its conversation for the whole run: probe and execution requests are turns of it, and every
request uses that worker's own workspace. A request that raises leaves the conversation as it was before the
request. A forced final turn reports at the worker tool limit. The shared trace counts all model/tool calls and
retains raw outputs.
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
    messages: list[dict]        # this request's turn: its user message, model replies and tool results
    status: str                 # ok | tool_limit | empty
    n_tool_calls: int = 0
    tools_used: list[str] = field(default_factory=list)


class Worker:
    def __init__(self, spec: WorkerSpec, client: LLMClient):
        self.spec = spec
        self.client = client
        self.messages: list[dict] = []  # the conversation so far; empty before the first request
        self.input_tokens = 0           # prompt tokens of the latest completed model call
        self.last_messages: list[dict] = []

    @property
    def id(self) -> str:
        return self.spec.id

    def system_message(self, kind: str = "task") -> dict:
        render = prompts.probe_system if kind == "probe" else prompts.worker_system
        return {"role": "system", "content": render(self.spec.system_prompt, self.spec.tools)}

    def run(self, original_task: str, instruction: str, toolbox: Toolbox, *, allow_tools: bool = True,
            max_tool_calls: int | None = None, kind: str = "task", context: str = "") -> WorkerCall:
        """One request in this worker's conversation. `kind` is "task" (execution: the request states this call's
        tool-call limit) or "probe" (review questions). The first request carries the original task; later
        requests carry only the new context and instruction. The system message follows the request's kind."""
        limit = self.spec.max_tool_calls if max_tool_calls is None else max_tool_calls
        tools = tool_schemas(self.spec.tools) if allow_tools and self.spec.tools else None
        tool_limit = limit if tools is not None else None
        if self.messages:
            request = prompts.continuation_request(instruction, context=context, kind=kind, tool_limit=tool_limit)
        else:
            request = prompts.worker_request(original_task, instruction, context=context, kind=kind,
                                             tool_limit=tool_limit)
        history = [self.system_message(kind), *self.messages[1:]]
        turn = [{"role": "user", "content": request}]
        self.last_messages = turn  # preserve partial evidence if a later model call fails
        n, used, status = 0, [], "ok"
        for _ in range(limit + 2):
            forced = tools is not None and n >= limit
            if forced:
                limit_message = prompts.PROBE_TOOL_LIMIT_REACHED if kind == "probe" else prompts.TOOL_LIMIT_REACHED
                turn.append({"role": "user", "content": limit_message})
                status = "tool_limit"
            res = self.client.chat(history + turn, tools=tools, tool_choice="none" if forced else None)
            self.input_tokens = int((res.usage or {}).get("prompt_tokens") or 0)
            message = dict(res.message)
            if not res.tool_calls or forced or tools is None:
                message.pop("tool_calls", None)  # a forced/no-tool turn is the report; drop stray calls
                turn.append(message)
                report = message.get("content") or ""
                self.messages = history + turn
                return WorkerCall(report, turn, status if report.strip() else "empty", n, used)
            turn.append(message)
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
                turn.append({"role": "tool", "tool_call_id": tc["id"], "content": out_text})
            if images:
                turn.append({"role": "user", "content": [{"type": "text", "text": prompts.IMAGES_FOLLOW}]
                             + [{"type": "image_url", "image_url": {"url": u}} for u in images]})
        raise RuntimeError("worker loop did not terminate")  # unreachable: the forced turn always returns
