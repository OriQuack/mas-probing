"""Draw the baseline task set (50 tasks) from the EXPLORATION split, stratified, seeded, nested on the dev set.

Pre-registered on 2026-10-09, before any run on the added tasks (decision E6). Same method as the old pilot's
make_eval_split.py / make_executor_selection_split.py, with two changes:
1. Level quotas L1:L2:L3 = 1:3:2 (harder than the eval set's mix): L1 8, L2 25, L3 17 (largest remainder).
2. Nested: the 12 dev tasks (`executor_selection_v1`) are kept, so their runs stay comparable.
Within a level, the target is the quota split across attachment modalities proportionally (largest remainder)
over the whole exploration pool; the dev tasks fill their cells first and the rest is drawn uniformly within each
cell with a fixed seed. Every modality present in the pool gets >= 1 task (taken from the largest `none` cell of
the level where the modality is most common). Never redraw; a change gets _v2.
"""

from pathlib import Path

import numpy as np
import pandas as pd

SPLITS = Path(__file__).resolve().parents[1] / "data/splits"
SEED = 20261009
TOTAL = 50
RATIO = {1: 1, 2: 3, 3: 2}


def largest_remainder(counts: pd.Series, total: int) -> pd.Series:
    exact = counts / counts.sum() * total
    alloc = np.floor(exact).astype(int)
    # Ties broken by larger stratum, then name, for determinism (as in the old pilot).
    order = sorted(counts.index, key=lambda k: (-(exact[k] - alloc[k]), -counts[k], k))
    for k in order[: total - alloc.sum()]:
        alloc[k] += 1
    return alloc


def main() -> None:
    pool = pd.read_csv(SPLITS / "exploration_v1.csv", keep_default_na=False)
    dev = pd.read_csv(SPLITS / "executor_selection_v1.csv", keep_default_na=False)
    assert dev.task_id.isin(pool.task_id).all()

    level_quota = largest_remainder(pd.Series(RATIO), TOTAL)
    cells = pool.groupby(["level", "modality"]).size()
    target = pd.concat({lvl: largest_remainder(cells.loc[lvl], int(q)) for lvl, q in level_quota.items()},
                       names=["level", "modality"])
    for mod in sorted(pool.modality.unique()):
        if target.xs(mod, level="modality").sum() == 0:
            lvl = cells.xs(mod, level="modality").idxmax()
            target[(lvl, "none")] -= 1
            target[(lvl, mod)] = target.get((lvl, mod), 0) + 1

    held = dev.groupby(["level", "modality"]).size().reindex(target.index, fill_value=0)
    need = target - held
    if (need < 0).any():
        raise SystemExit(f"dev set exceeds the target in cells:\n{need[need < 0]}")

    rest = pool[~pool.task_id.isin(dev.task_id)]
    rng = np.random.default_rng(SEED)
    picked = [dev]
    for (lvl, mod), n in sorted(need.items()):
        if n:
            cell = rest[(rest.level == lvl) & (rest.modality == mod)].sort_values("task_id")
            picked.append(cell.iloc[rng.choice(len(cell), size=n, replace=False)])
    cols = ["task_id", "level", "modality", "file_ext"]
    out = pd.concat(picked)[cols].sort_values(["level", "modality", "task_id"]).reset_index(drop=True)
    assert len(out) == TOTAL and out.task_id.is_unique
    out.to_csv(SPLITS / "baseline_v1.csv", index=False)
    print(f"seed={SEED}  n={len(out)}  (dev {len(dev)} + new {len(out) - len(dev)})")
    print(pd.crosstab(out.modality, out.level, margins=True))


if __name__ == "__main__":
    main()
