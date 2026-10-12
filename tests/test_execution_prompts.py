from minpilot import prompts
from minpilot.prompts.orchestrator import ORCHESTRATOR
from minpilot.prompts.evaluator import EVALUATOR
from minpilot.prompts.refiner import REFINER


def test_prompt_versions_and_report_contract():
    assert (prompts.PROMPTS_VERSION, prompts.REFINER_PROMPTS_VERSION, prompts.EVALUATOR_VERSION) == ("v18", "r21", "e6")
    text = prompts.worker_system("worker", ())
    assert text.index("Result:") < text.index("Evidence:") < text.index("Interpretation:") < text.index("Unfinished:")
    assert "Title:" in text and "access blocking" in text
    assert "Title:" in prompts.probe_instruction("draft", True, 3)


def test_prompt_walkthroughs_keep_original_scope():
    # Contract walkthroughs, not claims about a real model's behavior.
    cases = {
        "ArXiv historical proof": "exhaustive exclusion",
        "Secret Santa withholding": "withholding the answer",
        "USDA inclusion criteria": "inclusion and exclusion criteria",
        "Freud repeated search": "reported search terms",
    }
    for case, policy in cases.items():
        assert policy in EVALUATOR, case
    assert "new source, method or clue" in ORCHESTRATOR
    assert "add proof requirements" in REFINER


import json
from dataclasses import replace
import pytest
from test_harness import action, direct_script, evaluation, make_run, row


@pytest.mark.parametrize("name,question,report,state", [
    ("ArXiv", "Count papers offering a requested format in the specified collection.",
     "Title: Partial format check\nEvidence: papers 1–30 inspected. Unfinished: 31–97 remain; no extra historical proof requested.",
     [row(type="progress", status="incomplete", content="Papers 31–97 remain; do not impose historical exhaustive proof.")]),
    ("Secret Santa", "Who receives the gift according to the table and story?",
     "Title: Direction\nEvidence: table read. Interpretation: second column as recipient. Result: conditional candidate Fred.",
     [row(type="assumption", status="unverified", content="Second column is recipient."),
      row(content="If second column means recipient, candidate is Fred; deferred direction check is not automatic withholding.")]),
    ("USDA", "Aggregate all entries under the original inclusion criteria.",
     "Title: Aggregation\nEvidence: original population read. Interpretation: proposed extra exclusion changes the population.",
     [row(type="assumption", status="rejected", content="Excluding additional categories is not supported by the question.")]),
    ("Freud", "Locate and read the passage before identifying its subject.",
     "Title: Search failure\nUnfinished: query X, source Y, abstract read, body blocked; new clue Z supports the next method.",
     [row(type="progress", status="blocked", content="Query X/source Y: abstract read, body blocked. Retry with new clue Z; incompletion alone does not forbid retry.")]),
])
def test_scripted_prompt_walkthroughs_preserve_scope_and_evidence(tmp_path, task, name, question, report, state):
    # Synthetic contract examples; scripted outputs cannot demonstrate real-model improvement.
    task = replace(task, question=question)
    script = direct_script(worker=[report], evaluator_execution=[evaluation(state)],
                           orchestrator=[action(), action("finish")])
    run, llm = make_run(tmp_path, task, script)
    info = run.run_fresh()
    assert info["status"] == "ok"
    assert info["state"] == state
    payload = json.loads(llm.by_kind["evaluator_execution"][0]["messages"][1]["content"])
    assert question in payload["original_task"] and payload["reports"][0]["body"] == report
