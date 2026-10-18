"""jev_pilot's references: the real side from a comparison folder or an argument, the chat-model
baselines from their run folders; none of them a literal. Tiny fake inputs, no real data, no network."""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import jev_pilot  # noqa: E402

SUMMARY = {"rho_income_q1": 0.5, "rho_income_q2": 0.4, "q1_top2_share": 0.2, "q1_mean_confidence": 0.6,
           "q6_cost_top_share": 0.9, "approx_usd": 0.001, "elapsed_seconds": 1.0}


def _options(folder: Path, rows: str) -> Path:
    folder.mkdir(parents=True)
    (folder / "comparison_options.csv").write_text("run_id,our_id,category,real_share\n" + rows, encoding="utf-8")
    return folder


def test_real_q1_shares_come_from_the_comparison_folder(tmp_path: Path) -> None:
    folder = _options(tmp_path / "cmp", "r1,Q1,1,0.05\nr1,Q1,2,0.15\nr1,Q1,3,0.3\nr1,Q1,4,0.35\nr1,Q1,5,0.15\nr1,Q2,1,1.0\n")
    assert jev_pilot.real_q1_shares(folder) == [0.05, 0.15, 0.3, 0.35, 0.15]
    with pytest.raises(SystemExit):
        jev_pilot.real_q1_shares(_options(tmp_path / "no_q1", "r1,Q2,1,1.0\n"))


def _run(folder: Path, rows: list) -> Path:
    """A fake run folder: answers_wide.csv with persona_id, Q1 and Q6 only."""
    folder.mkdir(parents=True)
    lines = ["persona_id,Q1,Q6"] + [f'{pid},{q1},"{q6}"' for pid, q1, q6 in rows]
    (folder / "answers_wide.csv").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return folder


def test_baseline_reference_is_computed_from_the_run_folders(tmp_path: Path) -> None:
    personas = tmp_path / "personas.csv"
    personas.write_text("persona_id,exact_household_income\nA,10000\nB,20000\nC,30000\nD,40000\n", encoding="utf-8")
    cost, other = "The total cost (~$X)", "Something else"
    r1 = _run(tmp_path / "r1", [("A", 1, cost), ("B", 2, cost), ("C", 3, other), ("D", 4, cost)])
    r2 = _run(tmp_path / "r2", [("A", 1, cost), ("B", 2, other), ("C", 3, cost), ("D", 4, cost)])
    ref = jev_pilot.baseline_reference(f"ArmA={r1},{r2}", personas)
    assert ref == {"name": "ArmA", "runs": ["r1", "r2"], "rho_income_q1": 1.0, "q6_cost_top_share": 0.75}
    no_income = jev_pilot.baseline_reference(f"ArmB={r1}", None)
    assert no_income["rho_income_q1"] is None and no_income["q6_cost_top_share"] == 0.75
    with pytest.raises(SystemExit):
        jev_pilot.baseline_reference(f"ArmC={tmp_path / 'missing'}", personas)
    with pytest.raises(SystemExit):
        jev_pilot.baseline_reference(str(r1), personas)  # no NAME=
    with pytest.raises(SystemExit, match="not found"):
        jev_pilot.baseline_reference(f"ArmD={r1}", tmp_path / "no_personas.csv")


def test_baseline_refuses_a_persona_file_other_than_the_runs_one(tmp_path: Path) -> None:
    used = tmp_path / "used.csv"
    used.write_text("persona_id,exact_household_income\nA,10000\nB,20000\nC,30000\n", encoding="utf-8")
    renumbered = tmp_path / "renumbered.csv"  # same ids, other people: would join silently
    renumbered.write_text("persona_id,exact_household_income\nA,30000\nB,20000\nC,10000\n", encoding="utf-8")
    run = _run(tmp_path / "r1", [("A", 1, "x"), ("B", 2, "x"), ("C", 3, "x")])
    digest = hashlib.sha256(used.read_bytes()).hexdigest()
    (run / "manifest.json").write_text(json.dumps({"personas": {"path": "elsewhere/used.csv", "sha256": digest}}), encoding="utf-8")
    assert jev_pilot.baseline_reference(f"Arm={run}", used)["rho_income_q1"] == 1.0
    with pytest.raises(SystemExit, match="different persona file"):
        jev_pilot.baseline_reference(f"Arm={run}", renumbered)


def test_report_prints_real_values_and_baselines_only_when_passed_in() -> None:
    shares = [0.5, 0.2, 0.1, 0.1, 0.1]
    bare = "\n".join(jev_pilot.report_lines(SUMMARY, shares))
    assert jev_pilot.REAL_POINTER in bare and "pass --real-rho-income-q1" in bare and "pass --real-from" in bare
    assert bare.count(jev_pilot.BASELINE_POINTER) == 2  # the rho line and the Q6 line
    baselines = [{"name": "ArmA", "rho_income_q1": 0.25, "q6_cost_top_share": 0.4},
                 {"name": "ArmB", "rho_income_q1": None, "q6_cost_top_share": 0.6}]
    given = "\n".join(jev_pilot.report_lines(SUMMARY, shares, [0.05, 0.15, 0.3, 0.35, 0.15], 0.33, baselines))
    assert "(real 0.33 | ArmA 0.250 | ArmB n/a)" in given and "(ArmA 0.400 | ArmB 0.600)" in given and "(real 0.50)" in given
    assert "  real 600               0.05   0.15   0.30   0.35   0.15" in given and jev_pilot.REAL_POINTER not in given
    assert jev_pilot.BASELINE_POINTER not in given
