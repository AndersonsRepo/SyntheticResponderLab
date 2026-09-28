# DONE — "AI interviews you" (AI moderator, student respondent)

Spec decided at the 2026-09-10 team meeting and by Dr. Lin on 2026-09-26, so step 0 was skipped. Checks run from this
directory via `bash ./check.sh`.

## Outcomes

- [x] On /interview a student sees an "AI interviews you" entry that opens the new mode — check: `bash ./check.sh web "interview page links"`
- [x] A no-login classroom student can reach the mode's page and its one API call, and nothing wider opens — check: `bash ./check.sh web "classroom"`
- [x] Starting the mode, the student gets an opening question from the same interviewer agent and discussion guide the persona batches use, on the default interviewer model — check: `bash ./check.sh api test_opening_question_uses_the_batch_guide_and_default_model`
- [x] After the student answers, the next question follows up on what they actually wrote — check: `bash ./check.sh api test_followup_is_derived_from_the_student_answer`
- [x] At the guide's end (8 answers) the AI stops asking and the interview is marked complete, with no further paid call — check: `bash ./check.sh api test_interview_completes_at_the_guide_end_without_a_paid_call`
- [x] A no-login classroom student (classroom identity headers) can run it; another student cannot use their study or session — check: `bash ./check.sh api test_classroom_identity_owns_the_session`
- [x] Transcript exports as the same single-file CSV/Markdown the batch export uses, every row labelled as a human respondent, formula-safe — check: `bash ./check.sh web "export"`

## Adversarial pass (what a student will actually hit)

- [x] Empty/whitespace answer: Send stays disabled, and the API refuses it with 400 and no paid call — check: `bash ./check.sh web "send guard" && bash ./check.sh api test_empty_answer_is_refused_before_any_paid_call`
- [x] Double submit (double click, retried request): one paid call, same question back — check: `bash ./check.sh web "send guard" && bash ./check.sh api test_double_submit_charges_once_and_returns_the_same_question`
- [x] End mid-question: the interview ends at once, a question arriving after End is dropped, and the transcript is still exportable — check: `bash ./check.sh web "end"`
- [x] Budget exhausted (run cap, or NEO_LLM_BUDGET_USD=0): the API returns 429 quota_exceeded, zero budget makes no provider call, and the page shows the message and ends — check: `bash ./check.sh api test_budget_cap_stops_the_interview && bash ./check.sh web "errors"`
- [x] API/provider down: 503 with a message, the student's typed answer stays in the box, and resending the same transcript works — check: `bash ./check.sh api test_provider_failure_is_retryable && bash ./check.sh web "errors"`
- [x] Replay-only cache mode (no paid calls allowed) refuses with a clear 409, not a crash — check: `bash ./check.sh api test_replay_only_mode_refuses_clearly`
- [x] Refresh mid-interview: the browser warns before leaving an unfinished interview (answers are deliberately not stored, so nothing can be restored) — check: `bash ./check.sh web "refresh"`
- [x] Student answers are human data: never persisted server-side (no InterviewTurn, Job or cache row holds them) — check: `bash ./check.sh api test_student_answers_are_never_persisted`
- [x] Student answers leave the browser only in the next-question call: the page never writes them to local/sessionStorage or posts them to the server export — check: `bash ./check.sh web "human data"`

## Final

- [x] (final) Full API suite green — check: `bash ./check.sh api-all`
- [x] (final) Full web unit suite green — check: `bash ./check.sh web-all`
- [x] (final) Web typecheck clean — check: `bash ./check.sh typecheck`
- [x] (final) Web production build succeeds — check: `bash ./check.sh build`

## Out of scope

- Restoring an interview after refresh: would require storing the student's answers (server or browser), which the spec forbids beyond existing transcript storage. Covered instead by the leave warning above.
- Choosing the interviewer model: spec says use the model the interviewer already uses; the server pins `DEFAULT_INTERVIEW_MODEL_ID` and ignores any model the client sends.
- Codex refuter (`done.py refute`, `/verify-codex`): rate-limited per Anderson; replaced by the adversarial pass above.

## Decisions (unasked choices, and how to revert)

- **Student answers are never stored server-side** (stricter than the spec allows). Only the AI's questions and their cost go in `interview_turn` (persona_id `human`), the same way the AI-led interview records questions. To store answers too, add an `assistant` InterviewTurn in `next_human_question` (`apps/api/src/services/standalone_interview.py`).
- **Interview cache bypassed** for this mode: a cache row is keyed on the student's words and would outlive them. Same function; the `# ponytail:` comment marks it.
- **Guide = the batch guide** (`RESEARCH_BRIEF` in `standalone_interview.py`, Tahoe Mini), so a student's interview is comparable with the persona batch they ran. A study's saved research brief is ignored, as the batches already ignore it.
- **Separate page `/interview/you`**, linked from /interview as "AI interviews you", rather than a fourth mode inside the 1,350-line interview page.
- **Export happens in the browser** with the existing `batchExport` (same CSV/Markdown file as a batch). The server export endpoint was not used, because it would send the student's answers to the server a second time.
- **Model pinned server-side** to `DEFAULT_INTERVIEW_MODEL_ID` (currently `google/gemini-2.5-flash-lite`); any model the client sends is ignored.

## Unverified

- Real LLM behaviour: whether the default interviewer model writes good follow-ups to a real student's answers (every test uses a stub provider). Settle this with one live interview on a preview deploy.
- The live no-login chain (Next middleware → proxy → API with classroom headers). Tests cover the allowlist function and the API under classroom identity headers, not the running proxy. Settle this by opening `/interview/you` on a `CLASSROOM_NO_LOGIN=true` preview and answering two questions.
- SSO/Clerk logged-in path: not exercised. Settle this by doing the same while signed in.
- The browser's leave prompt actually appearing, and the page's look: checked from source only, and no browser run happened. Settle this by refreshing mid-interview in Chrome and Safari.
- Concurrent double-submit on Postgres: the dedupe relies on `validate_session`'s transaction lock and was only tested sequentially on SQLite. Settle this with two parallel POSTs against a Postgres instance.
- Production `CACHE_MODE`: if prod runs `replay_only`, this mode refuses (409) by design. Settle this by reading the Railway env var.
- The build check uses placeholder `API_BASE_URL`, `DEPLOYMENT_SHARED_SECRET` and `APP_ACCESS_PASSWORD`, which the production env guards need in order to prerender. Real values were not tested.
