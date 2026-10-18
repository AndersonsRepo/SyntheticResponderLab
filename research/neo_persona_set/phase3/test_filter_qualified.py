from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import filter_qualified  # noqa: E402


def test_is_qualified_rule() -> None:
    assert not filter_qualified.is_qualified("No") and not filter_qualified.is_qualified("no.") and not filter_qualified.is_qualified("  No, none")
    assert filter_qualified.is_qualified("Yes") and filter_qualified.is_qualified("I'm not sure, but possibly")
    assert filter_qualified.is_qualified("Not sure") and filter_qualified.is_qualified("None of the above") and filter_qualified.is_qualified("")


def test_filter_run_writes_qualified_copy(fake_run_dir: Path) -> None:
    summary = filter_qualified.filter_run(fake_run_dir)
    assert (summary["n_before"], summary["n_after"], summary["n_dropped"]) == (6, 4, 2)
    assert summary["dropped_persona_ids"] == ["P003", "P006"]
    out = fake_run_dir / "qualified"
    assert {p.name for p in out.iterdir()} == {"answers_wide.csv", "answers_long.csv", "questions.csv", "summary.json"}
    wide = list(csv.DictReader(open(out / "answers_wide.csv", newline="", encoding="utf-8-sig")))
    assert [r["persona_id"] for r in wide] == ["P001", "P002", "P004", "P005"] and all(not r["S3"].startswith("No") for r in wide)
    long_rows = list(csv.DictReader(open(out / "answers_long.csv", newline="", encoding="utf-8-sig")))
    assert {r["persona_id"] for r in long_rows} == {"P001", "P002", "P004", "P005"} and len(long_rows) == 4 * 21
    assert json.loads((out / "summary.json").read_text())["n_after"] == 4


def test_cli_and_guard(fake_run_dir: Path, tmp_path: Path) -> None:
    assert filter_qualified.main(["--runs", str(fake_run_dir)]) == 0
    with pytest.raises(SystemExit) as excinfo:
        filter_qualified.filter_run(tmp_path / "aytm" / "run")
    assert excinfo.value.code == 3
