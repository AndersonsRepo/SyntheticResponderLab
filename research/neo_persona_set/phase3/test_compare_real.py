"""End-to-end run of compare_real.main on the fake real CSV and fake run folders. No network."""
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import compare_real  # noqa: E402


def _read(path: Path):
    with open(path, newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def _row(rows, **match):
    return next(r for r in rows if all(r[k] == v for k, v in match.items()))


def _run(tmp_path: Path, fake_real_csv: Path, run_dirs, *extra: str) -> Path:
    out = tmp_path / "comparison"
    assert compare_real.main(["--real", str(fake_real_csv), "--runs", *map(str, run_dirs), "--out", str(out), *extra]) == 0
    return out


def test_end_to_end_outputs_and_offset(tmp_path: Path, fake_real_csv: Path, fake_run_dir: Path, second_fake_run_dir: Path) -> None:
    out = _run(tmp_path, fake_real_csv, [fake_run_dir, second_fake_run_dir])
    names = {p.name for p in out.iterdir()}
    assert names == {"comparison_long.csv", "comparison_options.csv", "comparison_summary.csv", "comparison_by_question.md", "unmapped.md", "crosswalk.csv", "manifest.json"}
    long_rows = _read(out / "comparison_long.csv")
    assert list(long_rows[0].keys()) == compare_real.LONG_COLUMNS and len(long_rows) == 39 * 2

    q1 = _row(long_rows, run_id="fake_run_r1", our_id="Q1")
    assert q1["real_key"] == "Q6" and q1["status"] == "ok" and q1["n_real"] == "12" and q1["n_synth"] == "4"
    assert q1["real_shares"] == "0.1667|0.1667|0.3333|0.1667|0.1667" and q1["mean_real"] == "3.0000" and q1["mean_synth"] == "3.7500" and q1["mean_diff"] == "0.7500"
    assert q1["top_real"] == "3" and q1["chi2_df"] == "4" and q1["close"] == "false"

    assert _row(long_rows, run_id="fake_run_r1", our_id="Q7")["status"] == "unmapped"
    assert _row(long_rows, run_id="fake_run_r1", our_id="Q2")["status"] == "real_column_missing"
    assert _row(long_rows, run_id="fake_run_r1", our_id="Q0B")["status"] == "our_question_missing"
    assert _row(long_rows, run_id="fake_run_r1", our_id="Q30")["scored"] == "false"

    q18 = _row(long_rows, run_id="fake_run_r1", our_id="Q18")
    assert q18["real_off_list_share"] == "0.1667" and q18["n_real"] == "10" and q18["real_shares"] == "0.2000|0.3000|0.5000"
    q22 = _row(long_rows, run_id="fake_run_r1", our_id="Q22")
    assert q22["synth_off_list_share"] == "0.2500" and q22["categories"].split("|")[0] == "Under $50,000"
    q14 = _row(long_rows, run_id="fake_run_r1", our_id="Q14")
    assert q14["status"] == "ok" and q14["real_shares"] == "0.4167|0.2500|0.3333" and q14["top_match"] == "true"
    q26 = _row(long_rows, run_id="fake_run_r1", our_id="Q26")
    assert q26["real_shares"] == "0.3333|0.6667" and q26["n_real"] == "12"
    q21 = _row(long_rows, run_id="fake_run_r1", our_id="Q21")
    assert q21["n_real"] == "12" and q21["categories"].startswith("18–24|25–34")
    s3 = _row(long_rows, run_id="fake_run_r1", our_id="S3")
    assert s3["n_synth"] == "4" and s3["categories"] == "Yes|I'm not sure, but possibly.|No"

    options = _read(out / "comparison_options.csv")
    assert list(options[0].keys()) == compare_real.OPTIONS_COLUMNS
    a1 = _row(options, run_id="fake_run_r1", our_id="Q20", category="Outdoor club sponsorships / community events")
    assert a1["real_share"] == "0.5000" and a1["real_n"] == "12" and a1["synth_share"] == "0.5000" and a1["synth_n"] == "4"
    assert _row(options, run_id="fake_run_r1", our_id="Q20", category="Social media ads (Facebook, Instagram)")["real_share"] == "0.2500"
    q20 = _row(long_rows, run_id="fake_run_r1", our_id="Q20")
    assert q20["n_real_off_list"] == "2" and q20["real_off_list_share"] == "0.0952"

    summary = _read(out / "comparison_summary.csv")
    assert list(summary[0].keys()) == compare_real.SUMMARY_COLUMNS and [r["run_id"] for r in summary] == ["fake_run_r1", "fake_run_r2"]
    assert summary[0]["n_synth_after_filter"] == "4" and summary[0]["n_dropped_outdoor"] == "2"
    assert int(summary[0]["questions_compared"]) == sum(1 for r in long_rows if r["run_id"] == "fake_run_r1" and r["status"] == "ok" and r["scored"] == "true")

    manifest = json.loads((out / "manifest.json").read_text())
    assert manifest["filters"]["require_outdoor_space"] is True and manifest["thresholds"]["close_tv"] == 0.1
    assert [r["n_after_outdoor_filter"] for r in manifest["runs"]] == [4, 4] and manifest["real"]["n_rows"] == 12
    assert set(manifest["outputs"]) == names - {"manifest.json"} and len(manifest["real"]["sha256"]) == 64

    by_question = (out / "comparison_by_question.md").read_text(encoding="utf-8")
    assert "## Q1 vs real Q6 (likert)" in by_question and "model-a r1 (n=4)" in by_question and "| mean (scale) | 3.00 | 3.75 | " in by_question
    unmapped = (out / "unmapped.md").read_text(encoding="utf-8")
    assert "| Q7 |" in unmapped and "| Q34 |" in unmapped and "| Q23 |" in unmapped and "Gender" in unmapped and "| Q6 |" not in unmapped
    crosswalk_rows = _read(out / "crosswalk.csv")
    assert _row(crosswalk_rows, our_id="Q18")["real_options"] == "Build quality and details|Installation speed|Permit-light positioning|Smart Technology"


def test_keep_all_and_exclude_fallback(tmp_path: Path, fake_real_csv: Path, fake_run_dir: Path) -> None:
    out = _run(tmp_path, fake_real_csv, [fake_run_dir], "--keep-all", "--exclude-fallback", "--close-tv", "0.5")
    long_rows = _read(out / "comparison_long.csv")
    assert _row(long_rows, our_id="Q1")["n_synth"] == "6"
    assert _row(long_rows, our_id="Q19")["n_synth"] == "5"
    assert _row(long_rows, our_id="S3")["real_shares"] == "0.8333|0.1667|0.0000"
    manifest = json.loads((out / "manifest.json").read_text())
    assert manifest["filters"] == {"require_outdoor_space": False, "screener_id": "S3", "exclude_fallback": True}
    assert manifest["runs"][0]["n_fallback_blanked"] == 1 and manifest["thresholds"]["close_tv"] == 0.5


def test_output_guard_refuses_real_folder(tmp_path: Path, fake_real_csv: Path, fake_run_dir: Path) -> None:
    for bad in (fake_real_csv.parent / "comparison", tmp_path / "aytm" / "out"):
        with pytest.raises(SystemExit) as excinfo:
            compare_real.main(["--real", str(fake_real_csv), "--runs", str(fake_run_dir), "--out", str(bad)])
        assert excinfo.value.code == 3
        assert not bad.exists()
    assert compare_real.main(["--real", str(tmp_path / "missing.csv"), "--runs", str(fake_run_dir), "--out", str(tmp_path / "o")]) == 2
