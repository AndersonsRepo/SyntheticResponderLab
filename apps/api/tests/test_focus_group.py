"""The simulated focus group: the PA3.5 rehearsal, in its own lane."""
import json
import logging
import re
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from src.persistence.models import InterviewTurn, Job, Persona, Study
from src.persistence.persona_seed import load_persona_seed_rows
from src.services import focus_group as fg
from src.services.exceptions import TransientProviderError
from src.services.interview_cache import InterviewAnswer

MODEL = "openai/gpt-4o-mini"
THREE = ["P001", "P002", "P003"]
FUNNEL = [
    ("icebreaker", "Tell me who lives with you and what a weekday looks like."),
    ("space_needs", "Where in your home do you run out of room?"),
    ("concept", "What is your first reaction to a backyard studio like this?"),
    ("price_reactions", "What would you expect something like this to cost, and how does $23,000 land?"),
    ("close", "Anything we should have asked and did not?"),
]


def _answer_text(persona_id, question):
    return (f"{persona_id} here. On '{question}' I would say I use the garage as an office and "
            f"it is honestly too cold in winter.")


def _memo_from_transcript(transcript):
    """A well-behaved memo model: every quote copied out of the transcript it was given."""
    said = re.findall(r"^(P\d+): (.+)$", transcript, re.M)
    themes = [{"label": f"Theme {i + 1}", "synthesis": "Participants converge here.",
               "quote": text[:40], "persona_id": pid, "sentiment": "neutral"}
              for i, (pid, text) in enumerate(said[:3])]
    return json.dumps({
        "themes": themes,
        "surprise": {"summary": "The winter complaint was unprompted.",
                     "quote": said[0][1][-30:], "persona_id": said[0][0]},
        "answer_options": [{"text": text[:25], "persona_id": pid} for pid, text in said[:3]],
    })


@pytest.fixture
def room(client, db_session, monkeypatch):
    db_session.add_all(Persona(**row) for row in load_persona_seed_rows())
    db_session.commit()
    study_id = client.post("/api/v1/studies", json={}).json()["data"]["study"]["study_id"]
    client.app.state.settings.openrouter_api_key = "stub"
    calls = []
    behavior = {"fail": None, "unusable": False, "memo": _memo_from_transcript}

    def provider(**kw):
        calls.append(kw)
        system = kw["messages"][0]["content"]
        if "JSON object" in system:
            transcript = kw["messages"][-1]["content"]
            return InterviewAnswer(text=behavior["memo"](transcript), model=kw["model"],
                                   tokens_in=50, tokens_out=50, cost_usd=Decimal(".002"))
        persona_id = re.search(r"participant (P\d+)", system).group(1)
        if behavior["unusable"]:
            raise TransientProviderError("empty completion", measured_usage=InterviewAnswer(
                text="", model=kw["model"], tokens_in=7, tokens_out=0, cost_usd=Decimal(".004")))
        if behavior["fail"] and behavior["fail"](persona_id):
            raise RuntimeError(f"provider exploded for {persona_id}")
        question = kw["messages"][-1]["content"].removeprefix("Moderator: ")
        return InterviewAnswer(text=_answer_text(persona_id, question), model=kw["model"],
                               tokens_in=10, tokens_out=5, cost_usd=Decimal(".001"))

    monkeypatch.setattr("src.services.interview_service._call_openrouter_messages", provider)
    return client, study_id, calls, behavior


def start(client, study_id, **overrides):
    payload = {"request_id": str(uuid4()), "persona_ids": list(THREE), "model": MODEL,
               "max_rounds": 8, **overrides}
    return client.post(f"/api/v1/studies/{study_id}/interview/focus-group/rooms", json=payload)


def ask(client, study_id, room, stage=None, question=None, **extra):
    body = {"revision": room["revision"], **extra}
    if stage:
        body["stage"] = stage
    if question:
        body["question"] = question
    return client.post(
        f"/api/v1/studies/{study_id}/interview/focus-group/rooms/{room['room_id']}/ask", json=body)


def walk(client, study_id, room, stages=FUNNEL):
    for stage, question in stages:
        response = ask(client, study_id, room, stage=stage, question=question)
        assert response.status_code == 200, response.text
        room = response.json()["data"]["room"]
    return room


# --- the room itself --------------------------------------------------------

def test_every_persona_answers_attributed_to_a_named_persona(room):
    client, study_id, calls, _ = room
    started = start(client, study_id).json()["data"]["room"]
    asked = ask(client, study_id, started, stage="icebreaker",
                question=FUNNEL[0][1]).json()["data"]["room"]
    answers = asked["rounds"][0]["answers"]
    assert [a["persona_id"] for a in answers] == THREE
    assert all(a["status"] == "answered" and a["persona_id"] in a["text"] for a in answers)
    assert len(calls) == 3


def test_fewer_than_three_personas_is_refused_before_any_call(room):
    client, study_id, calls, _ = room
    response = start(client, study_id, persona_ids=["P001", "P002"])
    assert response.status_code == 400
    assert "at least 3" in response.json()["error"]["message"]
    assert calls == []


def test_duplicate_personas_refused_so_the_memo_can_tell_speakers_apart(room):
    client, study_id, calls, _ = room
    response = start(client, study_id, persona_ids=["P001", "P001", "P002"])
    assert response.status_code == 400
    assert "one seat" in response.json()["error"]["message"]
    assert calls == []


@pytest.mark.parametrize("change", [
    {"persona_ids": [f"P{i:03d}" for i in range(1, 10)]},
    {"max_rounds": 13}, {"max_rounds": 0}, {"max_rounds": True}, {"max_rounds": "8"},
    {"model": "anthropic/claude-sonnet-4.5"},
    {"persona_ids": ["P001", "P002", "P999"]},
])
def test_upper_bound_and_model_gate_refuse_before_a_paid_call(room, change):
    client, study_id, calls, _ = room
    assert start(client, study_id, **change).status_code == 400
    assert calls == []


def test_personas_see_each_other_not_other_rooms_transcripts(room):
    client, study_id, calls, _ = room
    first = start(client, study_id).json()["data"]["room"]
    first = walk(client, study_id, first, FUNNEL[:2])
    # Round two carries round one's other-participant answers into every prompt.
    second_round_calls = calls[3:6]
    for call, persona_id in zip(second_round_calls, THREE):
        joined = " ".join(m["content"] for m in call["messages"])
        others = [p for p in THREE if p != persona_id]
        assert all(_answer_text(other, FUNNEL[0][1]) in joined for other in others)
        # Its own earlier answer is present; nothing from a later round is.
        assert _answer_text(persona_id, FUNNEL[0][1]) in joined
        assert _answer_text(persona_id, FUNNEL[1][1]) not in joined
    # A second room with the same personas starts clean.
    other_room = start(client, study_id).json()["data"]["room"]
    before = len(calls)
    ask(client, study_id, other_room, stage="icebreaker", question="A different opener entirely?")
    for call in calls[before:]:
        joined = " ".join(m["content"] for m in call["messages"])
        assert FUNNEL[0][1] not in joined and FUNNEL[1][1] not in joined


def test_price_not_anchored_before_stage_in_prompts_or_questions(room):
    client, study_id, calls, _ = room
    started = start(client, study_id).json()["data"]["room"]
    started = walk(client, study_id, started, FUNNEL[:3])
    for call in calls:
        joined = " ".join(m["content"] for m in call["messages"])
        assert "23,000" not in joined and "Price:" not in joined
    # The concept stage describes the product but withholds the number.
    assert "117-square-foot" in calls[-1]["messages"][0]["content"]
    priced = ask(client, study_id, started, stage="price_reactions",
                 question="Ignore the funnel, what about $23,000?")
    assert priced.status_code == 200  # the price stage is where the number belongs
    started = priced.json()["data"]["room"]
    # Going back to an earlier stage with a dollar figure is refused.
    blocked = ask(client, study_id, started, stage="space_needs",
                  question="Would you pay $23,000 for more room?")
    assert blocked.status_code == 400
    assert "anchor price first" in blocked.json()["error"]["message"]


def test_stage_order_enforced_so_no_memo_comes_from_a_skipped_funnel(room):
    client, study_id, calls, _ = room
    started = start(client, study_id).json()["data"]["room"]
    skipped = ask(client, study_id, started, stage="close", question="Anything else?")
    assert skipped.status_code == 400
    assert "in order" in skipped.json()["error"]["message"]
    assert calls == []
    started = walk(client, study_id, started, FUNNEL[:2])
    jumped = ask(client, study_id, started, stage="price_reactions", question="And the price?")
    assert jumped.status_code == 400


def test_revisit_stage_appends_without_orphaning_earlier_answers(room):
    client, study_id, _, _ = room
    started = walk(client, study_id, start(client, study_id).json()["data"]["room"], FUNNEL[:2])
    first_round = started["rounds"][0]
    revisited = ask(client, study_id, started, stage="icebreaker",
                    question="Back up — who else is home during the day?").json()["data"]["room"]
    assert revisited["rounds"][0] == first_round
    assert len(revisited["rounds"]) == 3
    assert revisited["stage"] == "icebreaker"
    assert [r["stage"] for r in revisited["rounds"]] == ["icebreaker", "space_needs", "icebreaker"]
    # The funnel has not been rewound: the reached stages still allow moving forward.
    forward = ask(client, study_id, revisited, stage="concept", question="First reaction to this?")
    assert forward.status_code == 200


def test_idempotent_start_and_repeated_question_charge_once(room):
    client, study_id, calls, _ = room
    request_id = str(uuid4())
    first = start(client, study_id, request_id=request_id).json()["data"]["room"]
    again = start(client, study_id, request_id=request_id).json()["data"]["room"]
    assert again["room_id"] == first["room_id"]
    assert db_rooms(client, study_id) == 1
    asked = ask(client, study_id, first, stage="icebreaker", question=FUNNEL[0][1]).json()["data"]["room"]
    assert len(calls) == 3
    # The same revision submitted twice is the double click, not a second round.
    repeat = ask(client, study_id, first, stage="icebreaker", question=FUNNEL[0][1]).json()["data"]["room"]
    assert len(calls) == 3
    assert repeat["rounds"] == asked["rounds"]
    assert repeat["revision"] == asked["revision"]


def db_rooms(client, study_id):
    return len(client.get(f"/api/v1/studies/{study_id}/interview/focus-group/rooms").json()["data"]["rooms"])


def test_concurrent_submissions_do_not_interleave_two_rounds(room):
    client, study_id, calls, _ = room
    started = start(client, study_id).json()["data"]["room"]
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(
            lambda q: ask(client, study_id, started, stage="icebreaker", question=q),
            [FUNNEL[0][1], "A completely different second question?"]))
    assert all(r.status_code == 200 for r in responses)
    assert len(calls) == 3
    final = client.get(
        f"/api/v1/studies/{study_id}/interview/focus-group/rooms/{started['room_id']}"
    ).json()["data"]["room"]
    assert len(final["rounds"]) == 1
    assert [a["persona_id"] for a in final["rounds"][0]["answers"]] == THREE


def test_resume_after_a_refresh_returns_the_same_room_and_stage(room):
    client, study_id, calls, _ = room
    started = walk(client, study_id, start(client, study_id).json()["data"]["room"], FUNNEL[:3])
    spent = len(calls)
    reopened = client.get(
        f"/api/v1/studies/{study_id}/interview/focus-group/rooms/{started['room_id']}"
    ).json()["data"]["room"]
    assert reopened["rounds"] == started["rounds"]
    assert reopened["stage"] == "concept"
    assert reopened["session_usage"]["cost_usd"] == started["session_usage"]["cost_usd"]
    assert len(calls) == spent
    assert client.get(
        f"/api/v1/studies/{study_id}/interview/focus-group/rooms").json()["data"]["rooms"][0]["room_id"] == started["room_id"]


def test_cancel_keeps_charged_answers_and_makes_no_further_paid_call(room):
    client, study_id, calls, _ = room
    started = walk(client, study_id, start(client, study_id).json()["data"]["room"], FUNNEL[:2])
    spent = len(calls)
    cancelled = client.post(
        f"/api/v1/studies/{study_id}/interview/focus-group/rooms/{started['room_id']}/cancel"
    ).json()["data"]["room"]
    assert cancelled["status"] == "cancelled"
    assert cancelled["rounds"] == started["rounds"]
    blocked = ask(client, study_id, cancelled, stage="concept", question="One more?")
    assert blocked.status_code == 409
    assert "cancelled" in blocked.json()["error"]["message"]
    assert len(calls) == spent


# --- failure, retry, budget -------------------------------------------------

def test_partial_failure_recoverable_and_the_missing_persona_named(room, caplog):
    client, study_id, calls, behavior = room
    started = start(client, study_id).json()["data"]["room"]
    behavior["fail"] = lambda persona_id: persona_id == "P002"
    with caplog.at_level(logging.WARNING, logger="src.services.focus_group"):
        failed = ask(client, study_id, started, stage="icebreaker",
                     question=FUNNEL[0][1]).json()["data"]["room"]
    assert failed["status"] == "failed"
    statuses = {a["persona_id"]: a["status"] for a in failed["rounds"][0]["answers"]}
    assert statuses == {"P001": "answered", "P002": "missing", "P003": "answered"}
    assert failed["error"]["missing"] == [{"round": 0, "persona_id": "P002"}]
    assert "Retry" in failed["error"]["message"]
    assert failed["complete"] is False
    assert len(calls) == 3


def test_failure_log_carries_room_stage_persona_and_provider_error(room, caplog):
    client, study_id, _, behavior = room
    started = start(client, study_id).json()["data"]["room"]
    behavior["fail"] = lambda persona_id: persona_id == "P002"
    with caplog.at_level(logging.WARNING, logger="src.services.focus_group"):
        ask(client, study_id, started, stage="icebreaker", question=FUNNEL[0][1])
    record = next(r for r in caplog.records if r.message.startswith("focus_group_failure"))
    line = record.getMessage()
    assert started["room_id"] in line and "stage=icebreaker" in line
    assert "persona=P002" in line and "exploded" in line


def test_retry_only_missing_turns_without_recharging_collected_answers(room):
    client, study_id, calls, behavior = room
    started = start(client, study_id).json()["data"]["room"]
    behavior["fail"] = lambda persona_id: persona_id == "P002"
    failed = ask(client, study_id, started, stage="icebreaker",
                 question=FUNNEL[0][1]).json()["data"]["room"]
    kept = [a["text"] for a in failed["rounds"][0]["answers"] if a["status"] == "answered"]
    cost_after_failure = Decimal(failed["session_usage"]["cost_usd"])
    behavior["fail"] = None
    retried = ask(client, study_id, failed, retry=True).json()["data"]["room"]
    assert retried["status"] == "running"
    assert len(calls) == 4  # only P002 was re-run
    assert Decimal(retried["session_usage"]["cost_usd"]) == cost_after_failure + Decimal(".001")
    answers = retried["rounds"][0]["answers"]
    assert [a["status"] for a in answers] == ["answered"] * 3
    assert [a["text"] for a in answers if a["persona_id"] != "P002"] == kept
    assert len(retried["rounds"]) == 1


def test_timeout_is_bounded_and_surfaces_as_a_retryable_failure(room):
    client, study_id, calls, behavior = room
    started = start(client, study_id).json()["data"]["room"]
    ask(client, study_id, started, stage="icebreaker", question=FUNNEL[0][1])
    assert all(call["timeout"] == fg.PROVIDER_TIMEOUT_SECONDS for call in calls)
    assert all(call["max_attempts"] == 1 for call in calls)
    assert fg.PROVIDER_TIMEOUT_SECONDS <= 120

    behavior["fail"] = lambda persona_id: True
    room_after = client.get(
        f"/api/v1/studies/{study_id}/interview/focus-group/rooms/{started['room_id']}"
    ).json()["data"]["room"]
    timed_out = ask(client, study_id, room_after, stage="space_needs",
                    question=FUNNEL[1][1]).json()["data"]["room"]
    assert timed_out["status"] == "failed"
    assert len(timed_out["error"]["missing"]) == 3
    assert "Retry" in timed_out["error"]["message"]


def test_budget_stop_records_every_charge_and_says_so_in_plain_words(room):
    client, study_id, calls, _ = room
    client.app.state.settings.llm_budget_usd = Decimal(".0018")
    started = start(client, study_id, max_rounds=1).json()["data"]["room"]
    stopped = ask(client, study_id, started, stage="icebreaker",
                  question=FUNNEL[0][1]).json()["data"]["room"]
    assert stopped["status"] == "budget_stopped"
    assert stopped["error"]["code"] == "quota_exceeded"
    message = stopped["error"]["message"]
    assert "budget stopped this room" in message and "remains" in message
    assert "still" in message
    # Every call that was actually charged is visible, in order, and accounted for.
    answered = [a for a in stopped["rounds"][0]["answers"] if a["status"] == "answered"]
    assert [a["persona_id"] for a in answered] == THREE[:len(answered)]
    assert Decimal(stopped["session_usage"]["cost_usd"]) == Decimal(".001") * len(calls)
    assert stopped["error"]["stage"] == "icebreaker"


def test_budget_records_a_billed_but_unusable_response(room):
    client, study_id, calls, behavior = room
    started = start(client, study_id).json()["data"]["room"]
    behavior["unusable"] = True
    failed = ask(client, study_id, started, stage="icebreaker",
                 question=FUNNEL[0][1]).json()["data"]["room"]
    assert failed["status"] == "failed"
    assert len(calls) == 3
    assert all(a["status"] == "missing" for a in failed["rounds"][0]["answers"])
    # The provider billed for three unusable responses; all three are on the ledger.
    assert Decimal(failed["session_usage"]["cost_usd"]) == Decimal(".012")


def test_actual_vs_estimated_cost_is_visible_after_the_run(room):
    client, study_id, _, _ = room
    started = start(client, study_id).json()["data"]["room"]
    estimated = Decimal(started["estimated_cost_usd"])
    assert estimated == fg.estimate_room_cost_usd(persona_count=3, rounds=8, model_id=MODEL)
    assert estimated > 0
    finished = walk(client, study_id, started)
    assert Decimal(finished["session_usage"]["cost_usd"]) == Decimal(".015")
    assert Decimal(finished["estimated_cost_usd"]) == estimated
    assert finished["status"] == "completed"


def test_estimate_formula_matches_the_web_pre_start_estimate():
    source = Path(__file__).resolve().parents[3] / "apps/web/src/lib/focus-group.ts"
    text = source.read_text()
    assert f"ESTIMATED_PROMPT_TOKENS_PER_TURN = {fg.ESTIMATED_PROMPT_TOKENS_PER_TURN}" in text
    assert f"ESTIMATED_COMPLETION_TOKENS_PER_TURN = {fg.ESTIMATED_COMPLETION_TOKENS_PER_TURN}" in text
    assert f"MIN_PERSONAS = {fg.MIN_PERSONAS}" in text
    assert f"MAX_PERSONAS = {fg.MAX_PERSONAS}" in text
    assert f"MAX_ROUNDS = {fg.MAX_ROUNDS}" in text
    assert all(f'"{stage}"' in text for stage in fg.STAGES)


def test_cached_replay_of_the_same_room_makes_no_new_paid_call(room):
    client, study_id, calls, _ = room
    finished = walk(client, study_id, start(client, study_id).json()["data"]["room"])
    spent = len(calls)
    # Re-opening the finished room and its memo view costs nothing.
    client.get(f"/api/v1/studies/{study_id}/interview/focus-group/rooms/{finished['room_id']}")
    client.get(f"/api/v1/studies/{study_id}/interview/focus-group/rooms/{finished['room_id']}/memo")
    assert len(calls) == spent
    # An identical room replays out of the durable answer cache, free.
    replay = walk(client, study_id, start(client, study_id).json()["data"]["room"])
    assert len(calls) == spent
    assert Decimal(replay["session_usage"]["cost_usd"]) == 0
    assert [r["answers"] for r in replay["rounds"]] == [r["answers"] for r in finished["rounds"]]


# --- memo -------------------------------------------------------------------

def test_memo_fields_are_themes_one_surprise_and_three_answer_options(room):
    client, study_id, _, _ = room
    finished = walk(client, study_id, start(client, study_id).json()["data"]["room"])
    view = memo(client, study_id, finished)
    assert view["eligible"] is True
    written = write_memo(client, study_id, finished, view)
    saved = written["saved"]
    assert fg.MEMO_MIN_THEMES <= len(saved["themes"]) <= fg.MEMO_MAX_THEMES
    assert all(t["quote"] and t["persona_id"] and t["sentiment"] for t in saved["themes"])
    assert saved["surprise"]["summary"] and saved["surprise"]["quote"]
    assert len(saved["answer_options"]) >= fg.MEMO_MIN_ANSWER_OPTIONS
    assert written["available"] is True


def memo(client, study_id, room_state):
    return client.get(
        f"/api/v1/studies/{study_id}/interview/focus-group/rooms/{room_state['room_id']}/memo"
    ).json()["data"]["memo"]


def write_memo(client, study_id, room_state, view, **extra):
    response = client.post(
        f"/api/v1/studies/{study_id}/interview/focus-group/rooms/{room_state['room_id']}/memo",
        json={"revision": view["revision"], "authorize_charge": True, **extra})
    assert response.status_code == 200, response.text
    return response.json()["data"]["memo"]


def test_verbatim_traceable_quotes_and_options_are_located_in_the_transcript(room):
    client, study_id, _, behavior = room
    finished = walk(client, study_id, start(client, study_id).json()["data"]["room"])
    saved = write_memo(client, study_id, finished, memo(client, study_id, finished))["saved"]
    said = {(a["persona_id"], r["index"]): a["text"]
            for r in finished["rounds"] for a in r["answers"]}
    for item in [*saved["themes"], *saved["answer_options"], saved["surprise"]]:
        where = item["located_at"]
        source = said[(where["persona_id"], where["round"])]
        assert item["quote" if "quote" in item else "text"] in source
        assert where["stage"] in fg.STAGES
    # An invented quote is refused rather than saved.
    behavior["memo"] = lambda transcript: json.dumps({
        "themes": [{"label": "Made up", "synthesis": "Nobody said this.",
                    "quote": "I would pay double on the spot.", "persona_id": "P001",
                    "sentiment": "positive"}] * 3,
        "surprise": {"summary": "s", "quote": "I would pay double on the spot.", "persona_id": "P001"},
        "answer_options": [{"text": "Never said", "persona_id": "P001"}] * 3})
    other = walk(client, study_id, start(client, study_id).json()["data"]["room"])
    rejected = write_memo(client, study_id, other, memo(client, study_id, other))
    assert rejected["available"] is False
    assert rejected["saved"]["themes"] is None
    assert "could not be validated" in rejected["saved"]["message"]


def test_memo_requires_enough_room_and_says_so_instead_of_padding(room):
    client, study_id, calls, behavior = room
    started = walk(client, study_id, start(client, study_id).json()["data"]["room"], FUNNEL[:2])
    view = memo(client, study_id, started)
    assert view["eligible"] is False
    assert "Tahoe Mini concept" in view["message"] and "Price reactions" in view["message"]
    spent = len(calls)
    assert write_memo(client, study_id, started, view)["saved"] is None
    assert len(calls) == spent  # refusing costs nothing
    # Reaching concept and price but with holes in the room is also refused, in plain words.
    behavior["fail"] = lambda persona_id: persona_id == "P003"
    thin = walk(client, study_id, start(client, study_id).json()["data"]["room"],
                [(stage, f"{q} Second room.") for stage, q in FUNNEL])
    thin_view = memo(client, study_id, thin)
    assert thin_view["eligible"] is False
    assert f"at least {fg.MEMO_MIN_ANSWERS}" in thin_view["message"]


def test_memo_is_cached_and_reopening_it_charges_nothing(room):
    client, study_id, calls, _ = room
    finished = walk(client, study_id, start(client, study_id).json()["data"]["room"])
    view = memo(client, study_id, finished)
    write_memo(client, study_id, finished, view)
    spent = len(calls)
    again = write_memo(client, study_id, finished, view)
    assert len(calls) == spent
    assert again["available"] is True


# --- lists, lanes, export, isolation ---------------------------------------

def test_room_list_lifecycle_reopen_export_and_delete(room):
    client, study_id, _, _ = room
    finished = walk(client, study_id, start(client, study_id).json()["data"]["room"])
    rooms = client.get(f"/api/v1/studies/{study_id}/interview/focus-group/rooms").json()["data"]["rooms"]
    assert [r["room_id"] for r in rooms] == [finished["room_id"]]
    assert client.get(
        f"/api/v1/studies/{study_id}/interview/focus-group/rooms/{finished['room_id']}").status_code == 200
    assert client.post(
        f"/api/v1/studies/{study_id}/interview/focus-group/rooms/{finished['room_id']}/export",
        json={"format": "markdown"}).status_code == 200
    assert client.delete(
        f"/api/v1/studies/{study_id}/interview/focus-group/rooms/{finished['room_id']}").status_code == 200
    assert client.get(f"/api/v1/studies/{study_id}/interview/focus-group/rooms").json()["data"]["rooms"] == []
    assert client.get(
        f"/api/v1/studies/{study_id}/interview/focus-group/rooms/{finished['room_id']}").status_code == 404


def test_deleting_a_room_keeps_its_spend_on_the_class_ledger(room, db_session):
    client, study_id, _, _ = room
    finished = walk(client, study_id, start(client, study_id).json()["data"]["room"])
    client.delete(f"/api/v1/studies/{study_id}/interview/focus-group/rooms/{finished['room_id']}")
    charged = db_session.scalar(select(func.count()).select_from(InterviewTurn)
                                .where(InterviewTurn.session_id == finished["room_id"]))
    assert charged == 15


def test_separate_lane_never_leaks_into_the_interview_section(room, db_session):
    client, study_id, _, _ = room
    finished = walk(client, study_id, start(client, study_id).json()["data"]["room"])
    assert client.get(f"/api/v1/studies/{study_id}/interview/batches").json()["data"]["batches"] == []
    assert client.get(
        f"/api/v1/studies/{study_id}/interview/batches/{finished['room_id']}").status_code == 404
    assert client.get(
        f"/api/v1/studies/{study_id}/interview/batches/{finished['room_id']}/themes").status_code == 404
    assert client.get(f"/api/v1/studies/{study_id}/interview/runs/latest").json()["data"]["interview_run"] is None
    assert db_session.scalar(select(Job.job_type).where(Job.public_id == finished["room_id"])) == "focus_group_room"
    # Focus-group turns carry no transcript text, so no interview corpus can pick them up.
    texts = db_session.scalars(select(InterviewTurn.text)
                               .where(InterviewTurn.session_id == finished["room_id"])).all()
    assert set(texts) == {""}


def test_export_attributes_every_turn_to_its_persona(room):
    client, study_id, _, _ = room
    finished = walk(client, study_id, start(client, study_id).json()["data"]["room"])
    write_memo(client, study_id, finished, memo(client, study_id, finished))
    exported = client.post(
        f"/api/v1/studies/{study_id}/interview/focus-group/rooms/{finished['room_id']}/export",
        json={"format": "markdown"}).json()["data"]["export"]
    assert exported["complete"] is True
    assert "INCOMPLETE" not in exported["content"]
    for persona_id in THREE:
        assert f"**{persona_id}:**" in exported["content"]
    for _, question in FUNNEL:
        assert question in exported["content"]
    assert "### One surprise" in exported["content"]
    assert exported["filename"].endswith(".md")
    csv_export = client.post(
        f"/api/v1/studies/{study_id}/interview/focus-group/rooms/{finished['room_id']}/export",
        json={"format": "csv"}).json()["data"]["export"]
    assert "P001" in csv_export["content"] and csv_export["filename"].endswith(".csv")


def test_export_of_an_unfinished_room_is_marked_incomplete(room):
    client, study_id, _, behavior = room
    started = start(client, study_id).json()["data"]["room"]
    behavior["fail"] = lambda persona_id: persona_id == "P003"
    failed = ask(client, study_id, started, stage="icebreaker",
                 question=FUNNEL[0][1]).json()["data"]["room"]
    exported = client.post(
        f"/api/v1/studies/{study_id}/interview/focus-group/rooms/{failed['room_id']}/export",
        json={"format": "markdown"}).json()["data"]["export"]
    assert exported["complete"] is False
    assert "INCOMPLETE — do not submit as final" in exported["content"]
    assert "0:P003" in exported["content"]
    assert "**P001:**" in exported["content"]
    assert "_no answer" in exported["content"]


def test_classroom_isolation_keeps_one_students_room_off_another_device(room, db_session):
    client, _, _, _ = room
    first = {"x-authenticated-user-id": f"classroom:{uuid4()}",
             "x-authenticated-auth-mode": "classroom-no-login"}
    second = {"x-authenticated-user-id": f"classroom:{uuid4()}",
              "x-authenticated-auth-mode": "classroom-no-login"}
    study_a = client.post("/api/v1/studies", json={}, headers=first).json()["data"]["study"]["study_id"]
    study_b = client.post("/api/v1/studies", json={}, headers=second).json()["data"]["study"]["study_id"]
    room_a = client.post(f"/api/v1/studies/{study_a}/interview/focus-group/rooms",
        json={"request_id": str(uuid4()), "persona_ids": list(THREE), "model": MODEL, "max_rounds": 5},
        headers=first).json()["data"]["room"]
    assert client.get(f"/api/v1/studies/{study_a}/interview/focus-group/rooms",
                      headers=second).status_code == 403
    assert client.get(f"/api/v1/studies/{study_a}/interview/focus-group/rooms/{room_a['room_id']}",
                      headers=second).status_code == 403
    assert client.get(f"/api/v1/studies/{study_a}/interview/focus-group/rooms/{room_a['room_id']}/memo",
                      headers=second).status_code == 403
    assert client.get(f"/api/v1/studies/{study_b}/interview/focus-group/rooms",
                      headers=second).json()["data"]["rooms"] == []
    # And student B cannot address student A's room through their own study either.
    assert client.get(f"/api/v1/studies/{study_b}/interview/focus-group/rooms/{room_a['room_id']}",
                      headers=second).status_code == 404


# --- refuter FG-1 / FG-2 ----------------------------------------------------

def test_memo_option_without_persona_id_is_refused(room):
    """An answer option with no speaker is refused, not attributed to a guess.

    Refuter FG-1: export read the model-supplied option['persona_id'], which the validator
    did not require — a memo it accepted then 500'd that room's export forever.
    Refuter FG-6: deriving the speaker from the first transcript match instead would credit
    group-distilled wording to whichever persona happened to be scanned first. So the
    validator now requires persona_id on options exactly as it does on themes, and export
    attributes from the located_at that requirement makes unambiguous.
    """
    client, study_id, _, behavior = room
    well_behaved = behavior["memo"]

    def no_persona_on_options(transcript):
        parsed = json.loads(well_behaved(transcript))
        parsed["answer_options"] = [{"text": o["text"]} for o in parsed["answer_options"]]
        return json.dumps(parsed)

    behavior["memo"] = no_persona_on_options
    finished = walk(client, study_id, start(client, study_id).json()["data"]["room"])
    view = memo(client, study_id, finished)
    refused = client.post(
        f"/api/v1/studies/{study_id}/interview/focus-group/rooms/{finished['room_id']}/memo",
        json={"revision": view["revision"], "authorize_charge": True})
    assert refused.status_code == 200, refused.text
    assert refused.json()["data"]["memo"]["saved"]["themes"] is None, "an unattributed memo is not saved"

    # A well-formed memo still exports, and the option's speaker comes from the transcript
    # location the validator derived rather than from the model's own claim.
    behavior["memo"] = well_behaved
    finished = walk(client, study_id, start(client, study_id).json()["data"]["room"])
    saved = write_memo(client, study_id, finished, memo(client, study_id, finished))["saved"]
    for fmt in ("markdown", "csv"):
        exported = client.post(
            f"/api/v1/studies/{study_id}/interview/focus-group/rooms/{finished['room_id']}/export",
            json={"format": fmt})
        assert exported.status_code == 200, exported.text
    content = client.post(
        f"/api/v1/studies/{study_id}/interview/focus-group/rooms/{finished['room_id']}/export",
        json={"format": "markdown"}).json()["data"]["export"]["content"]
    for option in saved["answer_options"]:
        assert option["located_at"]["persona_id"] == option["persona_id"]
        assert f"\"{option['text']}\" — {option['located_at']['persona_id']}" in content


def test_memo_option_is_attributed_to_its_own_speaker_not_the_first_match(room):
    """Refuter FG-6: wording two personas both used must not be credited to whichever
    one the transcript scan reached first."""
    client, study_id, _, behavior = room
    well_behaved = behavior["memo"]
    second = list(THREE)[1]

    def claim_the_second_persona(transcript):
        parsed = json.loads(well_behaved(transcript))
        # Every persona says this same sentence, so a first-match scan picks persona one.
        shared = "I use the garage as an office"
        assert transcript.count(shared) > 1, "the fixture must give two personas the same wording"
        parsed["answer_options"] = [{"text": shared, "persona_id": second}
                                    for _ in parsed["answer_options"]]
        return json.dumps(parsed)

    behavior["memo"] = claim_the_second_persona
    finished = walk(client, study_id, start(client, study_id).json()["data"]["room"])
    saved = write_memo(client, study_id, finished, memo(client, study_id, finished))["saved"]
    assert saved["answer_options"], saved
    for option in saved["answer_options"]:
        assert option["located_at"]["persona_id"] == second


def test_cancelled_room_cannot_buy_a_memo(room):
    """Refuter FG-2: cancel_room promises no further paid call; the memo is a paid call.

    A room that walked the whole funnel is `completed` and cannot be cancelled, so the
    reachable shape is the one the refuter named: finish the funnel, take a failed round,
    cancel the now-cancellable room, then try to buy the memo it is still eligible for.
    """
    client, study_id, calls, behavior = room
    walked = walk(client, study_id, start(client, study_id).json()["data"]["room"], FUNNEL[:-1])
    # One persona fails on the last stage: the stage is still reached (the other two
    # answered, so the memo is eligible) but the room is left cancellable.
    behavior["fail"] = lambda persona_id: persona_id == list(THREE)[0]
    stage, question = FUNNEL[-1]
    walked = ask(client, study_id, walked, stage=stage,
                 question=question).json()["data"]["room"]
    behavior["fail"] = None
    view = memo(client, study_id, walked)
    assert view["eligible"], "every stage the memo needs was still reached"
    cancelled = client.post(
        f"/api/v1/studies/{study_id}/interview/focus-group/rooms/{walked['room_id']}/cancel"
    ).json()["data"]["room"]
    assert cancelled["status"] == "cancelled", cancelled["status"]
    spent = len(calls)
    refused = client.post(
        f"/api/v1/studies/{study_id}/interview/focus-group/rooms/{walked['room_id']}/memo",
        json={"revision": view["revision"], "authorize_charge": True})
    assert refused.status_code == 409, refused.text
    assert "cancelled" in refused.json()["error"]["message"].lower()
    assert len(calls) == spent


def test_every_mutating_entry_point_is_serialized():
    """Refuter FG-4: cancel_room and delete_room were the only mutating entry points
    not wrapped, so under SQLite — which the app supports in production — a cancel
    issued during an in-flight round was overwritten when that round committed its
    own status, and the room accepted further paid rounds.
    """
    mutating = ("start_room", "ask_round", "cancel_room", "delete_room", "focus_group_memo")
    unguarded = [name for name in mutating
                 if getattr(getattr(fg, name), "__wrapped__", None) is None]
    assert not unguarded, f"not serialized: {unguarded}"


def test_stale_memo_is_not_available_and_is_marked_in_every_export(room):
    """Refuter FG-A: a memo written at minimum eligibility, then outrun by a later round.

    `available` used to mean only "a memo exists", so the UI hid the rewrite control while
    the export shipped the older memo with no warning — a student handed in a memo that
    never saw the last stage, with no way to refresh it.
    """
    client, study_id, _, _ = room
    started = walk(client, study_id, start(client, study_id).json()["data"]["room"], FUNNEL[:4])
    view = memo(client, study_id, started)
    assert view["eligible"]
    write_memo(client, study_id, started, view)
    fresh = memo(client, study_id, started)
    assert fresh["available"] and not fresh["stale"]

    stage, question = FUNNEL[4]
    finished = ask(client, study_id, started, stage=stage, question=question).json()["data"]["room"]
    after = memo(client, study_id, finished)
    assert after["stale"], "the memo predates the last round"
    assert not after["available"], "so it is not something to hand in, and the UI must offer a rewrite"
    assert after["saved"]["themes"], "the old memo is still readable"

    markdown = client.post(
        f"/api/v1/studies/{study_id}/interview/focus-group/rooms/{finished['room_id']}/export",
        json={"format": "markdown"}).json()["data"]["export"]["content"]
    assert "OUT OF DATE" in markdown
    csv_text = client.post(
        f"/api/v1/studies/{study_id}/interview/focus-group/rooms/{finished['room_id']}/export",
        json={"format": "csv"}).json()["data"]["export"]["content"]
    assert "out_of_date" in csv_text

    # And it can actually be refreshed: writing again is accepted and clears the staleness.
    write_memo(client, study_id, finished, after)
    assert memo(client, study_id, finished)["available"]


def test_csv_export_carries_the_memo_it_promises(room):
    """Refuter FG-B: the CSV branch returned after the transcript rows, so a student who
    exported CSV for submission silently got no themes, surprise, or answer options."""
    client, study_id, _, _ = room
    finished = walk(client, study_id, start(client, study_id).json()["data"]["room"])
    saved = write_memo(client, study_id, finished, memo(client, study_id, finished))["saved"]
    csv_text = client.post(
        f"/api/v1/studies/{study_id}/interview/focus-group/rooms/{finished['room_id']}/export",
        json={"format": "csv"}).json()["data"]["export"]["content"]
    assert "answer_option" in csv_text and "surprise" in csv_text
    for theme in saved["themes"]:
        assert theme["label"] in csv_text
    for option in saved["answer_options"]:
        assert option["text"] in csv_text


def test_a_pre_concept_round_asked_after_the_price_is_marked_as_such(room):
    """Refuter FG-C: the stage map blacks the price out of the system prompt, but
    _prior_messages replays every earlier round — so a space-needs question asked after
    the price stage is not pre-exposure data, and must not be exported as if it were."""
    client, study_id, calls, _ = room
    started = walk(client, study_id, start(client, study_id).json()["data"]["room"], FUNNEL[:4])
    before = len(calls)
    revisited = ask(client, study_id, started, stage="space_needs",
                    question="Back to your home — where else do you run out of room?")
    assert revisited.status_code == 200, revisited.text
    room_state = revisited.json()["data"]["room"]

    # The system prompt still honours the blackout, but the replayed transcript does not.
    for call in calls[before:]:
        assert "Price:" not in call["messages"][0]["content"]
    assert any("23,000" in " ".join(m["content"] for m in call["messages"])
               for call in calls[before:]), "the replay is what makes this round post-exposure"

    last = room_state["rounds"][-1]
    assert last["stage"] == "space_needs" and last["post_exposure"] is True
    assert room_state["rounds"][1]["post_exposure"] is False, "the original space-needs round is clean"
    content = client.post(
        f"/api/v1/studies/{study_id}/interview/focus-group/rooms/{room_state['room_id']}/export",
        json={"format": "markdown"}).json()["data"]["export"]["content"]
    assert "asked after the concept and price were shown" in content


def test_a_year_in_a_pre_price_question_is_not_mistaken_for_a_price(room):
    """Refuter FG-G: the anchor guard matched any four-digit integer, so an ordinary
    question mentioning a year was refused as price anchoring."""
    client, study_id, _, _ = room
    started = start(client, study_id).json()["data"]["room"]
    allowed = ask(client, study_id, started, stage="icebreaker",
                  question="How has your use of the space changed since 2020?")
    assert allowed.status_code == 200, allowed.text
    refused = ask(client, study_id, allowed.json()["data"]["room"], stage="space_needs",
                  question="Would you pay $23,000 for that?")
    assert refused.status_code == 400, refused.text
    assert "anchor price" in refused.json()["error"]["message"]
    spelled = ask(client, study_id, allowed.json()["data"]["room"], stage="space_needs",
                  question="Would 23000 dollars feel reasonable to you?")
    assert spelled.status_code == 400, spelled.text


def test_a_round_nobody_answered_says_so_instead_of_blaming_funnel_order(room):
    """Found by the first live run, not by any stub: when every persona in the opening
    round fails, `ask` returns 200 with a failed room, and the NEXT stage was refused with
    "Work the funnel in order" — an ordering complaint about a funnel worked in order."""
    client, study_id, _, behavior = room
    started = start(client, study_id).json()["data"]["room"]
    behavior["fail"] = lambda persona_id: True
    started = ask(client, study_id, started, stage="icebreaker",
                  question="Where do you work from at home?").json()["data"]["room"]
    behavior["fail"] = None
    assert all(a["status"] != "answered" for a in started["rounds"][0]["answers"])

    refused = ask(client, study_id, started, stage="space_needs",
                  question="What do you wish you had more room for?")
    assert refused.status_code == 400, refused.text
    message = refused.json()["error"]["message"]
    assert "No one answered" in message and "Icebreaker" in message
    assert "Work the funnel in order" not in message

    # And the named repair actually works.
    retried = ask(client, study_id, started, retry=True)
    assert retried.status_code == 200, retried.text
    assert ask(client, study_id, retried.json()["data"]["room"], stage="space_needs",
               question="What do you wish you had more room for?").status_code == 200


def test_every_seat_in_a_room_gets_a_different_stance():
    """The room disagrees only if its members start from different places.

    Personas all see each other's answers, which is the focus group and is also what
    drives them to agree. The counter-pressure is per-seat dispositions, so a roster
    drawing the same stance twice would be the bug this exists to catch.
    """
    # Every legal room size, not just three — MAX_PERSONAS seats is the case that
    # actually runs out of stances (refuter FG-STANCE-1).
    for size in range(fg.MIN_PERSONAS, fg.MAX_PERSONAS + 1):
        roster = [f"P{n:03d}" for n in range(1, size + 1)]
        seated = [fg.room_stance(roster, pid) for pid in roster]
        assert len(set(seated)) == size, f"a room of {size} doubled up on a stance"

    stances = [fg.room_stance(THREE, pid) for pid in THREE]
    assert all(s.strip() for s in stances)
    # Stable: the same seat gets the same stance on a retry, so a re-run of a missing
    # turn rebuilds the prompt the first attempt used.
    assert stances == [fg.room_stance(THREE, pid) for pid in THREE]


def test_stance_reaches_the_prompt_and_changes_the_cache_key():
    """A stance nobody sees is a stance that does nothing.

    The cache keys on a hash of the prior turns, and the system prompt is the first of
    them — so two stances must not collide onto one cached answer.
    """
    from src.services.interview_cache import hash_prior_turns

    profile = {"persona_id": "P001"}
    first = fg.build_room_system_prompt(profile, "concept", fg.room_stance(THREE, "P001"))
    second = fg.build_room_system_prompt(profile, "concept", fg.room_stance(THREE, "P002"))
    bare = fg.build_room_system_prompt(profile, "concept")

    assert fg.room_stance(THREE, "P001") in first
    assert "YOUR STANCE GOING IN:" in first
    assert "YOUR STANCE GOING IN:" not in bare
    assert hash_prior_turns([{"role": "system", "content": first}]) != \
        hash_prior_turns([{"role": "system", "content": second}])
    assert hash_prior_turns([{"role": "system", "content": first}]) != \
        hash_prior_turns([{"role": "system", "content": bare}])


def test_no_stance_reaches_a_pre_exposure_stage():
    """A skeptic at the icebreaker is a persona who already knows the product.

    icebreaker and space_needs are collected before the concept is introduced, so a
    product-directed disposition there contaminates exactly the answers _STAGE_CONTEXT
    keeps clean (refuter FG-STANCE-2).
    """
    profile = {"persona_id": "P001"}
    stance = fg.room_stance(THREE, "P001")
    for stage, context in fg._STAGE_CONTEXT.items():
        prompt = fg.build_room_system_prompt(profile, stage, stance)
        if context:
            assert "YOUR STANCE GOING IN:" in prompt, f"{stage} lost its stance"
        else:
            assert "YOUR STANCE GOING IN:" not in prompt, f"{stage} leaked a stance"
            assert stance not in prompt


def test_every_seat_in_a_room_gets_a_different_manner():
    """The first two rounds sound uniform unless the seats talk differently.

    _STANCES cannot run before the product is introduced, so at icebreaker and space_needs
    nothing in the prompt asks one seat to sound unlike another. The prompts are not
    identical — persona id and description differ — but nothing steers the register, which
    is what a room answering the first question in one voice actually looks like.
    """
    for size in range(1, fg.MAX_PERSONAS + 1):
        roster = [f"P{i:03d}" for i in range(1, size + 1)]
        seated = [fg.room_manner(roster, pid) for pid in roster]
        assert len(set(seated)) == size, f"a room of {size} doubled up on a manner"

    manners = [fg.room_manner(THREE, pid) for pid in THREE]
    assert all(m.strip() for m in manners)
    # Stable across retries, so a re-asked answer is not a different person.
    assert manners == [fg.room_manner(THREE, pid) for pid in THREE]


def test_manner_reaches_every_stage_including_pre_exposure():
    """The whole point is the stages a stance cannot reach."""
    profile = {"persona_id": "P001"}
    manner = fg.room_manner(THREE, "P001")
    for stage in fg._STAGE_CONTEXT:
        prompt = fg.build_room_system_prompt(profile, stage, "", manner)
        assert "HOW YOU TALK:" in prompt, f"{stage} lost its manner"
        assert manner in prompt, f"{stage} dropped the manner text"


def test_manner_changes_the_prompt_between_seats():
    """The manner alone must move the prompt, so it cannot be a no-op the persona masks.

    One profile is used for both seats on purpose: that isolates the manner as the only
    varying input. A real room also differs by persona id and description.
    """
    profile = {"persona_id": "P001"}
    first = fg.build_room_system_prompt(profile, "icebreaker", "", fg.room_manner(THREE, "P001"))
    second = fg.build_room_system_prompt(profile, "icebreaker", "", fg.room_manner(THREE, "P002"))
    bare = fg.build_room_system_prompt(profile, "icebreaker")
    assert first != second
    assert first != bare and second != bare


def test_no_manner_mentions_the_product():
    """A manner that leaks product awareness is a stance wearing a different label.

    This is the FG-STANCE-2 guarantee restated for the ungated block: manners run before
    the concept is introduced, so any of them naming it would contaminate exactly the
    answers _STAGE_CONTEXT keeps clean.
    """
    # The hand list catches the generic commercial register. The product's own vocabulary
    # is derived from the context the app actually shows, so a rename cannot leave this
    # test pinning words the product no longer uses (refuter FG-MANNER-4).
    generic = ("product", "buy", "purchase", "price", "cost", "device", "smart",
               "brand", "company", "subscription", "app")
    stopwords = {
        "a", "about", "and", "are", "backyard-scale", "being", "delivered", "discussed",
        "for", "has", "in", "is", "it", "no", "not", "or", "that", "the", "to", "with",
        "name", "description", "intended", "usable", "outdoor", "space", "compact",
        "square", "foot", "an",
    }
    from_product = {
        word
        for word in re.findall(r"[a-z]{3,}", (fg._CONCEPT_CONTEXT + fg._PRICE_CONTEXT).lower())
        if word not in stopwords
    }
    banned = tuple(sorted(set(generic) | from_product))
    assert "tahoe" in banned and "studio" in banned, "product vocabulary did not survive"
    # Whole words only: a substring check flags "app" inside "happened", which is how the
    # first version of this test failed on prose that named nothing at all.
    for manner in fg._MANNERS:
        lowered = manner.lower()
        for word in banned:
            assert not re.search(rf"\b{word}\b", lowered), f"manner names {word!r}: {manner!r}"
