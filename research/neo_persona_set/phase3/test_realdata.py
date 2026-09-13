"""Two-header parsing, value normalizers, path guards, and the phase-2 isolation check."""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import realdata  # noqa: E402

PHASE2_RUNNER = Path(__file__).resolve().parents[1] / "phase2" / "run_survey.py"


def test_canonical_keys_from_real_header_shapes() -> None:
    assert realdata.split_code("Q33.A4: Which outreach methods would most likely get your attention") == ("Q33", ["A4"])
    assert realdata.split_code("Q8.OE") == ("Q8", ["OE"])
    assert realdata.split_code("Q1: Please read: (Neo Smart Living is a company)") == ("Q1", [])
    assert realdata.split_code("PQ1: Does your property have any outdoor area") == ("PQ1", [])
    assert realdata.split_code("Household Income") is None
    assert realdata.short_sub_label("The total cost (~$23,000) : Below is a list of potential concerns") == "The total cost (~$23,000)"
    assert realdata.short_sub_label('Permit-light positioning: "At 117 sq ft, the Tahoe Mini"') == "Permit-light positioning"
    assert realdata.short_sub_label("1. so cheap that you would think it couldn't be a quality product.") == "1. so cheap that you would think it couldn't be a quality product."
    assert realdata.canonical_key("Q9: Below is a list", "The total cost (~$23,000) : Below is a list") == "Q9|The total cost (~$23,000)"
    assert realdata.canonical_key("Q33.A4: Which outreach", "") == "Q33|A4"
    assert realdata.canonical_key("Q33.A11.OE", "") == "Q33|A11|OE"
    assert realdata.canonical_key("Race", "White") == "Race|White"
    keys, _ = realdata.build_columns(["Race", "", "Gender", "", ""], ["White", "Asian", "", "", ""])
    assert keys == ["Race|White", "Race|Asian", "Gender", "Gender#2", "Gender#3"]


def test_load_fake_real_survey(fake_real_csv: Path) -> None:
    real = realdata.load_real_survey(fake_real_csv)
    assert real.n == 12 and len(real.columns) == 28
    assert "Q9|The total cost (~$23,000)" in real.columns and "Q30|Installation speed" in real.columns
    assert real.col("Q33") == ["Q33|A1", "Q33|A2", "Q33|A5", "Q33|A11", "Q33|A11|OE"]
    assert realdata.multiselect_columns(real.columns, "Q33") == ["Q33|A1", "Q33|A2", "Q33|A5", "Q33|A11"]
    assert real.find("q9|the total cost (~$23,000)") == "Q9|The total cost (~$23,000)"
    assert real.values("Q6")[0] == "1 - Not interested" and real.values("Age")[-1] == "55"
    assert real.rows[10]["Q33|A11|OE"] == "carrier pigeon,\nby hand"
    assert real.base_codes()[:6] == ["Response ID", "Gender", "Age", "Household Income", "PQ1", "Q1"]
    with pytest.raises(KeyError):
        real.values("Q99")


def test_likert_labels_parse() -> None:
    assert realdata.likert_label_to_int("1 - Not interested") == 1
    assert realdata.likert_label_to_int("5 - Extremely interested") == 5
    assert realdata.likert_label_to_int("3") == 3 and realdata.likert_label_to_int(" 4 ") == 4
    assert realdata.likert_label_to_int("") is None and realdata.likert_label_to_int("N/A") is None and realdata.likert_label_to_int(None) is None


def test_multiselect_block_per_respondent(fake_real_csv: Path) -> None:
    real = realdata.load_real_survey(fake_real_csv)
    picks = realdata.multiselect_block(real.rows, "Q33")
    assert len(picks) == 12
    assert picks[0] == {"Outdoor club sponsorships / community events", "Social media ads (Facebook, Instagram)", "Google / Search ads"}
    assert picks[10] == {"Other (please specify)"}
    assert sum(1 for chosen in picks if "Outdoor club sponsorships / community events" in chosen) == 6
    assert realdata.multiselect_sub_ids(real.rows, "Q37")[0] == {"A1"} and realdata.multiselect_sub_ids(real.rows, "Q37")[5] == {"A14"}


def test_run_survey_never_imports_realdata_or_phase3() -> None:
    text = PHASE2_RUNNER.read_text(encoding="utf-8")
    assert "realdata" not in text and "phase3" not in text
    assert not re.search(r"^\s*(from|import)\s+\S*(realdata|phase3)", text, re.MULTILINE)
    own = (Path(__file__).resolve().parent / "realdata.py").read_text(encoding="utf-8")
    assert "run_survey" not in own and "requests" not in own


def test_path_guards(tmp_path: Path) -> None:
    real_path = tmp_path / "real" / "fake-raw-data.csv"
    for bad in ("raw 600-participant dataset and a sample report from aytm/out", "AYTM/out", "x/survey-760085/out"):
        with pytest.raises(SystemExit) as excinfo:
            realdata.assert_not_real_data_path(tmp_path / bad, "--out")
        assert excinfo.value.code == 3
    with pytest.raises(SystemExit):
        realdata.assert_outside_real_folder(real_path.parent / "comparison", real_path, "--out")
    with pytest.raises(SystemExit):
        realdata.assert_outside_real_folder(real_path.parent, real_path, "--out")
    assert realdata.assert_outside_real_folder(tmp_path / "out", real_path, "--out") == (tmp_path / "out").resolve()
