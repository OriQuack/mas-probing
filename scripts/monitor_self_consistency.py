#!/usr/bin/env python
"""Local-file SC monitor; never submits API requests or launches workers."""
import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from perturbation_consistency.durable_batch import save
from datetime import datetime, timezone
from collections import Counter


def rows(path):
    if not path.exists():
        return []
    text = path.read_text()
    lines = text.splitlines()
    if text and not text.endswith('\n'):
        lines = lines[:-1]
    return [json.loads(line) for line in lines if line.strip()]


def snapshot(exp):
    def read(name):
        p = exp / name
        return json.loads(p.read_text()) if p.exists() else None
    manifest = read('manifest.json') or {}
    probes = rows(exp / 'results.jsonl')
    runs = rows(exp / 'continuation.jsonl')
    batches = rows(exp / 'probe_batches.jsonl')
    pkeys = [(r['target_id'], r['sample']) for r in probes]
    rkeys = [(r['target_id'], r['start_id'], r['rep']) for r in runs]
    return {'checked_at': datetime.now(timezone.utc).isoformat(), 'read_only_monitor': True,
            'probe_planned': len(rows(exp / 'targets.jsonl')) * max(manifest.get('ks', [20])),
            'probe_recorded': len(probes),
            'probe_cached_slots': len(list((exp / 'probe_batch/slots').glob('*.json'))),
            'probe_statuses': dict(Counter(r['status'] for r in probes)),
            'probe_submission': read('probe_batch/submission.json'),
            'remote_poll': read('probe_batch/poll_status.json'),
            'continuation_recorded': len(runs),
            'continuation_statuses': dict(Counter(r['status'] for r in runs)),
            'duplicate_probe_slots': len(pkeys) - len(set(pkeys)),
            'duplicate_continuation_slots': len(rkeys) - len(set(rkeys)),
            'probe_charged_usd': sum(float((r.get('usage') or {}).get('cost') or 0.) for r in batches if r.get('event') == 'finished'),
            'continuation_recorded_usd': sum(r.get('cost_usd', 0.) for r in runs),
            'workflow': read('workflow_status.json')}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--experiment', type=Path, required=True)
    parser.add_argument('--once', action='store_true')
    args = parser.parse_args()
    while True:
        status = snapshot(args.experiment)
        save(args.experiment / 'monitor_status.json', status)
        print(json.dumps(status), flush=True)
        if args.once or (status.get('workflow') or {}).get('state') in ('complete', 'failed', 'interrupted'):
            return
        time.sleep(30)


if __name__ == '__main__':
    main()
