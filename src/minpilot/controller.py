"""JSON decisions with bounded read-only memory access and one repair request."""
import json

from minpilot.llm.client import json_schema_format
from minpilot.runtime.trace import BudgetExceeded, InfraError
from minpilot.prompts.schemas import decision_schema


class DecisionError(ValueError):
    def __init__(self, message, responses=()):
        super().__init__(message)
        self.responses = list(responses)


def decide(client, trace, memory, *, stage, system, payload, validate, with_raw=False):
    messages = [{"role": "system", "content": system},
                {"role": "user", "content": json.dumps(payload, ensure_ascii=False)}]
    reads = repairs = 0
    responses = []
    fmt = json_schema_format(stage.replace(".", "_"), decision_schema(stage))
    while True:
        try:
            with trace.tags(stage=stage):
                response = client.chat(messages, response_format=fmt)
            messages.append({"role": "assistant", "content": response.content})
            responses.append(response.content)
            data = response.parsed
            if not isinstance(data, dict):
                try:
                    data = json.loads(response.content)
                except (ValueError, TypeError):
                    raise DecisionError("reply must be a JSON object")
            if not isinstance(data, dict):
                raise DecisionError("reply must be a JSON object")
            if data.get("action") == "read_memory":
                if reads >= 3:
                    raise DecisionError("read_memory limit is three rounds; return a decision")
                refs = data.get("refs")
                if not isinstance(refs, list) or not refs or not all(isinstance(r, str) for r in refs):
                    raise DecisionError("read_memory requires nonempty refs list")
                records = [memory.read(r) for r in refs]
                reads += 1
                trace.event("read_memory", stage=stage, refs=refs, records=records, round=reads)
                messages.append({"role": "user", "content": json.dumps({"memory": records}, ensure_ascii=False)})
                continue
            validate(data)
            trace.event("decision", stage=stage, input=payload, output=data, memory_rounds=reads)
            return (data, response.content) if with_raw else data
        except (BudgetExceeded, InfraError):
            raise
        except Exception as error:
            trace.event("decision_error", stage=stage, error=repr(error), repair=repairs)
            if repairs:
                raise DecisionError(str(error), responses) from error
            repairs += 1
            messages.append({"role": "user", "content": f"Invalid response: {error}. Correct once using the contract."})
