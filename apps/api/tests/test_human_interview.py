"""AI interviews you: the batch interviewer asks, a student answers."""
from decimal import Decimal

import pytest
import requests
from sqlalchemy import select

from src.persistence.models import InterviewCacheEntry, InterviewTurn, Job
from src.services.interview_cache import InterviewAnswer
from src.services.interview_service import _call_openrouter_messages as real_provider
from src.services.model_catalog import DEFAULT_INTERVIEW_MODEL_ID
from src.services.standalone_interview import RESEARCH_BRIEF

ALICE = {'x-authenticated-user-id': 'classroom:alice', 'x-authenticated-auth-mode': 'classroom-no-login'}
BOB = {'x-authenticated-user-id': 'classroom:bob', 'x-authenticated-auth-mode': 'classroom-no-login'}
ANSWER = 'Honestly my mother-in-law would move into it, which scares me a little.'


@pytest.fixture
def room(client, monkeypatch):
    client.app.state.settings.openrouter_api_key = 'stub'
    study_id = client.post('/api/v1/studies', headers=ALICE, json={}).json()['data']['study']['study_id']
    calls = []

    def provider(**kw):
        calls.append(kw)
        return InterviewAnswer(text=f'Why does detail {len(calls)} matter?', model=kw['model'],
                               tokens_in=10, tokens_out=5, cost_usd=Decimal('.001'))
    monkeypatch.setattr('src.services.interview_service._call_openrouter_messages', provider)
    return client, study_id, calls


def ask(client, study_id, messages=(), session_id=None, headers=ALICE, **extra):
    return client.post(f'/api/v1/studies/{study_id}/interview/human/next-question', headers=headers,
                       json={'messages': list(messages), 'session_id': session_id, **extra})


def interview(client, study_id, answers):
    """Answer `answers` questions; returns the transcript, the last reply and the session."""
    reply = ask(client, study_id).json()['data']['question']
    messages = []
    for answer in answers:
        messages += [{'role': 'user', 'content': reply['question']}, {'role': 'assistant', 'content': answer}]
        response = ask(client, study_id, messages, reply['session_id'])
        assert response.status_code == 200, response.text
        reply = response.json()['data']['question']
    return messages, reply


def test_opening_question_uses_the_batch_guide_and_default_model(room):
    client, study_id, calls = room
    response = ask(client, study_id, interviewer_model='anthropic/claude-sonnet-4.5')
    assert response.status_code == 200, response.text
    reply = response.json()['data']['question']
    assert reply['question'] == 'Why does detail 1 matter?'
    assert reply['turn_number'] == 1 and reply['turn_limit'] == 8 and reply['complete'] is False
    assert reply['session_id'].startswith('you_')
    assert len(calls) == 1 and calls[0]['model'] == DEFAULT_INTERVIEW_MODEL_ID
    system, user = calls[0]['messages']
    assert 'You are the interviewer' in system['content']
    assert RESEARCH_BRIEF['primary_question'] in user['content']
    assert 'No questions have been asked yet' in user['content']


def test_followup_is_derived_from_the_student_answer(room):
    client, study_id, calls = room
    _, reply = interview(client, study_id, [ANSWER])
    assert reply['turn_number'] == 2
    assert 'Derive the next question from this latest interviewee answer' in calls[1]['messages'][-1]['content']
    assert ANSWER in calls[1]['messages'][-1]['content']


def test_interview_completes_at_the_guide_end_without_a_paid_call(room):
    client, study_id, calls = room
    messages, reply = interview(client, study_id, [f'answer {i}' for i in range(8)])
    assert reply['complete'] is True and reply['question'] is None
    assert len(calls) == 8
    assert Decimal(reply['session_usage']['cost_usd']) == Decimal('.008')
    again = ask(client, study_id, messages, reply['session_id']).json()['data']['question']
    assert again['complete'] is True and len(calls) == 8


def test_classroom_identity_owns_the_session(room):
    client, study_id, calls = room
    messages, reply = interview(client, study_id, [ANSWER])
    assert ask(client, study_id, messages, reply['session_id'], headers=BOB).status_code == 403
    bob_study = client.post('/api/v1/studies', headers=BOB, json={}).json()['data']['study']['study_id']
    assert ask(client, bob_study, messages, reply['session_id'], headers=BOB).status_code == 404
    assert ask(client, study_id, session_id='batch_not_mine').status_code == 400
    assert len(calls) == 2


@pytest.mark.parametrize('answer', ['', '   \n '])
def test_empty_answer_is_refused_before_any_paid_call(room, answer):
    client, study_id, calls = room
    first = ask(client, study_id).json()['data']['question']
    response = ask(client, study_id, [{'role': 'user', 'content': first['question']},
                                      {'role': 'assistant', 'content': answer}], first['session_id'])
    assert response.status_code == 400
    too_long = ask(client, study_id, [{'role': 'user', 'content': first['question']},
                                      {'role': 'assistant', 'content': 'x' * 4001}], first['session_id'])
    assert too_long.status_code == 400
    assert len(calls) == 1


def test_double_submit_charges_once_and_returns_the_same_question(room):
    client, study_id, calls = room
    messages, reply = interview(client, study_id, [ANSWER])
    again = ask(client, study_id, messages, reply['session_id']).json()['data']['question']
    assert again['question'] == reply['question'] and again['turn_number'] == 2
    assert len(calls) == 2
    assert Decimal(again['session_usage']['cost_usd']) == Decimal('.002')


def test_budget_cap_stops_the_interview(room):
    client, study_id, calls = room
    client.app.state.settings.llm_budget_usd = Decimal('0')
    response = ask(client, study_id)
    assert response.status_code == 429 and response.json()['error']['code'] == 'quota_exceeded'
    assert calls == []
    # A run cap that the interview outgrows mid-way stops it with the same error.
    client.app.state.settings.llm_budget_usd = Decimal('.0025')
    reply = ask(client, study_id).json()['data']['question']
    messages = [{'role': 'user', 'content': reply['question']}, {'role': 'assistant', 'content': ANSWER}]
    second = ask(client, study_id, messages, reply['session_id'])
    assert second.status_code == 200
    messages += [{'role': 'user', 'content': second.json()['data']['question']['question']},
                 {'role': 'assistant', 'content': ANSWER}]
    third = ask(client, study_id, messages, reply['session_id'])
    assert third.status_code == 429 and third.json()['error']['code'] == 'quota_exceeded'
    assert len(calls) == 3
    assert ask(client, study_id, messages + [{'role': 'user', 'content': 'x'}, {'role': 'assistant', 'content': 'y'}],
               reply['session_id']).status_code == 429
    assert len(calls) == 3


def test_provider_failure_is_retryable(room, monkeypatch):
    client, study_id, calls = room
    first = ask(client, study_id).json()['data']['question']
    messages = [{'role': 'user', 'content': first['question']}, {'role': 'assistant', 'content': ANSWER}]
    attempts = []

    def down(*args, **kwargs):
        attempts.append(kwargs)
        raise requests.ConnectionError('provider down')
    monkeypatch.setattr('src.services.interview_service._call_openrouter_messages', real_provider)
    monkeypatch.setattr('src.services.interview_service.requests.post', down)
    failed = ask(client, study_id, messages, first['session_id'])
    assert failed.status_code == 503
    assert 'Your answer is kept' in failed.json()['error']['message']
    assert len(attempts) == 1
    monkeypatch.undo()
    monkeypatch.setattr('src.services.interview_service._call_openrouter_messages',
                        lambda **kw: InterviewAnswer(text='What changed your mind?', model=kw['model'],
                                                     tokens_in=1, tokens_out=1, cost_usd=Decimal('.001')))
    client.app.state.settings.openrouter_api_key = 'stub'
    retried = ask(client, study_id, messages, first['session_id'])
    assert retried.status_code == 200
    assert retried.json()['data']['question']['question'] == 'What changed your mind?'


def test_replay_only_mode_refuses_clearly(room):
    client, study_id, calls = room
    client.app.state.settings.cache_mode = 'replay_only'
    response = ask(client, study_id)
    assert response.status_code == 409 and 'replay' in response.json()['error']['message']
    assert calls == []


def test_student_answers_are_never_persisted(room, db_session):
    client, study_id, calls = room
    answers = [f'{ANSWER} (turn {i})' for i in range(8)]
    interview(client, study_id, answers)
    assert len(calls) == 8
    stored = [turn.text for turn in db_session.scalars(select(InterviewTurn))]
    stored += [f'{job.payload_json} {job.result_json}' for job in db_session.scalars(select(Job))]
    assert stored and not any('mother-in-law' in text for text in stored)
    assert db_session.scalars(select(InterviewCacheEntry)).all() == []
    turns = db_session.scalars(select(InterviewTurn)).all()
    assert {(turn.role, turn.persona_id) for turn in turns} == {('user', 'human')}
