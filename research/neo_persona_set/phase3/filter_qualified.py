"""Write a filtered copy of a run that keeps only personas passing the outdoor-space screener.

The real survey terminated respondents who answered PQ1 with "No", so the real file holds none of
them. Our runs answered S3 for everyone (about a third of the matched personas said "No"). This
writes <run_dir>/qualified/{answers_wide.csv, answers_long.csv, questions.csv, summary.json}.

    apps/api/.venv/bin/python research/neo_persona_set/phase3/filter_qualified.py --runs <run_dir> ...
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import realdata  # noqa: E402

SCREENER_ID = "S3"
QUALIFIED_DIR = "qualified"
CSV_ENCODING = "utf-8-sig"
_NO = re.compile(r"^\s*no\b", re.IGNORECASE)


def is_qualified(answer: Optional[str]) -> bool:
    """False when the screener answer starts with the word "No"; "Not sure" and blanks pass."""
    return not _NO.match(answer or "")


def read_csv_rows(path: Path) -> Tuple[List[str], List[Dict[str, str]]]:
    with open(path, newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        return list(reader.fieldnames or []), list(reader)


def write_csv_rows(path: Path, header: List[str], rows: List[Dict[str, str]]) -> None:
    with open(path, "w", newline="", encoding=CSV_ENCODING) as handle:
        writer = csv.DictWriter(handle, fieldnames=header)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in header})


def sha256_of_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def filter_run(run_dir: Path, *, question_id: str = SCREENER_ID) -> Dict[str, Any]:
    run_dir = realdata.assert_not_real_data_path(run_dir, "--runs")
    header, wide_rows = read_csv_rows(run_dir / "answers_wide.csv")
    if question_id not in header:
        raise ValueError(f"{run_dir}: answers_wide.csv has no {question_id} column")
    kept = [row for row in wide_rows if is_qualified(row.get(question_id))]
    kept_ids = {row["persona_id"] for row in kept}
    dropped_ids = [row["persona_id"] for row in wide_rows if row["persona_id"] not in kept_ids]

    out_dir = run_dir / QUALIFIED_DIR
    out_dir.mkdir(exist_ok=True)
    write_csv_rows(out_dir / "answers_wide.csv", header, kept)
    long_header, long_rows = read_csv_rows(run_dir / "answers_long.csv")
    write_csv_rows(out_dir / "answers_long.csv", long_header, [row for row in long_rows if row["persona_id"] in kept_ids])
    if (run_dir / "questions.csv").exists():
        shutil.copyfile(run_dir / "questions.csv", out_dir / "questions.csv")

    summary = {
        "run_id": kept[0]["run_id"] if kept else run_dir.name,
        "run_dir": str(run_dir),
        "question_id": question_id,
        "rule": f"keep personas whose {question_id} answer does not start with the word 'No'",
        "n_before": len(wide_rows),
        "n_after": len(kept),
        "n_dropped": len(dropped_ids),
        "dropped_persona_ids": dropped_ids,
        "source_sha256": {"answers_wide.csv": sha256_of_file(run_dir / "answers_wide.csv"), "answers_long.csv": sha256_of_file(run_dir / "answers_long.csv")},
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return summary


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--runs", type=Path, nargs="+", required=True, metavar="RUN_DIR")
    parser.add_argument("--question", default=SCREENER_ID, help="screener question id (default S3)")
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    for run_dir in args.runs:
        summary = filter_run(run_dir, question_id=args.question)
        print(f"{summary['run_id']}: kept {summary['n_after']} of {summary['n_before']} personas -> {Path(summary['run_dir']) / QUALIFIED_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
