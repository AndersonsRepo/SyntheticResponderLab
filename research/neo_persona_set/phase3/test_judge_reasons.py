from __future__ import annotations

import csv
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import conftest  # noqa: E402  (build_fake_run)
import judge_reasons  # noqa: E402


def _with_reasons(run_dir: Path, tag: str) -> Path:
    path = run_dir / "answers_long.csv"
    rows = list(csv.DictReader(open(path, newline="", encoding="utf-8")))
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()) + ["reason"])
        writer.writeheader()
        for row in rows:
            writer.writerow({**row, "reason": f"{tag} says so"})
    return run_dir


class StubJudge:
    def __init__(self) -> None:
        self.calls = 0
        self.captures = {}
        self.stats = Counter()
        self.current_round = 0
        self.current_chunk = None
        self.usd_reported = 0.0

    def generate_survey_response_with_openrouter(self, *, model_name, prompt_payload, timeout=0):
        self.calls += 1
        pick = "B" if self.calls % 2 else "A"
        return {"ok": True, "parsed_json": {"pick": pick, "why": f"{pick} is concrete"}, "raw_text": "{}", "error": None, "status_code": 200}


def test_judge_writes_a_run_shaped_folder(tmp_path: Path) -> None:
    a = _with_reasons(conftest.build_fake_run(tmp_path / "a", run_id="a_r1", model="stub/a"), "A")
    b = _with_reasons(conftest.build_fake_run(tmp_path / "b", run_id="b_r1", model="stub/b"), "B")
    out = tmp_path / "judged"
    judge = StubJudge()
    manifest = judge_reasons.judge_runs(a, b, out, judge_model="stub/judge", client=judge, concurrency=2, limit=None)
    assert judge.calls == 6 * 21 and manifest["picks"] == {"A": 63, "B": 63} and manifest["models"]["judge"] == "stub/judge"
    wide = list(csv.DictReader(open(out / "answers_wide.csv", newline="", encoding="utf-8-sig")))
    assert len(wide) == 6 and set(wide[0]) >= {"persona_id", "S3", "Q30"}
    long_rows = list(csv.DictReader(open(out / "answers_long.csv", newline="", encoding="utf-8-sig")))
    assert len(long_rows) == 126 and {r["picked"] for r in long_rows} == {"A", "B"} and long_rows[0]["why"]
    assert (out / "questions.csv").exists() and json.loads((out / "manifest.json").read_text())["source_runs"]["a"].endswith("a")
    messages = judge_reasons.build_judge_prompt("Purchase interest at $23,000", "1..5", {"answer": "2", "reason": "pricey"}, {"answer": "4", "reason": "worth it"})
    assert messages[0]["role"] == "system" and '"pick"' in messages[1]["content"] and "pricey" in messages[1]["content"]
