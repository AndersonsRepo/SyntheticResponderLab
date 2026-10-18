"""The crosswalk table: coverage, numbering offset, normalizers, banding, and the CSV deliverable."""
from __future__ import annotations

import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import crosswalk  # noqa: E402

OUR_IDS = ["S3", "Q0A", "Q0B", "Q1", "Q2", "Q3", "Q5_1", "Q5_2", "Q5_3", "Q5_4", "Q5_5", "Q5_6", "Q5_7", "Q6", "Q7", "Q9A", "Q9B", "Q10A", "Q10B",
           "Q11A", "Q11B", "Q12A", "Q12B", "Q13A", "Q13B", "Q14", "Q15", "Q16", "Q17", "Q18", "Q19", "Q20", "Q21", "Q22", "Q23", "Q24", "Q25", "Q26", "Q30"]


def test_table_covers_all_39_items_once() -> None:
    assert [m.our_id for m in crosswalk.CROSSWALK] == OUR_IDS
    assert all(m.kind in crosswalk.KINDS for m in crosswalk.CROSSWALK)
    assert [m.our_id for m in crosswalk.CROSSWALK if m.kind == "none"] == ["Q7", "Q23"]
    assert [m.our_id for m in crosswalk.CROSSWALK if not m.scored] == ["Q30"]


def test_numbering_offset_is_recorded() -> None:
    by = crosswalk.BY_OUR_ID
    assert by["Q1"].real_key == "Q6" and by["Q0A"].real_key == "Q2" and by["S3"].real_key == "PQ1"
    assert by["Q5_1"].real_key == "Q9|The total cost (~$23,000)" and by["Q5_7"].real_key == "Q9|Uncertainty about resale value"
    assert by["Q9A"].real_key == "Q15" and by["Q13B"].real_key == "Q28" and by["Q14"].real_key == "Q29"
    assert by["Q15"].real_key == "Q30|Permit-light positioning" and by["Q17"].real_key == "Q30|Build quality and details"
    assert by["Q20"].kind == "multi" and by["Q20"].real_key == "Q33"
    assert by["Q26"].kind == "derived_binary" and by["Q26"].real_map == {"A14": "No"}
    assert by["Q21"].kind == "age_bin" and by["Q22"].kind == "income_band"


def test_normalizers() -> None:
    assert crosswalk.normalize_label("I'm not sure, but possibly.") == crosswalk.normalize_label("I'm not sure, but possibly")
    assert crosswalk.normalize_label("55-64") == crosswalk.normalize_label("55–64")
    assert crosswalk.strip_tagline('Concept 1: Backyard Home Office ("Work smarter — right in your backyard")') == "Concept 1: Backyard Home Office"
    assert crosswalk.normalize_concept("Concept 5: Simplicity (Transparency + Speed + Less Headache)") == "concept 5"
    assert crosswalk.normalize_concept(crosswalk.CONCEPT_LABELS[4]) == "concept 5"
    assert crosswalk.normalize_concept("None of the above — I would not be motivated by any of these") == "none of the above"
    assert crosswalk.normalize_other("Other: ___________") == crosswalk.normalize_other("Other (please specify)") == "other"
    assert crosswalk.BY_OUR_ID["Q14"].map_our_label(crosswalk.CONCEPT_LABELS[0]) == "Concept 1: Backyard Home Office"
    assert crosswalk.BY_OUR_ID["S3"].map_our_label("I'm not sure, but possibly") == "I'm not sure, but possibly."
    assert crosswalk.BY_OUR_ID["Q22"].map_our_label("Prefer not to say") is None
    assert crosswalk.BY_OUR_ID["Q22"].map_our_label("$150,000-$199,999") == "$100,000-$199,999"


def test_age_and_income_banding() -> None:
    assert crosswalk.age_bucket_for(24) == "18–24" and crosswalk.age_bucket_for(34) == "25–34"
    assert crosswalk.age_bucket_for(65) == "65 or older" and crosswalk.age_bucket_for(86) == "65 or older"
    assert crosswalk.age_bucket_for(17) is None and crosswalk.age_bucket_for(None) is None
    assert crosswalk.BY_OUR_ID["Q22"].map_real_label("$25,000 - $49,999") == "Under $50,000"
    assert crosswalk.BY_OUR_ID["Q22"].map_real_label("$100,000 - $199,999") == "$100,000-$199,999"
    assert set(crosswalk.REAL_INCOME_TO_BAND.values()) == set(crosswalk.INCOME_BANDS)


def test_write_crosswalk_csv(tmp_path: Path, fake_run_dir: Path) -> None:
    questions = crosswalk.load_questions(fake_run_dir / "questions.csv")
    out = crosswalk.write_crosswalk_csv(tmp_path / "crosswalk.csv", our_options=crosswalk.our_options_from_questions(questions), real_options={"Q1": ["1 - Not interested", "2"]})
    rows = list(csv.DictReader(open(out, newline="", encoding="utf-8-sig")))
    assert list(rows[0].keys()) == crosswalk.CROSSWALK_COLUMNS and len(rows) == 39
    q1 = next(r for r in rows if r["our_id"] == "Q1")
    assert q1["real_column"] == "Q6" and q1["match_type"] == "likert" and q1["our_options"] == "1|2|3|4|5" and q1["real_options"] == "1 - Not interested|2"
    assert next(r for r in rows if r["our_id"] == "Q7")["real_column"] == "" and next(r for r in rows if r["our_id"] == "Q30")["match_type"] == "single (report only)"
    assert crosswalk.main(["--questions", str(fake_run_dir / "questions.csv"), "--out", str(tmp_path / "cw2.csv")]) == 0
