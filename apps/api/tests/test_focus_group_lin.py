"""Dr. Lin's five focus-group fixes (after the 2026-09-23 class). His acceptance checks are the spec."""
from decimal import Decimal

from src.services import focus_group as fg
from test_focus_group import FUNNEL, THREE, ask, memo, room, start, walk, write_memo  # noqa: F401

LABEL = "Synthetic rehearsal - not PA3.5 live fieldwork"


def base(study_id, room_state):
    return f"/api/v1/studies/{study_id}/interview/focus-group/rooms/{room_state['room_id']}"


def get_room(client, study_id, room_state):
    return client.get(base(study_id, room_state)).json()["data"]["room"]


def turns(room_state):
    return {a["turn_id"]: a for r in room_state["rounds"] for a in r["answers"] if a["status"] == "answered"}


def full_memo(room_state):
    """A complete hand-written memo whose every quote is copied from a real turn."""
    answered = list(turns(room_state).values())
    quote = lambda a: {"turn_id": a["turn_id"], "text": a["text"][:30]}  # noqa: E731
    return {
        "themes": [{"label": f"Theme {n}", "synthesis": "What the room kept returning to.",
                    "quotes": [quote(answered[n])]} for n in range(3)],
        "surprise": {"summary": "Winter came up unprompted.", "quote": quote(answered[4])},
        "answer_options": [{"text": f"Option {n}", "topic": "current space use",
                            "turn_id": answered[n]["turn_id"]} for n in range(3)],
        "moderation_improvement": "Ask the quiet participant directly sooner.",
    }


def save(client, study_id, room_state, body):
    return client.post(base(study_id, room_state) + "/manual-memo", json={"memo": body})


def export(client, study_id, room_state, fmt="markdown"):
    return client.post(base(study_id, room_state) + "/export", json={"format": fmt}).json()["data"]["export"]


# --- Fix 5: the debrief works without AI ------------------------------------

def test_manual_memo_without_ai_saves_complete_with_no_model_call(room):
    client, study_id, calls, _ = room
    finished = walk(client, study_id, start(client, study_id).json()["data"]["room"])
    client.app.state.settings.openrouter_api_key = None
    spent = len(calls)
    saved = save(client, study_id, finished, full_memo(finished))
    assert saved.status_code == 200, saved.text
    check = saved.json()["data"]["room"]["manual_memo_check"]
    assert check == {"saved": True, "complete": True, "problems": []}
    assert len(calls) == spent
    # It survives a re-open (a refresh, a new tab).
    assert get_room(client, study_id, finished)["manual_memo"]["moderation_improvement"]


def test_stable_turn_ids_survive_retries_and_later_rounds(room):
    client, study_id, _, behavior = room
    walked = walk(client, study_id, start(client, study_id).json()["data"]["room"], FUNNEL[:2])
    before = {(r["index"], a["persona_id"]): a["turn_id"] for r in walked["rounds"] for a in r["answers"]}
    assert before[(0, "P002")] == "R1-P002" and walked["rounds"][0]["turn_id"] == "R1-MOD"
    behavior["fail"] = lambda pid: pid == "P003"
    failed = ask(client, study_id, walked, stage="concept", question=FUNNEL[2][1]).json()["data"]["room"]
    behavior["fail"] = None
    retried = ask(client, study_id, failed, retry=True).json()["data"]["room"]
    after = {(r["index"], a["persona_id"]): a["turn_id"] for r in retried["rounds"] for a in r["answers"]}
    assert all(after[key] == value for key, value in before.items())
    assert after[(2, "P003")] == "R3-P003"
    assert len(set(after.values())) == len(after)


def test_quote_must_link_to_an_answered_turn_or_it_is_flagged(room):
    client, study_id, _, _ = room
    finished = walk(client, study_id, start(client, study_id).json()["data"]["room"])
    body = full_memo(finished)
    body["themes"][0]["quotes"] = [{"turn_id": "R9-P001", "text": "anything"}]
    body["themes"][1]["quotes"] = [{"turn_id": "R1-P001", "text": "words nobody said"}]
    body["themes"][2]["quotes"] = [{"turn_id": "R1-MOD", "text": "Tell me"}]
    check = save(client, study_id, finished, body).json()["data"]["room"]["manual_memo_check"]
    assert check["complete"] is False
    joined = " ".join(check["problems"])
    assert "R9-P001" in joined and "R1-MOD" in joined and "not the words" in joined
    content = export(client, study_id, finished)["content"]
    assert content.count("NOT LINKED") == 3
    assert "`[R9-P001]`" not in content


def test_export_manual_memo_without_any_ai_memo(room):
    client, study_id, _, _ = room
    finished = walk(client, study_id, start(client, study_id).json()["data"]["room"])
    body = full_memo(finished)
    save(client, study_id, finished, body)
    md = export(client, study_id, finished)["content"]
    assert "## Student memo (written by the student)" in md and "AI draft memo" not in md
    first = body["themes"][0]["quotes"][0]
    assert f"\"{first['text']}\" — P001 `[{first['turn_id']}]`, Icebreaker round 1" in md
    assert "[current space use] \"Option 0\"" in md
    assert "Ask the quiet participant directly sooner." in md
    csv_text = export(client, study_id, finished, "csv")["content"]
    assert f"theme_quote,P001,Theme 0,{first['text']},linked,True,{first['turn_id']}" in csv_text


def test_failed_ai_memo_preserves_work_and_explains_the_charge(room):
    client, study_id, calls, behavior = room
    finished = walk(client, study_id, start(client, study_id).json()["data"]["room"])
    body = full_memo(finished)
    save(client, study_id, finished, body)
    behavior["memo"] = lambda transcript: '{"themes": [], "surprise": {}, "answer_options": []}'
    failed = write_memo(client, study_id, finished, memo(client, study_id, finished))
    message = failed["saved"]["message"]
    assert "could not be validated" in message and "themes" in message.lower()
    assert "charged $0.0020" in message
    assert "finish your memo by hand" in message and "new charge" in message
    after = get_room(client, study_id, finished)
    assert after["manual_memo"]["themes"][0]["quotes"] == body["themes"][0]["quotes"]
    assert after["rounds"] == finished["rounds"]
    spent = len(calls)
    md = export(client, study_id, finished)["content"]
    assert "## Student memo" in md and "DRAFT" not in md
    assert len(calls) == spent


def test_draft_memo_is_kept_and_the_export_names_what_is_missing(room):
    client, study_id, _, _ = room
    finished = walk(client, study_id, start(client, study_id).json()["data"]["room"])
    saved = save(client, study_id, finished, {"themes": [{"label": "Cold garage"}]}).json()["data"]["room"]
    check = saved["manual_memo_check"]
    assert check["saved"] and not check["complete"]
    assert any("at least 3 themes" in p for p in check["problems"])
    assert saved["manual_memo"]["themes"][0]["label"] == "Cold garage"
    md = export(client, study_id, finished)["content"]
    assert "DRAFT — not complete" in md and "at least 3 themes" in md


def test_memo_input_bounds_refused_and_nothing_stored(room):
    client, study_id, _, _ = room
    started = start(client, study_id).json()["data"]["room"]
    for bad in ("text", {"themes": [{}] * 7}, {"themes": [{"label": "x" * 201}]},
                {"themes": [{"quotes": ["R1-P001"]}]}, {"moderation_improvement": 5},
                {"answer_options": "one"}):
        response = save(client, study_id, started, bad)
        assert response.status_code == 400, bad
        assert response.json()["error"]["message"]
    assert get_room(client, study_id, started).get("manual_memo") is None


def test_rehearsal_label_on_every_export(room):
    client, study_id, _, _ = room
    started = start(client, study_id).json()["data"]["room"]
    assert started["rehearsal_label"] == LABEL
    assert LABEL in export(client, study_id, started)["content"].splitlines()[2]
    assert export(client, study_id, started, "csv")["content"].lstrip("﻿").startswith(LABEL)


def test_serialized_new_mutating_entry_points():
    for name in ("save_manual_memo",):
        assert getattr(getattr(fg, name), "__wrapped__", None) is not None, name
