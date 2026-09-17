Goal: a student can moderate a focus group of simulated personas who react to each other, following the same funnel and producing the same memo fields as PA3.5, without being able to spend real money by accident.

## Outcomes

- [ ] A student can start a focus group with at least three personas and cannot start one with fewer — the control refuses two, and the refusal says why. — check: `cd ../../apps/web && npm run test:unit`
- [ ] The student types the question. Every persona in the room answers it, and each answer is attributed to a named persona the student picked. — check: `cd ../.. && ./apps/api/.venv/bin/python -m pytest apps/api/tests/test_focus_group.py -q -k 'every_persona_answers_attributed'`
- [ ] From the second question onward, each persona is given the other personas' answers to the earlier questions, so a persona can agree, disagree, or build on what another said. A persona never sees its own future turns or another room's transcript. — check: `cd ../.. && ./apps/api/.venv/bin/python -m pytest apps/api/tests/test_focus_group.py -q -k 'personas_see_each_other_not_other_rooms'`
- [ ] The session walks the five PA3.5 stages in order — icebreaker, general space needs, the Tahoe Mini concept, price reactions, close — and the student can see which stage they are in and move back to a previous one without losing answers already collected. — check: `cd ../../apps/web && npm run test:unit`
- [ ] Price is never anchored first: the app does not surface a price to the personas before the price-reactions stage. — check: `cd ../.. && ./apps/api/.venv/bin/python -m pytest apps/api/tests/test_focus_group.py -q -k 'price_not_anchored_before_stage'`
- [ ] At the end the student gets the PA3.5 memo fields off their own transcript: themes with a verbatim quote each, one surprise, and at least three closed-ended answer options phrased in participant language. — check: `cd ../.. && ./apps/api/.venv/bin/python -m pytest apps/api/tests/test_focus_group.py -q -k 'memo_fields'`
- [ ] Every quote and every answer option is verbatim from a transcript turn the student can locate, not paraphrased or invented. — check: `cd ../.. && ./apps/api/.venv/bin/python -m pytest apps/api/tests/test_focus_group.py -q -k 'verbatim_traceable'`
- [ ] Before a focus group starts, the student sees what it will cost — personas times rounds, not one call — and confirms it. Dismissing the confirmation starts nothing and spends nothing. — check: `cd ../../apps/web && npm run test:unit`
- [ ] A focus group cannot reach an expensive model without the expensive-model box checked; raising the persona count alone can never get there. — check: `cd ../../apps/web && npm run test:unit`
- [ ] Focus-group calls spend through the existing run and class budgets, and a billed-but-unusable response still records its cost. A budget stop leaves every answer that was actually charged visible and in order. — check: `cd ../.. && ./apps/api/.venv/bin/python -m pytest apps/api/tests/test_focus_group.py -q -k 'budget'`
- [ ] Re-opening a finished focus group, or its memo, makes no new paid call. — check: `cd ../.. && ./apps/api/.venv/bin/python -m pytest apps/api/tests/test_focus_group.py -q -k 'cached'`
- [ ] A provider failure mid-room leaves the answers already collected readable and offers an explicit retry, rather than an empty success or a stuck spinner. — check: `cd ../.. && ./apps/api/.venv/bin/python -m pytest apps/api/tests/test_focus_group.py -q -k 'partial_failure_recoverable'`
- [ ] The student can export the transcript and the memo for submission, with each turn attributed to its persona. — check: `cd ../.. && ./apps/api/.venv/bin/python -m pytest apps/api/tests/test_focus_group.py -q -k 'export'`
- [ ] Students in classroom no-login mode can run a focus group and get its memo without hitting a login wall. — check: `cd ../../apps/web && npm run test:unit`
- [ ] Nothing already working broke — the interview section, model comparison, follow-up chat, batch and regenerate controls, standalone themes and the pre-recorded interviews page all still work. — check: `cd ../../apps/web && npm run test:unit && cd ../.. && ./apps/api/.venv/bin/python -m pytest apps/api/tests/ -q`

## Don't touch

- the main gated workflow and its insights
- `scripts/prerecord_interviews.py`
- the budget constants, `enforce_run_preflight`, `enforce_measured_cost`
- `docs/cost-report.md` and `apps/api/tests/test_cost_report.py`
- no teacher/student role or permission system — Lin asked for a checkbox
- do not build AI-interviews-the-student; out of scope
