"""Standalone no-probe GAIA instruction comparison, preserving one worker conversation."""
from __future__ import annotations

import csv
import datetime as dt
import fcntl
import hashlib
import json
import os
from pathlib import Path
import random
import shutil
import subprocess
import sys
import time

from minpilot import prompts
from minpilot.agents.worker import Worker
from minpilot.config import WorkerSpec
from minpilot.data.gaia import ANSWER_FORMAT, GAIA_ROOT
from minpilot.eval.answer import EXTRACTION_VERSION, extract_final_answer
from minpilot.llm.client import LLMClient, RateLimited, http_transport
from minpilot.llm.specs import get_spec
from minpilot.runtime.trace import BudgetExceeded, InfraError, Limits, Trace
from minpilot.tools.config import ToolConfig
from minpilot.tools.sandbox import landlock_abi
from minpilot.tools.toolbox import Toolbox, ToolOutput
from minpilot.tools.web import WebTools

VERSION = 'gaia-instruction-execution-v1'
ARMS = ('naive', 'clarify', 'structured', 'verify')
MODEL = 'haiku-medium'
TOOLS = ('read_file', 'view_image', 'run_python')
RUN_CAP = .20
REPS = 3
MAX_TOOL_CALLS = 20
MAX_WALL_S = 10800
ROOT = Path(__file__).resolve().parents[2]
CONTINUATION = """Use the work you have completed in this conversation and the files in your workspace to solve the original task completely. Carry out any remaining work using your available tools. If your earlier work already establishes the answer, use it to finish. Preserve the original task's target, conditions, and requested answer format. You are now responsible for the original task, rather than only the earlier subtask.

Give your result and concise supporting evidence. End with exactly one final line:
Final answer: <the answer to the original task>
Put only the answer on that final line, following the original task's answer format."""
SYSTEM = ('You are a generalist worker. You read local files and documents, look at local images, '
          'and compute with Python, and you report results with their evidence. '
          'This experiment has no web access; use only local workspace files and your available knowledge.')


def now():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read_rows(path):
    return [json.loads(s) for s in Path(path).read_text().splitlines() if s.strip()]


def write_json(path, data):
    path = Path(path)
    temp = path.with_suffix(path.suffix + '.tmp')
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str) + '\n')
    temp.replace(path)


def append(path, record):
    with Path(path).open('a') as f:
        f.write(json.dumps(record, ensure_ascii=False, default=str) + '\n')


def make_plan(ids):
    plan = []
    for rep in range(REPS):
        for i, task_id in enumerate(ids):
            order = list(ARMS)
            random.Random(1000 * rep + i).shuffle(order)
            for arm in order:
                plan.append(dict(task_id=task_id, condition=arm, repetition=rep,
                    slot=f'{task_id}_{arm}_r{rep}'))
    return plan


def prepare(exp, source):
    import pyarrow.parquet as pq
    exp, source = Path(exp).resolve(), Path(source).resolve()
    if exp.exists():
        raise ValueError('use a new experiment directory')
    source_manifest = json.loads((source / 'manifest.json').read_text())
    for name, sha in source_manifest['artifact_sha256'].items():
        if digest(source / name) != sha:
            raise ValueError(f'changed candidate artifact: {name}')
    with (source / 'tasks.csv').open() as f:
        selected = list(csv.DictReader(f))
    ids = [r['task_id'] for r in selected]
    assert len(ids) == len(set(ids)) == 34
    candidates = read_rows(source / 'candidates.reviewed.jsonl')
    by_candidate = {r['task_id']: r for r in candidates}
    assert len(candidates) == len(by_candidate) == 34 and set(by_candidate) == set(ids)
    for r in candidates:
        assert r['accepted'] is True and set(r['instructions']) == set(ARMS)
        assert r['instructions']['naive'] == ''
    # Never read answer/annotation columns in preparation or execution.
    data = pq.read_table(GAIA_ROOT / 'validation/metadata.parquet',
        columns=['task_id', 'Level', 'Question', 'file_name'],
        filters=[('task_id', 'in', ids)]).to_pylist()
    by_data = {r['task_id']: r for r in data}
    inputs = []
    for task_id in ids:
        row = by_data[task_id]
        name = row['file_name'] or None
        path = GAIA_ROOT / 'validation' / name if name else None
        if path and not path.is_file():
            raise FileNotFoundError(path)
        inputs.append(dict(task_id=task_id, question=row['Question'], level=int(row['Level']),
            file_name=name, attachment_sha256=digest(path) if path else None))
    exp.mkdir(parents=True)
    for name in ['runs', 'logs', 'analysis']:
        (exp / name).mkdir()
    shutil.copyfile(source / 'tasks.csv', exp / 'tasks.csv')
    shutil.copyfile(source / 'candidates.reviewed.jsonl', exp / 'candidates.jsonl')
    (exp / 'inputs.jsonl').write_text(''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in inputs))
    plan = make_plan(ids)
    with (exp / 'planned.csv').open('w') as f:
        writer = csv.DictWriter(f, fieldnames=list(plan[0]))
        writer.writeheader(); writer.writerows(plan)
    snapshot = exp / 'snapshot'
    shutil.copytree(ROOT / 'src', snapshot / 'src', ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    (snapshot / 'scripts').mkdir()
    shutil.copyfile(ROOT / 'scripts/run_gaia_instruction_execution.py', snapshot / 'scripts/run_gaia_instruction_execution.py')
    hashes = {str(p.relative_to(snapshot)): digest(p) for p in sorted(snapshot.rglob('*.py'))}
    manifest = dict(schema_version=1, experiment_version=VERSION,
        purpose='Exploratory GAIA non-web: four fixed first-subtask instructions, no probe, same-worker completion',
        created_at=now(), original_workspace=str(ROOT), candidate_source=str(source),
        candidate_source_manifest_sha256=digest(source / 'manifest.json'), run_roots=['runs'],
        tasks=34, conditions=list(ARMS), repetitions=REPS, planned_run_count=len(plan),
        model=get_spec(MODEL).identity(), execution_prompt_version=prompts.PROMPTS_VERSION,
        first_request='reviewed common subtask + condition add-on', continuation_prompt=CONTINUATION,
        system_preamble=SYSTEM, tools=list(TOOLS), tool_config=ToolConfig(reader_chain=(), tools_version='v7-gaia-local-v1').to_dict(),
        per_request_tool_calls=MAX_TOOL_CALLS, per_run_cost_usd=RUN_CAP,
        session_cost_usd=round(len(plan) * RUN_CAP, 2), max_wall_s=MAX_WALL_S,
        max_llm_calls=100, max_tool_calls=40, starting_parallel_runs=2,
        rate_limit_policy='on first 429 permanently admit one run and serialize subsequent HTTP requests across active runs',
        sampling='fresh independent conversation/workspace per task-condition-repetition; no outcome-dependent resampling',
        order='repetition-major, source task order, deterministic shuffled arm order seed=1000*rep+task_index',
        completion='always same second request, even for terminal-capable subtasks; same worker and workspace',
        scoring='official GAIA scorer with extraction v1; non-ok/missing planned runs count as failures; task-level paired bootstrap',
        source_columns=['task_id', 'Level', 'Question', 'file_name'],
        input_hashes={n: digest(exp / n) for n in ['tasks.csv', 'candidates.jsonl', 'inputs.jsonl', 'planned.csv']},
        snapshot_hashes=hashes)
    write_json(exp / 'manifest.json', manifest)
    print(json.dumps(dict(prepared=str(exp), runs=len(plan), maximum_cost_usd=manifest['session_cost_usd'])), flush=True)


def verify(exp):
    manifest = json.loads((exp / 'manifest.json').read_text())
    assert manifest['experiment_version'] == VERSION
    assert manifest['model'] == get_spec(MODEL).identity()
    assert manifest['execution_prompt_version'] == prompts.PROMPTS_VERSION
    assert manifest['continuation_prompt'] == CONTINUATION and manifest['system_preamble'] == SYSTEM
    for name, sha in manifest['input_hashes'].items():
        assert digest(exp / name) == sha, name
    for name, sha in manifest['snapshot_hashes'].items():
        assert digest(exp / 'snapshot' / name) == sha, name
    return manifest


class AdaptiveTransport:
    """Shared/exclusive HTTP gate: first 429 atomically switches all processes to serial requests."""
    def __init__(self, exp, send):
        self.exp, self.send = Path(exp), send

    def __call__(self, body, timeout):
        with (self.exp / 'api.lock').open('a') as lock:
            serial = (self.exp / 'serial_after_429.json').exists()
            fcntl.flock(lock, fcntl.LOCK_EX if serial else fcntl.LOCK_SH)
            # A 429 may have occurred while this process waited for the shared gate.
            if not serial and (self.exp / 'serial_after_429.json').exists():
                fcntl.flock(lock, fcntl.LOCK_UN)
                fcntl.flock(lock, fcntl.LOCK_EX)
            try:
                return self.send(body, timeout)
            except RateLimited:
                try:
                    with (self.exp / 'serial_after_429.json').open('x') as f:
                        json.dump(dict(at=now(), pid=os.getpid(), parallel_runs=1), f)
                except FileExistsError:
                    pass
                raise
            finally:
                fcntl.flock(lock, fcntl.LOCK_UN)


class LocalToolbox(Toolbox):
    """Close view_image's URL path for this declared local-only standalone condition."""
    def _t_view_image(self, path):
        if str(path).strip().startswith(('http://', 'https://')):
            return ToolOutput('Error: only local workspace images are available in this experiment.'), {'error': 'local_only'}
        return super()._t_view_image(path)


def run_protocol(worker, original, subtask, addition, toolbox, trace, save_turn):
    first = subtask + ('\n\n' + addition if addition else '')
    for phase, instruction in [('first_subtask', first), ('completion', CONTINUATION)]:
        with trace.tags(stage='execution', phase=phase, worker=worker.id):
            trace.before_worker_call()
            result = worker.run(original, instruction, toolbox)
        save_turn(phase, result, worker.messages)
        if result.status == 'empty':
            raise RuntimeError(f'empty {phase} response')
    return result.report


def worker_run(exp, slot):
    from dotenv import load_dotenv
    manifest = verify(exp)
    load_dotenv(Path(manifest['original_workspace']) / '.env')
    with (exp / 'planned.csv').open() as f:
        jobs = [r for r in csv.DictReader(f) if r['slot'] == slot]
    assert len(jobs) == 1
    job = jobs[0]
    run_dir = exp / 'runs' / slot
    run_dir.mkdir(exist_ok=False)
    work = run_dir / 'work'
    work.mkdir()
    inputs = {r['task_id']: r for r in read_rows(exp / 'inputs.jsonl')}
    candidates = {r['task_id']: r for r in read_rows(exp / 'candidates.jsonl')}
    row, candidate = inputs[job['task_id']], candidates[job['task_id']]
    if row['file_name']:
        src = GAIA_ROOT / 'validation' / row['file_name']
        assert digest(src) == row['attachment_sha256']
        (work / 'attachments').mkdir()
        shutil.copyfile(src, work / 'attachments' / row['file_name'])
    limits = Limits(max_cost_usd=manifest['per_run_cost_usd'], max_wall_s=MAX_WALL_S,
        max_llm_calls=100, max_tool_calls=40, max_worker_calls=2)
    trace = Trace(run_dir, limits)
    info = dict(**job, label=f"{job['condition']}_r{job['repetition']}",
        experiment_version=VERSION, started_at=now(), status='running', final_answer=None, n_probes=0,
        model=manifest['model'], execution_prompt_version=prompts.PROMPTS_VERSION)
    write_json(run_dir / 'run.json', info)
    try:
        transport = AdaptiveTransport(exp, http_transport(os.environ['OPENROUTER_API_KEY']))
        client = LLMClient(get_spec(MODEL), trace, transport=transport)
        spec = WorkerSpec('executor', MODEL, TOOLS, SYSTEM, MAX_TOOL_CALLS)
        worker = Worker(spec, client)
        cfg = ToolConfig(reader_chain=(), tools_version='v7-gaia-local-v1', cache_path=run_dir / 'local_cache.sqlite')
        web = WebTools(cfg, question=row['question'])
        web.search_backends = []; web.read_backends = []
        toolbox = LocalToolbox(work, web, trace, question=row['question'])
        original = prompts.original_task_text(row['question'],
            f"attachments/{row['file_name']}" if row['file_name'] else None)
        original += '\n\nBenchmark final-answer format:\n' + ANSWER_FORMAT
        def save(phase, result, messages):
            write_json(run_dir / f'{phase}.json', dict(report=result.report, status=result.status,
                n_tool_calls=result.n_tool_calls, tools_used=result.tools_used, messages=messages))
        report = run_protocol(worker, original, candidate['subtask'],
            candidate['instructions'][job['condition']], toolbox, trace, save)
        info.update(status='ok', final_answer=extract_final_answer(report), raw_final_report=report)
    except BudgetExceeded as e:
        info.update(status='budget_exceeded', error=str(e))
    except Exception as e:
        info.update(status='error_infra' if isinstance(e, InfraError) else 'error',
            error=f'{type(e).__name__}: {e}'[:700])
    info.update(completed_at=now(), counters=trace.run_scope.counters(), usage=trace.usage)
    write_json(run_dir / 'run.json', info)
    print(json.dumps(dict(slot=slot, status=info['status'], counters=info['counters'])), flush=True)


def execute(exp):
    manifest = verify(exp)
    if landlock_abi() < 4:
        raise RuntimeError('Landlock ABI >=4 required')
    with (exp / 'controller.lock').open('a') as controller_lock:
        fcntl.flock(controller_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        _execute_locked(exp, manifest)


def _execute_locked(exp, manifest):
    with (exp / 'planned.csv').open() as f:
        plan = list(csv.DictReader(f))
    # Resume only never-started slots; never resample an observed result or an interrupted slot.
    launched = {r['slot'] for r in read_rows(exp / 'batch.jsonl') if r.get('event') == 'started'} if (exp / 'batch.jsonl').exists() else set()
    pending = [r for r in plan if r['slot'] not in launched]
    active, completed = {}, {}
    for job in plan:
        path = exp / 'runs' / job['slot'] / 'run.json'
        if path.exists():
            rec = json.loads(path.read_text())
            if rec['status'] != 'running':
                completed[job['slot']] = rec
    spent = sum(r.get('counters', {}).get('cost_usd', 0) for r in completed.values())
    if any(r.get('counters', {}).get('unknown_cost_calls') or r['status'] == 'error_infra' for r in completed.values()):
        raise RuntimeError('Prior unknown billing/infrastructure failure: inspect before resuming')
    if launched - set(completed):
        raise RuntimeError('Previously started slot lacks terminal record: inspect before resuming')
    stop = False
    script = exp / 'snapshot/scripts/run_gaia_instruction_execution.py'
    def record(rec):
        append(exp / 'batch.jsonl', dict(at=now(), **rec))
        print(json.dumps(rec, ensure_ascii=False), flush=True)
    while pending or active:
        parallel = 1 if (exp / 'serial_after_429.json').exists() else 2
        while pending and len(active) < parallel and not stop:
            job = pending.pop(0)
            if spent + (len(active) + 1) * RUN_CAP > manifest['session_cost_usd'] + 1e-8:
                stop = True; pending.insert(0, job); break
            out = (exp / 'logs' / f"{job['slot']}.out").open('a')
            err = (exp / 'logs' / f"{job['slot']}.err").open('a')
            child = subprocess.Popen([sys.executable, '-u', str(script), 'worker',
                '--experiment', str(exp), '--slot', job['slot']], stdout=out, stderr=err)
            active[job['slot']] = (child, job, out, err, time.monotonic())
            record(dict(event='started', **job, pid=child.pid, parallel_limit=parallel))
        for slot, (child, job, out, err, started) in list(active.items()):
            if child.poll() is None and time.monotonic() - started > MAX_WALL_S + 120:
                child.kill(); child.wait()
            if child.poll() is None:
                continue
            out.close(); err.close(); del active[slot]
            path = exp / 'runs' / slot / 'run.json'
            rec = json.loads(path.read_text()) if path.exists() else {}
            if not rec or rec.get('status') == 'running':
                stop = True
                record(dict(event='incomplete_process', **job, exit_code=child.returncode,
                    note='reservation retained; no automatic rerun'))
                continue
            completed[slot] = rec
            cost = rec['counters']['cost_usd']; spent += cost
            uncertain = bool(rec['counters']['unknown_cost_calls']) or rec['status'] == 'error_infra' or child.returncode != 0
            stop |= uncertain
            record(dict(event='completed', **job, status=rec['status'], cost_usd=cost,
                unknown_cost_calls=rec['counters']['unknown_cost_calls'], completed=len(completed),
                spent_usd=round(spent, 6), parallel_limit=parallel))
        write_json(exp / 'progress.json', dict(at=now(), planned=len(plan), completed=len(completed),
            active=list(active), pending=len(pending), parallel_limit=parallel,
            spent_usd=round(spent, 8), stopped=stop))
        if stop and not active:
            break
        if active:
            time.sleep(2)
    record(dict(event='batch_finished' if len(completed) == len(plan) else 'batch_stopped',
        completed=len(completed), planned=len(plan), spent_usd=round(spent, 8)))


def score(exp):
    import numpy as np
    import pyarrow.parquet as pq
    from minpilot.eval.gaia_scorer import question_scorer
    verify(exp)
    with (exp / 'planned.csv').open() as f:
        plan = list(csv.DictReader(f))
    ids = list(dict.fromkeys(r['task_id'] for r in plan))
    # Gold is read only here, after execution; never passed to a model.
    truth = {r['task_id']: r['Final answer'] for r in pq.read_table(GAIA_ROOT / 'validation/metadata.parquet',
        columns=['task_id', 'Final answer'], filters=[('task_id', 'in', ids)]).to_pylist()}
    scores = []
    for job in plan:
        path = exp / 'runs' / job['slot'] / 'run.json'
        r = json.loads(path.read_text()) if path.exists() else {}
        answer = extract_final_answer(r.get('final_answer'))
        c = r.get('counters', {})
        scores.append(dict(**job, status=r.get('status', 'missing'), answer=answer,
            correct=bool(r.get('status') == 'ok' and answer is not None and question_scorer(answer, truth[job['task_id']])),
            cost_usd=c.get('cost_usd', 0), unknown_cost_calls=c.get('unknown_cost_calls', 0),
            tool_calls=c.get('tool_calls', 0), llm_calls=c.get('llm_calls', 0), wall_s=c.get('wall_s', 0)))
    with (exp / 'analysis/scores.csv').open('w') as f:
        writer = csv.DictWriter(f, fieldnames=list(scores[0])); writer.writeheader(); writer.writerows(scores)
    per_task = {tid: {arm: sum(r['correct'] for r in scores if r['task_id'] == tid and r['condition'] == arm) / REPS
        for arm in ARMS} for tid in ids}
    rng = np.random.default_rng(0)
    sample = rng.integers(0, len(ids), size=(10000, len(ids)))
    arms = {}
    for arm in ARMS:
        rr = [r for r in scores if r['condition'] == arm]
        delta = np.array([per_task[t][arm] - per_task[t]['naive'] for t in ids])
        arms[arm] = dict(planned=len(rr), correct=sum(r['correct'] for r in rr),
            accuracy=float(np.mean([per_task[t][arm] for t in ids])), delta_vs_naive=float(delta.mean()),
            ci95_vs_naive=np.quantile(delta[sample].mean(axis=1), [.025, .975]).tolist(),
            cost_usd=sum(r['cost_usd'] for r in rr),
            statuses={s: sum(r['status'] == s for r in rr) for s in sorted({r['status'] for r in rr})})
    summary = dict(experiment_version=VERSION, planned=len(scores), tasks=len(ids), repetitions=REPS,
        extraction_version=EXTRACTION_VERSION, conditions=arms, per_task=per_task,
        cost_usd=sum(r['cost_usd'] for r in scores), unknown_cost_calls=sum(r['unknown_cost_calls'] for r in scores),
        rate_limit_serialized=(exp / 'serial_after_429.json').exists(), scored_at=now())
    write_json(exp / 'analysis/summary.json', summary)
    print(json.dumps({k: v for k, v in summary.items() if k != 'per_task'}, ensure_ascii=False, indent=2))
