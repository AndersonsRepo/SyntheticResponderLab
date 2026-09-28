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


def save(client, study_id, room_state, body, base_version=None):
    """Saves as the page does: on top of the memo version it last loaded (the current one)."""
    if base_version is None:
        base_version = (get_room(client, study_id, room_state).get("manual_memo") or {}).get("version", 0)
    return client.post(base(study_id, room_state) + "/manual-memo",
                       json={"memo": body, "base_version": base_version})


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
    padded = {"themes": [{"label": "Cold garage"}, {}, {}], "answer_options": [{}, {}, {}]}
    save(client, study_id, finished, padded)
    assert "(no label)" not in export(client, study_id, finished)["content"], "form padding is not content"


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
    from src.services import focus_group_personas as fgp
    for module, name in ((fg, "save_manual_memo"), (fg, "extend_room"),
                         (fgp, "create_persona"), (fgp, "update_persona")):
        assert getattr(getattr(module, name), "__wrapped__", None) is not None, name


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


# --- Fix 4: targeted questions, silence, probes --------------------------------

def default_start(client, study_id):
    """A room started the way the page starts one now: no explicit max_rounds."""
    from uuid import uuid4
    return client.post(f"/api/v1/studies/{study_id}/interview/focus-group/rooms", json={
        "request_id": str(uuid4()), "persona_ids": list(THREE), "model": "openai/gpt-4o-mini"}).json()["data"]["room"]


def test_targeted_question_makes_one_call_and_leaves_the_others_silent(room):
    client, study_id, calls, _ = room
    walked = walk(client, study_id, start(client, study_id).json()["data"]["room"], FUNNEL[:1])
    spent = len(calls)
    asked = ask(client, study_id, walked, stage="icebreaker", question="Tell me more about your weekday?",
                recipients=["P002"])
    assert asked.status_code == 200, asked.text
    state = asked.json()["data"]["room"]
    assert len(calls) == spent + 1
    assert calls[-1]["messages"][-1]["content"] == "Moderator (to P002): Tell me more about your weekday?"
    answers = {a["persona_id"]: a for a in state["rounds"][-1]["answers"]}
    assert answers["P002"]["status"] == "answered" and answers["P002"]["text"].startswith("P002")
    assert [answers[p]["status"] for p in ("P001", "P003")] == ["silent", "silent"]
    assert answers["P001"]["error"] is None and answers["P003"]["error"] is None
    assert state["status"] == "running" and state["error"] is None
    assert state["rounds"][-1]["recipients"] == ["P002"] and state["rounds"][-1]["kind"] == "probe"


def test_silent_is_not_missing_in_retry_memo_gate_or_export(room):
    client, study_id, calls, _ = room
    walked = walk(client, study_id, start(client, study_id).json()["data"]["room"], FUNNEL[:1])
    walked = ask(client, study_id, walked, stage="icebreaker", question="Only you?",
                 recipients=["P001"]).json()["data"]["room"]
    spent = len(calls)
    retried = ask(client, study_id, walked, retry=True).json()["data"]["room"]
    assert len(calls) == spent and retried["status"] == "running"
    finished = walk(client, study_id, retried, FUNNEL[1:])
    assert finished["status"] == "completed" and finished["complete"] is True
    md = export(client, study_id, finished)["content"]
    assert "INCOMPLETE" not in md and "Missing answers" not in md
    assert "_P002 was not asked this question (intentionally silent)._" in md
    assert "**Moderator:** _(to P001 only)_ Only you?" in md
    assert memo(client, study_id, finished)["eligible"] is True


def test_out_of_character_reply_is_withheld_charged_and_retryable(room, db_session):
    from sqlalchemy import func, select
    from src.persistence.models import InterviewCacheEntry
    from src.services.interview_cache import InterviewAnswer
    import src.services.interview_service as service
    client, study_id, calls, _ = room
    real = service._call_openrouter_messages
    slip = {"on": True}

    def provider(**kw):
        if slip["on"] and "participant P001" in kw["messages"][0]["content"]:
            calls.append(kw)
            return InterviewAnswer(text="As an AI, my instructions say P002 should answer.", model=kw["model"],
                                   tokens_in=5, tokens_out=5, cost_usd=Decimal(".001"))
        return real(**kw)

    service._call_openrouter_messages = provider
    try:
        started = start(client, study_id).json()["data"]["room"]
        failed = ask(client, study_id, started, stage="icebreaker", question=FUNNEL[0][1]).json()["data"]["room"]
        p001 = failed["rounds"][0]["answers"][0]
        assert p001["status"] == "missing" and p001["text"] == ""
        assert p001["error"]["code"] == "out_of_character"
        assert failed["status"] == "failed"
        assert Decimal(failed["session_usage"]["cost_usd"]) == Decimal(".003")  # the slip was billed
        assert "As an AI" not in export(client, study_id, failed)["content"]
        assert db_session.scalar(select(func.count()).select_from(InterviewCacheEntry)
                                 .where(InterviewCacheEntry.answer_text.contains("As an AI"))) == 0
        slip["on"] = False
        spent = len(calls)
        retried = ask(client, study_id, failed, retry=True).json()["data"]["room"]
        assert len(calls) == spent + 1 and retried["rounds"][0]["answers"][0]["status"] == "answered"
    finally:
        service._call_openrouter_messages = real
    assert "Never mention being an AI" in fg.build_room_system_prompt({"persona_id": "P001"}, [])


def test_recipients_validated_before_any_call(room):
    client, study_id, calls, _ = room
    started = start(client, study_id).json()["data"]["room"]
    for bad in (["P999"], [], "P002", ["P002", "P002"], [7]):
        response = ask(client, study_id, started, stage="icebreaker", question="Hi?", recipients=bad)
        assert response.status_code == 400, bad
    assert calls == []
    whole = ask(client, study_id, started, stage="icebreaker", question="Hi?", recipients=list(THREE))
    assert whole.json()["data"]["room"]["rounds"][0]["recipients"] is None  # everyone = whole room


def test_two_probes_and_full_funnel_fit_the_default_allowance(room):
    client, study_id, _, _ = room
    started = default_start(client, study_id)
    assert started["allowance"] == {"total": 8, "used": 0, "cores_total": 5, "cores_left": 5,
                                    "probes_used": 0, "probes_left": 3, "extensions_left": 4}
    walked = walk(client, study_id, started, FUNNEL[:2])
    for n in range(2):
        response = ask(client, study_id, walked, stage="space_needs", question=f"Probe {n}?",
                       recipients=["P003"] if n else None)
        assert response.status_code == 200, response.text
        walked = response.json()["data"]["room"]
    finished = walk(client, study_id, walked, FUNNEL[2:])
    assert finished["status"] == "completed"
    assert finished["allowance"]["probes_used"] == 2 and finished["allowance"]["cores_left"] == 0


def test_probes_never_starve_the_funnel_and_the_refusal_names_the_extension(room):
    client, study_id, calls, _ = room
    walked = walk(client, study_id, default_start(client, study_id), FUNNEL[:1])
    for n in range(3):
        walked = ask(client, study_id, walked, stage="icebreaker", question=f"Probe {n}?").json()["data"]["room"]
    spent = len(calls)
    refused = ask(client, study_id, walked, stage="icebreaker", question="One more?")
    assert refused.status_code == 400
    message = refused.json()["error"]["message"]
    assert "No follow-up probes left" in message and "extend" in message and "4 question(s)" in message
    assert len(calls) == spent
    assert walk(client, study_id, walked, FUNNEL[1:])["status"] == "completed"


def test_extension_needs_authorization_and_fits_the_budget(room):
    client, study_id, calls, _ = room
    walked = walk(client, study_id, default_start(client, study_id), FUNNEL[:1])
    url = base(study_id, walked) + "/extend"
    assert client.post(url, json={"revision": walked["revision"], "extra_rounds": 2}).status_code == 400
    assert client.post(url, json={"revision": walked["revision"], "extra_rounds": 5,
                                  "authorize_charge": True}).status_code == 400
    extended = client.post(url, json={"revision": walked["revision"], "extra_rounds": 2,
                                      "authorize_charge": True}).json()["data"]["room"]
    assert extended["allowance"]["probes_left"] == 5 and extended["allowance"]["extensions_left"] == 2
    assert Decimal(extended["estimated_total_cost_usd"]) == Decimal(extended["estimated_cost_usd"]) + \
        2 * Decimal(extended["extension_cost_per_round_usd"])
    again = client.post(url, json={"revision": walked["revision"], "extra_rounds": 2,
                                   "authorize_charge": True}).json()["data"]["room"]
    assert again["allowance"]["probes_left"] == 5, "a double-click extends once"
    client.app.state.settings.llm_budget_usd = Decimal(".0035")  # already spent .003
    over = client.post(url, json={"revision": extended["revision"], "extra_rounds": 2, "authorize_charge": True})
    assert over.status_code == 429 and "budget" in over.json()["error"]["message"].lower()
    assert calls and all(c["model"] for c in calls)  # the extension itself never calls a model
    assert len(calls) == 3


# --- Fix 3: student-created practice personas -----------------------------------

FIELDS = {"name": "Dana", "household": "Two adults and a toddler in a three-bedroom house",
          "tenure": "owner", "outdoor_space": "yes", "outdoor_note": "a flat side yard",
          "current_space_use": "the dining table doubles as an office", "willing_more_space": "maybe",
          "constraints": "tight budget after daycare", "style": "brief",
          "research_link": "Tests whether young families see a backyard office as childcare relief."}


def personas_url(study_id):
    return f"/api/v1/studies/{study_id}/interview/focus-group/personas"


def create(client, study_id, fields=FIELDS, **extra):
    from uuid import uuid4
    return client.post(personas_url(study_id), json={"request_id": str(uuid4()), "fields": fields, **extra})


def seat(client, study_id, persona_ids):
    return start(client, study_id, persona_ids=persona_ids)


def test_custom_persona_lifecycle_preview_save_edit_recruit(room):
    client, study_id, calls, _ = room
    preview = client.post(personas_url(study_id), json={"fields": FIELDS, "preview": True}).json()["data"]["persona"]
    assert preview["preview"] is True and preview["card"]["origin"] == "student_created"
    assert "flat side yard" in preview["description"]
    assert client.get(personas_url(study_id)).json()["data"]["personas"] == [], "preview stores nothing"
    made = create(client, study_id).json()["data"]["persona"]
    assert (made["persona_id"], made["version"]) == ("S01", 1)
    edited = client.post(f"{personas_url(study_id)}/{made['id']}",
                         json={"version": 1, "fields": {**FIELDS, "constraints": "HOA rules"}}).json()["data"]["persona"]
    assert edited["version"] == 2 and edited["card"]["version"] == 2
    stale = client.post(f"{personas_url(study_id)}/{made['id']}", json={"version": 1, "fields": FIELDS})
    assert stale.status_code == 409
    started = seat(client, study_id, ["P001", "P002", "S01"])
    assert started.status_code == 200, started.text
    room_state = started.json()["data"]["room"]
    ask(client, study_id, room_state, stage="icebreaker", question=FUNNEL[0][1])
    s01 = [c for c in calls if "participant S01" in c["messages"][0]["content"]]
    assert len(s01) == 1 and "HOA rules" in s01[0]["messages"][0]["content"]
    assert fg._MANNERS[0] in s01[0]["messages"][0]["content"], "brief style is the manner"


def test_duplicate_and_edit_starts_from_a_roster_persona_and_is_fictional(room):
    client, study_id, _, _ = room
    copy = create(client, study_id, based_on="P004").json()["data"]["persona"]
    assert copy["based_on"] == "P004"
    assert "copy of P004" in copy["card"]["origin_label"]
    assert {a["source"] for a in copy["card"]["attributes"]} <= {"fictional", "unknown"}
    assert create(client, study_id, based_on="P999").status_code == 400


def test_frozen_version_used_once_discussion_starts(room):
    client, study_id, calls, _ = room
    made = create(client, study_id).json()["data"]["persona"]
    room_state = seat(client, study_id, ["P001", "P002", "S01"]).json()["data"]["room"]
    client.post(f"{personas_url(study_id)}/{made['id']}",
                json={"version": 1, "fields": {**FIELDS, "household": "A retired couple"}})
    walked = walk(client, study_id, room_state, FUNNEL[:2])
    prompts = [c["messages"][0]["content"] for c in calls if "participant S01" in c["messages"][0]["content"]]
    assert len(prompts) == 2 and all("toddler" in p and "retired" not in p for p in prompts)
    assert {p["persona_id"]: p["card"].get("version") for p in walked["participants"]}["S01"] == 1
    fresh = seat(client, study_id, ["P001", "P002", "S01"]).json()["data"]["room"]
    assert {p["persona_id"]: p["card"].get("version") for p in fresh["participants"]}["S01"] == 2


def test_custom_export_names_origin_and_version_and_no_real_participant(room):
    client, study_id, _, _ = room
    create(client, study_id, based_on="P004")
    room_state = seat(client, study_id, ["P001", "P002", "S01"]).json()["data"]["room"]
    card = {p["persona_id"]: p["card"] for p in room_state["participants"]}["S01"]
    assert card["origin_label"].startswith("Student-created fictional persona")
    md = export(client, study_id, room_state)["content"]
    assert "S01: Student-created fictional persona, version 1, started from a copy of P004. " \
           "Not a real PA3.5 participant." in md
    assert "P001: roster persona grounded in one ACS household record" in md
    assert "Real PA3.5 participants in this room: 0" in md
    csv_text = export(client, study_id, room_state, "csv")["content"]
    assert "participant,S01,student_created_fictional,1,P004,False" in csv_text


def test_research_link_required_never_an_opinion_and_never_sent_to_the_model(room):
    client, study_id, calls, _ = room
    missing = create(client, study_id, fields={**FIELDS, "research_link": ""})
    assert missing.status_code == 400 and "research question" in missing.json()["error"]["message"]
    made = create(client, study_id, fields={**FIELDS, "product_opinion": "loves it",
                                            "desired_findings": "they buy"}).json()["data"]["persona"]
    assert "product_opinion" not in made["fields"] and "desired_findings" not in made["fields"]
    walk(client, study_id, seat(client, study_id, ["P001", "P002", "S01"]).json()["data"]["room"], FUNNEL[:1])
    assert calls and all(FIELDS["research_link"] not in joined(c) for c in calls)
    assert all("loves it" not in joined(c) for c in calls)


def test_custom_persona_isolated_to_its_own_study(room):
    client, study_id, _, _ = room
    made = create(client, study_id).json()["data"]["persona"]
    other = client.post("/api/v1/studies", json={}).json()["data"]["study"]["study_id"]
    assert client.get(personas_url(other)).json()["data"]["personas"] == []
    hijack = client.post(f"{personas_url(other)}/{made['id']}", json={"version": 1, "fields": FIELDS})
    assert hijack.status_code == 404
    assert seat(client, other, ["P001", "P002", "S01"]).status_code == 400


def test_custom_persona_bounds_refused_and_nothing_stored(room):
    from src.services import focus_group_personas as fgp
    client, study_id, _, _ = room
    for bad in ("text", {**FIELDS, "household": "x" * 301}, {**FIELDS, "tenure": "castle"},
                {**FIELDS, "household": ""}, {**FIELDS, "name": 7}, {**FIELDS, "style": "shouty"}):
        response = create(client, study_id, fields=bad)
        assert response.status_code == 400, bad
    assert client.get(personas_url(study_id)).json()["data"]["personas"] == []
    for _ in range(fgp.MAX_PER_STUDY):
        assert create(client, study_id).status_code == 200
    over = create(client, study_id)
    assert over.status_code == 400 and "at most" in over.json()["error"]["message"]


def test_student_data_stays_in_the_focus_group_rows(room, db_session, caplog):
    import logging
    from sqlalchemy import select
    from src.persistence.models import InterviewCacheEntry, InterviewTurn, Job
    client, study_id, _, behavior = room
    marker = "zebra-marker-4711"
    caplog.set_level(logging.DEBUG)
    create(client, study_id, fields={**FIELDS, "constraints": f"{marker} constraint",
                                     "research_link": f"{marker} link"})
    room_state = seat(client, study_id, ["P001", "P002", "S01"]).json()["data"]["room"]
    behavior["fail"] = lambda pid: pid == "P002"  # the failure path logs too
    room_state = ask(client, study_id, room_state, stage="icebreaker", question=FUNNEL[0][1]).json()["data"]["room"]
    save(client, study_id, room_state, {"moderation_improvement": f"{marker} memo"})
    for entry in db_session.scalars(select(InterviewCacheEntry)).all():
        assert marker not in entry.question and marker not in entry.answer_text
    assert all(marker not in (t.text or "") for t in db_session.scalars(select(InterviewTurn)).all())
    assert marker not in caplog.text
    rows = [j for j in db_session.scalars(select(Job)).all()
            if marker in str(j.payload_json) + str(j.result_json)]
    assert rows and {j.job_type for j in rows} <= {"focus_group_room", "focus_group_persona"}


# --- Refuter round: legacy rooms and the review's concerns ----------------------------------

def seed_legacy(client, study_id, db_session, stages, payload=None, status="running"):
    """A room exactly as the pre-branch API stored it (rooms students ran on 2026-09-23):
    rounds with no kind, no recipients, no stimulus."""
    from sqlalchemy import select
    from src.persistence.models import Job
    room_state = start(client, study_id).json()["data"]["room"]
    job = db_session.scalar(select(Job).where(Job.public_id == room_state["room_id"]))
    rounds = [{"index": i, "stage": stage, "question": f"Legacy {stage} question?",
               "post_exposure": False,
               "answers": [{"persona_id": pid, "text": f"{pid} said something about {stage}.",
                            "status": "answered", "error": None} for pid in THREE]}
              for i, stage in enumerate(stages)]
    job.result_json = {"revision": len(rounds), "stage_index": fg.STAGES.index(stages[-1]),
                       "rounds": rounds, "memo": None}
    job.payload_json = payload or {"persona_ids": list(THREE), "model": "openai/gpt-4o-mini",
                                   "max_rounds": 12, "estimated_cost_usd": "0.0100"}
    job.status = status
    db_session.commit()
    return get_room(client, study_id, room_state)


def test_legacy_room_exposure_derived_from_stage(room, db_session):
    client, study_id, calls, _ = room
    legacy = seed_legacy(client, study_id, db_session, ["icebreaker", "space_needs", "concept", "price_reactions"])
    md = export(client, study_id, legacy)["content"]
    assert "never — participants were not shown it" not in md
    assert "- Concept introduced: before round 3 (`R3-MOD`)" in md
    assert "- Price revealed: before round 4 (`R4-MOD`)" in md
    assert "Price: about $23,000" in md and "before Introduce/Reveal existed" in md
    csv_text = export(client, study_id, legacy, "csv")["content"]
    assert "R3-STIMULUS" in csv_text and "R4-STIMULUS" in csv_text
    assert [s["kind"] for s in legacy["shared"]] == ["concept", "price"]
    assert legacy["stages_reached"] == ["icebreaker", "space_needs", "concept", "price_reactions"]
    # Going back to space_needs after the old stage map showed concept and price.
    back = ask(client, study_id, legacy, stage="space_needs", question="Where do you run out of room now?")
    assert back.status_code == 200, back.text
    back = back.json()["data"]["room"]
    assert back["rounds"][-1]["post_exposure"] is True
    system = calls[-1]["messages"][0]["content"]
    assert "Nothing about any product" not in system and "No price has been shown" not in system
    assert "Tahoe Mini" in system and "$23,000" in system
    # The price was (legacy-)shown, so the moderator may name it; neither can be revealed twice.
    named = ask(client, study_id, back, stage="close", question="At $23,000, would you buy it?")
    assert named.status_code == 200, named.text
    assert named.json()["data"]["room"]["status"] == "completed"
    assert memo(client, study_id, named.json()["data"]["room"])["eligible"] is True
    again = seed_legacy(client, study_id, db_session, ["icebreaker", "space_needs", "concept"])
    refused = ask(client, study_id, again, stage="concept", question="Look again?", reveal="concept")
    assert refused.status_code == 400 and "already been shown" in refused.json()["error"]["message"]


def test_legacy_room_with_missing_payload_keys_or_retired_model_opens_and_exports(room, db_session):
    """git log -p on start_room: every stored room has persona_ids, model, max_rounds and
    estimated_cost_usd (all since the first commit). A partially written row, or a model that
    has since left the catalog, must still open rather than 500."""
    client, study_id, _, _ = room
    for payload in ({"persona_ids": list(THREE)},
                    {"persona_ids": list(THREE), "model": "retired/model", "max_rounds": 12,
                     "estimated_cost_usd": "0.01"}):
        legacy = seed_legacy(client, study_id, db_session, ["icebreaker", "space_needs"], payload=payload)
        assert legacy["allowance"]["total"] == fg.MAX_ROUNDS
        assert legacy["extension_cost_per_round_usd"] is None
        assert export(client, study_id, legacy)["content"]
        rooms = client.get(f"/api/v1/studies/{study_id}/interview/focus-group/rooms")
        assert rooms.status_code == 200


def test_memo_stale_write_refused_and_untouched_memo_not_persisted(room):
    client, study_id, _, _ = room
    finished = walk(client, study_id, start(client, study_id).json()["data"]["room"])
    blank = {"themes": [{}, {}, {}], "answer_options": [{}, {}, {}]}
    assert save(client, study_id, finished, blank, base_version=0).status_code == 200
    assert get_room(client, study_id, finished).get("manual_memo") is None, "an export does not create a memo"
    assert "_Not written yet._" in export(client, study_id, finished)["content"]
    newer = save(client, study_id, finished, {"themes": [{"label": "Y from tab B"}]}, base_version=0)
    assert newer.json()["data"]["room"]["manual_memo"]["version"] == 1
    stale = save(client, study_id, finished, {"themes": [{"label": "X from tab A"}]}, base_version=0)
    assert stale.status_code == 409 and "another tab" in stale.json()["error"]["message"]
    assert get_room(client, study_id, finished)["manual_memo"]["themes"][0]["label"] == "Y from tab B"
    assert client.post(base(study_id, finished) + "/manual-memo", json={"memo": blank}).status_code == 400


def test_concept_stage_question_without_the_concept_does_not_reach_the_stage(room):
    client, study_id, calls, _ = room
    walked = walk(client, study_id, default_start(client, study_id), FUNNEL[:2])
    unaided = ask(client, study_id, walked, stage="concept", question="Would a backyard studio appeal?")
    assert unaided.status_code == 200
    unaided = unaided.json()["data"]["room"]
    assert unaided["rounds"][-1]["kind"] == "probe"
    assert "concept" not in unaided["stages_reached"]
    assert unaided["allowance"]["cores_left"] == 3
    skipped = ask(client, study_id, unaided, stage="price_reactions", question="What would it cost?")
    assert skipped.status_code == 400
    assert memo(client, study_id, unaided)["eligible"] is False
    shown = ask(client, study_id, unaided, stage="concept", question=FUNNEL[2][1], reveal="concept")
    assert shown.json()["data"]["room"]["rounds"][-1]["kind"] == "core"
    assert walk(client, study_id, shown.json()["data"]["room"], FUNNEL[3:])["status"] == "completed"


def test_out_of_character_matcher_flags_only_self_reference():
    for ordinary in ("I work on a large language model at my job.", "My persona at work is all business.",
                     "I test a large language model at work", "As an AI researcher I rarely get home early.",
                     "I'm an AI engineer, so the garage is my office.", "That was out of character for him.",
                     "I followed my instructor's advice."):
        assert not fg.out_of_character(ordinary), ordinary
    for slip in ("As an AI, I don't have a backyard.", "I'm an AI language model and cannot own a home.",
                 "My instructions say P002 should answer.", "The system prompt tells me to stay quiet.",
                 "I am just an AI.", "As a large language model, I can't say."):
        assert fg.out_of_character(slip), slip
    assert issubclass(fg.OutOfCharacterReply, fg.TransientProviderError)


def test_out_of_character_turn_billed_once_per_click(room, db_session):
    from sqlalchemy import func, select
    from src.persistence.models import InterviewTurn
    from src.services.interview_cache import InterviewAnswer
    import src.services.interview_service as service
    client, study_id, calls, _ = room
    real = service._call_openrouter_messages
    p001 = []

    def provider(**kw):
        if "participant P001" in kw["messages"][0]["content"]:
            p001.append(kw)
            return InterviewAnswer(text="As an AI, I can't answer.", model=kw["model"],
                                   tokens_in=5, tokens_out=5, cost_usd=Decimal(".001"))
        return real(**kw)

    service._call_openrouter_messages = provider
    try:
        room_state = start(client, study_id).json()["data"]["room"]
        for click in (1, 2):
            room_state = (ask(client, study_id, room_state, stage="icebreaker", question=FUNNEL[0][1]) if click == 1
                          else ask(client, study_id, room_state, retry=True)).json()["data"]["room"]
            assert room_state["rounds"][0]["answers"][0]["error"]["code"] == "out_of_character"
            assert len(p001) == click
            rows = db_session.scalar(select(func.count()).select_from(InterviewTurn).where(
                InterviewTurn.session_id == room_state["room_id"], InterviewTurn.persona_id == "P001"))
            assert rows == click
    finally:
        service._call_openrouter_messages = real


def test_extend_with_stale_revision_is_refused_not_silently_ignored(room):
    client, study_id, calls, _ = room
    walked = walk(client, study_id, default_start(client, study_id), FUNNEL[:1])
    url = base(study_id, walked) + "/extend"
    moved = ask(client, study_id, walked, stage="space_needs", question=FUNNEL[1][1]).json()["data"]["room"]
    stale = client.post(url, json={"revision": walked["revision"], "extra_rounds": 2, "authorize_charge": True})
    assert stale.status_code == 409 and "nothing was added or charged" in stale.json()["error"]["message"]
    assert get_room(client, study_id, moved)["allowance"]["extensions_left"] == 4
    body = {"revision": moved["revision"], "extra_rounds": 2, "authorize_charge": True}
    assert client.post(url, json=body).status_code == 200
    assert client.post(url, json=body).status_code == 200, "a double-click is not a conflict"
    assert get_room(client, study_id, moved)["allowance"]["extensions_left"] == 2
    other = client.post(url, json={**body, "extra_rounds": 1})
    assert other.status_code == 409


# --- The student's product photo (2026-09-27) --------------------------------

PHOTO = {"filename": "tahoe-mini.jpg", "caption": "A small cedar-clad cabin with a glass door on a lawn."}


def introduce(client, study_id, walked, photo=PHOTO):
    return ask(client, study_id, walked, stage="concept", question=fg.CONCEPT_CARD["introduction"],
               reveal="concept", photo=photo)


def test_photo_caption_withheld_until_introduced(room):
    client, study_id, calls, _ = room
    walked = walk(client, study_id, start(client, study_id).json()["data"]["room"], FUNNEL[:2])
    spent = len(calls)
    for stage in ("space_needs", "concept"):
        early = ask(client, study_id, walked, stage=stage, question="Q?", photo=PHOTO)
        assert early.status_code == 400 and "introduces the concept" in early.json()["error"]["message"]
    assert len(calls) == spent
    assert all("cedar" not in joined(call) for call in calls)


def test_photo_caption_reaches_participants_after_introduction(room):
    client, study_id, calls, _ = room
    walked = walk(client, study_id, start(client, study_id).json()["data"]["room"], FUNNEL[:2])
    before = len(calls)
    introduced = introduce(client, study_id, walked)
    assert introduced.status_code == 200, introduced.text
    walked = walk(client, study_id, introduced.json()["data"]["room"], FUNNEL[3:])
    assert all("cedar" not in joined(c) for c in calls[:before])
    assert all(PHOTO["caption"] in c["messages"][0]["content"] for c in calls[before:])
    assert all("tahoe-mini.jpg" not in joined(c) for c in calls)
    assert PHOTO["caption"] in walked["shared"][0]["text"]


def test_photo_caption_price_refused_before_reveal(room):
    client, study_id, calls, _ = room
    walked = walk(client, study_id, start(client, study_id).json()["data"]["room"], FUNNEL[:2])
    spent = len(calls)
    for caption in ("Tag reads $23,000", "Sticker says 23,000", "price 23000 on the tag"):
        refused = introduce(client, study_id, walked, {"filename": "a.jpg", "caption": caption})
        assert refused.status_code == 400 and "dollar figure" in refused.json()["error"]["message"]
    assert len(calls) == spent


def test_photo_fields_bounded(room):
    client, study_id, calls, _ = room
    walked = walk(client, study_id, start(client, study_id).json()["data"]["room"], FUNNEL[:2])
    spent = len(calls)
    for bad in ({"filename": "a.jpg", "caption": "x" * 501}, {"filename": "", "caption": "x"},
                {"filename": "a" * 201, "caption": "x"}, "data:image/png;base64,AAAA",
                {"filename": "a.jpg", "caption": "x", "data": "data:image/png;base64,AAAA"}):
        assert introduce(client, study_id, walked, bad).status_code == 400
    assert len(calls) == spent


def test_photo_in_export(room):
    client, study_id, _, _ = room
    walked = walk(client, study_id, start(client, study_id).json()["data"]["room"], FUNNEL[:2])
    walked = introduce(client, study_id, walked).json()["data"]["room"]
    line = f"Photo shown: tahoe-mini.jpg, described as: {PHOTO['caption']}"
    assert line in export(client, study_id, walked)["content"]
    assert line in export(client, study_id, walked, "csv")["content"]
    bare = walk(client, study_id, start(client, study_id).json()["data"]["room"], FUNNEL[:2])
    bare = introduce(client, study_id, bare, {"filename": "b.png", "caption": ""}).json()["data"]["room"]
    assert "Photo shown: b.png, described as: (no description)" in export(client, study_id, bare)["content"]
    assert bare["shared"][0]["text"] == fg.CONCEPT_STIMULUS


def test_no_photo_room_unchanged(room):
    client, study_id, calls, _ = room
    walked = walk(client, study_id, start(client, study_id).json()["data"]["room"], FUNNEL[:3])
    stimulus = walked["rounds"][2]["stimulus"]
    assert stimulus == {"kind": "concept", "text": fg.CONCEPT_STIMULUS}
    assert all("Photo" not in joined(c) for c in calls)
    for fmt in ("markdown", "csv"):
        assert "Photo shown" not in export(client, study_id, walked, fmt)["content"]
