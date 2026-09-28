"""Student-created practice personas for the focus group (Lin fix 3).

Stored exactly where focus-group rooms are: study-scoped `jobs` rows, their own job_type.
A persona is fictional by construction: every attribute on its card is marked so, and the
card says it is not a real PA3.5 participant. A room freezes the version it seated.
"""
from __future__ import annotations

import hashlib
from uuid import UUID

from sqlalchemy import select

from src.persistence.models import Job
from src.persistence.persona_seed import card_attribute, screener
from src.services.exceptions import ConflictApiError, NotFoundApiError, ValidationApiError
from src.services.standalone_interview import serialized_local

JOB_TYPE = "focus_group_persona"
MAX_PER_STUDY = 20
ORIGIN_LABEL = "Student-created fictional persona — not a real PA3.5 participant"

TENURE = {"owner": "owns their home", "landowner": "owns land", "renter": "rents their home",
          "lives_with_family": "lives in a relative's home", "unknown": ""}
OUTDOOR = {"yes": "has usable outdoor space", "no": "has no usable outdoor space", "unknown": ""}
WILLING = {"yes": "would consider adding living or work space", "maybe": "might consider adding space",
           "no": "is not interested in adding space", "unknown": ""}
STYLE = {"": "", "brief": "brief", "talkative": "talkative"}
_TEXT = {"name": 60, "household": 300, "outdoor_note": 300, "current_space_use": 300,
         "constraints": 300, "research_link": 500}
_CHOICE = {"tenure": TENURE, "outdoor_space": OUTDOOR, "willing_more_space": WILLING, "style": STYLE}


def clean_fields(raw):
    """The trust boundary. No product-opinion or desired-findings field exists to fill."""
    if not isinstance(raw, dict):
        raise ValidationApiError("Send the persona as an object.")
    fields = {}
    for key, limit in _TEXT.items():
        value = raw.get(key) or ""
        if not isinstance(value, str):
            raise ValidationApiError(f"{key} must be text.")
        if len(value.strip()) > limit:
            raise ValidationApiError(f"{key} is longer than {limit} characters.")
        fields[key] = value.strip()
    for key, choices in _CHOICE.items():
        value = raw.get(key) or ("" if key == "style" else "unknown")
        if value not in choices:
            raise ValidationApiError(f"{key} must be one of: {', '.join(c or '(none)' for c in choices)}.")
        fields[key] = value
    if not fields["household"]:
        raise ValidationApiError("Describe the household and living situation.")
    if not fields["research_link"]:
        raise ValidationApiError("Say how this profile relates to your research question.")
    return fields


_TENURE_YOU = {"owner": "You own your home.", "landowner": "You own land.",
               "renter": "You rent your home.", "lives_with_family": "You live in a relative's home."}
_OUTDOOR_YOU = {"yes": "You have usable outdoor space", "no": "You have no usable outdoor space"}
_WILLING_YOU = {"yes": "You would consider adding living or work space.",
                "maybe": "You might consider adding living or work space.",
                "no": "You are not interested in adding living or work space."}


def describe(fields) -> str:
    """What the model is told. research_link is the student's own reflection and stays out."""
    outdoor = "; ".join(p for p in (_OUTDOOR_YOU.get(fields["outdoor_space"], ""), fields["outdoor_note"]) if p)
    parts = [f"You are {fields['name'] or 'a focus-group participant'}.",
             f"Your household and living situation: {fields['household']}.",
             _TENURE_YOU.get(fields["tenure"], ""),
             f"Outdoor space: {outdoor}." if outdoor else "",
             f"How you use your space today: {fields['current_space_use']}." if fields["current_space_use"] else "",
             _WILLING_YOU.get(fields["willing_more_space"], ""),
             f"Constraints you live with: {fields['constraints']}." if fields["constraints"] else "",
             "Anything not described here is yours to fill in naturally; keep it consistent."]
    return " ".join(p for p in parts if p)


def card(persona_id, fields, *, version, based_on=None):
    def pick(choices, key):
        return choices[fields[key]].capitalize() if choices[fields[key]] else ""
    outdoor = "; ".join(p for p in (pick(OUTDOOR, "outdoor_space"), fields["outdoor_note"]) if p)
    return {
        "persona_id": persona_id, "name": fields["name"], "origin": "student_created",
        "origin_label": ORIGIN_LABEL + (f" (started from a copy of {based_on})" if based_on else ""),
        "version": version, "based_on": based_on,
        "attributes": [
            card_attribute("name", "Name", fields["name"], "fictional"),
            card_attribute("household", "Household", fields["household"], "fictional"),
            card_attribute("tenure", "Homeowner or renter", pick(TENURE, "tenure"), "fictional"),
            card_attribute("outdoor_space", "Usable outdoor space", outdoor, "fictional"),
            card_attribute("willing_more_space", "Willing to consider more living/work space",
                           pick(WILLING, "willing_more_space"), "fictional"),
            card_attribute("current_space_use", "How they use their space today", fields["current_space_use"], "fictional"),
            card_attribute("constraints", "Constraints", fields["constraints"], "fictional"),
            card_attribute("style", "Conversation style", fields["style"], "fictional"),
        ],
        "screener": screener({"owner": "Owned (student-specified)", "landowner": "Owns land (student-specified)",
                              "renter": "Rented (student-specified)"}.get(fields["tenure"], ""),
                             fields["outdoor_space"], fields["willing_more_space"], "fictional", "fictional"),
        "research_link": fields["research_link"],
        "source_note": ("Every attribute was written by a student. This persona is invented for practice and "
                        "never counts as recruiting a real PA3.5 participant."),
    }


def _view(job):
    config = job.payload_json
    return {"id": job.public_id, "persona_id": config["persona_id"], "version": config["version"],
            "based_on": config.get("based_on"), "fields": config["fields"],
            "card": card(config["persona_id"], config["fields"], version=config["version"],
                         based_on=config.get("based_on")),
            "description": describe(config["fields"])}


def _study_personas(session, study):
    return session.scalars(select(Job).where(Job.study_id == study.id, Job.job_type == JOB_TYPE)
                           .order_by(Job.queued_at)).all()


def list_personas(session, study):
    return [_view(job) for job in _study_personas(session, study)]


def _based_on(value):
    if value is None:
        return None
    from src.persistence.persona_seed import persona_cards
    if not isinstance(value, str) or value not in persona_cards():
        raise ValidationApiError("Duplicate from a persona on the roster.")
    return value


@serialized_local
def create_persona(session, study, payload):
    from src.services.interview_cache import _lock_cache_key_for_transaction
    from src.services.interview_service import utcnow
    payload = payload or {}
    fields = clean_fields(payload.get("fields"))
    based_on = _based_on(payload.get("based_on"))
    if payload.get("preview") is True:
        # Preview stores nothing: the student sees the card and what the model would be told.
        return {"preview": True, "card": card("S??", fields, version=1, based_on=based_on),
                "description": describe(fields)}
    try:
        request_id = str(UUID(str(payload.get("request_id"))))
    except ValueError as exc:
        raise ValidationApiError("request_id must be a UUID.") from exc
    public_id = "fgp_" + hashlib.sha256(f"{study.id}:{request_id}".encode()).hexdigest()[:40]
    # One study's persona numbering is one critical section, so two tabs cannot both take S03.
    _lock_cache_key_for_transaction(session, hashlib.sha256(f"fgp:{study.id}".encode()).hexdigest())
    existing = session.scalar(select(Job).where(Job.public_id == public_id))
    if existing:
        return _view(existing)  # a double-clicked Save resolves to one persona
    count = len(_study_personas(session, study))
    if count >= MAX_PER_STUDY:
        raise ValidationApiError(f"A study holds at most {MAX_PER_STUDY} practice personas.")
    job = Job(public_id=public_id, study_id=study.id, job_type=JOB_TYPE, status="active",
              payload_json={"persona_id": f"S{count + 1:02d}", "version": 1, "fields": fields,
                            "based_on": based_on},
              result_json=None, queued_at=utcnow())
    session.add(job)
    session.commit()
    return _view(job)


@serialized_local
def update_persona(session, study, persona_public_id, payload):
    """Edits make a new version. A room already running keeps the version it seated."""
    payload = payload or {}
    job = session.scalar(select(Job).where(Job.public_id == persona_public_id, Job.study_id == study.id,
                                           Job.job_type == JOB_TYPE).with_for_update())
    if not job:
        raise NotFoundApiError("Practice persona not found.")
    if payload.get("version") != job.payload_json["version"]:
        raise ConflictApiError("This persona was edited elsewhere. Reload it before saving.")
    fields = clean_fields(payload.get("fields"))
    job.payload_json = {**job.payload_json, "fields": fields, "version": job.payload_json["version"] + 1}
    session.commit()
    return _view(job)


def is_student_persona_id(persona_id):
    return len(persona_id) == 3 and persona_id[0] == "S" and persona_id[1:].isdigit()


def frozen_seats(session, study, persona_ids):
    """The exact version of each student persona a room seats, copied into the room."""
    wanted = {pid for pid in persona_ids if is_student_persona_id(pid)}
    if not wanted:
        return {}
    found = {view["persona_id"]: view for view in list_personas(session, study) if view["persona_id"] in wanted}
    if set(found) != wanted:
        raise ValidationApiError("One or more of the selected personas is unavailable.")
    return {pid: {"id": view["id"], "version": view["version"], "based_on": view["based_on"],
                  "style": view["fields"]["style"], "description": view["description"], "card": view["card"]}
            for pid, view in found.items()}
