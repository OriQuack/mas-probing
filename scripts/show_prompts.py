"""Render current complete prompts without model or web calls."""
import argparse
from minpilot import prompts
from minpilot.config import load_pool
from minpilot.prompts.orchestrator import ORCHESTRATOR
from minpilot.prompts.reader import PROMPT


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--component", choices=("all", "orchestrator", "worker", "probe", "reader"), default="all")
    parser.add_argument("--pool", default="multi")
    args = parser.parse_args()
    worker = next(iter(load_pool(args.pool).workers.values()))
    values = {"orchestrator": ORCHESTRATOR,
              "worker": prompts.worker_system(worker.system_prompt, worker.tools),
              "probe": prompts.probe_system(worker.system_prompt, worker.tools) + "\n\n" + prompts.probe_instruction("Count unique orders.", True, 3),
              "reader": PROMPT.format(source="Example content.", question="What does it say?")}
    print(f"Execution {prompts.PROMPTS_VERSION}; probe {prompts.PROBE_PROMPTS_VERSION}")
    for key in values if args.component == "all" else [args.component]:
        print(f"\n## {key}\n\n{values[key]}")


if __name__ == "__main__":
    main()
