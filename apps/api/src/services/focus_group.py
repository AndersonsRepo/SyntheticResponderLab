"""Simulated focus group: one student moderator, several personas reacting to each other.

Its own lane. Rooms are `focus_group_room` jobs, so nothing here appears in the
interview section's batch lists, the standalone themes input, or the pre-recorded
interviews page — all of which select on their own job_type.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
from copy import deepcopy
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select

from src.persistence.models import InterviewTurn, Job, Persona
from src.services.exceptions import (ApiError, ConflictApiError, NotFoundApiError,
    ProviderUnavailableApiError, QuotaExceededApiError, TransientProviderError, ValidationApiError)
from src.services.interview_cache import resolve_interview_answer
from src.services.llm_budget import (enforce_budget_open, enforce_measured_cost, enforce_run_preflight,
    load_interview_budget_snapshot, lock_class_budget_for_transaction)
from src.services.model_catalog import list_interview_model_catalog
from src.services.standalone_interview import serialized_local, usage, validate_models

logger = logging.getLogger(__name__)

JOB_TYPE = "focus_group_room"

# The PA3.5 funnel, in order. Price is the fourth stop on purpose: "don't anchor first".
STAGES = ("icebreaker", "space_needs", "concept", "price_reactions", "close")
STAGE_LABELS = {
    "icebreaker": "Icebreaker",
    "space_needs": "General space needs",
    "concept": "The Tahoe Mini concept",
    "price_reactions": "Price reactions",
    "close": "Close",
}

MIN_PERSONAS = 3          # Lin: "3 is the floor — a group, not an interview"
MAX_PERSONAS = 8
MAX_ROUNDS = 12
PROVIDER_TIMEOUT_SECONDS = 60

# Planning allowance for ONE persona turn in a room (the transcript is resent each
# round, so the prompt is larger than a single chat turn and smaller than a full
# AI-to-AI interview). Mirrored in apps/web/src/lib/focus-group.ts so the pre-start
# estimate the student approves is the number the server bills against; a test pins
# the two copies together.
ESTIMATED_PROMPT_TOKENS_PER_TURN = 2_000
ESTIMATED_COMPLETION_TOKENS_PER_TURN = 400
_TOKENS_PER_MILLION = Decimal("1000000")

# A memo needs enough room to stand on: both product stages reached, and enough
# answered turns that themes/surprise/options are read rather than invented. The floor
# is the smallest clean room that reaches price — MIN_PERSONAS through the first four
# stages — so a room that got there with holes in it is refused rather than padded.
MEMO_REQUIRED_STAGES = ("concept", "price_reactions")
MEMO_MIN_ANSWERS = MIN_PERSONAS * (STAGES.index("price_reactions") + 1)
MEMO_MODEL = "openai/gpt-4o-mini"
MEMO_MIN_THEMES, MEMO_MAX_THEMES = 3, 6
MEMO_MIN_ANSWER_OPTIONS = 3

_CONCEPT_CONTEXT = """PRODUCT BEING DISCUSSED:
Name: Tahoe Mini by Neo Smart Living
Description: A compact 117-square-foot factory-built studio that is delivered and installed in a backyard. It is not an ADU and has no kitchen or bathroom.
Intended for: homeowners with usable outdoor space"""
_PRICE_CONTEXT = _CONCEPT_CONTEXT + "\nPrice: about $23,000"

# Stage -> what the personas are allowed to know. Anything before `concept` gets no
# product context at all: a persona who already knows the product cannot give an
# uncontaminated answer about how they use their space today.
_STAGE_CONTEXT = {
    "icebreaker": "",
    "space_needs": "",
    "concept": _CONCEPT_CONTEXT,
    "price_reactions": _PRICE_CONTEXT,
    "close": _PRICE_CONTEXT,
}

# A moderator question that names a dollar figure before the price stage anchors the
# room just as surely as the app doing it. Refuse it and say why.
# A dollar sign, a thousands-grouped figure, or a bare number carrying a money word.
# A bare four-digit integer alone is a year far more often than a price ("in 2026",
# "since 1990"), and refusing those blocked legitimate pre-price questions (refuter FG-G).
_MONEY = re.compile(r"\$\s*\d|\b\d{1,3},\d{3}\b"
                    r"|\b\d{3,}\s*(?:dollars|usd|bucks|k\b)|\b(?:dollars|usd|price|cost)\b[^.?!]{0,20}\b\d{3,}\b",
                    re.I)


# Personas that all see each other's answers converge on agreement. That is documented
# group conformity in multi-agent LLM systems, attributed to RLHF optimizing for
# agreeableness, and the literature reports it is tunable through PERSONA rather than
# through information framing (Findings of ACL 2025; arXiv 2405.03862). So the room is
# seeded with differing dispositions instead of hiding what each participant sees:
# mutual visibility IS the focus group, and withholding it would leave parallel
# interviews. A stance is a disposition, never a rewrite of who the persona is — the
# Census-drawn profile still decides the facts of their life.
_STANCES = (
    "You are the room's skeptic. Assume the product is overpromised until someone gives you a"
    " concrete reason otherwise, and say plainly when an answer has not convinced you.",
    "You are the most willing person in the room. When others hesitate, say so and make the case"
    " for trying it anyway.",
    "You judge everything by whether it fits the routine you already have. Abstract benefits do"
    " not move you; describe the specific moment in your day it would or would not fit.",
    "Value for money is your lens before anything else. Keep returning to what it costs against"
    " what you would actually get.",
    "You do not trust connected devices or the companies behind them with what happens in your"
    " home. Raise that even when nobody else in the room has.",
    "You expect things like this to end up unused after a month. Say what would have to be true"
    " for that not to happen, without claiming purchases your life has not actually included.",
    "You answer for your household before yourself. Keep asking how this would land for the other"
    " people you live with, not only for you.",
    "You believe it when you see it fail well. Ask what happens when it breaks, and say what would"
    " have to go wrong for you to walk away.",
)

# A room may seat up to MAX_PERSONAS, and the whole point is that no two seats share a
# disposition, so the list has to cover the largest legal room.
assert len(_STANCES) >= MAX_PERSONAS, "every seat in a full room needs its own stance"


# _STANCES are dispositions toward the product, so they cannot appear before the product
# does. That gate (below) is right, but it leaves icebreaker and space_needs undifferentiated
# -- every seat runs the identical prompt, and a room of five answers the first two questions
# in one voice. A manner is about HOW a person talks, not what they think of anything, so it
# carries no product awareness and is safe at every stage.
_MANNERS = (
    "You answer briefly. Two or three sentences and you are done; you do not pad with"
    " background nobody asked for.",
    "You think out loud and reach your point late. Start with the specific thing that"
    " happened recently, then say what it means.",
    "You qualify almost everything -- 'it depends', 'usually', 'I guess'. Stating something"
    " flatly makes you uncomfortable when the real answer varies.",
    "You state things flatly and do not hedge. If you are unsure you say so outright, but you"
    " never soften the part you do know.",
    "You are the one who disagrees. When the room converges, look for what nobody said and"
    " name where your own experience does not match theirs.",
    "You reach for concrete numbers and times -- how many minutes, how many times a week --"
    " instead of calling something 'a lot' or 'a while'.",
    "You volunteer more than was asked: a side story, an aside about someone else, the thing"
    " it reminds you of.",
    "You answer narrowly and literally. Respond to the question that was actually asked and"
    " do not extend it.",
)

# Same rule as _STANCES: no two seats in a full room share one.
assert len(_MANNERS) >= MAX_PERSONAS, "every seat in a full room needs its own manner"


def _seat_pick(options, persona_ids, persona_id: str) -> str:
    """Give each seat its own entry from options, deterministically.

    The modulo never actually wraps — the asserts above keep every list at least
    MAX_PERSONAS long — it is there so a larger room degrades to a repeat rather
    than an IndexError mid-answer.
    """
    seats = list(persona_ids)
    # The roster is what builds the answer rows, so a persona is always on it. Falling
    # back to the first seat keeps a malformed room answering rather than raising mid-turn.
    seat = seats.index(persona_id) if persona_id in seats else 0
    return options[seat % len(options)]


def room_stance(persona_ids, persona_id: str) -> str:
    """One disposition per seat, so a room of N draws N different stances."""
    return _seat_pick(_STANCES, persona_ids, persona_id)


def room_manner(persona_ids, persona_id: str) -> str:
    """One speaking manner per seat, drawn the same way a stance is.

    Kept separate from room_stance because the two answer different questions: a stance is
    what this person thinks of the product, a manner is how they talk at all. Only the
    second one is safe before the product has been introduced.
    """
    return _seat_pick(_MANNERS, persona_ids, persona_id)


def persona_description(profile: dict) -> str:
    from src.services.interview_service import build_persona_description
    return build_persona_description(profile)


def build_room_system_prompt(profile: dict, stage: str, stance: str = "", manner: str = "") -> str:
    context = _STAGE_CONTEXT[stage]
    product = f"\n{context}\n" if context else "\n"
    # Pre-exposure stages get no stance. Every disposition below is about the product,
    # and a persona already skeptical of it is a persona who knows it exists — which is
    # the contamination _STAGE_CONTEXT exists to prevent (refuter FG-STANCE-2). Gate on
    # the same boundary rather than a second copy of the stage list.
    stance_block = f"\nYOUR STANCE GOING IN:\n{stance}\n" if stance and context else ""
    # A manner carries no product awareness, so unlike a stance it is not gated on context.
    manner_block = f"\nHOW YOU TALK:\n{manner}\n" if manner else ""
    return f"""You are role-playing as a real person taking part in a moderated focus group with other participants.

You are participant {profile.get('persona_id', 'unknown')} in this room.

YOUR PERSONA:
{persona_description(profile)}
{product}{stance_block}{manner_block}
INSTRUCTIONS:
- Stay fully in character. Answer the moderator as this person would, in first person.
- This is a group, not an interview. Whenever other participants' answers are shown to you,
  respond to at least one of them BY NAME before or while answering the moderator — agree,
  push back, or add the thing they left out. "P002 said X, but for me..." is the shape.
  Do not restate the room's consensus; say where you differ.
- Be specific and personal. Real trade-offs, not marketing-speak.
- Do NOT prefix your answer with your own participant id — the transcript already attributes you.
- Keep it conversational, two to five sentences, plain prose."""


def estimate_room_cost_usd(*, persona_count: int, rounds: int, model_id: str) -> Decimal:
    model = next(m for m in list_interview_model_catalog()["models"] if m["id"] == model_id)
    per_turn = (Decimal(str(model["prompt_price_per_million"])) * ESTIMATED_PROMPT_TOKENS_PER_TURN
                + Decimal(str(model["completion_price_per_million"])) * ESTIMATED_COMPLETION_TOKENS_PER_TURN)
    return (per_turn * persona_count * rounds) / _TOKENS_PER_MILLION


def owned_room(session, study, room_id, *, lock=False):
    query = select(Job).where(Job.public_id == room_id, Job.study_id == study.id, Job.job_type == JOB_TYPE)
    if lock:
        query = query.with_for_update().execution_options(populate_existing=True)
    room = session.scalar(query)
    if not room or room.status == "deleted":
        raise NotFoundApiError("Focus group room not found.")
    return room


def _answered(state):
    return [(r, a) for r in state["rounds"] for a in r["answers"] if a["status"] == "answered"]


def room_status(session, settings, study, room_id, room=None):
    room = room or owned_room(session, study, room_id)
    state = room.result_json or {}
    stages_reached = sorted({r["stage"] for r in state.get("rounds", []) if
                             any(a["status"] == "answered" for a in r["answers"])}, key=STAGES.index)
    return {
        "room_id": room.public_id,
        "status": room.status,
        **room.payload_json,
        **state,
        "stage": STAGES[state.get("stage_index", 0)],
        "stages": list(STAGES),
        "stage_labels": STAGE_LABELS,
        "stages_reached": stages_reached,
        "complete": room.status == "completed" and not _missing(state),
        "error": room.error_json,
        "session_usage": usage(session, settings, room.public_id),
    }


def list_rooms(session, settings, study):
    rooms = session.scalars(select(Job).where(
        Job.study_id == study.id, Job.job_type == JOB_TYPE, Job.status != "deleted"
    ).order_by(Job.queued_at.desc())).all()
    return [room_status(session, settings, study, room.public_id, room=room) for room in rooms]


@serialized_local
def delete_room(session, study, room_id):
    room = owned_room(session, study, room_id, lock=True)
    # ponytail: tombstone, not a row delete. The room's InterviewTurn cost rows stay —
    # deleting them would let a student clear their own spend against the class budget.
    room.status = "deleted"
    session.commit()
    return {"room_id": room_id, "deleted": True}


@serialized_local
def start_room(session, settings, study, payload):
    from src.services.interview_service import utcnow
    persona_ids = payload.get("persona_ids")
    if not isinstance(persona_ids, list) or any(not isinstance(p, str) for p in persona_ids):
        raise ValidationApiError("Choose the personas for the room.")
    if len(persona_ids) != len(set(persona_ids)):
        raise ValidationApiError("Each persona can only take one seat in the room.")
    if len(persona_ids) < MIN_PERSONAS:
        raise ValidationApiError(
            f"A focus group needs at least {MIN_PERSONAS} personas — fewer than that is an interview, not a group.")
    if len(persona_ids) > MAX_PERSONAS:
        raise ValidationApiError(f"A room holds at most {MAX_PERSONAS} personas.")
    rounds = payload.get("max_rounds", MAX_ROUNDS)
    if type(rounds) is not int or not 1 <= rounds <= MAX_ROUNDS:
        raise ValidationApiError(f"Plan between 1 and {MAX_ROUNDS} questions for the room.")
    model = payload.get("model")
    validate_models([model], payload.get("allow_expensive_models"))
    found = session.scalars(select(Persona).where(Persona.persona_id.in_(persona_ids))).all()
    if len(found) != len(persona_ids):
        raise ValidationApiError("One or more of the selected personas is unavailable.")
    try:
        request_id = str(UUID(str(payload.get("request_id"))))
    except ValueError as exc:
        raise ValidationApiError("request_id must be a UUID.") from exc
    room_id = "fg_" + hashlib.sha256(f"{study.id}:{request_id}".encode()).hexdigest()[:40]
    from src.services.interview_cache import _lock_cache_key_for_transaction
    _lock_cache_key_for_transaction(session, hashlib.sha256(room_id.encode()).hexdigest())
    config = {"persona_ids": persona_ids, "model": model, "max_rounds": rounds,
              "estimated_cost_usd": str(estimate_room_cost_usd(
                  persona_count=len(persona_ids), rounds=rounds, model_id=model))}
    existing = session.scalar(select(Job).where(Job.public_id == room_id))
    if existing:
        # A double-clicked start, or a lost creation response, resolves to the one room.
        if existing.payload_json != config:
            raise ConflictApiError("This room request ID was already used with different settings.")
        return room_status(session, settings, study, room_id)
    room = Job(public_id=room_id, study_id=study.id, job_type=JOB_TYPE, status="running",
               payload_json=config, result_json={"revision": 0, "stage_index": 0, "rounds": [], "memo": None},
               queued_at=utcnow(), started_at=utcnow())
    session.add(room)
    session.commit()
    return room_status(session, settings, study, room_id)


@serialized_local
def cancel_room(session, settings, study, room_id):
    room = owned_room(session, study, room_id, lock=True)
    if room.status in {"running", "failed", "budget_stopped"}:
        room.status = "cancelled"
        # Already-charged answers stay exactly where they are; no further paid call
        # can be made against a cancelled room.
        session.commit()
    return room_status(session, settings, study, room_id)


def _missing(state):
    return [(r["index"], a["persona_id"]) for r in state.get("rounds", [])
            for a in r["answers"] if a["status"] != "answered"]


def _prior_messages(state, persona_id):
    """What this persona has seen: its own earlier answers, plus what the others said.

    Earlier ROUNDS only. Within a round every persona answers the same question from
    the same context, so no persona ever sees its own future turns and the room does
    not depend on the order the personas happened to be called in.
    """
    messages = []
    for round_ in state["rounds"]:
        answers = {a["persona_id"]: a for a in round_["answers"] if a["status"] == "answered"}
        if not answers:
            continue
        messages.append({"role": "user", "content": f"Moderator: {round_['question']}"})
        own = answers.get(persona_id)
        if own:
            messages.append({"role": "assistant", "content": own["text"]})
        others = [f"- {pid}: {answer['text']}" for pid, answer in answers.items() if pid != persona_id]
        if others:
            messages.append({"role": "user", "content": "In the room, the other participants answered:\n"
                             + "\n".join(others)})
    return messages


@serialized_local
def ask_round(session, settings, study, room_id, payload):
    """One moderator question -> one answer per persona, each separately budgeted.

    Exactly one accepted call per revision: a resubmitted or double-clicked revision
    returns the current room and spends nothing.
    """
    from src.services import interview_service as service
    room = owned_room(session, study, room_id, lock=True)
    if type(payload.get("revision")) is not int:
        raise ValidationApiError("An integer room revision is required.")
    if room.status in {"cancelled", "completed"}:
        raise ConflictApiError(f"This room is {room.status}; its transcript stays readable.")
    state = deepcopy(room.result_json)
    if payload["revision"] != state["revision"]:
        # Stale revision: a second submit while the first round was still generating,
        # or a retried request whose first attempt already landed.
        return room_status(session, settings, study, room_id)
    retry = payload.get("retry") is True
    if retry:
        if not _missing(state):
            return room_status(session, settings, study, room_id)
        targets = [r for r in state["rounds"] if any(a["status"] != "answered" for a in r["answers"])]
        stage = targets[-1]["stage"]
    else:
        stage = str(payload.get("stage") or STAGES[state["stage_index"]])
        if stage not in STAGES:
            raise ValidationApiError("Unknown focus-group stage.")
        reached = {r["stage"] for r in state["rounds"] if any(a["status"] == "answered" for a in r["answers"])}
        furthest = max((STAGES.index(s) for s in reached), default=-1)
        if STAGES.index(stage) > furthest + 1:
            # "Work the funnel in order" is the wrong sentence when the funnel WAS worked in
            # order and the provider simply never answered: a round whose every answer failed
            # leaves furthest where it was, and the student got told about ordering when the
            # real state is an unanswered round to retry. Say which it is.
            unanswered = [r for r in state["rounds"]
                          if not any(a["status"] == "answered" for a in r["answers"])]
            if unanswered:
                last = unanswered[-1]
                raise ValidationApiError(
                    f"No one answered your {STAGE_LABELS[last['stage']]} question yet, so the room "
                    f"cannot move on. Retry that round first.")
            raise ValidationApiError(
                f"Work the funnel in order: {STAGE_LABELS[STAGES[furthest + 1]]} comes before "
                f"{STAGE_LABELS[stage]}.")
        if len(state["rounds"]) >= room.payload_json["max_rounds"]:
            raise ValidationApiError("This room has used all the questions it was started with.")
        question = str(payload.get("question") or "").strip()
        if not question:
            raise ValidationApiError("Type the question you want to put to the room.")
        if STAGES.index(stage) < STAGES.index("price_reactions") and _MONEY.search(question):
            raise ValidationApiError(
                "Don't anchor price first — hold dollar figures until the price-reactions stage.")
        # The stage map blacks out the concept and the price for early stages, but
        # _prior_messages replays every earlier round, so a round asked at an early stage
        # AFTER the concept has run still carries both into the prompt. The round is not
        # refused — going back is something the funnel allows — but it is recorded as what
        # it is, so the export cannot present it as pre-exposure data (refuter FG-C).
        post_exposure = (STAGES.index(stage) < STAGES.index("concept")
                         and furthest >= STAGES.index("concept"))
        round_ = {"index": len(state["rounds"]), "stage": stage, "question": question,
                  "post_exposure": post_exposure,
                  "answers": [{"persona_id": pid, "text": "", "status": "missing", "error": None}
                              for pid in room.payload_json["persona_ids"]]}
        state["rounds"].append(round_)
        targets = [round_]
    model = room.payload_json["model"]
    stopped = None
    charged_any = False

    def run_answer(round_, answer, history):
        """One persona's turn: budgeted, cached, charged, and recorded on its own."""
        nonlocal charged_any
        persona = session.get(Persona, answer["persona_id"])
        stage_ = round_["stage"]
        seats = room.payload_json["persona_ids"]
        stance = room_stance(seats, answer["persona_id"])
        manner = room_manner(seats, answer["persona_id"])
        prior = [{"role": "system",
                  "content": build_room_system_prompt(persona.profile_json, stage_, stance, manner)},
                 *_prior_messages(history, answer["persona_id"])]
        question_text = round_["question"]
        budget_error = None

        def provider():
            nonlocal budget_error
            lock_class_budget_for_transaction(session)
            snapshot = load_interview_budget_snapshot(session, session_id=room_id,
                                                      run_budget_usd=settings.llm_budget_usd)
            enforce_budget_open(snapshot)
            if snapshot.run_provider_call_count == 0:
                enforce_run_preflight(estimated_cost_usd=room.payload_json["estimated_cost_usd"],
                                      class_spent_usd=snapshot.class_spent_usd,
                                      run_budget_usd=snapshot.run_budget_usd)
            if not settings.openrouter_api_key:
                raise ConflictApiError("OPENROUTER_API_KEY is not configured.")
            result = service._call_openrouter_messages(
                api_key=settings.openrouter_api_key or "", model=model,
                messages=[*prior, {"role": "user", "content": f"Moderator: {question_text}"}],
                timeout=PROVIDER_TIMEOUT_SECONDS, max_attempts=1)
            try:
                enforce_measured_cost(snapshot, cost_usd=result.cost_usd)
            except QuotaExceededApiError as exc:
                budget_error = exc
            return result

        def log(error):
            logger.warning("focus_group_failure room=%s stage=%s persona=%s model=%s code=%s error=%s",
                           room_id, stage_, answer["persona_id"], model, error.code, error.message)

        try:
            reply = resolve_interview_answer(session, cache_mode=settings.cache_mode,
                persona_id=answer["persona_id"], model=model, question=question_text,
                prior_turns=prior, call_provider=provider)
        except Exception as exc:
            measured = exc.measured_usage if isinstance(exc, TransientProviderError) else None
            if measured is not None:
                _record_usage(session, study, room_id, answer["persona_id"], measured)
                charged_any = True
            error = exc if isinstance(exc, ApiError) else ProviderUnavailableApiError(str(exc))
            answer["error"] = {"code": error.code, "message": error.message}
            log(error)
            # A budget stop ends the room's spending; one persona failing only leaves a
            # visible hole, so the personas after it still get their turn.
            return exc if isinstance(exc, QuotaExceededApiError) else None
        _record_usage(session, study, room_id, answer["persona_id"], reply)
        charged_any = charged_any or reply.cost_usd > 0
        answer.update(text=reply.text, status="answered", error=None)
        if budget_error is not None:
            log(budget_error)
        return budget_error

    for round_ in targets:
        # Prior context is read from the rounds BEFORE this one, so a retry rebuilds the
        # same prompts the first attempt used and lands on the same cache keys.
        history = {"rounds": state["rounds"][:round_["index"]]}
        for answer in round_["answers"]:
            if answer["status"] == "answered":
                continue  # A retry re-runs only the turns that are actually missing.
            stopped = run_answer(round_, answer, history)
            if stopped is not None:
                break
        if stopped is not None:
            break
    stage = round_["stage"]
    state["revision"] += 1
    if not retry:
        # A retry repairs holes wherever they are; it does not move the student's stage.
        state["stage_index"] = STAGES.index(stage)
    room.result_json = state
    remaining = _missing(state)
    if stopped is not None:
        room.status = "budget_stopped"
        snapshot = load_interview_budget_snapshot(session, session_id=room_id,
                                                  run_budget_usd=settings.llm_budget_usd)
        left = max(snapshot.run_budget_usd - snapshot.run_spent_usd, Decimal("0"))
        room.error_json = {
            "code": stopped.code, "stage": stage, "room_id": room_id,
            "message": ("The budget stopped this room. Every answer you were charged for is still "
                        f"here and in order. ${left:.2f} of this run's ${snapshot.run_budget_usd:.2f} "
                        "budget remains, so the rest of the round was not started."),
            "details": stopped.details}
    elif remaining:
        room.status = "failed"
        room.error_json = {
            "code": "provider_unavailable", "stage": stage, "room_id": room_id,
            "message": "Some personas did not answer. Retry to run only the missing turns; "
                       "answers already collected are kept and are not charged again.",
            "missing": [{"round": index, "persona_id": pid} for index, pid in remaining]}
    else:
        room.status = "completed" if STAGES[state["stage_index"]] == "close" else "running"
        room.error_json = None
    room.heartbeat_at = service.utcnow()
    if room.status == "completed":
        room.completed_at = service.utcnow()
    session.commit()
    status = room_status(session, settings, study, room_id)
    status["charged_this_round"] = charged_any
    return status


def _record_usage(session, study, room_id, persona_id, measured):
    """Accounting row. Empty text keeps focus-group turns out of the interview corpus."""
    from src.services.interview_service import utcnow
    session.add(InterviewTurn(study_id=study.id, persona_id=persona_id, session_id=room_id,
        role="assistant", text="", model=measured.model, tokens_in=measured.tokens_in,
        tokens_out=measured.tokens_out, cost_usd=measured.cost_usd, created_at=utcnow()))


# ---------------------------------------------------------------------------
# Memo: the PA3.5 hand-in fields, read off the student's own transcript
# ---------------------------------------------------------------------------

def _memo_prompt(room):
    return f"""You are helping a marketing-research student write the one-page memo for a focus group they just moderated.

Work ONLY from the transcript below. Every quote and every answer option must be copied \
VERBATIM from a participant's answer — character for character, no paraphrase, no invention, \
no cleanup. If you cannot find real supporting text, return fewer themes rather than inventing one.

Return ONLY a JSON object:
{{
  "themes": [
    {{"label": "...", "synthesis": "one sentence", "quote": "<verbatim>", "persona_id": "P0XX",
      "sentiment": "positive" | "neutral" | "negative"}}
  ],
  "surprise": {{"summary": "one sentence on the single most surprising thing", "quote": "<verbatim>", "persona_id": "P0XX"}},
  "answer_options": [
    {{"text": "<verbatim participant wording to use as a closed-ended survey option>", "persona_id": "P0XX"}}
  ]
}}

{MEMO_MIN_THEMES}–{MEMO_MAX_THEMES} themes, exactly one surprise, at least \
{MEMO_MIN_ANSWER_OPTIONS} answer options, each phrased in participant language."""


def _memo_transcript(state):
    lines = []
    for round_ in state["rounds"]:
        lines.append(f"## {STAGE_LABELS[round_['stage']]} — moderator: {round_['question']}")
        for answer in round_["answers"]:
            if answer["status"] == "answered":
                lines.append(f"{answer['persona_id']}: {answer['text']}")
    return "\n".join(lines)


def _locate(state, text, persona_id=None):
    """Where in the transcript this exact text appears, or None if it does not."""
    for round_ in state["rounds"]:
        for answer in round_["answers"]:
            if answer["status"] != "answered" or (persona_id and answer["persona_id"] != persona_id):
                continue
            if text and text in answer["text"]:
                return {"persona_id": answer["persona_id"], "round": round_["index"],
                        "stage": round_["stage"], "question": round_["question"]}
    return None


def _revision(state):
    """Which transcript a memo is about. The export compares against this too, so a memo
    written before the last round cannot be handed in unmarked (refuter FG-A)."""
    return hashlib.sha256(json.dumps(state.get("rounds", []), sort_keys=True).encode()).hexdigest()


def memo_view(session, settings, study, room_id, room=None):
    room = room or owned_room(session, study, room_id)
    state = room.result_json or {}
    answers = _answered(state)
    reached = {r["stage"] for r, _ in answers}
    missing_stages = [s for s in MEMO_REQUIRED_STAGES if s not in reached]
    if missing_stages:
        eligible, message = False, (
            "This room never reached " + " or ".join(STAGE_LABELS[s] for s in missing_stages)
            + ". A memo written without those stages would be invented, not observed.")
    elif len(answers) < MEMO_MIN_ANSWERS:
        eligible, message = False, (
            f"This room has {len(answers)} answered turns. The memo needs at least "
            f"{MEMO_MIN_ANSWERS} before themes, a surprise, and answer options can be read "
            "off the transcript rather than padded.")
    else:
        eligible, message = True, "Write the memo from this transcript."
    revision = _revision(state)
    saved = state.get("memo")
    stale = bool(saved and saved["revision"] != revision)
    prompt = _memo_prompt(room) + _memo_transcript(state)
    model = next(m for m in list_interview_model_catalog()["models"] if m["id"] == MEMO_MODEL)
    estimate = (Decimal(len(prompt.encode()) + 100) * Decimal(str(model["prompt_price_per_million"]))
                + Decimal(2000) * Decimal(str(model["completion_price_per_million"]))) / _TOKENS_PER_MILLION
    return {"room_id": room.public_id, "revision": revision, "eligible": eligible, "message": message,
            "answered_turns": len(answers), "stages_reached": sorted(reached, key=STAGES.index),
            # "available" means a memo the student can hand in as-is. A memo written
            # before the last round describes a transcript that no longer exists, so it
            # is NOT available — that is what re-opens the rewrite control instead of
            # leaving the room with a stale memo and no way to refresh it (refuter FG-A).
            "available": bool(saved and saved.get("themes")) and not stale,
            "stale": stale,
            "estimated_cost_usd": str(estimate), "model": MEMO_MODEL, "saved": saved,
            "session_usage": usage(session, settings, room.public_id)}


@serialized_local
def focus_group_memo(session, settings, study, room_id, payload=None):
    """Read-only unless the student authorizes the charge; re-opening never pays twice."""
    from src.services import interview_service as service
    room = owned_room(session, study, room_id, lock=True)
    view = memo_view(session, settings, study, room_id, room=room)
    if payload is None or not view["eligible"]:
        return view
    if payload.get("revision") != view["revision"]:
        raise ConflictApiError("The transcript changed. Review the new memo estimate before confirming.")
    saved = view["saved"]
    if saved and not view["stale"]:
        if saved.get("themes"):
            return view  # Already written. Re-opening it is free.
        if payload.get("retry_attempt") != saved.get("attempt"):
            return view
    if room.status == "cancelled":
        # cancel_room promises no further paid call against a cancelled room; the memo is
        # a paid call, so it has to honour that too. Reading an already-written memo stays
        # free — those paths returned above.
        raise ConflictApiError("This room was cancelled. Writing its memo would be a new charge.")
    if payload.get("authorize_charge") is not True:
        raise ValidationApiError("Confirm the additional memo charge first.")
    if settings.cache_mode == "replay_only":
        raise ConflictApiError("Cache-only mode: no saved memo exists for this transcript.")
    lock_class_budget_for_transaction(session)
    snapshot = load_interview_budget_snapshot(session, session_id=room_id, run_budget_usd=settings.llm_budget_usd)
    enforce_budget_open(snapshot)
    enforce_run_preflight(estimated_cost_usd=Decimal(view["estimated_cost_usd"]) + snapshot.run_spent_usd,
        class_spent_usd=snapshot.class_spent_usd - snapshot.run_spent_usd, run_budget_usd=snapshot.run_budget_usd)
    if not settings.openrouter_api_key:
        raise ConflictApiError("Memo writing is not configured.")
    state = deepcopy(room.result_json)
    attempt = (saved.get("attempt", 0) if saved else 0) + 1
    record = {"revision": view["revision"], "attempt": attempt, "outcome": "unknown", "themes": None}
    try:
        try:
            result = service._call_openrouter_messages(api_key=settings.openrouter_api_key, model=MEMO_MODEL,
                messages=[{"role": "system", "content": _memo_prompt(room)},
                          {"role": "user", "content": f"FOCUS GROUP TRANSCRIPT:\n{_memo_transcript(state)}"}],
                timeout=PROVIDER_TIMEOUT_SECONDS, max_attempts=1)
        except TransientProviderError as exc:
            # Billed but unusable still costs money; record it before failing.
            if exc.measured_usage is not None:
                _record_usage(session, study, room_id, "__memo__", exc.measured_usage)
                record.update(outcome="charged", cost_usd=str(exc.measured_usage.cost_usd))
            raise
        _record_usage(session, study, room_id, "__memo__", result)
        record.update(outcome="charged", cost_usd=str(result.cost_usd))
        try:
            enforce_measured_cost(snapshot, cost_usd=result.cost_usd)
        except QuotaExceededApiError as exc:
            record["budget_stop"] = exc.message
        record.update(_validate_memo(json.loads(result.text), state))
    except Exception:
        record["message"] = ("The memo could not be written from this transcript. Your transcript is "
            "preserved. " + ("The response could not be validated against the transcript; its measured "
            "charge is recorded. Retrying adds another charge." if record["outcome"] == "charged"
            else "The provider's billing outcome is unknown. Retrying may incur another charge."))
    logger.log(logging.INFO if record["themes"] else logging.WARNING,
               "focus_group_memo study=%s room=%s revision=%s attempt=%s outcome=%s valid=%s",
               study.public_id, room_id, view["revision"], attempt, record["outcome"], bool(record["themes"]))
    state["memo"] = record
    room.result_json = state
    session.commit()
    return memo_view(session, settings, study, room_id, room=room)


def _validate_memo(parsed, state):
    """Accept only memo fields that can be pointed at in the transcript."""
    themes = parsed.get("themes")
    surprise = parsed.get("surprise")
    options = parsed.get("answer_options")
    if not isinstance(themes, list) or not MEMO_MIN_THEMES <= len(themes) <= MEMO_MAX_THEMES:
        raise ValueError(f"Expected {MEMO_MIN_THEMES}–{MEMO_MAX_THEMES} themes")
    located_themes = []
    for theme in themes:
        if (not isinstance(theme, dict)
                or any(not isinstance(theme.get(k), str) or not theme[k].strip()
                       for k in ("label", "synthesis", "quote", "persona_id"))
                or theme.get("sentiment") not in ("positive", "neutral", "negative")):
            raise ValueError("Invalid theme")
        found = _locate(state, theme["quote"], theme["persona_id"])
        if not found:
            raise ValueError("Theme quote is not verbatim from this transcript")
        located_themes.append({**theme, "located_at": found})
    if (not isinstance(surprise, dict)
            or any(not isinstance(surprise.get(k), str) or not surprise[k].strip()
                   for k in ("summary", "quote", "persona_id"))):
        raise ValueError("Expected exactly one surprise")
    surprise_at = _locate(state, surprise["quote"], surprise["persona_id"])
    if not surprise_at:
        raise ValueError("Surprise quote is not verbatim from this transcript")
    if not isinstance(options, list) or len(options) < MEMO_MIN_ANSWER_OPTIONS:
        raise ValueError(f"Expected at least {MEMO_MIN_ANSWER_OPTIONS} answer options")
    located_options = []
    for option in options:
        # persona_id is required here for the same reason it is on themes and the surprise:
        # without it _locate falls back to the first containment hit, and option wording
        # distilled from a group routinely appears in more than one persona's answer — so a
        # student would hand in participant language credited to a participant who may not
        # have said it. Refusing is better than guessing at attribution (refuter FG-6).
        if (not isinstance(option, dict)
                or any(not isinstance(option.get(k), str) or not option[k].strip()
                       for k in ("text", "persona_id"))):
            raise ValueError("Invalid answer option")
        found = _locate(state, option["text"], option["persona_id"])
        if not found:
            raise ValueError("Answer option is not verbatim participant language")
        located_options.append({**option, "located_at": found})
    return {"themes": located_themes, "surprise": {**surprise, "located_at": surprise_at},
            "answer_options": located_options}


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------

def build_room_export(status, export_format):
    """Markdown or CSV of the transcript and memo, attributed turn by turn."""
    from src.services.interview_export import InterviewTranscriptExport, _as_csv_text
    import csv
    import io
    room_id = status["room_id"]
    incomplete = [f"{r['index']}:{a['persona_id']}" for r in status["rounds"]
                  for a in r["answers"] if a["status"] != "answered"]
    unfinished = status["status"] != "completed" or bool(incomplete)
    memo = (status.get("memo") or {}) if isinstance(status.get("memo"), dict) else {}
    memo_stale = bool(memo.get("themes") and memo.get("revision") != _revision(status))
    stem = re.sub(r"[^A-Za-z0-9._-]+", "-", room_id).strip(".-")[:64] or "room"

    if export_format == "csv":
        output = io.StringIO(newline="")
        writer = csv.writer(output, lineterminator="\r\n")
        writer.writerow(["round", "stage", "speaker", "role", "text", "status", "complete"])
        for round_ in status["rounds"]:
            writer.writerow([round_["index"] + 1, round_["stage"], "Moderator", "moderator",
                             _as_csv_text(round_["question"]), "asked", str(not unfinished)])
            for answer in round_["answers"]:
                writer.writerow([round_["index"] + 1, round_["stage"], _as_csv_text(answer["persona_id"]),
                                 "participant", _as_csv_text(answer["text"]), answer["status"],
                                 str(not unfinished)])
        # The docstring and the UI button both promise the memo; the CSV used to stop at
        # the transcript and say nothing about it (refuter FG-B).
        if memo.get("themes"):
            fresh = str(not unfinished and not memo_stale)
            memo_status = "out_of_date" if memo_stale else "current"
            writer.writerow([])
            writer.writerow(["memo", "field", "speaker", "role", "text", "status", "complete"])
            for theme in memo["themes"]:
                writer.writerow(["memo", "theme", _as_csv_text(theme["located_at"]["persona_id"]),
                                 theme["sentiment"],
                                 _as_csv_text(f"{theme['label']}: {theme['synthesis']} - \"{theme['quote']}\""),
                                 memo_status, fresh])
            surprise = memo["surprise"]
            writer.writerow(["memo", "surprise", _as_csv_text(surprise["located_at"]["persona_id"]),
                             "surprise",
                             _as_csv_text(f"{surprise['summary']} - \"{surprise['quote']}\""),
                             memo_status, fresh])
            for option in memo["answer_options"]:
                writer.writerow(["memo", "answer_option", _as_csv_text(option["located_at"]["persona_id"]),
                                 "answer_option", _as_csv_text(option["text"]), memo_status, fresh])
        return InterviewTranscriptExport(content="﻿" + output.getvalue(),
            filename=f"focus-group-{stem}.csv", media_type="text/csv")

    lines = ["# Focus group transcript", ""]
    if unfinished:
        lines += [f"> **INCOMPLETE — do not submit as final.** Room status: `{status['status']}`."
                  + (f" Missing answers (round:persona): {', '.join(incomplete)}." if incomplete else ""), ""]
    lines += [f"- Room: `{room_id}`", f"- Model: `{status['model']}`",
              f"- Participants: {', '.join(status['persona_ids'])}",
              f"- Stages reached: {', '.join(STAGE_LABELS[s] for s in status['stages_reached']) or 'none'}", ""]
    for round_ in status["rounds"]:
        lines += [f"## {round_['index'] + 1}. {STAGE_LABELS[round_['stage']]}"
                  + (" — asked after the concept and price were shown" if round_.get("post_exposure") else ""),
                  "",
                  f"**Moderator:** {round_['question']}", ""]
        for answer in round_["answers"]:
            lines += ([f"**{answer['persona_id']}:** {answer['text']}", ""] if answer["status"] == "answered"
                      else [f"**{answer['persona_id']}:** _no answer — {answer['status']}_", ""])
    if memo.get("themes"):
        lines += ["## Memo", ""]
        if memo_stale:
            lines += ["> **OUT OF DATE — do not submit as final.** This memo was written before "
                      "the last round below and does not describe it. Rewrite the memo.", ""]
        lines += ["### Themes", ""]
        for theme in memo["themes"]:
            lines += [f"- **{theme['label']}** ({theme['sentiment']}) — {theme['synthesis']}",
                      f"  - \"{theme['quote']}\" — {theme['persona_id']}, "
                      f"{STAGE_LABELS[theme['located_at']['stage']]} round {theme['located_at']['round'] + 1}"]
        surprise = memo["surprise"]
        lines += ["", "### One surprise", "", f"{surprise['summary']}",
                  f"- \"{surprise['quote']}\" — {surprise['persona_id']}", "",
                  "### Closed-ended answer options (participant language)", ""]
        # Attribute from located_at, the transcript position _validate_memo verified the
        # option against. The validator requires persona_id on options (FG-6), so the two
        # agree by construction; located_at is the one the transcript itself vouches for.
        lines += [f"- \"{option['text']}\" — {option['located_at']['persona_id']}"
                  for option in memo["answer_options"]]
        lines.append("")
    elif not unfinished:
        lines += ["## Memo", "", "_Not written yet._", ""]
    return InterviewTranscriptExport(content="\n".join(lines),
        filename=f"focus-group-{stem}.md", media_type="text/markdown")


def export_room(session, settings, study, room_id, payload):
    export_format = str((payload or {}).get("format") or "markdown")
    if export_format not in ("markdown", "csv"):
        raise ValidationApiError("Export format must be markdown or csv.")
    status = room_status(session, settings, study, room_id)
    export = build_room_export(status, export_format)
    return {"content": export.content, "filename": export.filename,
            "media_type": export.media_type, "complete": status["complete"]}
