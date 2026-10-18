"""Rewrite a run's CSVs with a UTF-8 BOM so Excel opens them correctly; keep the manifest hashes true.

    apps/api/.venv/bin/python research/neo_persona_set/phase3/add_bom.py <run_dir> ... [--index <survey_runs>/index.csv]
"""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

BOM = b"\xef\xbb\xbf"
CSV_NAMES = ["answers_long.csv", "answers_wide.csv", "questions.csv"]


def add_bom_to_file(path: Path) -> bool:
    data = path.read_bytes()
    if data.startswith(BOM):
        return False
    path.write_bytes(BOM + data)
    return True


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def add_bom_to_run(run_dir: Path) -> Dict[str, Any]:
    run_dir = Path(run_dir)
    rewritten: List[str] = []
    for name in CSV_NAMES + [f"qualified/{n}" for n in CSV_NAMES]:
        path = run_dir / name
        if path.is_file() and add_bom_to_file(path):
            rewritten.append(name)
    manifest_path = run_dir / "manifest.json"
    if rewritten and manifest_path.is_file():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        outputs = manifest.get("outputs") or {}
        for name in rewritten:
            if name in outputs:
                outputs[name] = sha256(run_dir / name)
        manifest["outputs"] = outputs
        manifest["bom_added_at"] = datetime.now(timezone.utc).isoformat()
        manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8")
    return {"run_dir": str(run_dir), "rewritten": rewritten}


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("runs", type=Path, nargs="+", metavar="RUN_DIR")
    parser.add_argument("--index", type=Path, default=None, help="also add a BOM to this index.csv")
    args = parser.parse_args(argv)
    for run_dir in args.runs:
        result = add_bom_to_run(run_dir)
        print(f"{run_dir.name}: rewrote {len(result['rewritten'])} file(s)")
    if args.index and args.index.is_file():
        print(f"{args.index}: {'rewritten' if add_bom_to_file(args.index) else 'already had a BOM'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
