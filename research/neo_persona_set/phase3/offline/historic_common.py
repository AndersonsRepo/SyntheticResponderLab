"""Shared helpers for the recovered side analyses in this folder (sept17_side_tables.py, sept25_review_checks.py).

The side analyses behind some EXPERIMENT_LOG.md numbers were run inline in Claude Code sessions and
never committed; the scripts here recover them. Each check compares what it recomputes with the number
the log records. The logged numbers are read from EXPERIMENT_LOG.md at run time (never written into
code): some of them are real-survey aggregates, which must not appear in committed files, and the rest
are synthetic-run results, which the team rules say to read rather than hard-code.

Helpers: where the reorganized Assets folder lives, output-folder guards (outside the repository and
outside the real-data folder), reading a logged number out of the log, comparing at the logged
precision, and writing CSVs. Not a CLI.
"""

from __future__ import annotations

import csv
import math
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

HERE = Path(__file__).resolve().parent
PHASE3 = HERE.parent
REPO_ROOT = PHASE3.parents[2]
if str(PHASE3) not in sys.path:
    sys.path.insert(0, str(PHASE3))

import make_real_split  # noqa: E402
import realdata  # noqa: E402

# The research data folder sits next to the repository (reorganized 2026-10-03, see its FOLDER_MAP.csv).
DEFAULT_ASSETS = REPO_ROOT.parent / "SyntheticResponderLab-Assets"
LOG_REL = Path("0_logs/EXPERIMENT_LOG.md")
SEPT17_REL = Path("5_experiments/2026-09-17_S1_prompt_and_sampling_tests")
SEPT24_REL = Path("5_experiments/2026-09-24_Yaza_ablations_models_styles")
PERSONAS_600_V2_REL = Path("4_persona_sets/matched_600_v2_S1-S6_2026-09-16")
OUT_FOLDER = "reproduced_2026-10-18"
CSV_ENCODING = "utf-8-sig"
CHECK_COLUMNS = ["check", "metric", "logged", "reproduced", "match", "note"]
NAN = float("nan")

_NUMBER = re.compile(r"[-+−]?\d[\d,]*(?:\.\d+)?")


class LogText:
    """The experiment log, searched by regex; a pattern that is not found yields None (reported, never guessed)."""

    def __init__(self, text: str, path: str = "EXPERIMENT_LOG.md") -> None:
        self.text = text
        self.path = path

    @classmethod
    def read(cls, path: Path) -> "LogText":
        return cls(Path(path).read_text(encoding="utf-8"), str(path))

    def groups(self, pattern: str) -> Optional[Sequence[str]]:
        match = re.search(pattern, self.text)
        return match.groups() if match else None

    def contains(self, phrase: str) -> bool:
        return phrase in self.text


def to_number(text: str) -> float:
    """'1,234' -> 1234.0, '−0.25' (unicode minus) -> -0.25, '+0.5' -> 0.5, '12%' -> 12.0."""
    cleaned = text.strip().replace("−", "-").replace(",", "").rstrip("%")
    return float(cleaned)


def decimals_of(text: str) -> int:
    cleaned = text.strip().rstrip("%")
    return len(cleaned.split(".", 1)[1]) if "." in cleaned else 0


def matches_logged(logged: Optional[str], value: Optional[float], *, percent: bool = False) -> bool:
    """True when the logged number is a correct rounding of `value` at the logged precision.

    That is |value - logged| <= half a unit of the last logged digit (ties either way count).
    percent=True means the log shows a percentage ('21%') and `value` is a share (0.207).
    """
    if logged is None or value is None or (isinstance(value, float) and math.isnan(value)):
        return False
    shown = value * 100.0 if percent else value
    places = decimals_of(logged)
    return abs(shown - to_number(logged)) <= 0.5 * 10 ** (-places) + 1e-9


def fmt(value: Any, digits: int = 4) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float):
        return "nan" if math.isnan(value) else f"{value:.{digits}f}"
    return str(value)


def check_row(check: str, metric: str, logged: Optional[str], reproduced: Any, match: bool, note: str = "") -> Dict[str, str]:
    return {"check": check, "metric": metric, "logged": "NOT FOUND IN LOG" if logged is None else logged,
            "reproduced": reproduced if isinstance(reproduced, str) else fmt(reproduced), "match": fmt(bool(match)), "note": note}


def numeric_check(check: str, metric: str, logged: Optional[str], value: Optional[float], *, percent: bool = False,
                  digits: int = 4, note: str = "") -> Dict[str, str]:
    shown = None if value is None else (value * 100.0 if percent else value)
    text = fmt(shown, digits) + ("%" if percent and shown is not None else "")
    return check_row(check, metric, logged, text, matches_logged(logged, value, percent=percent), note)


def resolve_out(out: Optional[Path], default: Path, real_path: Optional[Path] = None) -> Path:
    """The output folder: never inside the repository, never inside (or named after) the real-data folder."""
    target = Path(out) if out is not None else default
    if real_path is not None:
        target = realdata.assert_outside_real_folder(target, real_path, "--out")
    else:
        target = realdata.assert_not_real_data_path(target, "--out")
    target = make_real_split.assert_outside_repo(target, "--out")
    target.mkdir(parents=True, exist_ok=True)
    return target


def real_file(path: Optional[Path]) -> Path:
    if path is None:
        raise SystemExit("--real is required for this check (the AYTM raw-data CSV; there is no default path)")
    resolved = Path(path).expanduser().resolve()
    if not resolved.is_file():
        raise SystemExit(f"--real {resolved} is not a file")
    return resolved


def write_csv(path: Path, rows: List[Dict[str, Any]], header: Optional[List[str]] = None) -> Path:
    header = header or (list(rows[0]) if rows else [])
    with open(path, "w", newline="", encoding=CSV_ENCODING) as handle:
        writer = csv.DictWriter(handle, fieldnames=header)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: (row.get(key) if isinstance(row.get(key), str) else fmt(row.get(key))) for key in header})
    return path


def read_csv(path: Path) -> List[Dict[str, str]]:
    with open(path, newline="", encoding=CSV_ENCODING) as handle:
        return list(csv.DictReader(handle))


def print_checks(rows: List[Dict[str, str]]) -> None:
    width = max([len(r["metric"]) for r in rows] + [6])
    for row in rows:
        flag = "MATCH" if row["match"] == "true" else "DIFF "
        print(f"  {flag} {row['metric']:{width}s} logged {row['logged']:>14s}  reproduced {row['reproduced']:>14s}  {row['note']}")
