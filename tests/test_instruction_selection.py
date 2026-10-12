"""Probe rewrites are saved before routing and delivered verbatim, offline."""
import json
from contextlib import contextmanager
import pytest
from fakes import Raw, ScriptedLLM, fake_web, kind_of
from minpilot.harness import Run
from minpilot.runtime.trace import Limits
from test_harness import action, evaluation, make_run, row
from test_refiners import probe_script


def choose_saved(body):
    payload = json.loads(body['messages'][1]['content'])
    if payload['first_action']:
        return action('probe', wid=None)
    if payload['latest_probe']:
        return action(instruction=None,
                      instruction_id=payload['latest_probe']['refinement']['instruction_id'],
                      artifact_ids=['t00000'])
    return action('finish')


def test_rewrite_routes_required_source_and_survives_restore(tmp_path, task):
    rewritten = '  Count distinct IDs using the complete sheet.\nKeep 2025 scope.  '
    raw = '\n' + json.dumps({'action': 'refine', 'can_refine': True, 'instruction': rewritten,
                'context_notes': 'Select t00000: complete sheet body.', 'rationale': 'Clarify unit.'}) + '  '
    script = probe_script(orchestrator=choose_saved,
        worker=[{'tool_calls': [('read_file', {'path': 'attachments/sheet.csv'})]},
                'Title: Probe A\nRead sheet', 'Title: Probe B\nCount IDs', 'Title: Count\n2'],
        refiner=[Raw(raw)], evaluator_probe=[evaluation([row('t00000')], changes='Clarify unit')])
    run, llm = make_run(tmp_path, task, script, 'adaptive_probe')
    info = run.run_fresh()
    assert info['status'] == 'ok', info
    selected = run.actions[1]
    assert selected['instruction'] is None
    assert selected['delivered_instruction'] == rewritten == run.delegations[0]['final']
    assert run.memory.read(selected['selected_instruction_id'])['body'] == raw
    assert 'order_id,date,amount' in selected['context']
    assert 'Select t00000' not in selected['context']
    worker_input = llm.by_kind['worker'][-1]['messages'][1]['content']
    assert rewritten in worker_input and 'order_id,date,amount' in worker_input
    ev = json.loads(llm.by_kind['evaluator_execution'][0]['messages'][1]['content'])
    assert ev['instruction'] == rewritten and ev['context'] == selected['context']
    ref_input = json.loads(llm.by_kind['refiner'][0]['messages'][1]['content'])
    assert 'executor' not in ref_input and 'changes' not in ref_input
    assert ref_input['state'] == [row('t00000')]
    assert ref_input['evaluation']['changes'] == 'Clarify unit'
    calls = [kind_of(b) for b in llm.bodies]
    assert calls.index('evaluator_probe') < calls.index('refiner') < calls.index('evaluator_execution')
    restored_llm = ScriptedLLM({'worker': ['Title: Restored\n2'], 'evaluator_execution': [evaluation()],
                               'orchestrator': [action('finish')]})
    restored = Run.restore(run.run_dir / 'checkpoints/a1', tmp_path / 'restored', task=task,
        web=fake_web(tmp_path), tool_cfg=run.tool_cfg, transport=restored_llm)
    assert restored.run_restored()['status'] == 'ok'
    assert restored.delegations[0]['final'] == rewritten
    assert not restored_llm.by_kind['refiner']


@pytest.mark.parametrize('reply,status', [
    ({'action': 'refine', 'can_refine': False, 'instruction': '', 'context_notes': '', 'rationale': 'Unavailable'}, 'refiner_unapplied'),
    (Raw('{'), 'refiner_failed'),
    (RuntimeError('model unavailable'), 'refiner_failed'),
])
def test_refinement_fallback_exposes_draft_and_preserves_originals(tmp_path, task, reply, status):
    script = probe_script(refiner=[reply, reply], orchestrator_select=[action(instruction=None, instruction_id='a00000')])
    run, llm = make_run(tmp_path, task, script, 'adaptive_probe')
    assert run.run_fresh()['status'] == 'ok'
    result = run.actions[0]['refinement']
    assert result['status'] == status and result['instruction_id'] == 'a00000'
    assert run.delegations[0]['final'] == run.memory.read('a00000')['body']
    assert run.memory.read('a00001')['body'].endswith('probe marker one')
    assert [i['instruction_id'] for i in run._instructions()] == ['a00000']


def test_unchanged_refinement_precedes_finish(tmp_path, task):
    draft = action()['instruction']
    script = probe_script(orchestrator=[action('probe', wid=None), action('finish')], refiner=[
        {'action': 'refine', 'can_refine': True, 'instruction': draft, 'context_notes': '', 'rationale': 'No edit needed'}])
    run, llm = make_run(tmp_path, task, script, 'adaptive_probe')
    assert run.run_fresh()['status'] == 'ok'
    assert len(llm.by_kind['refiner']) == 1 and not run.delegations
    assert run._instructions()[-1]['instruction'] == draft
    assert [kind_of(b) for b in llm.bodies][-2:] == ['refiner', 'orchestrator']


def test_refinement_cap_returns_to_orchestrator_without_execution(tmp_path, task):
    script = probe_script(orchestrator=[action('probe', wid=None), action('finish')])
    run, llm = make_run(tmp_path, task, script, 'adaptive_probe')
    original_scope = run.trace.budget_scope
    @contextmanager
    def scope(name, limits):
        with original_scope(name, Limits(max_llm_calls=0) if name == 'refinement' else limits) as active:
            yield active
    run.trace.budget_scope = scope
    assert run.run_fresh()['status'] == 'ok'
    assert run.actions[0]['refinement'] == {'status': 'refinement_budget_exceeded', 'instruction_id': 'a00000'}
    assert not llm.by_kind['refiner'] and not run.delegations
    assert run.memory.read('a00000')['body'] == action()['instruction']


@pytest.mark.parametrize('extra', [
    {'refine': False}, {'changes': ''},
    {'instruction_id': 'missing', 'instruction': None},
    {'instruction_id': 'a00001', 'instruction': None},
    {'instruction_id': 'a00000'},
])
def test_invalid_instruction_contract_repaired_once(tmp_path, task, extra):
    script = probe_script(orchestrator=[action('probe', wid=None), action(**extra), action('finish')])
    run, llm = make_run(tmp_path, task, script, 'adaptive_probe')
    assert run.run_fresh()['status'] == 'ok'
    assert not run.delegations
    assert 'Invalid response' in llm.by_kind['orchestrator'][-1]['messages'][-1]['content']


@pytest.mark.parametrize('wid', ['gen_luna', 'gen_haiku'])
def test_consecutive_probes_keep_instruction_origins_and_latest_state(tmp_path, task, wid):
    state_a = [row('a00001', content='First unresolved item', type='progress', status='incomplete')]
    state_b = [row('a00006', content='Second unresolved item', type='progress', status='incomplete')]
    turns = iter([action('probe', wid=None), action('probe', wid=None, instruction='Check another result.'),
                  action(instruction=None, instruction_id='a00009', wid=wid, state_rows=[0]),
                  action(instruction='Perform a new assignment.', wid=wid), action('finish')])
    def route(body):
        return next(turns)
    def rewrite(body):
        payload = json.loads(body['messages'][1]['content'])
        return {'action': 'refine', 'can_refine': True, 'instruction': payload['draft'] + ' Preserve scope.',
                'context_notes': '', 'rationale': 'Apply assessment'}
    script = {'orchestrator': route, 'worker': ['Title: Report\nEvidence'] * 6,
              'evaluator_probe': [evaluation(state_a), evaluation(state_b)],
              'refiner': rewrite, 'evaluator_execution': [evaluation(state_b), evaluation(state_b)]}
    run, llm = make_run(tmp_path, task, script, 'adaptive_probe')
    info = run.run_fresh()
    assert info['status'] == 'ok', info
    assert len(llm.by_kind['refiner']) == 2
    assert [json.loads(b['messages'][1]['content'])['state'] for b in llm.by_kind['refiner']] == [state_a, state_b]
    assert run.delegations[0]['instruction_id'] == 'a00009'
    assert run.delegations[0]['draft'] == 'Check another result.'
    assert run.delegations[0]['final'] == 'Check another result. Preserve scope.'
    assert json.loads(run.delegations[0]['context'])['state'][0]['content'] == 'Second unresolved item'
    assert run.delegations[1]['final'] == 'Perform a new assignment.'


def test_refinement_repair_budget_keeps_invalid_original(tmp_path, task):
    script = probe_script(refiner=[Raw('INVALID ORIGINAL')],
                          orchestrator=[action('probe', wid=None), action('finish')])
    run, llm = make_run(tmp_path, task, script, 'adaptive_probe')
    original_scope = run.trace.budget_scope
    @contextmanager
    def scope(name, limits):
        with original_scope(name, Limits(max_llm_calls=1) if name == 'refinement' else limits) as active:
            yield active
    run.trace.budget_scope = scope
    assert run.run_fresh()['status'] == 'ok'
    assert run.actions[0]['refinement']['status'] == 'refinement_budget_exceeded'
    failed = [a for a in run.memory.artifacts if a['stage'] == 'instruction.refined']
    assert len(failed) == 1 and failed[0]['body'] == 'INVALID ORIGINAL' and failed[0]['status'] == 'failed'
    assert len(llm.by_kind['refiner']) == 1 and not run.delegations
