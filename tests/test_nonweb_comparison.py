import importlib.util
from pathlib import Path
import json
from fakes import ScriptedLLM, fake_web
from test_harness import action, evaluation
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
        script={'orchestrator':[action(),action('finish')], 'worker':['Title: Count\n2'],
                'evaluator_execution':[evaluation()]}
        if arm=='adaptive_probe':
            script={'orchestrator':[action('probe',wid=None),action(instruction=None,instruction_id='a00004'),action('finish')],
                    'worker':['Title: Probe\nPlan']*2+['Title: Count\n2'], 'evaluator_probe':[evaluation()],
                    'refiner':[{'action':'refine','can_refine':True,'instruction':'Count unique orders.',
                                'context_notes':'','rationale':'Keep scope'}], 'evaluator_execution':[evaluation()]}
        llm=ScriptedLLM(script)
        cfg=RunConfig(pool,load_condition(arm),budget=Limits(max_cost_usd=.20))
        run=Run(cfg,task,tmp_path/arm,transport=llm,web=fake_web(tmp_path))
        assert run.run_fresh()['status']=='ok'
        for body in llm.by_kind['worker']:
            names={t['function']['name'] for t in body.get('tools',[])}
            assert names==set(nonweb.LOCAL_TOOLS)
