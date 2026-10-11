"""Perturbation consistency: pick a worker by how consistently it answers the first subtask, then let it do the rest.

A separate experiment harness, not part of the `minpilot` orchestrator framework (it reuses only minpilot's LLM
client, trace/budget accounting and dataset loaders). On LongCoT math chains (nodes whose answers feed later nodes):

- each of k candidate workers answers the first node n times, each time told to solve it a different way (chain of
  thought, plan-and-solve, solve then check, step-back, no instruction) around the unchanged problem text; its consistency is the share of its
  answers in the largest group of equivalent answers;
- the most consistent worker (ties: seeded random) solves the remaining nodes, starting from its modal first answer
  (arm `consistency_routed`);
- every worker also solves the whole chain several times on its own (arms `fixed_<worker>`), as the comparison.

Gold answers are read only by the analysis script.
"""
