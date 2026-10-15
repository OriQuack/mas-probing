"""Fixed-worker, original-instruction voting on the first segment only."""
from __future__ import annotations

import statistics
from perturbation_consistency import instruction_selection as ins, longcot_math

VERSION = "self-consistency-v1"
KS = (1, 3, 5, 10, 20)
WORKER = ins.EXECUTOR
REPS = 3


def index_rows(rows, expected, fields):
    indexed = {}
    for row in rows:
        key = tuple(row[f] for f in fields)
        if key in indexed or key not in expected:
            raise ValueError(f"duplicate or unplanned record: {key}")
        indexed[key] = row
    return indexed


def votes(targets, probes, *, complete=True):
    expected = {(t['target_id'], i) for t in targets for i in range(max(KS))}
    by = index_rows(probes, expected, ('target_id', 'sample'))
    if any(r['worker'] != WORKER for r in probes):
        raise ValueError('unexpected probe worker')
    if complete and set(by) != expected:
        raise ValueError('finish all probe slots before continuation')
    out = []
    for t in targets:
        tid = t['target_id']
        representatives = []
        for k in KS:
            rr = [by.get((tid, i), {}) for i in range(k)]
            aa = [r.get('answer') if r.get('status') == 'ok' else None for r in rr]
            groups = [g for g in longcot_math.group(aa) if aa[g[0]] is not None]
            answer = aa[groups[0][0]] if groups else None
            shared = next((r for r in representatives if
                           (answer is None and r['answer'] is None) or
                           (answer is not None and r['answer'] is not None and
                            longcot_math.same(answer, r['answer']))), None)
            row = {'target_id': tid, 'k': k, 'answer': answer,
                   'start_id': shared['start_id'] if shared else f'k{k}',
                   'support': len(groups[0]) if groups else 0,
                   'valid_answers': sum(a is not None for a in aa),
                   'failed_samples': sum(bool(r) and a is None for r, a in zip(rr, aa)),
                   'pending_samples': sum(not r for r in rr),
                   'tied': len(groups) > 1 and len(groups[0]) == len(groups[1]),
                   'probe_cost_usd': sum(r.get('cost_usd', 0.) for r in rr)}
            if shared is None:
                representatives.append(row)
            out.append(row)
    return out


def analyze(targets, probes, runs):
    vv = votes(targets, probes, complete=False)
    expected = {(v['target_id'], v['start_id'], rep) for v in vv for rep in range(REPS)}
    by = index_rows(runs, expected, ('target_id', 'start_id', 'rep'))
    if any(r['worker'] != WORKER for r in runs):
        raise ValueError('unexpected continuation worker')
    if any(v['pending_samples'] for v in vv) and runs:
        raise ValueError('continuations require completed probes')
    details = []
    for t in targets:
        tid = t['target_id']
        nodes = t['requested_after']
        for v in (v for v in vv if v['target_id'] == tid):
            rr = [by.get((tid, v['start_id'], rep), {}) for rep in range(REPS)]
            node = [statistics.mean(r.get('requested', {}).get(n) == 'correct' for r in rr) for n in nodes]
            cost = sum(r.get('cost_usd', 0.) for r in rr)
            details.append({**v, 'segment_correct': node[0],
                            'downstream_share': statistics.mean(node[1:]) if len(node) > 1 else None,
                            'requested_share': statistics.mean(node),
                            'all_requested': statistics.mean(all(r.get('requested', {}).get(n) == 'correct'
                                                                for n in nodes) for r in rr),
                            'continuation_cost_usd_3_reps': cost,
                            'policy_cost_usd_3_reps': v['probe_cost_usd'] + cost,
                            'policy_cost_usd_mean_1_rep': v['probe_cost_usd'] + cost / REPS,
                            'missing_rollouts': sum(not r for r in rr)})
    baseline = {r['target_id']: r for r in details if r['k'] == 1}
    summary = {'experiment_version': VERSION, 'targets': len(targets),
               'probes_planned': len(targets) * max(KS), 'probes_recorded': len(probes),
               'unique_rollouts_planned': len(expected), 'unique_rollouts_recorded': len(runs),
               'complete': len(probes) == len(targets) * max(KS) and len(runs) == len(expected),
               'policies': {}, 'interpretation': 'Original naive prompt repeated; first segment only; not cost-matched. Missing planned executions score zero.'}
    for k in KS:
        rows = [r for r in details if r['k'] == k]
        metrics = {}
        for metric in ('segment_correct', 'downstream_share', 'requested_share', 'all_requested'):
            valid = [r for r in rows if r[metric] is not None]
            vals = [r[metric] for r in valid]
            diffs = [r[metric] - baseline[r['target_id']][metric] for r in valid]
            metrics[metric] = {'mean': statistics.mean(vals) if vals else None,
                               'ci95': ins.interval(vals) if vals else None,
                               'delta_vs_k1': statistics.mean(diffs) if diffs else None,
                               'delta_ci95': ins.interval(diffs) if diffs else None}
        summary['policies'][str(k)] = {'metrics': metrics,
            'probe_cost_usd': sum(r['probe_cost_usd'] for r in rows),
            'policy_cost_usd_3_reps': sum(r['policy_cost_usd_3_reps'] for r in rows),
            'policy_cost_usd_mean_1_rep': sum(r['policy_cost_usd_mean_1_rep'] for r in rows),
            'failed_samples': sum(r['failed_samples'] for r in rows),
            'pending_samples': sum(r['pending_samples'] for r in rows),
            'missing_rollouts': sum(r['missing_rollouts'] for r in rows)}
    return summary, details
