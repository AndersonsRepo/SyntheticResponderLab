# Brief — simulated focus group, the rehearsal for PA3.5

Source: Dr. Lin's email 2026-09-17 12:42 PM, plus his course hub
(`https://lyf718718.github.io/mktg-research-sim/hub/`). Vault: `LRN-20260917-201`.

## What he asked for, in his words

> "The student interviewer talking to simulated personas reacting to one another is most
> important. The goal is to allow students to gain experience with the training process
> before they moderate real people (homeowners or landowners who fit the target market of
> neo-smart living) who talk to each other."

So the student moderates and the personas react to each other. Both halves matter: a page
where personas answer in isolation is the interview section we already have, and a page
where the AI interviews the student is a different feature he did not ask for.

## Why the shape is not ours to choose

This is practice for **PA3.5**, a graded assignment. Students run a real Zoom focus group
with at least three recruited participants — his words, "3 is the floor — a group, not an
interview" — for 20–30 minutes on a fixed funnel:

> icebreaker → general space needs → the Tahoe Mini concept → price reactions (don't anchor
> first) → close

They hand in a screener table, a one-page memo carrying **themes, one surprise, and at least
three closed-ended answer options phrased in participant language**, the recording, the
moderator's guide as run, and an AI reflection.

The simulated version should mirror that: same three-persona floor, same five stages, same
memo fields. If it doesn't, it isn't rehearsal for anything.

## Dates

Round 6 (moderator's guide, in class) is **Wed Sep 23**. PA3.5 fields **Sep 24–27**. Lin
asked for this by **Tue Sep 22**. One day of slack between the app working and students
moderating real people.

## What already exists — reuse it, do not rebuild

- `standalone_interview.py` — session validation, model validation, `remember_answer`,
  batch jobs, regeneration guards, usage accounting.
- `interview_cache.py` — durable cached answers keyed on persona + question + model.
- `llm_budget.py` — `RUN_BUDGET_USD` ($0.75), class ceiling, preflight and measured-cost
  enforcement. Every provider call already records its cost even when the response is
  unusable; three separate bugs were fixed to get that right. Do not route around it.
- `standalone_themes.py` — 3–6 themes with a verbatim quote, scoped to the student's own
  session, cached so re-opening is free.
- `apps/web/src/app/interview/page.tsx` — the stepper, the expensive-model checkbox, the
  batch cost confirmation, the back buttons.

## Explicitly NOT in scope

- AI-interviews-the-student. Lin did not ask for it.
- Any change to the main gated workflow, `prerecord_interviews.py`, the budget constants,
  or the cost report and its tests.
- A teacher/student role system. He asked for a checkbox.
- Round 7. He cited it as an example but it is not published; ask him rather than guess.
