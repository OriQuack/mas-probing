#!/usr/bin/env python
"""First-segment original-prompt self-consistency: prepare / probe / continue / analyze."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
import subprocess
import tarfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
sys.path.insert(0, str(ROOT / 'scripts'))
import run_instruction_selection as base
from minpilot.llm.specs import get_spec
from perturbation_consistency import self_consistency as sc
from perturbation_consistency import instruction_selection as ins, longcot_math
from perturbation_consistency.longcot_nodes import parse_chain

DEFAULT_SOURCE = ROOT / 'outputs/experiments/2026-10-13_instruction-selection-session-r2'


def implementation_hashes():
    paths = [Path(__file__).resolve(), ROOT / 'scripts/run_self_consistency_workflow.py',
             ROOT / 'scripts/monitor_self_consistency.py', ROOT / 'src/perturbation_consistency/self_consistency.py',
             ROOT / 'src/perturbation_consistency/durable_batch.py',
             ROOT / 'src/minpilot/llm/specs.py', ROOT / 'src/minpilot/llm/client.py',
             ROOT / 'src/minpilot/runtime/trace.py', ROOT / 'src/perturbation_consistency/batch.py']
    return {**base.implementation_hashes(), **{str(p.relative_to(ROOT)): base.digest(p) for p in paths}}


def verify_dataset(dataset):
    source = base.longcot.LONGCOT_ROOT.parents[2] / 'SOURCE.json'
    if json.loads(source.read_text())['revision'] != dataset['revision']:
        raise ValueError('local dataset revision differs from frozen source')


def prepare(args):
    source = args.source.resolve()
    manifest = json.loads((source / 'manifest.json').read_text())
    if manifest.get('experiment_version') != ins.VERSION or not manifest.get('frozen'):
        raise ValueError('source must be a frozen instruction-selection experiment')
    if manifest['equivalence_version'] != longcot_math.EQUIVALENCE_VERSION:
        raise ValueError('source equivalence version differs')
    for name, sha in {**manifest['input_hashes'], **manifest['frozen_hashes']}.items():
        if base.digest(source / name) != sha:
            raise ValueError(f'source artifact changed: {name}')
    verify_dataset(manifest['dataset'])
    source_path = source / 'manifest.json'
    targets = base.read_rows(source / 'targets.jsonl')
    inputs = base.read_rows(source / 'inputs.jsonl')
    if not targets or len({t['target_id'] for t in targets}) != len(targets):
        raise ValueError('missing or duplicate targets')
    by_input = {r['target_id']: r for r in inputs}
    if len(by_input) != len(inputs) or set(by_input) != {t['target_id'] for t in targets}:
        raise ValueError('invalid source inputs')
    source_prompts = base.read_rows(source / 'prompts.jsonl')
    prompts = []
    for t in targets:
        tid = t['target_id']
        chain = parse_chain(t['question_id'], by_input[tid]['prompt'])
        if tuple(t['nodes']) != tuple(n.name for n in chain.nodes[:len(t['nodes'])]) or t['node'] != t['nodes'][-1]:
            raise ValueError(f'invalid segment: {tid}')
        names = [n.name for n in chain.nodes]
        requested = sorted((n for n in chain.requested if names.index(n) >= names.index(t['node'])), key=names.index)
        if t['requested_after'] != requested:
            raise ValueError(f'invalid requested nodes: {tid}')
        prompt = ins.segment_prompt(chain, base.target_obj(t), '')
        naive = [p for p in source_prompts if p['target_id'] == tid and p['condition'] == 'naive']
        if len(naive) != 3 or any(p['prompt'] != prompt for p in naive):
            raise ValueError(f'source naive prompt mismatch: {tid}')
        prompts.append({'target_id': tid, 'prompt': prompt, 'answer_node': t['node']})
    if manifest['models'][sc.WORKER] != get_spec(sc.WORKER).identity():
        raise ValueError('source worker settings differ')
    preview(targets, prompts)
    if args.dry_run:
        return
    exp = args.experiment
    if exp.resolve() == source:
        raise ValueError('use a separate experiment directory')
    exp.mkdir(parents=True, exist_ok=True)
    with base.exclusive(exp):
        if (exp / 'manifest.json').exists():
            raise ValueError('experiment already prepared')
        for name, rows in [('targets.jsonl', targets), ('inputs.jsonl', inputs), ('prompts.jsonl', prompts)]:
            (exp / name).write_text(''.join(json.dumps(r) + '\n' for r in rows))
        with tarfile.open(exp / 'code_snapshot.tar.gz', 'w:gz') as archive:
            for directory in ('src', 'scripts'):
                for p in sorted((ROOT / directory).rglob('*.py')):
                    archive.add(p, arcname=str(p.relative_to(ROOT)))
        base.write_json(exp / 'manifest.json', {
            'experiment_version': sc.VERSION, 'source_experiment': str(source),
            'source_manifest_sha256': base.digest(source_path), 'dataset': manifest['dataset'],
            'worker': sc.WORKER, 'model': get_spec(sc.WORKER).identity(), 'ks': list(sc.KS),
            'continuation_reps': sc.REPS, 'tie_policy': 'earliest_sample',
            'equivalence_version': longcot_math.EQUIVALENCE_VERSION,
            'input_hashes': {n: base.digest(exp / n) for n in ('targets.jsonl', 'inputs.jsonl', 'prompts.jsonl')},
            'implementation_hashes': implementation_hashes(),
            'code_snapshot_sha256': base.digest(exp / 'code_snapshot.tar.gz'),
            'git_commit': subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=ROOT,
                                         capture_output=True, text=True, check=True).stdout.strip(),
            'created_at': base.now()})
    print(f'Prepared {exp}')


def preview(targets, prompts):
    print(json.dumps({'targets': len(targets), 'worker': sc.WORKER, 'ks': sc.KS,
                      'probe_calls': len(targets) * max(sc.KS),
                      'max_unique_continuation_rollouts': len(targets) * len(sc.KS) * sc.REPS}, indent=2))
    print(prompts[0]['prompt'])


def load(exp):
    manifest = json.loads((exp / 'manifest.json').read_text())
    if (manifest['experiment_version'] != sc.VERSION or manifest['ks'] != list(sc.KS)
            or manifest['continuation_reps'] != sc.REPS or manifest['worker'] != sc.WORKER
            or manifest['implementation_hashes'] != implementation_hashes()):
        raise ValueError('implementation changed: use snapshot or a new experiment')
    if manifest['equivalence_version'] != longcot_math.EQUIVALENCE_VERSION or manifest['model'] != get_spec(sc.WORKER).identity():
        raise ValueError('model or equivalence changed')
    for name, sha in manifest['input_hashes'].items():
        if base.digest(exp / name) != sha:
            raise ValueError(f'frozen artifact changed: {name}')
    verify_dataset(manifest['dataset'])
    targets = base.read_rows(exp / 'targets.jsonl')
    inputs = {r['target_id']: r for r in base.read_rows(exp / 'inputs.jsonl')}
    chains = {t['target_id']: parse_chain(t['question_id'], inputs[t['target_id']]['prompt']) for t in targets}
    return manifest, targets, chains


def execute(args, stage_name, jobs, worker_fn):
    if not jobs:
        print(f'{stage_name}: all slots recorded; no calls')
        return
    stage = base.Stage(args, stage_name, [sc.WORKER])
    try:
        with ThreadPoolExecutor(max_workers=min(128, len(jobs)) if args.batch else args.concurrency) as pool:
            list(pool.map(lambda item: worker_fn(stage, item), jobs))
    finally:
        stage.close()


def probe(args, targets):
    if args.batch:
        from perturbation_consistency import durable_batch
        from types import SimpleNamespace
        return durable_batch.run(args, targets, SimpleNamespace(base=base))
    if (args.experiment / 'probe_batch/requests.json').exists():
        raise ValueError('durable batch exists: resume with --batch to avoid duplicate calls')
    path = args.experiment / 'results.jsonl'
    recorded = base.read_rows(path)
    sc.votes(targets, recorded, complete=False)
    done = {(r['target_id'], r['sample']) for r in recorded}
    jobs = [(p, i) for p in base.read_rows(args.experiment / 'prompts.jsonl') for i in range(max(sc.KS))
            if (p['target_id'], i) not in done]

    def job(stage, item):
        p, sample = item
        tid = p['target_id']
        key = hashlib.sha256(f'{tid}:{sample}'.encode()).hexdigest()[:20]
        with stage.lock:
            client, trace = stage.client(key, sc.WORKER)
        with trace.tags(stage='self_consistency_probe', target_id=tid, sample=sample, worker=sc.WORKER):
            result = ins.solve_segment(client, p['prompt'], p['answer_node'])
        with stage.lock:
            base.append(path, {'target_id': tid, 'sample': sample, 'worker': sc.WORKER,
                               **result, 'cost_usd': trace.run_scope.cost_usd})
    execute(args, 'probe', jobs, job)


def frozen_votes(args, targets):
    path = args.experiment / 'votes.json'
    vv = sc.votes(targets, base.read_rows(args.experiment / 'results.jsonl'))
    artifact = {'probe_sha256': base.digest(args.experiment / 'results.jsonl'), 'votes': vv}
    if path.exists():
        if json.loads(path.read_text()) != artifact:
            raise ValueError('probes or frozen votes changed')
    else:
        base.write_json(path, artifact)
    return vv


def restore_continuations(exp):
    from perturbation_consistency.durable_batch import publish_jsonl, read, save
    slots = exp / 'continuation_slots'
    path = exp / 'continuation.jsonl'
    if slots.exists():
        records = [read(p) for p in sorted(slots.glob('*.json'))]
        publish_jsonl(path, records)
        return records
    records = base.read_rows(path)
    slots.mkdir()
    for r in records:
        key = hashlib.sha256(f"{r['target_id']}:{r['start_id']}:{r['rep']}".encode()).hexdigest()[:20]
        save(slots / (key + '.json'), r)
    return records


def continuation(args, targets, chains):
    vv = frozen_votes(args, targets)
    representatives = {(v['target_id'], v['start_id']): v for v in reversed(vv)}
    expected = {(tid, start, rep) for tid, start in representatives for rep in range(sc.REPS)}
    path = args.experiment / 'continuation.jsonl'
    done = sc.index_rows(restore_continuations(args.experiment), expected, ('target_id', 'start_id', 'rep'))
    jobs = [(t, v, rep) for t in targets for (tid, start), v in representatives.items()
            if tid == t['target_id'] for rep in range(sc.REPS) if (tid, start, rep) not in done]
    if not jobs:
        return
    gold = {}
    for difficulty in {t['difficulty'] for t in targets}:
        refs = base.longcot.load_references('math', difficulty)
        for t in targets:
            if t['difficulty'] == difficulty:
                gold[t['target_id']] = dict(zip(chains[t['target_id']].requested,
                    longcot_math.answer_parts(refs[t['question_id']].answer)))

    def job(stage, item):
        t, v, rep = item
        tid, start = t['target_id'], v['start_id']
        key = hashlib.sha256(f'{tid}:{start}:{rep}'.encode()).hexdigest()[:20]
        with stage.lock:
            client, trace = stage.client(key, sc.WORKER)
        with trace.tags(stage='self_consistency_continuation', target_id=tid, start_id=start, rep=rep):
            result = ins.continue_chain(client, trace, chains[tid], base.target_obj(t), v['answer'], gold[tid], '')
        with stage.lock:
            from perturbation_consistency.durable_batch import save
            record = {'target_id': tid, 'start_id': start, 'rep': rep, 'worker': sc.WORKER,
                      **result, 'cost_usd': trace.run_scope.cost_usd}
            save(args.experiment / 'continuation_slots' / (key + '.json'), record)
            base.append(path, record)
    execute(args, 'continuation', jobs, job)


def stage_costs(exp, stage):
    costs = [base.trace_costs(exp / j['trace']) for j in base.read_rows(exp / f'{stage}_jobs.jsonl')]
    return {**{key: sum(c[key] for c in costs) for key in
               ('recorded_request_cost', 'unknown_cost_calls', 'unknown_reserved_usd')},
            'batch_charged_cost': sum(float((r.get('usage') or {}).get('cost') or 0.) for r in
                base.read_rows(exp / f'{stage}_batches.jsonl') if r.get('event') == 'finished')}


def analyze(args, manifest, targets):
    probes = base.read_rows(args.experiment / 'results.jsonl')
    if (args.experiment / 'votes.json').exists():
        frozen_votes(args, targets)
    runs = restore_continuations(args.experiment)
    summary, details = sc.analyze(targets, probes, runs)
    summary['actual_experiment_cost_usd'] = {s: stage_costs(args.experiment, s) for s in ('probe', 'continuation')}
    # Read current source outcomes without altering the source; stamp their provenance.
    source = Path(manifest['source_experiment'])
    source_targets = base.read_rows(source / 'targets.jsonl')
    if source_targets != targets or base.digest(source / 'manifest.json') != manifest['source_manifest_sha256']:
        raise ValueError('comparison source changed')
    selections = base.read_rows(source / 'selection.jsonl')
    source_runs = base.read_rows(source / 'continuation.jsonl')
    summary['instruction_comparison'] = {'available': bool(selections), 'cost_matched': False}
    if selections:
        source_args = argparse.Namespace(experiment=source)
        base.selections(source_args, {}, source_targets)  # read-only verification of an existing freeze
        comparison = ins.analyze(targets, selections, source_runs)
        summary['instruction_comparison'].update({
            'complete': comparison['missing_rollouts'] == 0,
            'selection': comparison['selection'],
            'policy_costs': instruction_costs(source, selections, source_runs),
            'actual_experiment_cost_usd': {s: stage_costs(source, s) for s in ('generate', 'probe', 'continuation')},
            'limitations': 'Instruction policies pool multiple workers; SC uses one worker. Accuracy shares include three continuation replicates. Oracle includes all candidate evaluations.',
            'result_hashes': {n: base.digest(source / n) for n in
                ('results.jsonl', 'selection.jsonl', 'continuation.jsonl') if (source / n).exists()}})
    out = args.experiment / 'analysis'
    out.mkdir(exist_ok=True)
    base.write_json(out / 'summary.json', summary)
    with (out / 'per_task.csv').open('w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=list(details[0]))
        writer.writeheader()
        writer.writerows(details)
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    fig, axes = plt.subplots(1, 2, figsize=(10, 4), layout='constrained')
    for metric in ('segment_correct', 'requested_share', 'all_requested'):
        axes[0].plot(sc.KS, [summary['policies'][str(k)]['metrics'][metric]['mean'] for k in sc.KS], marker='o', label=metric)
    axes[0].set(xlabel='K', ylabel='Accuracy', ylim=(0, 1), xticks=sc.KS,
                title='Complete' if summary['complete'] else 'INCOMPLETE: missing runs score zero')
    axes[0].legend(fontsize=8)
    axes[1].plot(sc.KS, [summary['policies'][str(k)]['policy_cost_usd_mean_1_rep'] for k in sc.KS], marker='o')
    axes[1].set(xlabel='K', ylabel='Total policy cost USD (mean one continuation)', xticks=sc.KS)
    fig.savefig(out / 'accuracy_cost.png', dpi=150)
    plt.close(fig)
    print(json.dumps({'summary': str(out / 'summary.json'), 'complete': summary['complete']}, indent=2))


def instruction_costs(source, selections, runs):
    probes = base.read_rows(source / 'results.jsonl')
    selected = {s['target_id']: s['primary']['candidate'] for s in selections}
    prep = stage_costs(source, 'generate')['recorded_request_cost']
    costs = {}
    for policy in ('selected', 'naive', 'best_in_hindsight'):
        total_probe = sum(r.get('cost_usd', 0.) for r in probes if policy != 'naive' or r['condition'] == 'naive')
        if policy == 'best_in_hindsight':
            total_cont = sum(r.get('cost_usd', 0.) for r in runs)
        else:
            total_cont = sum(r.get('cost_usd', 0.) for r in runs
                             if r['candidate'] == ('naive' if policy == 'naive' else selected.get(r['target_id'])))
        costs[policy] = {'probe_cost_usd': total_probe,
                         'generation_cost_usd': 0. if policy == 'naive' else prep,
                         'continuation_cost_usd_3_reps': total_cont,
                         'total_cost_usd_3_reps': total_probe + total_cont + (0. if policy == 'naive' else prep),
                         'total_cost_usd_mean_1_rep': total_probe + total_cont / sc.REPS + (0. if policy == 'naive' else prep),
                         'interpretation': 'Oracle cost includes evaluation of every candidate.' if policy == 'best_in_hindsight' else 'Recorded policy calls; excludes interrupted attempts and unknown costs.'}
    return costs


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('stage', choices=['prepare', 'probe', 'continue', 'analyze'])
    parser.add_argument('--experiment', type=Path, required=True)
    parser.add_argument('--source', type=Path, default=DEFAULT_SOURCE)
    parser.add_argument('--session-cost-usd', type=float)
    parser.add_argument('--run-cost-usd', type=float)
    parser.add_argument('--concurrency', type=int, default=12)
    parser.add_argument('--batch', action='store_true')
    parser.add_argument('--submit-only', action='store_true', help='probe --batch: submit once, save ID, return without polling')
    parser.add_argument('--env-file', type=Path, default=ROOT / '.env')
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()
    if args.submit_only and (args.stage != 'probe' or not args.batch):
        parser.error('--submit-only requires probe --batch')
    if args.concurrency < 1:
        parser.error('--concurrency must be positive')
    if args.stage == 'prepare':
        prepare(args)
        return
    manifest, targets, chains = load(args.experiment)
    if args.dry_run:
        preview(targets, base.read_rows(args.experiment / 'prompts.jsonl'))
        print(f'stage={args.stage}; transport={"batch" if args.batch else "sync"}; no writes or API calls')
        return
    with base.exclusive(args.experiment):
        if args.stage == 'probe':
            probe(args, targets)
        elif args.stage == 'continue':
            continuation(args, targets, chains)
        else:
            analyze(args, manifest, targets)


if __name__ == '__main__':
    main()
