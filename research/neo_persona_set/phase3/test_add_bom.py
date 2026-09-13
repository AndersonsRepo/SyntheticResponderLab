from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import add_bom  # noqa: E402


def test_adds_bom_once_and_updates_manifest_hashes(fake_run_dir: Path, tmp_path: Path) -> None:
    manifest = json.loads((fake_run_dir / "manifest.json").read_text())
    manifest["outputs"] = {"answers_wide.csv": "0" * 64}
    (fake_run_dir / "manifest.json").write_text(json.dumps(manifest))
    index = tmp_path / "index.csv"
    index.write_text("run_id,status\nfake_run_r1,completed\n", encoding="utf-8")
    result = add_bom.add_bom_to_run(fake_run_dir)
    assert set(result["rewritten"]) == {"answers_long.csv", "answers_wide.csv", "questions.csv"}
    for name in result["rewritten"]:
        assert (fake_run_dir / name).read_bytes()[:3] == b"\xef\xbb\xbf"
    again = add_bom.add_bom_to_run(fake_run_dir)
    assert again["rewritten"] == [] and (fake_run_dir / "answers_wide.csv").read_bytes().count(b"\xef\xbb\xbf") == 1
    updated = json.loads((fake_run_dir / "manifest.json").read_text())
    assert updated["outputs"]["answers_wide.csv"] == hashlib.sha256((fake_run_dir / "answers_wide.csv").read_bytes()).hexdigest()
    assert updated["bom_added_at"]
    assert add_bom.main([str(fake_run_dir), "--index", str(index)]) == 0
    assert index.read_bytes()[:3] == b"\xef\xbb\xbf"
