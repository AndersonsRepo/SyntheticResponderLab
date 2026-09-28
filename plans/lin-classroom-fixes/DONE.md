Goal: Dr. Lin's five focus-group fixes (email after the 2026-09-23 class), shipped in the order 5 → 2 → 1 → 4 → 3 so each can deploy alone before PA3.5 (due Tue 2026-09-29). His acceptance checks are the spec. Keep: 5-stage funnel, 3-person minimum, cost preview, manual stage changes, cross-references between participants, and the "AI interviews you" mode.

Checks run from this directory. `P` = `cd ../.. && ./apps/api/.venv/bin/python -m pytest apps/api/tests/test_focus_group_lin.py -q`, `W` = `sh ./webcheck.sh`.

## Fix 5 — the debrief works without AI

- [ ] A student can write the PA3.5 memo by hand — three themes each with a linked quote, one surprise, at least three PA4 answer options tagged by question topic, one moderation improvement — and save it with no OpenRouter key configured and no model call. — check: `cd ../.. && ./apps/api/.venv/bin/python -m pytest apps/api/tests/test_focus_group_lin.py -q -k 'manual_memo_without_ai'`
- [ ] Every turn in the transcript has a turn ID that does not change when later rounds are asked or a failed turn is retried. — check: `cd ../.. && ./apps/api/.venv/bin/python -m pytest apps/api/tests/test_focus_group_lin.py -q -k 'stable_turn_ids'`
- [ ] Every cited quote links to an actual turn: a quote naming a turn that does not exist, a silent/unanswered turn, or text that is not in that turn is flagged and never exported as a linked quote. — check: `cd ../.. && ./apps/api/.venv/bin/python -m pytest apps/api/tests/test_focus_group_lin.py -q -k 'quote_must_link'`
- [ ] The student can export the transcript and the human-written memo (Markdown and CSV) without any AI memo ever succeeding; each quote in the export carries its turn ID, stage and round. — check: `cd ../.. && ./apps/api/.venv/bin/python -m pytest apps/api/tests/test_focus_group_lin.py -q -k 'export_manual_memo'`
- [ ] A failed AI memo attempt keeps the transcript and the student's memo intact, says why it failed and exactly what it charged, and the retry control says a retry is a new charge; the student can finish and export the manual memo without retrying. — check: `cd ../.. && ./apps/api/.venv/bin/python -m pytest apps/api/tests/test_focus_group_lin.py -q -k 'failed_ai_memo_preserves'`
- [ ] A half-finished memo is saved as a draft rather than lost, and the export marks it a draft and names what is missing. — check: `cd ../.. && ./apps/api/.venv/bin/python -m pytest apps/api/tests/test_focus_group_lin.py -q -k 'draft_memo'`
- [ ] Oversized or malformed memo input is refused with a plain message and stores nothing. — check: `cd ../.. && ./apps/api/.venv/bin/python -m pytest apps/api/tests/test_focus_group_lin.py -q -k 'memo_input_bounds'`
- [ ] Every export and the focus-group page carry "Synthetic rehearsal - not PA3.5 live fieldwork". — check: `cd ../.. && ./apps/api/.venv/bin/python -m pytest apps/api/tests/test_focus_group_lin.py -q -k 'rehearsal_label' && cd plans/lin-classroom-fixes && sh ./webcheck.sh 'rehearsal label'`
- [ ] On the page the manual memo form comes before the optional AI feedback, each answered turn shows its ID with a "Quote" control, and a saved draft is restored when the room is re-opened. — check: `sh ./webcheck.sh 'manual memo'`

## Fix 2 — the concept is shown and information is released on purpose

- [ ] A concept card (name, description, specifications, an editable read-aloud introduction, and a copy-as-text control for ChatGPT) sits directly above the question field, and its text is the exact stimulus the server gives participants. — check: `cd ../.. && ./apps/api/.venv/bin/python -m pytest apps/api/tests/test_focus_group_lin.py -q -k 'concept_card_is_the_stimulus' && cd plans/lin-classroom-fixes && sh ./webcheck.sh 'concept card'`
- [ ] Until the moderator introduces the concept, no product fact reaches any participant prompt — including a question asked at the concept stage without introducing it. — check: `cd ../.. && ./apps/api/.venv/bin/python -m pytest apps/api/tests/test_focus_group_lin.py -q -k 'concept_withheld_until_introduced'`
- [ ] The price never reaches the model before an explicit Reveal price — across all five stages, the system prompt and every replayed message. — check: `cd ../.. && ./apps/api/.venv/bin/python -m pytest apps/api/tests/test_focus_group_lin.py -q -k 'price_never_reaches_model_before_reveal'`
- [ ] Reveal price is refused until the concept was introduced and an unaided price question was answered; it then reaches every later prompt. — check: `cd ../.. && ./apps/api/.venv/bin/python -m pytest apps/api/tests/test_focus_group_lin.py -q -k 'reveal_price_order'`
- [ ] Before the price is revealed the moderator cannot anchor it either: a dollar figure in any question is refused with a message pointing at Reveal price. — check: `cd ../.. && ./apps/api/.venv/bin/python -m pytest apps/api/tests/test_focus_group_lin.py -q -k 'moderator_price_refused_before_reveal'`
- [ ] Participants are told what they have and have not been shown: before reveal they may guess a price but are instructed not to state one as the product's price. — check: `cd ../.. && ./apps/api/.venv/bin/python -m pytest apps/api/tests/test_focus_group_lin.py -q -k 'unshared_facts_are_unknown'`
- [ ] The student can state exactly what participants have seen at each stage: an "Information shared with participants" panel lists each stimulus and the round it was shown at, and the export records the stimulus text and reveal points. — check: `cd ../.. && ./apps/api/.venv/bin/python -m pytest apps/api/tests/test_focus_group_lin.py -q -k 'shared_info_in_export' && cd plans/lin-classroom-fixes && sh ./webcheck.sh 'shared with participants'`

## Fix 1 — who is in the room

- [ ] At recruitment every roster persona is an expandable card showing ID/name, household context, owner/renter, usable outdoor space, and willingness to consider more living/work space; each attribute is marked source-backed (ACS PUMS), fictional, or unknown, and missing facts read "Unknown". — check: `cd ../.. && ./apps/api/.venv/bin/python -m pytest apps/api/tests/test_focus_group_lin.py -q -k 'persona_cards' && cd plans/lin-classroom-fixes && sh ./webcheck.sh 'persona card'`
- [ ] Each card states, per PA3.5 screener criterion, whether the persona meets it, does not, or the data cannot tell — so the student can explain the choice before starting. — check: `cd ../.. && ./apps/api/.venv/bin/python -m pytest apps/api/tests/test_focus_group_lin.py -q -k 'screener'`
- [ ] While moderating, the same cards for the seated participants are available beside the discussion without leaving the room, including after re-opening it. — check: `cd ../.. && ./apps/api/.venv/bin/python -m pytest apps/api/tests/test_focus_group_lin.py -q -k 'room_carries_participant_cards' && cd plans/lin-classroom-fixes && sh ./webcheck.sh 'beside the discussion'`
- [ ] Showing cards does not change what the model is told about a roster persona. — check: `cd ../.. && ./apps/api/.venv/bin/python -m pytest apps/api/tests/test_focus_group_lin.py -q -k 'cards_do_not_change_prompt'`

## Fix 4 — targeted questions, silence, probes

- [ ] A question addressed only to P002 makes one call and produces one in-character answer; the others show as intentionally silent, not errors, and the room is not failed. — check: `cd ../.. && ./apps/api/.venv/bin/python -m pytest apps/api/tests/test_focus_group_lin.py -q -k 'targeted_question'`
- [ ] Silent participants never appear as missing answers — not in retry, the memo gate, or the export. — check: `cd ../.. && ./apps/api/.venv/bin/python -m pytest apps/api/tests/test_focus_group_lin.py -q -k 'silent_is_not_missing'`
- [ ] A reply that talks about being an AI, a model, prompts or instructions is withheld from the dialogue, its charge recorded, and the turn offered for retry; the prompt forbids such commentary. — check: `cd ../.. && ./apps/api/.venv/bin/python -m pytest apps/api/tests/test_focus_group_lin.py -q -k 'out_of_character'`
- [ ] Recipients naming someone not in the room, or nobody, are refused before any call. — check: `cd ../.. && ./apps/api/.venv/bin/python -m pytest apps/api/tests/test_focus_group_lin.py -q -k 'recipients_validated'`
- [ ] With the default allowance (5 core + 3 probes) a student can ask two probes in one stage and still complete all five stages. — check: `cd ../.. && ./apps/api/.venv/bin/python -m pytest apps/api/tests/test_focus_group_lin.py -q -k 'two_probes_and_full_funnel'`
- [ ] Probes can never use up the questions the remaining stages need; when probes run out the refusal says so and names the extension. — check: `cd ../.. && ./apps/api/.venv/bin/python -m pytest apps/api/tests/test_focus_group_lin.py -q -k 'probes_never_starve_the_funnel'`
- [ ] A budgeted extension adds probes only after the student authorizes its shown cost, and goes through the same run/class budget cap (refused when it would exceed it). — check: `cd ../.. && ./apps/api/.venv/bin/python -m pytest apps/api/tests/test_focus_group_lin.py -q -k 'extension'`
- [ ] The page has a Whole room / Selected participant(s) selector, separate "Ask follow-up" and "Next stage" controls, keeps manual stage buttons, shows remaining core questions and probes, and shows technical errors outside the participant dialogue. — check: `sh ./webcheck.sh 'recipient selector'`

## Fix 3 — student-created practice personas

- [ ] A student can create a persona through a structured form (household, tenure, outdoor space, current space use, willingness to consider more space, constraints, optional style), preview its card, save it, edit it (version goes up), and recruit it alongside roster personas. — check: `cd ../.. && ./apps/api/.venv/bin/python -m pytest apps/api/tests/test_focus_group_lin.py -q -k 'custom_persona_lifecycle'`
- [ ] "Duplicate and edit" starts from a roster persona's facts and records which one it came from; the copy is fictional, not source-backed. — check: `cd ../.. && ./apps/api/.venv/bin/python -m pytest apps/api/tests/test_focus_group_lin.py -q -k 'duplicate'`
- [ ] Once discussion starts the persona version is frozen: every call for that seat uses the same profile, and later edits do not change the running room. — check: `cd ../.. && ./apps/api/.venv/bin/python -m pytest apps/api/tests/test_focus_group_lin.py -q -k 'frozen'`
- [ ] The card and the export label it "Student-created fictional persona" with its origin and version, and say it is not a real PA3.5 participant. — check: `cd ../.. && ./apps/api/.venv/bin/python -m pytest apps/api/tests/test_focus_group_lin.py -q -k 'custom_export'`
- [ ] The form asks how the profile relates to the research question and never asks for a product opinion or desired findings; that reflection is not sent to the model. — check: `cd ../.. && ./apps/api/.venv/bin/python -m pytest apps/api/tests/test_focus_group_lin.py -q -k 'research_link'`
- [ ] A student's personas are visible only in their own study (another classroom device cannot list, edit or seat them). — check: `cd ../.. && ./apps/api/.venv/bin/python -m pytest apps/api/tests/test_focus_group_lin.py -q -k 'custom_persona_isolated'`
- [ ] Oversized or malformed persona input is refused with a plain message and stores nothing; a study cannot create unbounded personas. — check: `cd ../.. && ./apps/api/.venv/bin/python -m pytest apps/api/tests/test_focus_group_lin.py -q -k 'custom_persona_bounds'`
- [ ] The page has Create persona and Duplicate and edit beside the roster, a preview before saving, and the fictional label on the card. — check: `sh ./webcheck.sh 'create persona'`

## Cross-cutting

- [ ] Every new endpoint a student hits is on the classroom no-login allowlist, and nothing wider opened (other methods, suffixes, and encoded paths still refused). — check: `sh ./webcheck.sh 'classroom allowlist'`
- [ ] Every new mutating entry point is serialized like the existing ones, and the only new paid path (extension) goes through the budget. — check: `cd ../.. && ./apps/api/.venv/bin/python -m pytest apps/api/tests/test_focus_group_lin.py -q -k 'serialized'`
- [ ] Student-created persona text and memo text are stored only in the focus-group jobs rows, not in the answer cache or logs. — check: `cd ../.. && ./apps/api/.venv/bin/python -m pytest apps/api/tests/test_focus_group_lin.py -q -k 'student_data_stays'`
- [ ] (final) Nothing already working broke — full API suite (incl. the "AI interviews you" tests and the original focus-group tests: funnel, 3-person floor, cost preview, manual stages, cross-references). — check: `cd ../.. && ./apps/api/.venv/bin/python -m pytest apps/api/tests -q`
- [ ] (final) Full web unit suite green and `next build` passes. — check: `cd ../../apps/web && npm run test:unit && API_BASE_URL=https://api.example.invalid DEPLOYMENT_SHARED_SECRET=build-only-secret APP_ACCESS_PASSWORD=build-only-password ./node_modules/.bin/next build` (placeholder env: the build refuses to prerender without a backend origin and proxy secret)

## Out of scope

- Real-participant recruitment or any claim that personas predict real customers.
- Instructor authoring UI for the concept card (the card is the instructor-approved text in code).
