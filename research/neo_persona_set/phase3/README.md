# Phase 3 — synthetic runs vs the real AYTM survey

Compares each phase-2 run with the real 600-respondent AYTM export, question by question, offline.
Only `realdata.py` opens the real file and only when `--real` is passed; nothing in phase 2 imports
phase 3 (a test enforces it), and no output is ever written into the raw-data folder (exit 3).

## Run (from the repository root)

```bash
ASSETS=../SyntheticResponderLab-Assets
REAL="$ASSETS/2_real_data_aytm/survey-760085-2026-03-25-raw-data.csv"
RUNS=$ASSETS/5_experiments/2026-09-10_first_full_600_runs/matched_600_v1/survey_runs
apps/api/.venv/bin/python research/neo_persona_set/phase3/filter_qualified.py --runs $RUNS/*_matched
apps/api/.venv/bin/python research/neo_persona_set/phase3/compare_real.py --real "$REAL" \
  --runs $RUNS/*_matched --out $ASSETS/5_experiments/2026-09-10_first_full_600_runs/matched_600_v1/real_comparison/$(date -u +%Y%m%dT%H%MZ)
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
`write_start_here.py` (START_HERE.md for the shared folder), `import_driver_personas.py` (Dr. Lin's driver
files onto the team's persona file), `make_mixed_panel.py` (one persona per
arm across several runs), `spread_diagnostics.py` (spread and the income gradient; `--real-from <compare_real
folder>` adds the real survey's row, computed at run time), `judge_reasons.py` (a third model
picks the better-reasoned answer between two `--reason-per-answer` runs; needs the API). Tests:
`apps/api/.venv/bin/python -m pytest research/neo_persona_set/phase3 -q`.

Analyses that back numbers in the experiment log but were first run inline are in `offline/`
(section at the end).

## Scoring standard: Dr. Lin's calibration / validation split

Adopted 2026-09-30. Anything fitted to real answers (driver donors, model adjustments) uses only the
calibration items and the fit half of respondents; results are scored only on the 13 validation
items against the other 300. Every headline number from now on is on this standard.

```bash
# 1. convert his split (3_scoring_standard/DrLin_split/aytm_respondent_split_ids.csv) into Response-ID files.
#    His ids are row indexes: aytm_N = respondent row N of the raw file, in file order.
#    Written outside the repo; the script refuses the repo and the real-data folder.
apps/api/.venv/bin/python research/neo_persona_set/phase3/make_real_split.py --real "$REAL" \
  --from-lin ../SyntheticResponderLab-Assets/3_scoring_standard/DrLin_split/aytm_respondent_split_ids.csv \
  --out ../SyntheticResponderLab-Assets/3_scoring_standard/real_splits/lin-seed42

# 2. score only the 13 validation items, against only his 300 val respondents
apps/api/.venv/bin/python research/neo_persona_set/phase3/compare_real.py --real "$REAL" \
  --runs <run_dir> ... --out <dir> \
  --items lin13-validation \
  --real-ids ../SyntheticResponderLab-Assets/3_scoring_standard/real_splits/lin-seed42/score_ids.txt
```

- `--items` takes a named set from `item_sets.py` (`lin13-validation`, `lin13-calibration`,
  `all-scored`) or a file of question ids. Questions outside the set are still compared and
  reported, with `scored=false`. Without `--items` every comparable question counts, as before.
- The named sets match his `item_split.csv` (`item_sets.LIN_ITEM_NAMES` translates his names).
  Q15 and Q24 are set aside (Dr. Wang, 2026-09-24) and are in no named set; `all-scored` is the
  other 34. On our survey the calibration set has 10 items, not 13: our survey carries only 3 of
  the 5 value drivers and Q15 is set aside.
- `--real-ids` takes a file of AYTM Response IDs. `3_scoring_standard/real_splits/lin-seed42/` is his split;
  `3_scoring_standard/real_splits/provisional-seed42/` was a stand-in drawn before his arrived and is superseded.
  Without `--from-lin`, `make_real_split.py` still draws a new seeded split.
- `comparison_summary.csv` gains `item_set` and `n_real_respondents`; `manifest.json` records the
  item list and the id file's hash.

## Hybrid runs (driver personas)

Dr. Lin's driver method gives each persona four answers copied from a real respondent in the
calibration half with the same income band, age group and kids: prior consideration (Q0A), primary
use (Q3), outdoor recreation (Q25) and club membership (Q26). Real answers then reach the prompt,
so these runs are labelled hybrid end to end:

1. Dr. Lin's persona files (`4_persona_sets/hybrid_drivers/from_DrLin_2026-10-01/personas_S*_drv.csv`) are the
   team's persona file plus `prior_consideration_of_backyard_unit`, `outdoor_recreation_frequency`,
   `member_of_outdoor_club`, `most_likely_use_for_a_backyard_unit` and `driver_donor_id` (an
   `aytm_N` row id, never sent to the model). `import_driver_personas.py` checks them (persona
   columns equal the team file, drivers filled, every donor in the cal half) and writes a
   run-ready copy to `4_persona_sets/hybrid_drivers/run_ready/` that keeps the team file's columns and P001-P100
   numbering, so a hybrid prompt differs from the synthetic one only by `customer_facts` and the
   mixed-panel deal matches the baselines. The runner refuses such a file without `--hybrid`, and
   `--hybrid` needs `hybrid` in the run tag (`phase2/README.md`).
2. `make_mixed_panel.py` deals personas to arms that must share the persona file, seed, answer
   mode, persona kind and style mix (`--allow-mismatch trait_mix` to mix styled and unstyled on
   purpose); `probabilities.csv` is carried for `--answer-mode distribution` arms.
3. `compare_real.py` refuses a hybrid run without `--real-ids` or with any of the four driver
   items in the scored set (`item_sets.LIN_DRIVERS`).

Pre-registered: R020 (unstyled four-model mix) and R020b (styled), then R021 (drawing only) and
R021b (drivers only) to separate R020's two changes, in `registry.csv`. R022 (2026-10-19) is the
S2 confirmation of R020 on Dr. Lin's S2, judged by his rule against R022u (the same mix without
drivers or drawing); its row's notes give the exact run, panel and random-control commands.

`offline/r020_r021_attribution.py` re-derives the first four from the saved panels and scores
R022 with `--only R022` (section below).

## offline/ — recovered analyses (2026-10-18)

Some numbers in the experiment log come from analyses that were run inline in Claude Code
sessions and never committed. The scripts in `offline/` recover them from the session record.
- They make no API calls and use no network.
- Each refuses an output folder inside the repository or the real-data folder.
- Each writes to a `reproduced_2026-10-18/` folder inside the experiment folder it re-derives, in
  the Assets folder. The one exception is `r020_r021_attribution.py --only R022`, a new experiment
  rather than a reproduction: it writes to `lin_rule_verdict/` inside the R022 folder.
- The checks against the log read the logged numbers from `0_logs/EXPERIMENT_LOG.md` at run time.
  No logged or real-derived value is written into the code.
- The real file is read only for aggregates, directly or through `compare_real.py`.

The tests (`test_offline_*.py`) use tiny fake inputs only.

| Script | Reproduces | Outputs in `5_experiments/…/reproduced_2026-10-18/` (unless another folder is named) |
| --- | --- | --- |
| `sept17_side_tables.py` | R010: Q1 by income band and rho(income, Q1 / Q2) (`income-table`, needs `--real`). R004: money reasons among Q1 = 1 answers (`money-reasons`) | `2026-09-17_S1_prompt_and_sampling_tests` |
| `sept25_review_checks.py` | The Sept 25 review: the 18 comparison folders and 38 ALL_ARMS rows, the persona bootstrap, the unstyled mix, the money-strip audit, the random control, shuffle invariance and the income-gradient shares (`all`, about a minute) | `2026-09-24_Yaza_ablations_models_styles` |
| `r020_r021_attribution.py` | R020 / R020b / R021 / R021b: the persona -> model deal against R018u / R018b; Lin-standard scores; income rho on the drawn and the expected Q1; the Q1 4-5 share; the verdicts. The rules are read from `registry.csv`, as committed at each row's pre-registration commit when git can show it, and R020's gains computed from the score files. It builds no panel: a missing one is reported (exit 2). The default run is R020 and R021 | `2026-10-01_R020_drivers_plus_drawing`, `2026-10-02_R021_drawing_only_vs_drivers_only` |
| `r020_r021_attribution.py --only R022` | Not a reproduction: R022 against R022u under Dr. Lin's rule on his S2 (income link from `4_persona_sets/hybrid_drivers/run_ready/s2lin_drv.csv`), with the S2 random control. Needs none of the S1 panels and is not checked against the log | `2026-10-20_R022_S2_confirmation/lin_rule_verdict/` |
| `jev_drawn_offline.py` | The Oct 5 Jev arm: answers drawn from the saved Sept 24 Jev odds with `phase2/run_survey.draw_answer` (seeds 202610051 / 202610052), scored on the Lin standard; `--check-against` compares with the Oct 5 folder byte for byte | `2026-10-05_jev_drawn_offline` |
| `noise_check_bootstrap.py` | The Oct 5 noise check: a paired persona bootstrap between saved arms (income link, Q1 4-5 share) and the exact gaps for Anderson's tie table. It reads synthetic runs only; the tie band is passed in | `2026-10-05_noise_check_and_average_shape` |
| `average_shape_baseline.py` | The average human answer shape fitted on the fit respondents. It pools the calibration items by default; `--pool-items all-likert` reproduces the Oct 5 and Anderson numbers and warns that the pool overlaps the scored items | `2026-10-05_noise_check_and_average_shape` |
| `historic_common.py` | shared helpers for the two Sept scripts (not a CLI) | — |

```bash
ASSETS=../SyntheticResponderLab-Assets
REAL="$ASSETS/2_real_data_aytm/survey-760085-2026-03-25-raw-data.csv"
SPLIT=$ASSETS/3_scoring_standard/real_splits/lin-seed42
PY=apps/api/.venv/bin/python; OFF=research/neo_persona_set/phase3/offline
$PY $OFF/sept17_side_tables.py income-table --real "$REAL"
$PY $OFF/sept17_side_tables.py money-reasons
$PY $OFF/sept25_review_checks.py all --real "$REAL"
$PY $OFF/r020_r021_attribution.py --real "$REAL"
$PY $OFF/r020_r021_attribution.py --real "$REAL" --only R022   # after the R022 runs and panels
$PY $OFF/jev_drawn_offline.py \
  --jev-run $ASSETS/5_experiments/2026-09-24_Yaza_ablations_models_styles/survey_runs/20260924T170819Z_jev-latest_r1_s1-jev-full \
  --personas $ASSETS/4_persona_sets/matched_600_v2_S1-S6_2026-09-16/phase1_interview_matched600_s1.csv \
  --real "$REAL" --real-ids $SPLIT/score_ids.txt \
  --out $ASSETS/5_experiments/2026-10-05_jev_drawn_offline/reproduced_2026-10-18 \
  --check-against $ASSETS/5_experiments/2026-10-05_jev_drawn_offline
# the tie band is a real-vs-real number: take it from Anderson's report
# (3_scoring_standard/real_baselines_Anderson_2026-10-05.pdf); it is not stored in the repo
$PY $OFF/noise_check_bootstrap.py --preset oct05 --assets $ASSETS \
  --tie-band-tv <TV band> --tie-band-rank <rank band> \
  --out $ASSETS/5_experiments/2026-10-05_noise_check_and_average_shape/reproduced_2026-10-18
$PY $OFF/average_shape_baseline.py --real "$REAL" \
  --fit-ids $SPLIT/fit_ids.txt --score-ids $SPLIT/score_ids.txt \
  --pool-items lin13-calibration --pool-items all-likert --score-items lin13-validation \
  --out $ASSETS/5_experiments/2026-10-05_noise_check_and_average_shape/reproduced_2026-10-18
```

`jev_drawn_offline.py` imports `phase2/run_survey.py`, so it needs the `apps/api` venv. What each
run reproduced, and the few numbers that did not match, are in the experiment log in the Assets
folder (the 2026-10-05 entries, section 6 Reproducibility, section 8 Open issues).
