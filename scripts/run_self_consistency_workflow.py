#!/usr/bin/env python
"""Resume saved batch collection, then sync continuation and analysis, with local monitoring."""
import argparse
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from perturbation_consistency.durable_batch import save
import run_instruction_selection as base
from monitor_self_consistency import snapshot


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--experiment', type=Path, required=True)
    parser.add_argument('--probe-cap', type=float, required=True)
    parser.add_argument('--continuation-cap', type=float, required=True)
    args = parser.parse_args()
    exp = args.experiment.resolve()
    child = None
    state = {'state': 'starting', 'pid': os.getpid(), 'started_at': base.now()}

    def status(**updates):
        state.update(updates, checked_at=base.now())
        save(exp / 'workflow_status.json', state)
        save(exp / 'monitor_status.json', snapshot(exp))

    def interrupted(signum, frame):
        if child is not None and child.poll() is None:
            child.terminate()
            try:
                child.wait(timeout=15)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait()
        status(state='interrupted', signal=signum)
        raise SystemExit(128 + signum)

    signal.signal(signal.SIGTERM, interrupted)
    signal.signal(signal.SIGINT, interrupted)
    # Separate controller lock: each stage also owns the experiment writer lock.
    with (exp / '.workflow.lock').open('a') as lock:
        import fcntl
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        stages = [
            ('probe', ['--batch', '--session-cost-usd', str(args.probe_cap), '--run-cost-usd', '.1']),
            ('continue', ['--session-cost-usd', str(args.continuation_cap), '--run-cost-usd', '1', '--concurrency', '8']),
            ('analyze', [])]
        for stage, flags in stages:
            command = [sys.executable, '-u', str(ROOT / 'scripts/run_self_consistency.py'), stage,
                       '--experiment', str(exp), *flags]
            with (exp / f'{stage}.log').open('a') as output:
                child = subprocess.Popen(command, cwd=ROOT, stdout=output, stderr=subprocess.STDOUT)
                status(state='running', stage=stage, child_pid=child.pid)
                print(json.dumps(state), flush=True)
                while child.poll() is None:
                    status()
                    time.sleep(15)
                if child.returncode:
                    status(state='failed', exit_code=child.returncode)
                    raise SystemExit(child.returncode)
            if stage == 'probe':
                collection = json.loads((exp / 'probe_batch/collection.json').read_text())
                if collection['batch_status'] != 'completed':
                    status(state='failed', error='batch did not complete; preserved results, continuation not started')
                    raise SystemExit(1)
        status(state='complete')
        print(json.dumps(state), flush=True)


if __name__ == '__main__':
    main()
