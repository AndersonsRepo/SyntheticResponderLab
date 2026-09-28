Goal: Dr. Lin's five focus-group fixes (email after the 2026-09-23 class), shipped in the order 5 → 2 → 1 → 4 → 3 so each can deploy alone before PA3.5 (due Tue 2026-09-29). His acceptance checks are the spec. Keep: 5-stage funnel, 3-person minimum, cost preview, manual stage changes, cross-references between participants, and the "AI interviews you" mode.

Checks run from this directory. `P` = `cd ../.. && ./apps/api/.venv/bin/python -m pytest apps/api/tests/test_focus_group_lin.py -q`, `W` = `sh ./webcheck.sh`.

## Fix 5 — the debrief works without AI

- [x] A student can write the PA3.5 memo by hand — three themes each with a linked quote, one surprise, at least three PA4 answer options tagged by question topic, one moderation improvement — and save it with no OpenRouter key configured and no model call. — check: `cd ../.. && ./apps/api/.venv/bin/python -m pytest apps/api/tests/test_focus_group_lin.py -q -k 'manual_memo_without_ai'`
- [x] Every turn in the transcript has a turn ID that does not change when later rounds are asked or a failed turn is retried. — check: `cd ../.. && ./apps/api/.venv/bin/python -m pytest apps/api/tests/test_focus_group_lin.py -q -k 'stable_turn_ids'`
- [x] Every cited quote links to an actual turn: a quote naming a turn that does not exist, a silent/unanswered turn, or text that is not in that turn is flagged and never exported as a linked quote. — check: `cd ../.. && ./apps/api/.venv/bin/python -m pytest apps/api/tests/test_focus_group_lin.py -q -k 'quote_must_link'`
- [x] The student can export the transcript and the human-written memo (Markdown and CSV) without any AI memo ever succeeding; each quote in the export carries its turn ID, stage and round. — check: `cd ../.. && ./apps/api/.venv/bin/python -m pytest apps/api/tests/test_focus_group_lin.py -q -k 'export_manual_memo'`
- [x] A failed AI memo attempt keeps the transcript and the student's memo intact, says why it failed and exactly what it charged, and the retry control says a retry is a new charge; the student can finish and export the manual memo without retrying. — check: `cd ../.. && ./apps/api/.venv/bin/python -m pytest apps/api/tests/test_focus_group_lin.py -q -k 'failed_ai_memo_preserves'`
- [x] A half-finished memo is saved as a draft rather than lost, and the export marks it a draft and names what is missing. — check: `cd ../.. && ./apps/api/.venv/bin/python -m pytest apps/api/tests/test_focus_group_lin.py -q -k 'draft_memo'`
- [x] If saving the memo is refused (say a field is too long), Export still downloads the transcript with the last saved memo and tells the student their latest edits were not saved. — check: `sh ./webcheck.sh 'manual memo: the form comes before'`
- [x] Oversized or malformed memo input is refused with a plain message and stores nothing. — check: `cd ../.. && ./apps/api/.venv/bin/python -m pytest apps/api/tests/test_focus_group_lin.py -q -k 'memo_input_bounds'`
- [x] Every export and the focus-group page carry "Synthetic rehearsal - not PA3.5 live fieldwork". — check: `cd ../.. && ./apps/api/.venv/bin/python -m pytest apps/api/tests/test_focus_group_lin.py -q -k 'rehearsal_label' && cd plans/lin-classroom-fixes && sh ./webcheck.sh 'rehearsal label'`
- [x] On the page the manual memo form comes before the optional AI feedback, each answered turn shows its ID with a "Quote" control, and a saved draft is restored when the room is re-opened. — check: `sh ./webcheck.sh 'manual memo'`

## Fix 2 — the concept is shown and information is released on purpose

- [x] A concept card (name, description, specifications, an editable read-aloud introduction, and a copy-as-text control for ChatGPT) sits directly above the question field, and its text is the exact stimulus the server gives participants. — check: `cd ../.. && ./apps/api/.venv/bin/python -m pytest apps/api/tests/test_focus_group_lin.py -q -k 'concept_card_is_the_stimulus' && cd plans/lin-classroom-fixes && sh ./webcheck.sh 'concept card'`
- [x] Until the moderator introduces the concept, no product fact reaches any participant prompt — including a question asked at the concept stage without introducing it. — check: `cd ../.. && ./apps/api/.venv/bin/python -m pytest apps/api/tests/test_focus_group_lin.py -q -k 'concept_withheld_until_introduced'`
- [x] The price never reaches the model before an explicit Reveal price — across all five stages, the system prompt and every replayed message. — check: `cd ../.. && ./apps/api/.venv/bin/python -m pytest apps/api/tests/test_focus_group_lin.py -q -k 'price_never_reaches_model_before_reveal'`
- [x] Reveal price is refused until the concept was introduced and an unaided price question was answered; it then reaches every later prompt. — check: `cd ../.. && ./apps/api/.venv/bin/python -m pytest apps/api/tests/test_focus_group_lin.py -q -k 'reveal_price_order'`
- [x] Before the price is revealed the moderator cannot anchor it either: a dollar figure in any question is refused with a message pointing at Reveal price. — check: `cd ../.. && ./apps/api/.venv/bin/python -m pytest apps/api/tests/test_focus_group_lin.py -q -k 'moderator_price_refused_before_reveal'`
- [x] Participants are told what they have and have not been shown: before reveal they may guess a price but are instructed not to state one as the product's price. — check: `cd ../.. && ./apps/api/.venv/bin/python -m pytest apps/api/tests/test_focus_group_lin.py -q -k 'unshared_facts_are_unknown'`
- [x] The student can state exactly what participants have seen at each stage: an "Information shared with participants" panel lists each stimulus and the round it was shown at, and the export records the stimulus text and reveal points. — check: `cd ../.. && ./apps/api/.venv/bin/python -m pytest apps/api/tests/test_focus_group_lin.py -q -k 'shared_info_in_export' && cd plans/lin-classroom-fixes && sh ./webcheck.sh 'shared with participants'`

## Fix 1 — who is in the room

- [x] At recruitment every roster persona is an expandable card showing ID/name, household context, owner/renter, usable outdoor space, and willingness to consider more living/work space; each attribute is marked source-backed (ACS PUMS), fictional, or unknown, and missing facts read "Unknown". — check: `cd ../.. && ./apps/api/.venv/bin/python -m pytest apps/api/tests/test_focus_group_lin.py -q -k 'persona_cards' && cd plans/lin-classroom-fixes && sh ./webcheck.sh 'persona card'`
- [x] Each card states, per PA3.5 screener criterion, whether the persona meets it, does not, or the data cannot tell — so the student can explain the choice before starting. — check: `cd ../.. && ./apps/api/.venv/bin/python -m pytest apps/api/tests/test_focus_group_lin.py -q -k 'screener'`
- [x] While moderating, the same cards for the seated participants are available beside the discussion without leaving the room, including after re-opening it. — check: `cd ../.. && ./apps/api/.venv/bin/python -m pytest apps/api/tests/test_focus_group_lin.py -q -k 'room_carries_participant_cards' && cd plans/lin-classroom-fixes && sh ./webcheck.sh 'beside the discussion'`
- [x] Showing cards does not change what the model is told about a roster persona. — check: `cd ../.. && ./apps/api/.venv/bin/python -m pytest apps/api/tests/test_focus_group_lin.py -q -k 'cards_do_not_change_prompt'`

## Fix 4 — targeted questions, silence, probes

- [x] A question addressed only to P002 makes one call and produces one in-character answer; the others show as intentionally silent, not errors, and the room is not failed. — check: `cd ../.. && ./apps/api/.venv/bin/python -m pytest apps/api/tests/test_focus_group_lin.py -q -k 'targeted_question'`
- [x] Silent participants never appear as missing answers — not in retry, the memo gate, or the export. — check: `cd ../.. && ./apps/api/.venv/bin/python -m pytest apps/api/tests/test_focus_group_lin.py -q -k 'silent_is_not_missing'`
- [x] A reply that talks about being an AI, a model, prompts or instructions is withheld from the dialogue, its charge recorded, and the turn offered for retry; the prompt forbids such commentary. — check: `cd ../.. && ./apps/api/.venv/bin/python -m pytest apps/api/tests/test_focus_group_lin.py -q -k 'out_of_character'`
- [x] Recipients naming someone not in the room, or nobody, are refused before any call. — check: `cd ../.. && ./apps/api/.venv/bin/python -m pytest apps/api/tests/test_focus_group_lin.py -q -k 'recipients_validated'`
- [x] With the default allowance (5 core + 3 probes) a student can ask two probes in one stage and still complete all five stages. — check: `cd ../.. && ./apps/api/.venv/bin/python -m pytest apps/api/tests/test_focus_group_lin.py -q -k 'two_probes_and_full_funnel'`
- [x] Probes can never use up the questions the remaining stages need; when probes run out the refusal says so and names the extension. — check: `cd ../.. && ./apps/api/.venv/bin/python -m pytest apps/api/tests/test_focus_group_lin.py -q -k 'probes_never_starve_the_funnel'`
- [x] A budgeted extension adds probes only after the student authorizes its shown cost, and goes through the same run/class budget cap (refused when it would exceed it). — check: `cd ../.. && ./apps/api/.venv/bin/python -m pytest apps/api/tests/test_focus_group_lin.py -q -k 'extension'`
- [x] The page has a Whole room / Selected participant(s) selector, separate "Ask follow-up" and "Next stage" controls, keeps manual stage buttons, shows remaining core questions and probes, and shows technical errors outside the participant dialogue. — check: `sh ./webcheck.sh 'recipient selector'`

## Fix 3 — student-created practice personas

- [x] A student can create a persona through a structured form (household, tenure, outdoor space, current space use, willingness to consider more space, constraints, optional style), preview its card, save it, edit it (version goes up), and recruit it alongside roster personas. — check: `cd ../.. && ./apps/api/.venv/bin/python -m pytest apps/api/tests/test_focus_group_lin.py -q -k 'custom_persona_lifecycle'`
- [x] "Duplicate and edit" starts from a roster persona's facts and records which one it came from; the copy is fictional, not source-backed. — check: `cd ../.. && ./apps/api/.venv/bin/python -m pytest apps/api/tests/test_focus_group_lin.py -q -k 'duplicate'`
- [x] Once discussion starts the persona version is frozen: every call for that seat uses the same profile, and later edits do not change the running room. — check: `cd ../.. && ./apps/api/.venv/bin/python -m pytest apps/api/tests/test_focus_group_lin.py -q -k 'frozen'`
- [x] The card and the export label it "Student-created fictional persona" with its origin and version, and say it is not a real PA3.5 participant. — check: `cd ../.. && ./apps/api/.venv/bin/python -m pytest apps/api/tests/test_focus_group_lin.py -q -k 'custom_export'`
- [x] The form asks how the profile relates to the research question and never asks for a product opinion or desired findings; that reflection is not sent to the model. — check: `cd ../.. && ./apps/api/.venv/bin/python -m pytest apps/api/tests/test_focus_group_lin.py -q -k 'research_link'`
- [x] A student's personas are visible only in their own study (another classroom device cannot list, edit or seat them). — check: `cd ../.. && ./apps/api/.venv/bin/python -m pytest apps/api/tests/test_focus_group_lin.py -q -k 'custom_persona_isolated'`
- [x] Oversized or malformed persona input is refused with a plain message and stores nothing; a study cannot create unbounded personas. — check: `cd ../.. && ./apps/api/.venv/bin/python -m pytest apps/api/tests/test_focus_group_lin.py -q -k 'custom_persona_bounds'`
- [x] The page has Create persona and Duplicate and edit beside the roster, a preview before saving, and the fictional label on the card. — check: `sh ./webcheck.sh 'create persona'`

## Cross-cutting

- [x] Every new endpoint a student hits is on the classroom no-login allowlist, and nothing wider opened (other methods, suffixes, and encoded paths still refused). — check: `sh ./webcheck.sh 'classroom allowlist'`
- [x] Every new mutating entry point is serialized like the existing ones, and the only new paid path (extension) goes through the budget. — check: `cd ../.. && ./apps/api/.venv/bin/python -m pytest apps/api/tests/test_focus_group_lin.py -q -k 'serialized'`
- [x] Student-created persona text and memo text are stored only in the focus-group jobs rows, not in the answer cache or logs. — check: `cd ../.. && ./apps/api/.venv/bin/python -m pytest apps/api/tests/test_focus_group_lin.py -q -k 'student_data_stays'`
- [x] (final) Nothing already working broke — full API suite (incl. the "AI interviews you" tests and the original focus-group tests: funnel, 3-person floor, cost preview, manual stages, cross-references). — check: `cd ../.. && ./apps/api/.venv/bin/python -m pytest apps/api/tests -q`
- [x] (final) Full web unit suite green and next build passes (with placeholder env: the build refuses to prerender without a backend origin and proxy secret). — check: `cd ../../apps/web && npm run test:unit && API_BASE_URL=https://api.example.invalid DEPLOYMENT_SHARED_SECRET=build-only-secret APP_ACCESS_PASSWORD=build-only-password ./node_modules/.bin/next build`

## Refuter round (2026-09-27) — legacy rooms first

- [x] Rooms stored before this branch (run in class 2026-09-23) get their concept/price exposure derived from the stage, as the old stage map gave it: the export says the concept and price WERE shown and where, a later early-stage round is post-exposure, the system prompt lists what was shown, the moderator may name the price, and neither can be revealed twice. — check: `cd ../.. && ./apps/api/.venv/bin/python -m pytest apps/api/tests/test_focus_group_lin.py -q -k 'legacy_room_exposure_derived_from_stage'`
- [x] A room row missing payload keys, or whose model left the catalog, still opens, lists and exports (every stored room has all four keys per git history; this is belt and braces). — check: `cd ../.. && ./apps/api/.venv/bin/python -m pytest apps/api/tests/test_focus_group_lin.py -q -k 'legacy_room_with_missing_payload_keys'`
- [x] A memo save on top of a newer saved memo is refused with 409 and a clear message; an untouched form is never persisted, and Export saves only real edits. — check: `cd ../.. && ./apps/api/.venv/bin/python -m pytest apps/api/tests/test_focus_group_lin.py -q -k 'memo_stale_write_refused' && cd plans/lin-classroom-fixes && sh ./webcheck.sh 'memo lost update'`
- [x] A concept-stage question without the concept shown is a probe and does not reach the concept stage (funnel and memo eligibility). — check: `cd ../.. && ./apps/api/.venv/bin/python -m pytest apps/api/tests/test_focus_group_lin.py -q -k 'concept_stage_question_without_the_concept' && cd plans/lin-classroom-fixes && sh ./webcheck.sh 'concept stage: a question'`
- [x] The out-of-character matcher flags only self-referential AI talk (not "I work on a large language model at my job" or "my persona at work"), uses its own exception type, and a flagged turn is billed once per click. — check: `cd ../.. && ./apps/api/.venv/bin/python -m pytest apps/api/tests/test_focus_group_lin.py -q -k 'flags_only_self_reference or billed_once_per_click'`
- [x] Extending with a stale revision is a 409 the page shows (a double-click of the extension just recorded is still a no-op). — check: `cd ../.. && ./apps/api/.venv/bin/python -m pytest apps/api/tests/test_focus_group_lin.py -q -k 'extend_with_stale_revision' && cd plans/lin-classroom-fixes && sh ./webcheck.sh 'extension: a refused'`

## Out of scope

- Real-participant recruitment or any claim that personas predict real customers.
- Instructor authoring UI for the concept card (the card is the instructor-approved text in code).

## Adversarial pass (own, in place of Sol/Codex — rate-limited)

Found and fixed: out-of-character check ran before the measured-cost budget check; export
listed the form's blank padding themes; a refused memo save aborted the whole export (now
exports the last saved memo and says so). Checked and left: stale-revision reveal is dropped
client-side only if the server ignored the ask (no charge); the student can still say a price
in words ("twenty-three thousand") — it is in the transcript, so "what participants saw" stays
visible, but it is not refused.

## Design calls made without asking (file — how to revert)

1. Before Reveal price, a dollar figure in ANY moderator question is refused, including at the price stage (old rule allowed it there). — `focus_group.py` ask_round `_MONEY` check; revert by re-adding the stage condition.
2. Concept facts reach participants only on a question that introduces the card (`reveal: "concept"`); a concept-stage question without it gets no product facts. The page pre-selects introduce when arriving at the concept stage. — `_check_reveal`, `page.tsx` stage onClick.
3. No concept image: none was found in the repo, so the card has description + specs only. — `CONCEPT_CARD`.
4. Roster names marked "fictional" (ACS PUMS has no names); usable outdoor space and willingness to add space are "unknown" for every roster persona. — `persona_seed.py persona_card`.
5. PA3.5 screener = homeowner/landowner, usable outdoor space, open to adding space (from Lin's fix-1 wording). — `persona_seed.py screener`.
6. Core vs probe is derived: the first question at a stage is core, later ones are probes; probes cannot spend a question a not-yet-asked stage needs. Extension capped at 4 extra probes per room. Asking the close question still completes the room (no probes after close). — `allowance`, `MAX_EXTENSION_ROUNDS`.
7. Out-of-character guard is a phrase list of self-referential AI talk only (occupational "language model"/"persona" talk passes); a flagged reply is charged once per click, withheld and retryable. — `_OUT_OF_CHARACTER`, `OutOfCharacterReply`.
8. Manual memo saves drafts in any room state (incl. cancelled), completeness checked live; answer options may optionally cite a turn. Turn IDs are `R<round>-<speaker>`, derived on read. — `manual_memo_check`, `turn_id`.
9. CSV export's first row is the rehearsal label (then the header). — `build_room_export`.
10. Student personas count toward the room's 3-seat minimum but every export says 0 real PA3.5 participants; IDs are S01–S20 per study; no delete endpoint. — `focus_group_personas.py`.
11. The AI memo button is now labelled optional feedback and sits after the manual form. — `page.tsx`.

## Unverified

- The live model actually obeys "no price has been shown — frame guesses as guesses" and "never mention being an AI"; tests prove only that the price is absent from every prompt and that flagged replies are withheld. — settle: one real room on staging through all five stages without Reveal price, read the transcript.
- The out-of-character phrase list has an acceptable false-positive rate on real replies. — settle: grep production `focus_group_failure ... code=out_of_character` logs after the first class.
- Rooms already in progress at deploy time: exposure is now derived from the stage (refuter round), proven on seeded legacy-shaped rows only. — settle: open one real pre-deploy room on staging after deploy and export it.
- Layout/readability of the new cards, side panel and forms in a real browser (only `next build` and source checks ran; no screenshot). — settle: click through /focus-group on a preview deploy.
- Deploy order: web and API ship separately; the new web sends `reveal`/`recipients`/`max_rounds=5+probes` which an old API ignores. — settle: deploy API first.
