"""Offline contracts for no-probe, same-worker GAIA instruction comparison."""
import json
from pathlib import Path
import threading
import time

from minpilot.agents.worker import Worker
from minpilot.config import WorkerSpec
from minpilot.llm.client import LLMClient, RateLimited
from minpilot.llm.specs import get_spec
from minpilot.runtime.trace import Limits, Trace
from perturbation_consistency import gaia_instruction_execution as experiment
from tests.fakes import ScriptedLLM


def test_plan_covers_four_conditions_three_independent_repetitions():
    ids = [f'task-{i}' for i in range(34)]
    plan = experiment.make_plan(ids)
    assert len(plan) == len({r['slot'] for r in plan}) == 408
    assert {(r['task_id'], r['condition'], r['repetition']) for r in plan} == {
        (tid, arm, rep) for tid in ids for arm in experiment.ARMS for rep in range(3)}
    assert plan == experiment.make_plan(ids)
    assert max(r['repetition'] for r in plan[:136]) == 0


def test_same_worker_retains_tool_results_and_files_then_completes(tmp_path):
    fake = ScriptedLLM({'worker': [
        {'tool_calls': [('read_file', {'path': 'attachments/input.txt'})]},
        'intermediate observed value', 'evidence\nFinal answer: 42']})
    trace = Trace(tmp_path / 'trace', Limits(max_worker_calls=2))
    worker = Worker(WorkerSpec('executor', 'haiku-medium', ('read_file',), 'local worker', 20),
        LLMClient(get_spec('haiku-medium'), trace, transport=fake))
    class FakeToolbox:
        def call(self, name, arguments, allowed):
            from minpilot.tools.toolbox import ToolOutput
            (tmp_path / 'retained.txt').write_text('workspace state')
            return ToolOutput('original source value')
    saved = []
    result = experiment.run_protocol(worker, 'original task', 'extract intermediate only',
        'verify addon', FakeToolbox(), trace, lambda *args: saved.append(args))
    assert result.endswith('42')
    assert (tmp_path / 'retained.txt').read_text() == 'workspace state'
    assert [r[0] for r in saved] == ['first_subtask', 'completion']
    assert len(fake.bodies) == 3 and trace.run_scope.worker_calls == 2
    final = fake.bodies[-1]['messages']
    assert any(m.get('content') == 'original source value' for m in final)
    assert 'verify addon' in final[1]['content']
    assert experiment.CONTINUATION in final[-1]['content']
    assert trace.run_scope.worker_calls == 2  # no additional probe request


def test_429_switches_to_serial_and_is_not_charged(tmp_path):
    fake = ScriptedLLM({'worker': [RateLimited('429'), 'ok']})
    trace = Trace(tmp_path / 'trace')
    client = LLMClient(get_spec('haiku-medium'), trace,
        transport=experiment.AdaptiveTransport(tmp_path, fake), sleep=lambda seconds: None)
    assert client.chat([{'role': 'user', 'content': 'test'}]).content == 'ok'
    assert json.loads((tmp_path / 'serial_after_429.json').read_text())['parallel_runs'] == 1
    assert trace.run_scope.unknown_cost_calls == 0
    assert trace.run_scope.llm_calls == 2
    assert trace.run_scope.cost_usd == fake.cost


def test_serial_gate_excludes_concurrent_http_requests(tmp_path):
    (tmp_path / 'serial_after_429.json').write_text('{}')
    lock = threading.Lock()
    state = {'active': 0, 'maximum': 0}
    def send(body, timeout):
        with lock:
            state['active'] += 1
            state['maximum'] = max(state['maximum'], state['active'])
        time.sleep(.02)
        with lock:
            state['active'] -= 1
        return {}
    threads = [threading.Thread(target=lambda: experiment.AdaptiveTransport(tmp_path, send)({}, 1)) for _ in range(3)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert state['maximum'] == 1


def test_nonweb_image_url_is_blocked_before_fetch():
    toolbox = object.__new__(experiment.LocalToolbox)
    result, metadata = toolbox._t_view_image('https://example.org/image.png')
    assert metadata['error'] == 'local_only'
    assert 'local' in result.text


def test_worker_run_writes_two_turn_result_without_gold(tmp_path, monkeypatch):
    exp = tmp_path / 'experiment'
    (exp / 'runs').mkdir(parents=True)
    (exp / 'planned.csv').write_text('task_id,condition,repetition,slot\ntest,verify,0,test_verify_r0\n')
    (exp / 'inputs.jsonl').write_text(json.dumps(dict(task_id='test', question='Compute from supplied input',
        level=1, file_name=None, attachment_sha256=None)) + '\n')
    (exp / 'candidates.jsonl').write_text(json.dumps(dict(task_id='test', subtask='first assignment',
        instructions={'verify': 'check the result'})) + '\n')
    monkeypatch.setenv('OPENROUTER_API_KEY', 'offline-test-key')
    monkeypatch.setattr(experiment, 'verify', lambda path: dict(original_workspace=str(tmp_path),
        model=get_spec('haiku-medium').identity(), per_run_cost_usd=.2))
    fake = ScriptedLLM({'worker': ['intermediate', 'Final answer: 42']})
    monkeypatch.setattr(experiment, 'http_transport', lambda key: fake)
    experiment.worker_run(exp, 'test_verify_r0')
    result = json.loads((exp / 'runs/test_verify_r0/run.json').read_text())
    assert result['status'] == 'ok' and result['final_answer'] == '42'
    assert result['n_probes'] == 0 and result['counters']['worker_calls'] == 2
    assert (exp / 'runs/test_verify_r0/first_subtask.json').exists()
    assert (exp / 'runs/test_verify_r0/completion.json').exists()
