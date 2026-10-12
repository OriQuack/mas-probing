"""Unified action loop contracts, entirely offline."""
import json
from dataclasses import replace
import pytest
from fakes import Raw, ScriptedLLM, fake_web
from minpilot.config import ConditionConfig
from minpilot.harness import Run
from minpilot.runtime.trace import Limits
from test_harness import action, evaluation, make_run, row


def payloads(llm):
    return [json.loads(b['messages'][1]['content']) for b in llm.by_kind['orchestrator']]


def test_probe_can_finish_without_execution(tmp_path, task):
    script = {'orchestrator': [action('probe', wid=None), action('finish')],
              'worker': ['Title: A\nAnswer 2 with evidence', 'Title: B\nIndependent evidence'],
              'evaluator_probe': [evaluation([row()])]}
    run, llm = make_run(tmp_path, task, script, 'adaptive_probe')
    info = run.run_fresh()
    assert info['status'] == 'ok' and info['n_delegations'] == 0 and info['n_probes'] == 1
    assert len(llm.by_kind['refiner']) == 2 and not llm.by_kind['evaluator_execution']
    first, second = payloads(llm)
    assert first['first_action'] and not second['first_action']
    assert 'request' not in first and 'request' not in second
    assert second['state'] == [row()]
    assert second['latest_probe']['context'] == run.actions[0]['context']
    assert second['latest_probe']['reports'][0]['body'] == 'Title: A\nAnswer 2 with evidence'


def test_probe_payload_deduplicates_without_mutating_trace_or_checkpoint(tmp_path, task):
    from test_refiners import probe_script

    original_probe = {}

    def choose(body):
        payload = json.loads(body['messages'][1]['content'])
        if payload['first_action']:
            return action('probe', wid=None)
        if payload['latest_probe']:
            original_probe.update(json.loads(json.dumps(run.latest_probe)))
            return action(instruction=None, instruction_id=payload['latest_probe']['refinement']['instruction_id'])
        return action('finish')

    run, llm = make_run(tmp_path, task, probe_script(orchestrator=choose), 'adaptive_probe')
    assert run.run_fresh()['status'] == 'ok'
    after_probe = payloads(llm)[1]
    assert 'instructions' not in after_probe['latest_probe']
    assert 'evaluation' not in after_probe['latest_probe']
    assert after_probe['instructions'] and after_probe['evaluation']['artifact_id']
    assert after_probe['latest_probe']['refinement']['result']['instruction'] == run.delegations[0]['final']

    events = [json.loads(line) for line in (run.run_dir / 'events.jsonl').read_text().splitlines()]
    probe_event = next(event for event in events if event['event'] == 'probe_refinement')
    checkpoint = run.run_dir / 'checkpoints/a1'
    for key in ('instructions', 'evaluation'):
        assert original_probe[key] == probe_event[key] == after_probe[key]
    assert original_probe['reports'] == after_probe['latest_probe']['reports']
    saved = json.loads((checkpoint / 'state.json').read_text())
    assert saved['evaluation'] == original_probe['evaluation']
    saved_artifacts = {record['id']: record for record in saved['memory']['artifacts']}
    for ref in (original_probe['evaluation']['artifact_id'], original_probe['refinement']['artifact_id']):
        assert saved_artifacts[ref]['body'] == run.memory.read(ref)['body']

    restored_llm = ScriptedLLM({'worker': ['Title: Restored\n2'],
                              'evaluator_execution': [evaluation()], 'orchestrator': [action('finish')]})
    restored = Run.restore(checkpoint, tmp_path / 'restored', task=task, web=fake_web(tmp_path),
                           tool_cfg=run.tool_cfg, transport=restored_llm)
    assert restored._payload()['instructions'] == after_probe['instructions']
    assert restored.run_restored()['status'] == 'ok'
    assert restored.delegations[0]['final'] == run.delegations[0]['final']


def test_mixed_actions_share_loop_and_probe_does_not_consume_execution_cap(tmp_path, task):
    choices = [action(), action('probe', wid=None, state_rows=[0]),
               action('probe', wid=None), action(wid='gen_haiku', state_rows=[0]), action('finish')]
    script = {'orchestrator': choices, 'worker': ['Title: Report\n2'] * 6,
              'evaluator_execution': [evaluation([row()])] * 2,
              'evaluator_probe': [evaluation([row()])] * 2}
    run, llm = make_run(tmp_path, task, script, 'adaptive_probe', max_delegations=2)
    info = run.run_fresh()
    assert info['status'] == 'ok', info
    assert [a['action'] for a in run.actions] == ['execute', 'probe', 'probe', 'execute']
    assert info['n_delegations'] == 2 and info['n_probes'] == 2
    assert [p['remaining_delegations'] for p in payloads(llm)] == [2, 1, 1, 1, 0]
    assert payloads(llm)[3]['latest_probe'] is not None
    assert payloads(llm)[4]['latest_probe'] is None
    assert json.loads(run.delegations[1]['context'])['state'][0]['content'] == row()['content']
    assert sorted(p.name for p in (run.run_dir / 'checkpoints').iterdir()) == ['a0', 'a1', 'a2', 'a3']
    ck = run.run_dir / 'checkpoints/a2'
    saved = json.loads((ck / 'state.json').read_text())
    assert saved['delegation'] == 1 and saved['action_index'] == 2 and not saved['first_action']
    restored_llm = ScriptedLLM({'worker': ['Title: Probe\n2'] * 2,
                              'evaluator_probe': [evaluation([row()])], 'orchestrator': [action('finish')]})
    restored = Run.restore(ck, tmp_path / 'restored', task=task, web=fake_web(tmp_path),
                           transport=restored_llm, tool_cfg=run.tool_cfg)
    assert restored.trace.run_scope.llm_calls == saved['trace']['counters']['llm_calls']
    assert restored.run_restored()['status'] == 'ok'
    assert not payloads(restored_llm)[0]['first_action']


@pytest.mark.parametrize('old', ['delegate', 'select', 'probe'])
def test_direct_rejects_old_actions_and_probe(tmp_path, task, old):
    run, llm = make_run(tmp_path, task, {'orchestrator': [action(old), action('finish')]})
    assert run.run_fresh()['status'] == 'ok'
    assert not run.actions
    assert 'invalid decision action' in llm.by_kind['orchestrator'][1]['messages'][-1]['content']


def test_old_condition_rejected():
    with pytest.raises(ValueError, match='unsupported'):
        ConditionConfig('multi_worker_probe')
    from minpilot.config import load_condition
    with pytest.raises(ValueError, match='retired'):
        load_condition('multi_worker_probe')


def test_probe_evaluation_failure_preserves_state_and_reports(tmp_path, task):
    script = {'orchestrator': [action('probe', wid=None), action('finish')],
              'worker': ['ORIGINAL A', 'ORIGINAL B'], 'evaluator_probe': [Raw('{'), Raw('{')]}
    run, llm = make_run(tmp_path, task, script, 'adaptive_probe')
    run.memory.add('worker', 'execution', 'seed')
    run.memory.replace([row()], evaluation='seed', reason='prior')
    assert run.run_fresh()['status'] == 'ok'
    assert run.memory.state == [row()] and not run.delegations
    assert [r['body'] for r in payloads(llm)[-1]['latest_probe']['reports']] == ['ORIGINAL A', 'ORIGINAL B']
    assert payloads(llm)[-1]['evaluation']['error']


def test_memory_read_keeps_first_action(tmp_path, task):
    script = {'orchestrator': [{'action': 'read_memory', 'refs': ['a00000']}, action(), action('finish')],
              'worker': ['Title: Count\n2'], 'evaluator_execution': [evaluation()]}
    run, llm = make_run(tmp_path, task, script, 'adaptive_probe')
    run.memory.add('worker', 'execution', 'seed')
    assert run.run_fresh()['status'] == 'ok'
    assert payloads(llm)[0]['first_action'] and payloads(llm)[1]['first_action']
    assert [a['action'] for a in run.actions] == ['execute']


def test_refinement_budget_keeps_selected_instruction_context(tmp_path, task):
    script = {'orchestrator': [action(), action('finish')],
              'worker': ['Title: Count\n2'], 'evaluator_execution': [evaluation()]}
    run, llm = make_run(tmp_path, task, script, 'adaptive_probe')
    run.cfg = replace(run.cfg, condition=ConditionConfig('adaptive_probe', budget=Limits(max_llm_calls=0)))
    assert run.run_fresh()['status'] == 'ok'
    assert not llm.by_kind['refiner']
    assert run.delegations[0]['final'] == run.actions[0]['instruction']
    assert run.delegations[0]['context'] == run.actions[0]['context']
