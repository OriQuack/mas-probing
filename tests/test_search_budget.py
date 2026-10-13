"""Actual Serper request boundary, fake HTTP only: retries/cache/forks/restore."""
import requests
import pytest
from minpilot.tools.backends import SerperBackend
from minpilot.tools.cache import ToolCache
from minpilot.tools.config import ToolConfig
from minpilot.tools.web import WebTools
from minpilot.tools.search_budget import PaidSearchBudget, SearchLimit
from fakes import FakeReader, FakeSearch


class Response:
    def __init__(self, code=200):
        self.status_code = code
        self.text = "error" if code != 200 else "ok"
        self.headers = {"Retry-After": "0"}
    def json(self):
        return {"organic": [{"title": "Example", "link": "https://example.org/a", "snippet": "source"}]}


def web_with_http(tmp_path, monkeypatch, replies=None):
    cfg = ToolConfig(cache_path=tmp_path / "cache.sqlite", min_interval_s={"serper": 0}, credit_reserve={"serper": 0})
    monkeypatch.setenv("SERPER_API_KEY", "fake")
    backend = SerperBackend(cfg)
    backend.balance = lambda: 100000
    free = FakeSearch()
    free.name = "ddg"
    web = WebTools(cfg, search_backends=[backend, free], read_backends=[FakeReader()])
    requests_sent = []
    def post(*args, **kwargs):
        requests_sent.append(kwargs["json"]["q"])
        result = replies.pop(0) if replies else Response()
        if isinstance(result, Exception):
            raise result
        return result
    monkeypatch.setattr(requests, "post", post)
    return web, requests_sent


def test_cap_shared_across_probe_execution_cache_and_restore(tmp_path, monkeypatch):
    web, sent = web_with_http(tmp_path, monkeypatch)
    probe = web.fork()
    for i in range(50):
        probe.web_search(f"probe source {i}")
    for i in range(50):
        web.web_search(f"execution source {i}")
    assert len(sent) == 100
    assert web.state_dict()["paid_search"]["billed"] == 100
    text, rec = probe.web_search("new source")
    assert len(sent) == 100 and rec["paid_search_limited"] and rec["backend"] == "ddg"
    assert "credit limit" in text
    _, rec = web.web_search("probe source 0")
    assert rec["cache_hit"] and len(sent) == 100
    state = web.state_dict()
    restored, restored_sent = web_with_http(tmp_path, monkeypatch)
    restored.load_state_dict(state)
    text, rec = restored.web_search("after checkpoint")
    assert not restored_sent and rec["paid_search_limited"]


def test_429_retry_nonbillable_unknown_attempts_consume_headroom(tmp_path, monkeypatch):
    web, sent = web_with_http(tmp_path, monkeypatch, [Response(429), Response(), requests.Timeout("unknown"), Response(503)])
    web.web_search("retry source")
    web.web_search("timeout source")
    web.pinned_search = "serper"
    _, rec = web.web_search("server failure")
    counters = web.paid_search.dump()
    assert counters == {"limit": 100, "billed": 1, "unknown": 2, "nonbillable": 1, "inflight": 0}
    assert len(sent) == 4
    assert rec["unknown_credits"] == {"serper": 1}
    assert rec["credits"] == {}


def test_last_credit_retry_is_allowed_after_429(tmp_path, monkeypatch):
    web, sent = web_with_http(tmp_path, monkeypatch, [Response(429), Response()])
    web.paid_search.billed = 99
    web.web_search("last credit")
    assert len(sent) == 2 and web.paid_search.billed == 100
    web.web_search("blocked paid request")
    assert len(sent) == 2


def test_reservations_are_atomic_and_invalid_restore_rejected():
    budget = PaidSearchBudget()
    for _ in range(100):
        budget.reserve()
    with pytest.raises(SearchLimit):
        budget.reserve()
    with pytest.raises(ValueError):
        budget.load(budget.dump())
    for _ in range(100):
        budget.settle("nonbillable")
    budget.reserve()
    budget.settle("billed")
    assert budget.dump()["billed"] == 1


def test_harness_forks_and_checkpoint_keep_paid_headroom(tmp_path, task, monkeypatch):
    from fakes import ScriptedLLM
    from test_harness import action, evaluation
    from minpilot.config import RunConfig, ConditionConfig, load_pool
    from minpilot.harness import Run
    web, sent = web_with_http(tmp_path, monkeypatch)
    web.paid_search.billed = 99  # prefix already spent before this delegation checkpoint
    def script():
        return {"orchestrator": [action("probe", wid=None), action("execute", wid="gen_haiku"), action("finish")],
                "worker": [{"tool_calls": [("web_search", {"query": "probe one source"})]}, "Title: Probe one\nplan: read",
                           {"tool_calls": [("web_search", {"query": "probe two source"})]}, "Title: Probe two\nplan: read",
                           {"tool_calls": [("web_search", {"query": "execution source"})]}, "Title: Execution\n2"],
                "evaluator_probe": [evaluation()],
                "evaluator_execution": [evaluation()]}
    run = Run(RunConfig(load_pool("multi"), ConditionConfig("adaptive_probe")), task, tmp_path / "run",
              web=web, tool_cfg=web.cfg, transport=ScriptedLLM(script()))
    assert run.run_fresh()["status"] == "ok"
    assert len(sent) == 1 and run.web.paid_search.billed == 100
    assert "credit limit" in run.memory.read(run.memory.read("a00002")["tool_ids"][0])["content"]
    # Restore starts from the pre-probe 99-credit prefix; cache hits never spend its remaining credit.
    restored_web, restored_sent = web_with_http(tmp_path, monkeypatch)
    restored_script = script()
    restored_script["orchestrator"] = [action("execute", wid="gen_haiku"), action("finish")]
    restored = Run.restore(run.run_dir / "checkpoints/a0", tmp_path / "restored", task=task,
        web=restored_web, tool_cfg=web.cfg, transport=ScriptedLLM(restored_script))
    assert restored.web.paid_search.billed == 99
    assert restored.run_restored()["status"] == "ok"
    assert not restored_sent and restored.web.paid_search.billed == 99
