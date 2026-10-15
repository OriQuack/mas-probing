import importlib.util
from pathlib import Path
import json
from fakes import ScriptedLLM, fake_web
from test_harness import action
from minpilot.config import RunConfig, load_condition
from minpilot.harness import Run
from minpilot.runtime.trace import Limits

spec=importlib.util.spec_from_file_location('nonweb',Path(__file__).resolve().parents[1]/'scripts/run_nonweb_comparison.py')
nonweb=importlib.util.module_from_spec(spec);spec.loader.exec_module(nonweb)


def test_nonweb_pool_and_both_runtime_paths(tmp_path,task):
    pool=nonweb.local_pool()
    assert set(pool.workers)=={'gen_luna','gen_haiku'}
    assert all(w.tools==('read_file','view_image','run_python') for w in pool.workers.values())
    for arm in nonweb.ARMS:
        script={'orchestrator':[action(),action('finish')], 'worker':['Count: 2']}
        if arm=='adaptive_probe':
            script={'orchestrator':[action('probe'),action(),action('finish')], 'worker':['plan: read']*2+['Count: 2']}
        llm=ScriptedLLM(script)
        cfg=RunConfig(pool,load_condition(arm),budget=Limits(max_cost_usd=.20))
        run=Run(cfg,task,tmp_path/arm,transport=llm,web=fake_web(tmp_path))
        assert run.run_fresh()['status']=='ok'
        for body in llm.by_kind['worker']:
            names={t['function']['name'] for t in body.get('tools',[])}
            assert names==set(nonweb.LOCAL_TOOLS)


def test_tasks_needing_web_facts_are_excluded_from_new_selections():
    assert nonweb.EXCLUDED_TASKS == {'305ac316-eef6-4446-960a-92d80d542f82', '5a0c1adf-205e-4841-a666-7c3ef95def9d'}

