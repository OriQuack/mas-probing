"""Offline contracts for fixed-worker first-segment self-consistency."""
import argparse
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from fakes import ScriptedLLM
from perturbation_consistency import self_consistency as sc
from test_positive_instruction_selection import PROMPT, INSTRUCTIONS, fixture_chain


def probes(answers):
    return [{'target_id': 'q', 'worker': sc.WORKER, 'sample': i, 'answer': a,
             'status': 'ok' if a is not None else 'error', 'cost_usd': .1}
            for i, a in enumerate(answers)]


def test_votes_prefix_equivalence_ties_order_failures():
    targets = [{'target_id': 'q'}]
    rows = probes(['16', '99', '16.0', None, '99', '99', '99', '99', '99', None] + ['16'] * 10)
    vv = sc.votes(targets, rows)
    assert [v['answer'] for v in vv] == ['16', '16', '16', '99', '16']
    assert [v['start_id'] for v in vv] == ['k1', 'k1', 'k1', 'k10', 'k1']
    assert vv[2]['tied'] and vv[2]['failed_samples'] == 1
    assert vv[3]['probe_cost_usd'] == pytest.approx(1.)
    assert vv == sc.votes(targets, list(reversed(rows)))
    nulls = sc.votes(targets, probes([None] * max(sc.KS)))
    assert all(v['answer'] is None and v['start_id'] == 'k1' for v in nulls)
    with pytest.raises(ValueError, match='duplicate'):
        sc.votes(targets, rows + rows[:1])
    with pytest.raises(ValueError, match='finish'):
        sc.votes(targets, rows[:3])


def test_shared_costs_missing_runs_and_paired_metrics():
    targets = [{'target_id': 'q', 'requested_after': ['node_1', 'node_2']}]
    rows = probes(['16'] * max(sc.KS))
    runs = [{'target_id': 'q', 'start_id': 'k1', 'rep': i, 'worker': sc.WORKER,
             'requested': {'node_1': 'correct', 'node_2': 'wrong'}, 'cost_usd': .2}
            for i in range(3)]
    summary, details = sc.analyze(targets, rows, runs)
    assert summary['complete']
    assert summary['unique_rollouts_planned'] == 3
    assert details[0]['policy_cost_usd_3_reps'] == pytest.approx(.7)
    assert details[-1]['policy_cost_usd_3_reps'] == pytest.approx(2.6)
    assert details[-1]['policy_cost_usd_mean_1_rep'] == pytest.approx(2.2)
    assert summary['policies']['10']['metrics']['requested_share']['mean'] == .5
    assert summary['policies']['10']['metrics']['requested_share']['delta_vs_k1'] == 0
    summary, _ = sc.analyze(targets, rows, runs[:1])
    assert not summary['complete']
    assert summary['policies']['1']['metrics']['segment_correct']['mean'] == pytest.approx(1 / 3)
    summary, _ = sc.analyze(targets, [], [])
    assert not summary['complete'] and summary['policies']['20']['pending_samples'] == 20


@pytest.fixture
def runner():
    path = Path(__file__).resolve().parents[1] / 'scripts/run_self_consistency.py'
    spec = importlib.util.spec_from_file_location('sc_runner', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_lifecycle_freeze_resume_gold_and_analysis(tmp_path, monkeypatch, runner):
    base = runner.base
    monkeypatch.setattr(runner, 'verify_dataset', lambda dataset: None)
    chain, target = fixture_chain()
    initial = tmp_path / 'initial'
    initial.mkdir()
    (initial / 'targets.jsonl').write_text(json.dumps(target.__dict__) + '\n')
    (initial / 'manifest.json').write_text(json.dumps({'dataset': {'name': 'LongCoT', 'revision': 'test'}}))
    monkeypatch.setattr(base.longcot, 'load_questions', lambda *a, **kw: [SimpleNamespace(question_id=chain.question_id, prompt=PROMPT)])
    def forbidden(*a, **kw):
        raise AssertionError('gold loaded before continuation')
    monkeypatch.setattr(base.longcot, 'load_references', forbidden)
    monkeypatch.setenv('OPENROUTER_API_KEY', 'offline-fake')
    source = tmp_path / 'source'
    args = argparse.Namespace(experiment=source, source=initial, dry_run=False, batch=False,
        env_file=tmp_path / 'absent.env', session_cost_usd=100., run_cost_usd=2., concurrency=1,
        generation_mode='session')
    base.prepare(args)
    manifest, targets, inputs, chains = base.load(source)
    args.candidate_file = tmp_path / 'candidates.jsonl'
    args.author = 'offline'
    args.candidate_file.write_text(json.dumps({'target_id': target.target_id, 'instructions': INSTRUCTIONS,
                                              'review': {'accepted': True, 'notes': 'offline'}}) + '\n')
    base.import_candidates(args, manifest, targets, chains)
    source_before = {p.name: p.read_bytes() for p in source.iterdir() if p.is_file()}
    args.source, args.experiment, args.dry_run = source, tmp_path / 'sc', True
    runner.prepare(args)
    assert not args.experiment.exists()
    args.dry_run = False
    runner.prepare(args)
    manifest, targets, chains = runner.load(args.experiment)
    llm = ScriptedLLM({'worker': lambda body: 'answer = 16'})
    monkeypatch.setattr(base, 'http_transport', lambda key: llm)
    runner.probe(args, targets)
    assert len(llm.bodies) == max(sc.KS)
    runner.probe(args, targets)
    assert len(llm.bodies) == max(sc.KS)
    assert all('Recall and solve' not in b['messages'][0]['content'] for b in llm.bodies)
    monkeypatch.setattr(base.longcot, 'load_references', lambda *a, **kw: {chain.question_id: SimpleNamespace(answer='16,11,22')})
    llm = ScriptedLLM({'worker': lambda body: 'answer = 11' if 'Problem node_2:' in body['messages'][0]['content'] else 'answer = 22'})
    monkeypatch.setattr(base, 'http_transport', lambda key: llm)
    runner.continuation(args, targets, chains)
    assert len(llm.bodies) == 6  # One shared start, three two-node continuations.
    assert all('22' not in b['messages'][0]['content'] for b in llm.bodies)
    # A process can die between saving a slot and appending the aggregate JSONL.
    (args.experiment / 'continuation.jsonl').write_text('{partial')
    runner.continuation(args, targets, chains)
    assert len(llm.bodies) == 6
    assert len(base.read_rows(args.experiment / 'continuation.jsonl')) == 3
    runner.analyze(args, manifest, targets)
    saved = json.loads((args.experiment / 'analysis/summary.json').read_text())
    assert saved['complete'] and saved['policies']['10']['metrics']['all_requested']['mean'] == 1
    assert not saved['instruction_comparison']['available']
    assert (args.experiment / 'analysis/accuracy_cost.png').stat().st_size > 0
    assert {p.name: p.read_bytes() for p in source.iterdir() if p.is_file()} == source_before
    # Complete source results to exercise read-only comparison and cost reporting.
    monkeypatch.setattr(base, 'http_transport', lambda key: ScriptedLLM({'worker': lambda body: 'answer = 16'}))
    source_args = argparse.Namespace(**vars(args))
    source_args.experiment = source
    source_manifest, source_targets, source_inputs, source_chains = base.load(source)
    base.probe(source_args, source_manifest)
    base.selections(source_args, source_manifest, source_targets)
    base.continuation(source_args, source_manifest, source_targets, source_chains)
    runner.analyze(args, manifest, targets)
    saved = json.loads((args.experiment / 'analysis/summary.json').read_text())
    comparison = saved['instruction_comparison']
    assert comparison['available'] and comparison['complete']
    assert not comparison['cost_matched']
    assert set(comparison['policy_costs']) == {'selected', 'naive', 'best_in_hindsight'}
    rows = base.read_rows(args.experiment / 'results.jsonl')
    rows[0]['answer'] = '99'
    (args.experiment / 'results.jsonl').write_text(''.join(json.dumps(r) + '\n' for r in rows))
    with pytest.raises(ValueError, match='frozen votes'):
        runner.continuation(args, targets, chains)
    (args.experiment / 'prompts.jsonl').write_text('changed')
    with pytest.raises(ValueError, match='frozen artifact'):
        runner.load(args.experiment)


def test_failed_slots_are_not_retried(tmp_path, monkeypatch, runner):
    chain, target = fixture_chain()
    targets = [{'target_id': target.target_id}]
    exp = tmp_path / 'sc'
    exp.mkdir()
    runner.base.append(exp / 'prompts.jsonl', {'target_id': target.target_id, 'prompt': 'q', 'answer_node': target.node})
    args = argparse.Namespace(experiment=exp, session_cost_usd=.01, run_cost_usd=.01,
                              env_file=tmp_path / 'absent.env', batch=False, concurrency=1)
    monkeypatch.setenv('OPENROUTER_API_KEY', 'offline-fake')
    llm = ScriptedLLM({'worker': []})
    monkeypatch.setattr(runner.base, 'http_transport', lambda key: llm)
    runner.probe(args, targets)
    assert len(runner.base.read_rows(exp / 'results.jsonl')) == max(sc.KS)
    assert not llm.bodies
    runner.probe(args, targets)
    assert len(runner.base.read_rows(exp / 'probe_jobs.jsonl')) == max(sc.KS)
