"""A third model reads two models' answers and reasons to the same question for the same persona and
picks the better-reasoned one (Dr. Lin's annotation -> judge loop). Produces a run-shaped folder.

    apps/api/.venv/bin/python research/neo_persona_set/phase3/judge_reasons.py \\
        --run-a <run with --reason-per-answer> --run-b <run with --reason-per-answer> --judge-model zai/glm-5 --out <dir>
"""

from __future__ import annotations

import argparse
import csv
import json
import shutil
import sys
from collections import Counter, OrderedDict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

HERE = Path(__file__).resolve().parent
PHASE2 = HERE.parent / "phase2"
for folder in (HERE, PHASE2):
    if str(folder) not in sys.path:
        sys.path.insert(0, str(folder))

CSV_ENCODING = "utf-8-sig"


def read_rows(path: Path) -> List[Dict[str, str]]:
    with open(path, newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def build_judge_prompt(question_text: str, option_text: str, a: Dict[str, str], b: Dict[str, str]) -> List[Dict[str, str]]:
    system = ("You are a market-research supervisor. Two synthetic respondents with the same profile answered the same survey question and each "
              "gave a reason. Pick the answer whose reason is more consistent with the profile and more plausible for a real consumer. "
              'Return strict JSON only: {"pick": "A" or "B", "why": "<one sentence>"}.')
    user = (f"Question: {question_text}\nAnswer format: {option_text}\n\n"
            f"A answered: {a.get('answer')!r}\nA's reason: {a.get('reason') or '(none)'}\n\n"
            f"B answered: {b.get('answer')!r}\nB's reason: {b.get('reason') or '(none)'}\n\n"
            'Which is better reasoned? Return {"pick": "A"|"B", "why": "..."}.')
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def _index(rows: List[Dict[str, str]]) -> "OrderedDict[tuple, Dict[str, str]]":
    return OrderedDict(((r["persona_id"], r["question_id"]), r) for r in rows)


def judge_runs(run_a: Path, run_b: Path, out: Path, *, judge_model: str, client: Any, concurrency: int = 8, limit: Optional[int] = None) -> Dict[str, Any]:
    started = datetime.now(timezone.utc)
    a_rows, b_rows = _index(read_rows(run_a / "answers_long.csv")), _index(read_rows(run_b / "answers_long.csv"))
    questions = {q["question_id"]: q for q in read_rows(run_a / "questions.csv")}
    keys = [k for k in a_rows if k in b_rows]
    if limit:
        keep = []
        seen: List[str] = []
        for key in keys:
            if key[0] not in seen:
                if len(seen) == limit:
                    break
                seen.append(key[0])
            keep.append(key)
        keys = keep

    def ask(key: tuple) -> Dict[str, Any]:
        a, b, question = a_rows[key], b_rows[key], questions.get(key[1], {})
        option_text = question.get("options") or f"{question.get('min_value')}..{question.get('max_value')}"
        payload = {"messages": build_judge_prompt(question.get("text", key[1]), option_text, a, b), "temperature": 0.0, "max_tokens": 300, "_persona_id": f"{key[0]}|{key[1]}"}
        result = client.generate_survey_response_with_openrouter(model_name=judge_model, prompt_payload=payload, timeout=120)
        pick = str(((result.get("parsed_json") or {}).get("pick") or "")).strip().upper()
        if pick not in ("A", "B"):
            pick = "A"  # unreadable verdict: keep run A's answer and say so
            why = f"judge unreadable: {result.get('error') or result.get('raw_text', '')[:80]}"
        else:
            why = str((result.get("parsed_json") or {}).get("why") or "")
        chosen = a if pick == "A" else b
        return {**chosen, "picked": pick, "why": why, "model": judge_model, "run_id": out.name}

    with ThreadPoolExecutor(max_workers=max(1, concurrency)) as pool:
        judged = list(pool.map(ask, keys))

    out.mkdir(parents=True, exist_ok=True)
    long_header = [c for c in judged[0].keys()] if judged else []
    with open(out / "answers_long.csv", "w", newline="", encoding=CSV_ENCODING) as handle:
        writer = csv.DictWriter(handle, fieldnames=long_header)
        writer.writeheader()
        writer.writerows(judged)
    question_ids = list(questions)
    wide: "OrderedDict[str, Dict[str, str]]" = OrderedDict()
    for row in judged:
        entry = wide.setdefault(row["persona_id"], {"run_id": out.name, "model": judge_model, "repeat": row.get("repeat", ""), "seed": row.get("seed", ""), "persona_id": row["persona_id"], "respondent_id": row.get("respondent_id", "")})
        entry[row["question_id"]] = row.get("answer", "")
    with open(out / "answers_wide.csv", "w", newline="", encoding=CSV_ENCODING) as handle:
        header = ["run_id", "model", "repeat", "seed", "persona_id", "respondent_id", *question_ids, "n_fallback", "all_live"]
        writer = csv.DictWriter(handle, fieldnames=header)
        writer.writeheader()
        for entry in wide.values():
            writer.writerow({**{k: "" for k in header}, **entry, "n_fallback": 0, "all_live": "true"})
    shutil.copyfile(run_a / "questions.csv", out / "questions.csv")
    picks = Counter(row["picked"] for row in judged)
    stats = getattr(client, "stats", Counter())
    manifest = {
        "run_id": out.name, "status": "completed", "created_at": started.isoformat(), "finished_at": datetime.now(timezone.utc).isoformat(),
        "models": {"a": a_rows[keys[0]]["model"] if keys else None, "b": b_rows[keys[0]]["model"] if keys else None, "judge": judge_model, "requested": judge_model},
        "source_runs": {"a": str(run_a), "b": str(run_b)}, "pairs_judged": len(judged), "picks": dict(picks),
        "tokens": {"prompt": int(stats.get("prompt_tokens", 0)), "completion": int(stats.get("completion_tokens", 0))},
        "cost": {"usd_reported": getattr(client, "usd_reported", None)},
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8")
    return manifest


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--run-a", type=Path, required=True)
    parser.add_argument("--run-b", type=Path, required=True)
    parser.add_argument("--judge-model", required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--limit", type=int, default=None, help="judge only the first N personas")
    parser.add_argument("--concurrency", type=int, default=8)
    args = parser.parse_args(argv)
    import run_survey  # noqa: E402  (phase2; provides the OpenRouter client and the key from apps/api/.env)

    for path in (args.run_a, args.run_b, args.out):
        run_survey.assert_not_real_data(path, "path")
    client = run_survey.OpenRouterClient(api_key=run_survey.env_value("OPENROUTER_API_KEY", "") or "", base_url=run_survey.env_value("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1") or "",
                                         seed=None, max_retries=3, reasoning_effort="off", progress_every=100)
    manifest = judge_runs(args.run_a, args.run_b, args.out, judge_model=args.judge_model, client=client, concurrency=args.concurrency, limit=args.limit)
    print(f"judged {manifest['pairs_judged']} pairs: {manifest['picks']} -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
