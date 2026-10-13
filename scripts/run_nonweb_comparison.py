"""Frozen exploratory GAIA non-web fresh comparison; prepare before explicitly executing.

Only task IDs in exploration_v1 are read. Tools metadata is used for selection only;
answers are read solely by the separate post-run score command.
"""
from __future__ import annotations
import argparse
from concurrent.futures import ThreadPoolExecutor
import csv
import datetime as dt
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import threading

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / 'src'))
from minpilot import prompts
from minpilot.config import RunConfig, load_condition, load_pool, PoolConfig
from minpilot.data.gaia import GaiaTask, GAIA_ROOT
from minpilot.harness import Run, code_hash, new_run_dir
from minpilot.runtime.trace import Limits
from minpilot.tools.config import ToolConfig
from minpilot.tools.sandbox import landlock_abi
from minpilot.tools.web import WebTools

ARMS = ('direct_execution', 'adaptive_probe')
WEB = re.compile(r'web|browser|search|wikipedia|google maps|street view|youtube', re.I)
LOCAL_TOOLS = ('read_file', 'view_image', 'run_python')
RUN_CAP = .20
TOTAL_CAP = 5.


def local_pool():
    from dataclasses import replace
    pool = load_pool('multi')
    return PoolConfig('multi_local', {wid: replace(w, tools=LOCAL_TOOLS,
        system_prompt='You are a generalist worker. You read files and documents, look at images, '
                      'and compute with Python, and you report results with their evidence.')
        for wid, w in pool.workers.items()})


def read_csv(path):
    with Path(path).open() as f:
        return list(csv.DictReader(f))


def write_csv(path, rows):
    with Path(path).open('w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader(); writer.writerows(rows)


def prepare(root):
    import pyarrow.parquet as pq
    if root.exists():
        raise ValueError('use a new experiment directory')
    exploration = read_csv(REPO / 'data/splits/exploration_v1.csv')
    scope = {r['task_id']: r for r in read_csv(REPO / 'data/splits/task_scope.csv')}
    records = pq.read_table(GAIA_ROOT / 'validation/metadata.parquet',
        columns=['task_id', 'Annotator Metadata.Tools'],
        filters=[('task_id', 'in', [r['task_id'] for r in exploration])]).to_pylist()
    tools = {r['task_id']: r['Tools'] for r in records}
    chosen = [r for r in exploration if scope[r['task_id']]['included'].lower() in ('true', '1')
              and tools[r['task_id']] is not None and not WEB.search(tools[r['task_id']])]
    assert len(chosen) == 36 and len({r['task_id'] for r in chosen}) == 36
    root.mkdir(parents=True)
    (root / 'logs').mkdir(); (root / 'analysis').mkdir()
    write_csv(root / 'tasks.csv', chosen)
    plan = []
    for i, task in enumerate(chosen):
        order = ARMS if i % 2 == 0 else ARMS[::-1]
        for arm in order:
            plan.append(dict(task_id=task['task_id'], label=arm+'_r0', mode='fresh', pool='multi_local',
                             condition=arm, checkpoint='', override_source=''))
    write_csv(root / 'planned.csv', plan)
    manifest = dict(schema_version=1, purpose='Non-web exploratory GAIA: direct execution versus adaptive probe',
        created_at=dt.datetime.now(dt.timezone.utc).isoformat(), run_roots=['runs'], planned_run_count=72,
        conditions=list(ARMS), execution_prompt_versions=[prompts.PROMPTS_VERSION],
        refiner_prompt_versions=[prompts.REFINER_PROMPTS_VERSION], evaluator_prompt_versions=[prompts.EVALUATOR_VERSION],
        code_hash=code_hash(), runner_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        selection='exploration_v1 intersect existing AV scope; exclude any Tools web/search/Wikipedia/Maps/YouTube mention including optional; exclude null Tools',
        task_csv_sha256=hashlib.sha256((root/'tasks.csv').read_bytes()).hexdigest(),
        pool=local_pool().to_dict(), per_run_cost_usd=RUN_CAP, session_cost_usd=TOTAL_CAP,
        max_wall_s=10800, max_delegations=12, parallel_pairs=2, repetitions=1,
        order='task pairs, alternating which condition runs first; no outcome-dependent edits or retries',
        budget_policy='Reserve $0.40 per task pair before launch; release only after both completed with known cost; stop admission on missing/unknown billing or infrastructure error',
        scoring='official scorer and extraction v1 after execution; missing/non-ok count as failures; paired by task_id',
        condition_configs={a:load_condition(a).to_dict() for a in ARMS})
    (root/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2))
    subprocess.run(['tar','czf',str(root/'code_snapshot.tar.gz'),'--exclude=__pycache__',
                    'src','configs','scripts','pyproject.toml'],cwd=REPO,check=True)
    print(json.dumps({'prepared':str(root),'tasks':36,'runs':72,'landlock_abi':landlock_abi()}))


def worker(root, task_id, arm):
    from dotenv import load_dotenv
    import pyarrow.parquet as pq
    load_dotenv(REPO/'.env')
    assert task_id in {r['task_id'] for r in read_csv(root/'tasks.csv')}
    r = pq.read_table(GAIA_ROOT/'validation/metadata.parquet',columns=['task_id','Level','Question','file_name'],
                      filters=[('task_id','=',task_id)]).to_pylist()[0]
    task = GaiaTask(task_id,int(r['Level']),r['Question'],r['file_name'] or None,
                    GAIA_ROOT/'validation'/r['file_name'] if r['file_name'] else None)
    cfg = RunConfig(local_pool(),load_condition(arm),label=arm+'_r0',
                    budget=Limits(max_llm_calls=400,max_tool_calls=400,max_cost_usd=RUN_CAP,max_wall_s=10800))
    run_dir = new_run_dir(task_id,cfg.label,root/'runs')
    tc = ToolConfig(reader_chain=(),cache_path=root/'local_cache.sqlite')
    web = WebTools(tc,question=task.question)
    web.search_backends=[]; web.read_backends=[]
    run = Run(cfg,task,run_dir,tool_cfg=tc,web=web)
    # Same hard-deadline guard as the main CLI, without eval split loading or reader service startup.
    def deadline():
        import os
        try:
            run._finish('budget_exceeded',error='hard deadline')
        finally:
            os._exit(0)
    timer=threading.Timer(10920,deadline);timer.daemon=True;timer.start()
    info=run.run_fresh()
    timer.cancel()
    print(json.dumps(dict(run_dir=str(run_dir),status=info['status'],cost_usd=info['counters']['cost_usd'],
                         unknown_cost_calls=info['counters']['unknown_cost_calls'])),flush=True)


def execute(root):
    m=json.loads((root/'manifest.json').read_text())
    assert m['code_hash']==code_hash() and m['runner_sha256']==hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    assert m['task_csv_sha256']==hashlib.sha256((root/'tasks.csv').read_bytes()).hexdigest()
    if (root/'batch.jsonl').exists():raise ValueError('already started; no implicit retries')
    if landlock_abi()<4:raise RuntimeError('Landlock ABI 4 required')
    plan=read_csv(root/'planned.csv');lock=threading.Lock();state=dict(spent=0.,reserved=0.,stop=False)
    def record(rec):
        with (root/'batch.jsonl').open('a') as f:f.write(json.dumps(rec)+'\n')
        print(json.dumps(rec),flush=True)
    def pair(items):
        with lock:
            if state['stop'] or state['spent']+state['reserved']+2*RUN_CAP>TOTAL_CAP:
                for item in items:record({**item,'skipped':'session_cost_guard'})
                return
            state['reserved']+=2*RUN_CAP
        cost=0.;uncertain=False
        for item in items:
            tag=item['task_id'][:8]+'_'+item['label']
            with (root/'logs'/f'{tag}.out').open('w') as out,(root/'logs'/f'{tag}.err').open('w') as err:
                try:
                    rc=subprocess.run([sys.executable,'-u',__file__,'worker','--experiment',str(root),
                        '--task-id',item['task_id'],'--arm',item['condition']],stdout=out,stderr=err,
                        cwd=REPO,timeout=11400).returncode
                except subprocess.TimeoutExpired:rc='killed_timeout'
            rec={**item,'exit':rc}
            try:
                result=json.loads((root/'logs'/f'{tag}.out').read_text().strip().splitlines()[-1])
                rec.update(result);cost+=float(result['cost_usd'])
                uncertain |= bool(result['unknown_cost_calls']) or result['status']=='error_infra' or rc!=0
            except Exception:
                uncertain=True;rec['note']='no valid result; budget reservation retained'
            with lock:
                record(rec)
                if uncertain:state['stop']=True
            if uncertain:break
        with lock:
            state['spent']+=cost
            if not uncertain:state['reserved']-=2*RUN_CAP
            (root/'budget.json').write_text(json.dumps(state,indent=2))
    with ThreadPoolExecutor(max_workers=2) as pool:list(pool.map(pair,[plan[i:i+2] for i in range(0,len(plan),2)]))
    print(json.dumps({'finished':state}),flush=True)


def score(root):
    import pyarrow.parquet as pq
    from minpilot.artifacts import find_run_records
    from minpilot.eval.answer import extract_final_answer
    from minpilot.eval.gaia_scorer import question_scorer
    tasks=read_csv(root/'tasks.csv')
    truth={r['task_id']:r['Final answer'] for r in pq.read_table(GAIA_ROOT/'validation/metadata.parquet',
        columns=['task_id','Final answer'],filters=[('task_id','in',[r['task_id'] for r in tasks])]).to_pylist()}
    runs={}
    for path in find_run_records(root):
        r=json.loads(path.read_text());key=(r['task_id'],r['condition'])
        if key in runs:raise ValueError('duplicate run')
        runs[key]=r
    rows=[]
    for item in read_csv(root/'planned.csv'):
        r=runs.get((item['task_id'],item['condition']),{});c=r.get('counters',{})
        answer=extract_final_answer(r.get('final_answer'))
        rows.append({**item,'status':r.get('status','missing'),'correct':r.get('status')=='ok' and question_scorer(answer,truth[item['task_id']]),
            'answer':answer,'cost_usd':c.get('cost_usd',0),'unknown_cost_calls':c.get('unknown_cost_calls',0),
            'wall_s':c.get('wall_s',0),'n_probes':r.get('n_probes',0),'n_delegations':r.get('n_delegations',0)})
    write_csv(root/'analysis/scores.csv',rows)
    summary={}
    for arm in ARMS:
        rr=[r for r in rows if r['condition']==arm]
        summary[arm]=dict(planned=len(rr),correct=sum(r['correct'] for r in rr),
            statuses={s:sum(r['status']==s for r in rr) for s in sorted({r['status'] for r in rr})},
            cost_usd=sum(r['cost_usd'] for r in rr),unknown_cost_calls=sum(r['unknown_cost_calls'] for r in rr),
            n_probes=sum(r['n_probes'] for r in rr),n_delegations=sum(r['n_delegations'] for r in rr))
    lookup={(r['task_id'],r['condition']):r for r in rows}
    summary['paired']={str(a)+','+str(b):sum(lookup[(t['task_id'],ARMS[0])]['correct']==a and
        lookup[(t['task_id'],ARMS[1])]['correct']==b for t in tasks) for a in (False,True) for b in (False,True)}
    (root/'analysis/summary.json').write_text(json.dumps(summary,indent=2))
    print(json.dumps(summary,indent=2))


if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('mode',choices=['prepare','execute','worker','score'])
    ap.add_argument('--experiment',type=Path,required=True);ap.add_argument('--task-id');ap.add_argument('--arm',choices=ARMS)
    a=ap.parse_args();root=a.experiment.resolve()
    if a.mode=='worker':worker(root,a.task_id,a.arm)
    else:globals()[a.mode](root)
