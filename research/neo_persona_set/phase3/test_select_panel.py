from __future__ import annotations

import csv
import json
import random
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import select_panel  # noqa: E402


def _personas(tmp_path: Path, n: int = 600) -> Path:
    rng = random.Random(1)
    path = tmp_path / "personas.csv"
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["persona_id", "sex", "age_bucket", "income_bucket", "exact_age"])
        for i in range(1, n + 1):
            writer.writerow([f"P{i:03d}", rng.choice(["Female", "Male"]), rng.choice(["25-29", "35-44", "55-64", "65+"]), rng.choice(["<$25k", "$50k-$75k", "$100k-$150k"]), 40])
    return path


def test_panel_is_exact_size_deterministic_and_proportional(tmp_path: Path) -> None:
    path = _personas(tmp_path)
    rows = select_panel.read_rows(path)
    ids = select_panel.select_panel(rows, size=150, seed=20260912, strata=["sex", "age_bucket", "income_bucket"])
    assert len(ids) == 150 and len(set(ids)) == 150
    assert ids == select_panel.select_panel(rows, size=150, seed=20260912, strata=["sex", "age_bucket", "income_bucket"])
    assert ids != select_panel.select_panel(rows, size=150, seed=1, strata=["sex", "age_bucket", "income_bucket"])
    order = {row["persona_id"]: i for i, row in enumerate(rows)}
    assert ids == sorted(ids, key=order.__getitem__)
    by_id = {row["persona_id"]: row for row in rows}
    cells_all = Counter((r["sex"], r["age_bucket"], r["income_bucket"]) for r in rows)
    cells_panel = Counter((by_id[i]["sex"], by_id[i]["age_bucket"], by_id[i]["income_bucket"]) for i in ids)
    for cell, count in cells_all.items():
        assert abs(cells_panel.get(cell, 0) - count * 150 / 600) <= 1.0, cell


def test_cli_writes_ids_and_summary(tmp_path: Path) -> None:
    path = _personas(tmp_path, 60)
    out = tmp_path / "panel.txt"
    assert select_panel.main(["--personas", str(path), "--size", "20", "--seed", "3", "--out", str(out), "--strata", "sex"]) == 0
    ids = [line for line in out.read_text(encoding="utf-8").splitlines() if line and not line.startswith("#")]
    assert len(ids) == 20
    summary = json.loads((tmp_path / "panel.txt.summary.json").read_text())
    assert summary["size"] == 20 and summary["seed"] == 3 and summary["strata"] == ["sex"] and sum(summary["cells"][k]["selected"] for k in summary["cells"]) == 20
