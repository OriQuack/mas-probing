#!/usr/bin/env python
"""No-probe GAIA first-subtask instruction comparison: prepare/execute/worker/score."""
import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from perturbation_consistency import gaia_instruction_execution as experiment


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('mode', choices=['prepare', 'execute', 'worker', 'score'])
    ap.add_argument('--experiment', type=Path, required=True)
    ap.add_argument('--source', type=Path)
    ap.add_argument('--slot')
    args = ap.parse_args()
    exp = args.experiment.resolve()
    if args.mode == 'prepare':
        experiment.prepare(exp, args.source)
    elif args.mode == 'worker':
        experiment.worker_run(exp, args.slot)
    else:
        getattr(experiment, args.mode)(exp)
