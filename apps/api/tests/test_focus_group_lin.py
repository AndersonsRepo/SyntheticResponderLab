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


# --- Fix 2: the concept is shown, and information is released on purpose ---

PRICE_FIGURES = ("23,000", "23000", "$23")


def joined(call):
    return " ".join(m["content"] for m in call["messages"])


def test_concept_card_is_the_stimulus_participants_receive(room):
    client, study_id, calls, _ = room
    started = start(client, study_id).json()["data"]["room"]
    card = started["concept_card"]
    assert card["name"] and card["description"] and card["specs"] and card["introduction"]
    assert card["text"] == fg.CONCEPT_STIMULUS
    walked = walk(client, study_id, started, FUNNEL[:3])
    for call in calls[-3:]:
        assert card["text"] in call["messages"][0]["content"]
    assert walked["shared"][0]["text"] == card["text"]


def test_concept_withheld_until_introduced_even_at_the_concept_stage(room):
    client, study_id, calls, _ = room
    walked = walk(client, study_id, start(client, study_id).json()["data"]["room"], FUNNEL[:2])
    asked = ask(client, study_id, walked, stage="concept", question="What would you use a backyard studio for?")
    assert asked.status_code == 200
    for call in calls:
        text = joined(call)
        assert "Tahoe" not in text and "117" not in text and "PRODUCT CONCEPT" not in text
        assert "YOUR STANCE GOING IN" not in text
        assert "Nothing about any product" in call["messages"][0]["content"]
    introduced = ask(client, study_id, asked.json()["data"]["room"], stage="concept",
                     question=fg.CONCEPT_CARD["introduction"], reveal="concept")
    assert introduced.status_code == 200
    assert all("Tahoe Mini" in c["messages"][0]["content"] for c in calls[-3:])


def test_price_never_reaches_model_before_reveal_across_all_five_stages(room):
    import inspect
    client, study_id, calls, _ = room
    # The one place the figure lives in the focus-group code is the withheld stimulus.
    assert inspect.getsource(fg).count("23,000") == 1 and "23,000" in fg.PRICE_STIMULUS
    walked = walk(client, study_id, start(client, study_id).json()["data"]["room"])
    assert walked["status"] == "completed" and len(calls) == 15
    for call in calls:
        assert not any(figure in joined(call) for figure in PRICE_FIGURES), joined(call)
        assert "No price has been shown to you" in call["messages"][0]["content"]
    assert [s["kind"] for s in walked["shared"]] == ["concept"]


def test_reveal_price_order_is_concept_then_unaided_question_then_price(room):
    client, study_id, calls, _ = room
    started = start(client, study_id).json()["data"]["room"]
    early = ask(client, study_id, started, stage="icebreaker", question="Hi?", reveal="concept")
    assert early.status_code == 400 and "concept stage" in early.json()["error"]["message"]
    walked = walk(client, study_id, started, FUNNEL[:2])
    no_concept = ask(client, study_id, walked, stage="concept", question="Q?", reveal="price")
    assert no_concept.status_code == 400 and "concept before" in no_concept.json()["error"]["message"]
    walked = walk(client, study_id, walked, FUNNEL[2:3])
    twice = ask(client, study_id, walked, stage="concept", question="Again?", reveal="concept")
    assert twice.status_code == 400 and "already been shown" in twice.json()["error"]["message"]
    unaided_first = ask(client, study_id, walked, stage="price_reactions", question="Cost?", reveal="price")
    assert unaided_first.status_code == 400 and "unaided" in unaided_first.json()["error"]["message"]
    bogus = ask(client, study_id, walked, stage="concept", question="Q?", reveal="discount")
    assert bogus.status_code == 400
    spent = len(calls)
    walked = walk(client, study_id, walked, FUNNEL[3:4])
    revealed = ask(client, study_id, walked, stage="price_reactions",
                   question="It is about $23,000. How does that compare?", reveal="price")
    assert revealed.status_code == 200, revealed.text
    assert len(calls) == spent + 6
    assert all("PRICE SHOWN BY THE MODERATOR: about $23,000" in c["messages"][0]["content"] for c in calls[-3:])
    closed = walk(client, study_id, revealed.json()["data"]["room"], FUNNEL[4:])
    assert all("23,000" in c["messages"][0]["content"] for c in calls[-3:])
    assert closed["status"] == "completed"


def test_moderator_price_refused_before_reveal_at_every_stage(room):
    client, study_id, calls, _ = room
    walked = walk(client, study_id, start(client, study_id).json()["data"]["room"], FUNNEL[:4])
    spent = len(calls)
    for stage in ("concept", "price_reactions", "close"):
        refused = ask(client, study_id, walked, stage=stage, question="Would $19,999 be fair?")
        assert refused.status_code == 400 and "Reveal price" in refused.json()["error"]["message"]
    assert len(calls) == spent


def test_unshared_facts_are_unknown_to_participants(room):
    prompt = fg.build_room_system_prompt({"persona_id": "P001"}, [])
    assert "Nothing about any product" in prompt and "No price has been shown to you" in prompt
    assert "never state a figure as the product's actual price" in prompt
    concept = [{"kind": "concept", "text": fg.CONCEPT_STIMULUS}]
    assert "No price has been shown to you" in fg.build_room_system_prompt({"persona_id": "P001"}, concept)
    priced = fg.build_room_system_prompt(
        {"persona_id": "P001"}, concept + [{"kind": "price", "text": fg.PRICE_STIMULUS}])
    assert "No price has been shown to you" not in priced and fg.PRICE_STIMULUS in priced


def test_shared_info_in_export_and_room_names_each_stimulus_and_round(room):
    client, study_id, _, _ = room
    walked = walk(client, study_id, start(client, study_id).json()["data"]["room"], FUNNEL[:4])
    walked = ask(client, study_id, walked, stage="price_reactions", question="About $23,000 — reactions?",
                 reveal="price").json()["data"]["room"]
    assert [(s["kind"], s["round"], s["turn_id"]) for s in walked["shared"]] == [
        ("concept", 2, "R3-MOD"), ("price", 4, "R5-MOD")]
    md = export(client, study_id, walked)["content"]
    assert "- Concept introduced: before round 3 (`R3-MOD`)" in md
    assert "- Price revealed: before round 5 (`R5-MOD`)" in md
    assert "> PRICE SHOWN BY THE MODERATOR: about $23,000" in md
    assert "> Name: Tahoe Mini by Neo Smart Living" in md
    csv_text = export(client, study_id, walked, "csv")["content"]
    assert "Stimulus,shown_to_participants" in csv_text and "R5-STIMULUS" in csv_text
    unrevealed = walk(client, study_id, start(client, study_id).json()["data"]["room"], FUNNEL[:2])
    assert "- Price revealed: never" in export(client, study_id, unrevealed)["content"]


# --- Fix 1: who is in the room -------------------------------------------------

REQUIRED_CARD_KEYS = ["name", "household", "tenure", "outdoor_space", "willing_more_space"]


def test_persona_cards_mark_every_attribute_source_backed_fictional_or_unknown(room):
    client, _, _, _ = room
    personas = client.get("/api/v1/personas").json()["data"]["personas"]
    assert len(personas) == 30
    for persona in personas:
        card = persona["card"]
        keys = [a["key"] for a in card["attributes"]]
        assert keys[:5] == REQUIRED_CARD_KEYS, keys
        assert card["persona_id"] == persona["persona_id"] and card["name"]
        by_key = {a["key"]: a for a in card["attributes"]}
        assert by_key["name"]["source"] == "fictional"
        assert by_key["tenure"]["source"] == "census" and by_key["household"]["source"] == "census"
        for key in ("outdoor_space", "willing_more_space"):
            assert by_key[key] == {**by_key[key], "value": "Unknown", "source": "unknown"}
        for attribute in card["attributes"]:
            assert attribute["source"] in {"census", "fictional", "unknown"}
            assert attribute["value"], attribute
            assert (attribute["value"] == "Unknown") == (attribute["source"] == "unknown")
        assert "ACS" in card["source_note"] and "invented" in card["source_note"]


def test_screener_verdicts_say_meets_does_not_or_cannot_tell():
    from src.persistence.persona_seed import persona_card, persona_cards
    verdicts = [(s["criterion"], s["verdict"]) for s in persona_cards()["P001"]["screener"]]
    assert verdicts == [("Homeowner or landowner", "meets"), ("Has usable outdoor space", "unknown"),
                        ("Open to adding living or work space", "unknown")]
    renter = persona_card({"persona_id": "PX", "tenure_detail": "Rented"})["screener"][0]
    assert renter["verdict"] == "does_not_meet" and "Rented" in renter["why"]
    blank = persona_card({"persona_id": "PY"})
    assert blank["screener"][0]["verdict"] == "unknown"
    assert {a["key"]: a["value"] for a in blank["attributes"]}["tenure"] == "Unknown"
    assert all(s["why"] for s in blank["screener"])


def test_room_carries_participant_cards_including_after_reopen(room):
    client, study_id, _, _ = room
    started = start(client, study_id).json()["data"]["room"]
    assert [p["persona_id"] for p in started["participants"]] == THREE
    assert all(p["card"]["attributes"] for p in started["participants"])
    reopened = get_room(client, study_id, started)
    assert reopened["participants"] == started["participants"]


def test_cards_do_not_change_prompt_for_a_roster_persona(room, db_session):
    from src.persistence.models import Persona
    client, study_id, calls, _ = room
    ask(client, study_id, start(client, study_id).json()["data"]["room"], stage="icebreaker",
        question=FUNNEL[0][1])
    profile = db_session.get(Persona, "P001").profile_json
    assert "card" not in profile
    system = next(c for c in calls if "participant P001" in c["messages"][0]["content"])["messages"][0]["content"]
    assert fg.persona_description(profile) in system
    for card_only in ("Usable outdoor space", "Source-backed", "ACS", "Unknown", "screener"):
        assert card_only not in system
