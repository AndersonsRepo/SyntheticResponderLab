# Phase 3 — synthetic runs vs the real AYTM survey

Compares each phase-2 run with the real 600-respondent AYTM export, question by question, offline.
Only `realdata.py` opens the real file and only when `--real` is passed; nothing in phase 2 imports
phase 3 (a test enforces it), and no output is ever written into the raw-data folder (exit 3).

## Run (from the repository root)

```bash
ASSETS=../SyntheticResponderLab-Assets
REAL="$ASSETS/raw 600-participant dataset and a sample report from aytm/survey-760085-2026-03-25-raw-data.csv"
RUNS=$ASSETS/match_600_persona/survey_runs
apps/api/.venv/bin/python research/neo_persona_set/phase3/filter_qualified.py --runs $RUNS/*_matched
apps/api/.venv/bin/python research/neo_persona_set/phase3/compare_real.py --real "$REAL" \
  --runs $RUNS/*_matched --out $ASSETS/match_600_persona/real_comparison/$(date -u +%Y%m%dT%H%MZ)
```

Flags: `--require-outdoor-space` (default; drops synthetic personas whose S3 starts with "No", about
31% of the matched set) / `--keep-all`, `--close-tv 0.10`, `--exclude-fallback`.

## Method

`crosswalk.py` maps our 39 ids to the AYTM columns (our Q1 = real Q6, Q5_1..7 = Q9 matrix rows,
Q15..17 = Q30 rows 1..3, Q26 derived from the Q37 club multi-select, Q21/Q22 from Age/Income).
Q7 and Q23 have no counterpart; Q30 is reported, not scored. Categories are the options both
surveys share; real-only options (Q11 Other, Q31 Smart Technology/Showroom/Other, six Q33
channels) and our-only options (Q22 Prefer not to say) are reported as off-list shares. Per run x
question: TV distance, JS divergence, Spearman on option shares, top-option match, likert means and
their difference, chi-square GOF p (hand-rolled), `close` = TV <= threshold. Per option: shares and
a two-proportion z-test.

## Outputs (`--out`)

| File | Contents |
| --- | --- |
| `comparison_long.csv` | one row per run x question |
| `comparison_options.csv` | one row per run x question x category |
| `comparison_summary.csv` | per run: questions compared/close, mean/median TV, mean JS, top-match share, mean abs likert diff |
| `comparison_by_question.md` | real vs each run side by side |
| `unmapped.md` | items without counterpart on either side |
| `crosswalk.csv` | the mapping with both option lists |
| `manifest.json` | sha256 of inputs and outputs, filters, thresholds, N per run, git commit |

## Other tools

`lint_personas.py` (checks a persona CSV), `select_panel.py` (stratified 150-persona panel),
`add_bom.py` (Excel-safe rewrite of old run CSVs), `registry.py` (hypothesis registry),
`write_start_here.py` (START_HERE.md for the shared folder), `judge_reasons.py` (a third model
picks the better-reasoned answer between two `--reason-per-answer` runs; needs the API). Tests:
`apps/api/.venv/bin/python -m pytest research/neo_persona_set/phase3 -q`.
