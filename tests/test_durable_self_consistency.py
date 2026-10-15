"""Durable batch restart must collect saved IDs, never buy another batch."""
import argparse
import json
from types import SimpleNamespace

import pytest
from perturbation_consistency import durable_batch as durable, self_consistency as sc
from test_self_consistency import runner


def setup(tmp_path, runner):
    exp = tmp_path / 'sc'
    exp.mkdir()
    (exp / 'manifest.json').write_text('{}')
    runner.base.append(exp / 'prompts.jsonl', {'target_id': 'q', 'prompt': 'What is 16?', 'answer_node': 'node_1'})
    args = argparse.Namespace(experiment=exp, env_file=tmp_path / 'missing.env',
                              session_cost_usd=10., run_cost_usd=.1, submit_only=True)
    return args, [{'target_id': 'q'}], SimpleNamespace(base=runner.base)


def test_submit_restart_collect_without_second_post(tmp_path, runner):
    args, targets, interface = setup(tmp_path, runner)
    calls = []
    def http(method, path, body):
        calls.append((method, path))
        if method == 'POST':
            assert len(body['requests']) == max(sc.KS)
            assert (args.experiment / 'probe_batch/requests.json').exists()
            assert durable.read(args.experiment / 'probe_batch/submission.json')['state'] == 'submitting'
            return 201, {'id': 'batch-test'}
        requests = durable.read(args.experiment / 'probe_batch/requests.json')
        model = durable.get_spec(sc.WORKER)
        results = [{'custom_id': r['custom_id'], 'response': {'body': {
                    'model': model.model, 'choices': [{'message': {'content': 'answer = 16'}, 'finish_reason': 'stop'}],
                    'usage': {'prompt_tokens': 20, 'completion_tokens': 10}}}} for r in reversed(requests)]
        return 200, {'id': 'batch-test', 'status': 'completed', 'results': results, 'usage': {'cost': .01}}
    durable.run(args, targets, interface, http=http)
    args.submit_only = False
    # Simulate crash while publishing a per-slot result: raw remote results are already cached.
    original_save = durable.save
    def fail_on_slot(path, value):
        if path.parent.name == 'slots':
            raise RuntimeError('simulated interruption')
        return original_save(path, value)
    from unittest.mock import patch
    with patch.object(durable, 'save', fail_on_slot), pytest.raises(RuntimeError, match='interruption'):
        durable.run(args, targets, interface, http=http)
    durable.run(args, targets, interface, http=http)
    durable.run(args, targets, interface, http=http)
    assert sum(m == 'POST' for m, _ in calls) == 1
    assert sum(m == 'GET' for m, _ in calls) == 1
    results = runner.base.read_rows(args.experiment / 'results.jsonl')
    assert len(results) == max(sc.KS) and all(r['answer'] == '16' for r in results)
    assert len({r['custom_id'] for r in results}) == max(sc.KS)
    assert len(runner.base.read_rows(args.experiment / 'probe_jobs.jsonl')) == max(sc.KS)
    assert len(runner.base.read_rows(args.experiment / 'probe_batches.jsonl')) == 2
    for job in runner.base.read_rows(args.experiment / 'probe_jobs.jsonl'):
        trace = runner.base.read_rows(args.experiment / job['trace'] / 'llm_calls.jsonl')
        assert [r['status'] for r in trace] == ['started', 'ok']


def test_uncertain_post_does_not_retry(tmp_path, runner):
    args, targets, interface = setup(tmp_path, runner)
    calls = []
    def http(*a):
        calls.append(a)
        return 0, {'error': {'message': 'timeout'}}
    with pytest.raises(RuntimeError, match='no automatic'):
        durable.run(args, targets, interface, http=http)
    with pytest.raises(ValueError, match='no automatic'):
        durable.run(args, targets, interface, http=http)
    assert len(calls) == 1


def test_caps_checked_before_network(tmp_path, runner):
    args, targets, interface = setup(tmp_path, runner)
    args.session_cost_usd = .001
    with pytest.raises(ValueError, match='session cap'):
        durable.run(args, targets, interface, http=lambda *a: pytest.fail('unexpected network'))
