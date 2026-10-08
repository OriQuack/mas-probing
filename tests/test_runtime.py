"""LLM client checks, budgets, configs, tools sandbox and leakage guards."""

from __future__ import annotations

import json

import pytest

from fakes import ScriptedLLM, fake_web
from minpilot.config import CONFIG_DIR, load_pool, load_refiner
from minpilot.data.gaia import GaiaTask
from minpilot.llm.client import LLMClient, TransientError
from minpilot.llm.specs import get_spec
from minpilot.runtime.trace import BudgetExceeded, InfraError, Limits, Trace
from minpilot.tools.config import REPO_ROOT
from minpilot.tools.toolbox import Toolbox


def client(tmp_path, key, llm, limits=None):
    return LLMClient(get_spec(key), Trace(tmp_path / "tr", limits), transport=llm, sleep=lambda s: None)


# -- client ------------------------------------------------------------------------------------
def test_request_pins_provider_and_reasoning(tmp_path):
    llm = ScriptedLLM({"worker": ["hi"]})
    client(tmp_path, "luna", llm).chat([{"role": "user", "content": "x"}])
    b = llm.bodies[0]
    assert b["provider"] == {"only": ["openai"], "allow_fallbacks": False, "require_parameters": True,
                             "data_collection": "deny"}
    assert b["reasoning"] == {"effort": "none"} and b["max_tokens"] == 8192


def test_effort_high_key_refuses_tools(tmp_path):
    with pytest.raises(ValueError, match="must not receive tools"):
        client(tmp_path, "luna-high", ScriptedLLM({})).chat([{"role": "user", "content": "x"}],
                                                            tools=[{"type": "function", "function": {"name": "f"}}])


def test_wrong_provider_is_infra_error(tmp_path):
    with pytest.raises(InfraError, match="served by provider"):
        client(tmp_path, "luna", ScriptedLLM({"worker": ["x"]}, provider="Azure")).chat([{"role": "user", "content": "x"}])


def test_missing_cost_is_infra_error(tmp_path):
    llm = ScriptedLLM({"worker": ["x"]})
    orig = llm.__call__

    def no_cost(body, t):
        r = orig(body, t)
        r["usage"].pop("cost")
        return r

    with pytest.raises(InfraError, match="no cost"):
        client(tmp_path, "luna", no_cost).chat([{"role": "user", "content": "x"}])


def test_transient_errors_retried_and_recorded(tmp_path):
    llm = ScriptedLLM({"worker": [TransientError("HTTP 503"), "ok"]})
    c = client(tmp_path, "luna", llm)
    assert c.chat([{"role": "user", "content": "x"}]).content == "ok"
    recs = [json.loads(l) for l in (tmp_path / "tr" / "llm_calls.jsonl").read_text().splitlines()]
    assert [r["status"] for r in recs] == ["started", "error", "started", "ok"]
    assert c.trace.run_scope.llm_calls == 2


def test_cost_cap_refuses_before_sending(tmp_path):
    llm = ScriptedLLM({"worker": ["x"]})
    with pytest.raises(BudgetExceeded):
        client(tmp_path, "luna", llm, Limits(max_cost_usd=0.001)).chat([{"role": "user", "content": "x"}])
    assert llm.bodies == []  # the worst case (8192 output tokens) did not fit; nothing was sent


def test_reasoning_details_kept_for_gemini(tmp_path):
    def reply(body, t):
        return {"id": "g", "provider": "Google AI Studio", "model": body["model"],
                "choices": [{"message": {"role": "assistant", "content": "a", "reasoning_details": [{"x": 1}]}}],
                "usage": {"cost": 1e-6}}

    res = client(tmp_path, "gemini", reply).chat([{"role": "user", "content": "x"}])
    assert res.message["reasoning_details"] == [{"x": 1}]


# -- configs -----------------------------------------------------------------------------------
@pytest.mark.parametrize("name", sorted(p.stem for p in (CONFIG_DIR / "pools").glob("*.yaml")))
def test_pools_load(name):
    pool = load_pool(name)
    for role in pool.roles.values():
        tools = {pool.workers[w].tools for w in (role.executor, *role.probe_workers)}
        assert len(tools) == 1, "probe workers of a role get the same tools as its executor"


@pytest.mark.parametrize("name", sorted(p.stem for p in (CONFIG_DIR / "refiners").glob("*.yaml")))
def test_refiners_load(name):
    load_refiner(name)


def test_B_and_C_share_budget_caps():
    b, c = load_refiner("B_self_review"), load_refiner("C_probe")
    assert b.budget == c.budget and b.max_verifications == c.max_verifications
    assert b.samples_per_worker == c.samples_per_worker and b.questions == c.questions


# -- tools -------------------------------------------------------------------------------------
def toolbox(tmp_path, question="q"):
    work = tmp_path / "work"
    (work / "attachments").mkdir(parents=True)
    return Toolbox(work, fake_web(tmp_path, question), Trace(tmp_path / "tr"), question=question)


def test_file_tools_confined_to_workspace(tmp_path):
    tb = toolbox(tmp_path)
    (tmp_path / "secret.txt").write_text("secret")
    out = tb.call("read_file", {"path": "../secret.txt"}, ("read_file",))
    assert "outside the working directory" in out.text
    assert "not available" in tb.call("run_python", {"code": "1"}, ("read_file",)).text


def test_web_tools_blocklist_and_cache(tmp_path):
    tb = toolbox(tmp_path)
    out = tb.call("web_search", {"query": "GAIA benchmark answers"}, ("web_search",))
    assert "not permitted" in out.text
    assert "not permitted" in tb.call("read_url", {"url": "https://huggingface.co/datasets/x"}, ("read_url",)).text
    first = tb.call("read_url", {"url": "https://example.org/a"}, ("read_url",)).text
    assert first == tb.call("read_url", {"url": "https://example.org/a"}, ("read_url",)).text


def test_view_image_returns_image(tmp_path):
    from PIL import Image

    tb = toolbox(tmp_path)
    Image.new("RGB", (40, 20), "red").save(tb.work_dir / "attachments" / "x.png")
    out = tb.call("view_image", {"path": "attachments/x.png"}, ("view_image",))
    assert out.images and out.images[0].startswith("data:image/png;base64,") and "40x20" in out.text


@pytest.mark.landlock
def test_sandbox_blocks_repo_network_and_processes(tmp_path):
    tb = toolbox(tmp_path)
    run = lambda code: tb.call("run_python", {"code": code}, ("run_python",)).text  # noqa: E731
    assert "Permission denied" in run(f"print(open({str(REPO_ROOT / 'pyproject.toml')!r}).read())")
    assert "Network access is not permitted" in run("import urllib.request; urllib.request.urlopen('http://example.org')")
    assert "Starting processes is not permitted" in run("import os; os.system('ls')")
    assert "hello" in run("open('f.txt','w').write('hello'); print(open('f.txt').read())")
    assert str(tb.work_dir) not in run("import os; print(os.getcwd())")


@pytest.mark.landlock
@pytest.mark.gaia_data
def test_sandbox_cannot_read_gaia_answers(tmp_path):
    from minpilot.data.gaia import GAIA_ROOT

    tb = toolbox(tmp_path)
    p = GAIA_ROOT / "validation" / "metadata.parquet"
    out = tb.call("run_python", {"code": f"import pandas as pd; print(pd.read_parquet({str(p)!r}).shape)"},
                  ("run_python",)).text
    assert "Permission denied" in out or "Error" in out


@pytest.mark.gaia_data
def test_tasks_carry_no_ground_truth():
    from minpilot.data.gaia import load_tasks

    t = load_tasks()[0]
    assert set(GaiaTask.__dataclass_fields__) == {"task_id", "level", "question", "file_name", "file_path"}
    assert t.question
