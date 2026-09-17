"""The compression diagnostics: Q1 != Q2 rate, likert SD, top-2-box, repeat agreement, cross-call coupling."""
from __future__ import annotations

import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import conftest  # noqa: E402
import spread_diagnostics  # noqa: E402


def test_diagnostics_on_the_fake_runs(tmp_path: Path) -> None:
    r1 = conftest.build_fake_run(tmp_path / "a_r1", run_id="a_r1", model="stub/a", repeat="1")
    r2 = conftest.build_fake_run(tmp_path / "a_r2", run_id="a_r2", model="stub/a", repeat="2")
    arm = spread_diagnostics.diagnose_arm("fake", [r1, r2])
    # Q1 = 3,3,1,4,5,2 vs Q2 = 2,3,1,4,3,2 -> differs on P001 and P005 = 2 of 6, in both repeats
    assert arm["q1_ne_q2_share"] == 4 / 12
    items = [q for q in spread_diagnostics.LIKERT_ITEMS if q in conftest.FAKE_ANSWERS]  # the fake run has 9 of the 25
    assert arm["n_likert_items"] == len(items) == 9 and 0.0 < arm["mean_sd"] < 2.0
    assert arm["top2_share"] == sum(1 for q in items for v in conftest.FAKE_ANSWERS[q] if int(v) >= 4) * 2 / (len(items) * 12)
    assert arm["repeat_agreement"] == 1.0  # identical repeats
    import math
    assert math.isnan(arm["q1_concept_corr"])  # the fake run has no Q9B..Q13B columns
    text = spread_diagnostics.render([arm])
    assert "fake" in text and "Q1 != Q2" in text
    out = tmp_path / "diag.csv"
    assert spread_diagnostics.main(["--arm", f"fake={r1},{r2}", "--out", str(out)]) == 0
    rows = list(csv.DictReader(open(out, newline="", encoding="utf-8-sig")))
    assert rows[0]["arm"] == "fake" and float(rows[0]["repeat_agreement"]) == 1.0


def test_income_gradient_uses_the_persona_file(tmp_path: Path) -> None:
    r1 = conftest.build_fake_run(tmp_path / "a_r1", run_id="a_r1", model="stub/a", repeat="1")
    personas = tmp_path / "personas.csv"
    incomes = {"P001": 30000, "P002": 40000, "P003": 20000, "P004": 90000, "P005": 150000, "P006": 45000}  # Q1 = 3,3,1,4,5,2
    personas.write_text("persona_id,exact_household_income\n" + "\n".join(f"{k},{v}" for k, v in incomes.items()) + "\n", encoding="utf-8")
    arm = spread_diagnostics.diagnose_arm("fake", [r1], personas_csv=personas)
    assert arm["rho_income_q1"] > 0.8
    assert spread_diagnostics.diagnose_arm("fake", [r1])["rho_income_q1"] != arm["rho_income_q1"]  # NaN without the file
    assert "rho(income, Q1)" in spread_diagnostics.render([arm])
    assert spread_diagnostics.main(["--arm", f"fake={r1}", "--personas", str(personas)]) == 0
