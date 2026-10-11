"""Aggregate the JSON summary blocks of docs/reports/cases/analysis/<task>.md (+ _allcorrect.md) into tables.
usage: python scripts/aggregate_case_analysis.py > outputs/analysis/case-summary.txt
writes agg_runs.csv, agg_issues.csv into outputs/analysis/2026-10-10-case-analysis/ (overwrites the retained copies;
the 2026-10-11 cleanup checked that the moved analysis files reproduce them byte for byte)"""
import csv, json, re, collections, sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
D = REPO / "docs/reports/cases/analysis"
OUT = REPO / "outputs/analysis/2026-10-10-case-analysis"
OUT.mkdir(parents=True, exist_ok=True)


def last_json(text):
    blocks = re.findall(r"```json\s*(.*?)```", text, re.S)
    for b in reversed(blocks):
        try:
            return json.loads(b)
        except Exception:
            continue
    return None


def phase_arm(run):
    ph, _, lab = run.partition("__")
    arm = "A" if lab.startswith(("A_none", "base", "fresh")) or ph in ("v5", "v6", "rBfresh") else lab[:2]
    if ph in ("v5", "v6", "rBfresh"):
        arm = "fresh"
    return ph, arm


runs, issues, tasks, bad = [], [], {}, []
for f in sorted(D.glob("*.md")):
    j = last_json(f.read_text())
    if j is None:
        bad.append(f.name)
        continue
    if f.name == "_allcorrect.md":
        recs = j if isinstance(j, list) else j.get("records") or j.get("refine") or []
        for r in recs:
            for i in r.get("issues", []) or []:
                issues.append({"task": r.get("task"), "run": f"s4__{r.get('arm')}", "set": "allcorrect",
                               "source": i.get("source"), "decision": i.get("decision"),
                               "quality": i.get("quality")})
        continue
    t = j.get("task", f.stem)
    tasks[t] = j.get("task_level", {})
    for r in j.get("runs", []):
        ph, arm = phase_arm(r.get("run", ""))
        runs.append({"task": t, "run": r.get("run"), "phase": ph, "arm": arm, "ok": r.get("ok"),
                     "answer": str(r.get("answer"))[:40], "primary": r.get("primary_cause"),
                     "causes": "+".join(r.get("causes") or []), "preventable": r.get("preventable"),
                     "confidence": r.get("confidence")})
    for r in j.get("refine", []):
        for i in r.get("issues", []) or []:
            issues.append({"task": t, "run": r.get("run"), "set": "failtask", "source": i.get("source"),
                           "decision": i.get("decision"), "quality": i.get("quality"),
                           "effect": r.get("effect_vs_A"), "foresaw": r.get("foresaw_failure")})

out = OUT
with open(out / "agg_runs.csv", "w", newline="") as fh:
    w = csv.DictWriter(fh, fieldnames=list(runs[0].keys())); w.writeheader(); w.writerows(runs)
with open(out / "agg_issues.csv", "w", newline="") as fh:
    keys = sorted({k for i in issues for k in i}); w = csv.DictWriter(fh, fieldnames=keys); w.writeheader()
    w.writerows(issues)
print("unparsed:", bad)
fail = [r for r in runs if r["ok"] is False]
print(f"runs {len(runs)}, failed {len(fail)}")
print("failed by primary cause:", collections.Counter(r["primary"] for r in fail).most_common())
print("failed by preventable:", collections.Counter(r["preventable"] for r in fail).most_common())
for ph in ("v5", "v6", "s4", "rA", "rBfresh", "rB", "rBredo"):
    sub = [r for r in fail if r["phase"] == ph]
    if sub:
        print(ph, collections.Counter((r["arm"], r["primary"]) for r in sub).most_common())
print("\ntask-level:")
for t, v in sorted(tasks.items()):
    print(f"  {t}: {v.get('preventable')} | test={v.get('test_with_counterfactual')}")
print("\nissues by source item:", collections.Counter(re.sub(r"^r\d\.?", "", str(i["source"] or "")).split(";")[0].split(",")[0].strip() for i in issues).most_common())
print("issues by quality:", collections.Counter(i["quality"] for i in issues).most_common())
