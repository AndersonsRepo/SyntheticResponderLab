import json
from decimal import Decimal
from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import select

from test_standalone_batch import classroom, start, finish
from src.persistence.models import Job
from src.services.interview_cache import InterviewAnswer
import src.services.interview_service as insights_module
# Bound at import, before any fixture replaces the module attribute, so a test can
# put the real helper back and exercise the parser at the HTTP boundary.
from src.services.interview_service import _call_openrouter_messages as _real_openrouter_call


@pytest.fixture
def completed(classroom, monkeypatch):
    client, study, calls = classroom
    batch = finish(client, study, start(client, study).json()['data']['batch'])
    url = f'/api/v1/studies/{study}/interview/batches/{batch["job_id"]}/themes'
    extra = []
    themes = [{'label': f'Theme {i}', 'count': 1, 'synthesis': 'An interest in the option.',
        'representative_quote': batch['transcripts'][0]['messages'][1]['content'],
        'quote_persona_id': batch['transcripts'][0]['persona_id'], 'sentiment': 'positive'} for i in range(3)]
    def provider(**kw):
        extra.append(kw)
        return InterviewAnswer(text=json.dumps({'themes': themes}), model=kw['model'],
            tokens_in=10, tokens_out=10, cost_usd=Decimal('.002'))
    monkeypatch.setattr('src.services.interview_service._call_openrouter_messages', provider)
    revision = client.get(url).json()['data']['insights']['revision']
    return client, url, batch, extra, themes, {'revision': revision, 'authorize_charge': True}


def test_standalone_themes_scoped_cached(completed):
    client, url, batch, calls, themes, payload = completed
    assert not client.get(url).json()['data']['insights']['available']
    assert calls == []
    result = client.post(url, json=payload).json()['data']['insights']
    assert result['saved']['themes'] == themes
    assert result['session_usage']['cost_usd'] == '0.050'
    assert len(calls) == 1 and calls[0]['max_attempts'] == 1
    assert client.post(url, json=payload).json()['data']['insights']['available']
    assert client.get(url).json()['data']['insights']['available']
    assert len(calls) == 1
    other = client.post('/api/v1/studies', json={}).json()['data']['study']['study_id']
    assert client.get(url.replace(url.split('/')[4], other)).status_code == 404


def test_standalone_themes_explicit_authorization(completed):
    client, url, _, calls, _, payload = completed
    assert client.post(url, json={'revision': payload['revision']}).status_code == 400
    assert client.post(url, json={**payload, 'revision': 'old'}).status_code == 409
    assert calls == []


@pytest.mark.parametrize('mode', ['replay_only', 'zero', 'run', 'class'])
def test_standalone_themes_budgets(completed, mode, db_session):
    client, url, _, calls, _, payload = completed
    if mode == 'replay_only':
        client.app.state.settings.cache_mode = mode
    else:
        client.app.state.settings.llm_budget_usd = Decimal('0' if mode == 'zero' else '.048' if mode == 'run' else '.75')
        if mode == 'class':
            from src.persistence.models import InterviewTurn
            turn = db_session.scalar(select(InterviewTurn))
            turn.cost_usd = Decimal('23')
            db_session.commit()
    assert client.post(url, json=payload).status_code in (409, 429)
    assert not calls


def test_standalone_themes_concurrent(completed):
    client, url, _, calls, _, payload = completed
    with ThreadPoolExecutor(max_workers=3) as pool:
        responses = list(pool.map(lambda _: client.post(url, json=payload), range(3)))
    assert all(r.status_code == 200 for r in responses)
    assert len(calls) == 1


def test_standalone_themes_timeout_retry_and_safe_diagnostics(completed, monkeypatch, caplog):
    client, url, batch, calls, _, payload = completed
    def fail(**kw):
        calls.append(kw)
        raise RuntimeError('secret transcript credential')
    monkeypatch.setattr('src.services.interview_service._call_openrouter_messages', fail)
    with caplog.at_level('INFO'):
        response = client.post(url, json=payload).json()['data']['insights']
    assert response['saved']['outcome'] == 'unknown'
    assert 'unknown' in response['saved']['message']
    assert batch['job_id'] in caplog.text and payload['revision'] in caplog.text
    assert 'secret transcript credential' not in caplog.text
    assert 'secret transcript credential' not in response['saved']['message']
    assert response['saved']['reason'] == 'RuntimeError'
    assert 'produced no usable response' in response['saved']['message']
    client.post(url, json=payload)
    assert len(calls) == 1
    retry = {**payload, 'retry_attempt': response['saved']['attempt']}
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(lambda _: client.post(url, json=retry), range(2)))
    assert len(calls) == 2
    assert client.get(url.removesuffix('/themes')).json()['data']['batch']['transcripts'] == batch['transcripts']


@pytest.mark.parametrize('invalid', ['quote', 'empty', 'json'])
def test_standalone_themes_malformed_preserves_cost(completed, invalid, monkeypatch):
    client, url, batch, calls, themes, payload = completed
    if invalid == 'quote': themes[0]['representative_quote'] = 'fabricated quote'
    if invalid == 'empty': themes.clear()
    if invalid == 'json':
        monkeypatch.setattr('src.services.interview_service._call_openrouter_messages', lambda **kw:
            InterviewAnswer(text='broken json', model=kw['model'], tokens_in=10, tokens_out=1, cost_usd=Decimal('.002')))
    result = client.post(url, json=payload).json()['data']['insights']
    assert not result['available'] and result['saved']['outcome'] == 'charged'
    # A rule-breaking response is re-asked once, so it bills twice; an unparseable one
    # never reaches validation and bills once.
    assert Decimal(result['session_usage']['cost_usd']) == Decimal(
        '.050' if invalid == 'json' else '.052')
    assert client.get(url.removesuffix('/themes')).json()['data']['batch']['transcripts'] == batch['transcripts']


@pytest.mark.parametrize('state', ['running', 'failed', 'budget_stopped', 'empty', 'partial'])
def test_standalone_themes_availability(completed, db_session, state):
    client, url, batch, calls, _, payload = completed
    job = db_session.scalar(select(Job).where(Job.public_id == batch['job_id']))
    if state == 'empty': job.result_json = {**job.result_json, 'transcripts': []}
    elif state == 'partial': job.result_json = {**job.result_json, 'transcripts': job.result_json['transcripts'][:1]}
    else: job.status = state
    db_session.commit()
    response = client.post(url, json=payload).json()['data']['insights']
    assert not response['eligible'] and not calls


def test_standalone_themes_revision(completed, db_session):
    client, url, batch, calls, _, payload = completed
    client.post(url, json=payload)
    job = db_session.scalar(select(Job).where(Job.public_id == batch['job_id']))
    transcripts = json.loads(json.dumps(job.result_json['transcripts']))
    transcripts[0]['messages'].append({'role': 'assistant', 'content': 'A new answer'})
    job.result_json = {**job.result_json, 'transcripts': transcripts}
    db_session.commit()
    result = client.get(url).json()['data']['insights']
    assert result['stale'] and result['saved']['revision'] == payload['revision']
    assert client.post(url, json=payload).status_code == 409
    assert len(calls) == 1


@pytest.mark.parametrize('content', ['', '<think>only reasoning</think>', None])
def test_standalone_themes_unusable_content_records_measured_cost(completed, monkeypatch, content):
    """A charged call whose content cannot be used must still move the ledger.

    Refuter round 1 blocker B1. Mock at the HTTP boundary, not at
    `_call_openrouter_messages`, so the real parser runs and really raises —
    mocking the helper would skip the exact code path under test.
    """
    client, url, batch, calls, _, payload = completed
    message = {} if content is None else {'content': content}

    class Response:
        status_code = 200
        def raise_for_status(self): pass
        def json(self, **kw):
            return {'model': 'openai/gpt-4o-mini',
                    'choices': [{'message': message}],
                    'usage': {'prompt_tokens': 10, 'completion_tokens': 4, 'cost': Decimal('.002')}}

    monkeypatch.setattr('src.services.interview_service._call_openrouter_messages', _real_openrouter_call)
    monkeypatch.setattr('src.services.interview_service.requests.post', lambda *a, **kw: Response())
    result = client.post(url, json=payload).json()['data']['insights']

    assert not result['available'], 'unusable content must not present themes'
    assert result['saved']['outcome'] == 'charged', 'the provider billed for this call'
    # The batch itself already spent .048; the discarded call adds its own .002.
    assert Decimal(result['session_usage']['cost_usd']) == Decimal('.050'), \
        'the measured charge must reach the ledger or the next budget check undercounts'
    assert 'billing outcome is unknown' not in result['saved']['message'], \
        'the charge is known and recorded — do not tell the student otherwise'
    assert client.get(url.removesuffix('/themes')).json()['data']['batch']['transcripts'] == batch['transcripts']


@pytest.mark.parametrize('rendering', [
    '0: {quote}',                      # the transcript's own answer prefix
    '“{quote}”',             # typographic quotation marks
    '  {quote}  ',                     # stray whitespace
    '“0: {quote}”',          # both at once: the prefix inside the quotation marks
])
def test_standalone_themes_accepts_a_rerendered_quote(completed, rendering):
    """A quote the model really did copy must survive being re-rendered.

    Every one of these is the same sentence from the same persona; rejecting them costs
    the student another charge for a response that was never wrong.
    """
    client, url, batch, calls, themes, payload = completed
    themes[0]['representative_quote'] = rendering.format(quote=themes[0]['representative_quote'])
    result = client.post(url, json=payload).json()['data']['insights']
    assert result['available'], result.get('saved', {}).get('message')


def test_standalone_themes_failure_names_the_rule_it_broke(completed):
    """The student pays per retry, so a rejection has to say what was wrong."""
    client, url, batch, calls, themes, payload = completed
    themes[0]['representative_quote'] = 'a quote nobody said'
    saved = client.post(url, json=payload).json()['data']['insights']['saved']
    assert saved['reason'] == "Theme 1 quote is not in %s's answers" % themes[0]['quote_persona_id']
    assert saved['reason'] in saved['message']
    assert 'broke a rule' in saved['message']


def test_standalone_themes_reads_a_fenced_json_answer(completed, monkeypatch):
    """A fenced block is still a JSON answer; only an unparseable one is a failure."""
    client, url, batch, calls, themes, payload = completed
    real = insights_module._call_openrouter_messages
    def fenced(**kw):
        answer = real(**kw)
        return InterviewAnswer(text='Here is the JSON:\n\n```json\n' + answer.text + '\n```', model=answer.model,
            tokens_in=answer.tokens_in, tokens_out=answer.tokens_out, cost_usd=answer.cost_usd)
    monkeypatch.setattr('src.services.interview_service._call_openrouter_messages', fenced)
    result = client.post(url, json=payload).json()['data']['insights']
    assert result['available'], result.get('saved', {}).get('message')


def test_extract_themes_counts_only_the_interviews_it_renders():
    """The prompt's interview count has to match the corpus, or validate accepts a count the model never saw."""
    pairs = [{'persona_id': 'p1', 'model_a': {'answers': {'0': 'said something'}}},
             {'persona_id': 'p2', 'model_a': {'answers': {}}},
             # Every answer here is one the corpus builder skips, so the model sees no text.
             {'persona_id': 'p3', 'model_a': {'answers': {'0': '[no answer]',
                                                          'additional_thoughts': 'aside'}}}]
    seen = {}
    def call(**prompts):
        seen.update(prompts)
        return '{"themes": []}'
    insights_module._extract_insight_themes(pairs, '', call)
    assert 'There are 1 interviews' in seen['user_prompt']
    assert 'p2' not in seen['user_prompt'] and 'p3' not in seen['user_prompt']
    # The quote check must not reach text the prompt never carried.
    assert [p['persona_id'] for p in insights_module.rendered_pairs(pairs)] == ['p1']


def test_standalone_themes_refuses_an_unreadable_corpus(completed, db_session):
    """Every answer is one the corpus skips, so the call could only come back rejected."""
    client, url, batch, calls, _, payload = completed
    job = db_session.scalar(select(Job).where(Job.public_id == batch['job_id']))
    result = dict(job.result_json)
    result['transcripts'] = [{**t, 'messages': [
        {**m, 'content': '[no answer]'} if m['role'] == 'assistant' else m for m in t['messages']]}
        for t in result['transcripts']]
    job.result_json = result
    db_session.commit()
    view = client.get(url).json()['data']['insights']
    # Eligibility still reflects the batch as run — the refusal is loud, not silent.
    assert view['eligible']
    assert client.post(url, json={**payload, 'revision': view['revision']}).status_code == 409
    assert calls == []


def test_standalone_themes_accepts_a_quote_from_a_repeated_persona(completed, db_session):
    """Two transcripts can share a persona_id; the prompt carries both, so the check must too."""
    client, url, batch, calls, themes, payload = completed
    job = db_session.scalar(select(Job).where(Job.public_id == batch['job_id']))
    result = dict(job.result_json)
    first = result['transcripts'][0]['persona_id']
    result['transcripts'] = [{**t, 'persona_id': first} for t in result['transcripts']]
    job.result_json = result
    db_session.commit()
    revision = client.get(url).json()['data']['insights']['revision']
    saved = client.post(url, json={**payload, 'revision': revision}).json()['data']['insights']
    assert saved['available'], saved.get('saved', {}).get('message')


def test_standalone_themes_one_placeholder_answer_stays_eligible(completed, db_session):
    """One unusable answer must not quietly take the whole batch out of eligibility."""
    client, url, batch, calls, themes, payload = completed
    job = db_session.scalar(select(Job).where(Job.public_id == batch['job_id']))
    result = dict(job.result_json)
    first = result['transcripts'][0]
    messages = list(first['messages'])
    last = max(i for i, m in enumerate(messages) if m['role'] == 'assistant')
    messages[last] = {**messages[last], 'content': '[no answer]'}
    result['transcripts'] = [{**first, 'messages': messages}, *result['transcripts'][1:]]
    job.result_json = result
    db_session.commit()
    view = client.get(url).json()['data']['insights']
    assert view['eligible'], view['message']


def test_standalone_themes_re_asks_once_before_charging_the_student(completed):
    """A rejected response is a slip the student cannot see; the server fixes it itself.

    First call returns an ungrounded quote, second returns a real one. The student must
    get themes, not a Retry button, and must be told both calls' cost.
    """
    client, url, batch, calls, themes, payload = completed
    good = themes[0]['representative_quote']
    themes[0]['representative_quote'] = 'a quote nobody said'

    provider = insights_module._call_openrouter_messages
    def fix_on_retry(**kw):
        if 'previous response was rejected' in kw['messages'][1]['content']:
            themes[0]['representative_quote'] = good
        return provider(**kw)
    insights_module._call_openrouter_messages = fix_on_retry
    try:
        saved = client.post(url, json=payload).json()['data']['insights']
    finally:
        insights_module._call_openrouter_messages = provider

    assert saved['available'], saved.get('saved', {}).get('message')
    assert len(calls) == 2
    assert saved['saved']['retried_reason'] == "Theme 1 quote is not in %s's answers" % themes[0]['quote_persona_id']
    assert saved['saved']['cost_usd'] == '0.004'


def test_standalone_themes_reports_batch_emotion_for_free(completed):
    """Emotion is lexical, so it is on the page before any charge and after a rejection."""
    client, url, batch, calls, themes, payload = completed
    free = client.get(url).json()['data']['insights']
    assert calls == []
    emotion = free['emotion']
    assert emotion['scored'] == len(batch['transcripts'])
    assert set(emotion['counts']) == {'positive', 'neutral', 'negative'}
    # The distribution is over ANSWERS, not over people: no interviewee carries a verdict.
    assert sum(emotion['counts'].values()) == emotion['answers'] > emotion['scored']
    assert {p['persona_id'] for p in emotion['personas']} == {
        t['persona_id'] for t in batch['transcripts']}
    assert all('emotional_classification' not in p for p in emotion['personas'])
    assert all(sum(p[name] for name in ('positive', 'neutral', 'negative')) == p['answers']
               for p in emotion['personas'])

    # A rejected extraction must not take the free read off the page with it.
    themes[0]['representative_quote'] = 'a quote nobody said'
    rejected = client.post(url, json=payload).json()['data']['insights']
    assert not rejected['available'] and rejected['emotion']['counts'] == emotion['counts']


def test_standalone_themes_estimate_covers_the_re_ask(completed, monkeypatch):
    """One authorization can make two calls, so the figure the student confirms covers two."""
    from src.services import standalone_themes as themes_module
    client, url, _, calls, _, _ = completed
    shown = Decimal(client.get(url).json()['data']['insights']['estimated_cost_usd'])
    monkeypatch.setattr(themes_module, 'MAX_PROVIDER_CALLS', 1)
    one_call = Decimal(client.get(url).json()['data']['insights']['estimated_cost_usd'])
    assert one_call > 0 and shown == one_call * 2
    assert calls == []


def test_standalone_themes_re_ask_prompt_is_bounded(completed):
    """The rejection reason quotes model-controlled text, so the re-ask cannot carry it whole."""
    client, url, _, calls, themes, payload = completed
    themes[0]['quote_persona_id'] = 'P' * 50_000
    client.post(url, json=payload)
    assert len(calls) == 2
    first, retry = (len(c['messages'][1]['content']) for c in calls)
    assert retry - first < 1_000, 'a 50KB persona id must not ride into the second prompt'


def test_standalone_themes_re_ask_spend_is_cumulative(completed, monkeypatch):
    """The snapshot is frozen, so the measured-cost stop has to see the running total.

    Checking each call alone lets two calls that each fit the remaining allowance
    exceed it together — the whole point of a hard cap the class shares.
    """
    from src.services import standalone_themes as themes_module
    client, url, _, calls, themes, payload = completed
    themes[0]['representative_quote'] = 'a quote nobody said'
    seen = []
    real = themes_module.enforce_measured_cost
    monkeypatch.setattr(themes_module, 'enforce_measured_cost',
        lambda snapshot, *, cost_usd: (seen.append(Decimal(cost_usd)), real(snapshot, cost_usd=cost_usd))[1])
    client.post(url, json=payload)
    assert len(calls) == 2
    assert seen == [Decimal('.002'), Decimal('.004')], 'second check must carry the first call'


def test_standalone_themes_unparseable_re_ask_is_not_called_a_broken_rule(completed):
    """A second call that never parsed did not break a rule — say which failure it was."""
    client, url, _, calls, themes, payload = completed
    themes[0]['representative_quote'] = 'a quote nobody said'
    provider = insights_module._call_openrouter_messages

    def broken_on_retry(**kw):
        calls.append(kw)
        if 'previous response was rejected' in kw['messages'][1]['content']:
            return InterviewAnswer(text='broken json', model=kw['model'],
                tokens_in=10, tokens_out=1, cost_usd=Decimal('.002'))
        return provider(**kw)
    insights_module._call_openrouter_messages = broken_on_retry
    try:
        saved = client.post(url, json=payload).json()['data']['insights']['saved']
    finally:
        insights_module._call_openrouter_messages = provider
    assert len(calls) == 3  # the stub records the first call twice: its own and the fixture's
    assert 'produced no usable response' in saved['message']
    assert 'broke a rule' not in saved['message']


def test_standalone_themes_emotion_says_how_much_of_the_room_it_scored(completed, db_session):
    """A skipped interviewee must not silently shrink the room the distribution covers."""
    from src.persistence.models import Job
    client, url, batch, calls, _, _ = completed
    job = db_session.scalars(select(Job).where(Job.public_id == batch['job_id'])).one()
    result = dict(job.result_json)
    transcripts = [dict(t) for t in result['transcripts']]
    transcripts[0] = {**transcripts[0], 'messages': []}  # answered nothing
    job.result_json = {**result, 'transcripts': transcripts}
    db_session.commit()
    emotion = client.get(url).json()['data']['insights']['emotion']
    assert emotion['interviewed'] == len(transcripts)
    assert emotion['scored'] == len(transcripts) - 1
    assert sum(emotion['counts'].values()) == emotion['answers']


def test_standalone_themes_re_ask_that_vanishes_is_not_reported_as_a_known_charge(completed):
    """One call billed cleanly, one vanished — the student is not told the ledger is complete."""
    client, url, _, calls, themes, payload = completed
    themes[0]['representative_quote'] = 'a quote nobody said'
    provider = insights_module._call_openrouter_messages

    def vanish_on_retry(**kw):
        if 'previous response was rejected' in kw['messages'][1]['content']:
            raise RuntimeError('boom')
        return provider(**kw)
    insights_module._call_openrouter_messages = vanish_on_retry
    try:
        saved = client.post(url, json=payload).json()['data']['insights']['saved']
    finally:
        insights_module._call_openrouter_messages = provider
    assert saved['outcome'] == 'charged' and saved['unknown_billing'] is True
    assert 'billing outcome is unknown' in saved['message']
    assert 'measured charge is recorded' not in saved['message']


# None, a non-dict turn and a turn with no content also crash corpus() on this and on
# every earlier revision of this file — a pre-existing fragility this change neither
# introduced nor fixes. These are the shapes that reach emotion() at all.
@pytest.mark.parametrize('messages', [[], {}])
def test_standalone_themes_emotion_survives_a_malformed_transcript(completed, db_session, messages):
    """emotion() rides the free view and the post-charge response; it cannot 500 either."""
    from src.persistence.models import Job
    client, url, batch, _, _, _ = completed
    job = db_session.scalars(select(Job).where(Job.public_id == batch['job_id'])).one()
    result = dict(job.result_json)
    transcripts = [dict(t) for t in result['transcripts']]
    transcripts[0] = {**transcripts[0], 'messages': messages}
    job.result_json = {**result, 'transcripts': transcripts}
    db_session.commit()
    response = client.get(url)
    assert response.status_code == 200
    emotion = response.json()['data']['insights']['emotion']
    assert emotion['interviewed'] == len(transcripts) and emotion['scored'] == len(transcripts) - 1


def test_standalone_themes_never_exceeds_its_authorized_call_budget(completed):
    """The estimate and preflight reserve MAX_PROVIDER_CALLS; the call path must honour it.

    Also bounds provider time: the class budget lock is held for the whole request,
    so the two calls share one deadline rather than each getting the full timeout.
    """
    import time as _time
    from src.services import standalone_themes as themes_module
    client, url, _, calls, themes, payload = completed
    themes[0]['representative_quote'] = 'a quote no re-ask will ever ground'
    provider = insights_module._call_openrouter_messages
    insights_module._call_openrouter_messages = lambda **kw: (_time.sleep(1), provider(**kw))[1]
    try:
        client.post(url, json=payload)
    finally:
        insights_module._call_openrouter_messages = provider
    assert len(calls) == themes_module.MAX_PROVIDER_CALLS
    first, retry = (c['timeout'] for c in calls)
    assert first <= themes_module.PROVIDER_DEADLINE_S
    assert retry < first, 'the re-ask spends what is left of the deadline, not a fresh one' 


def test_standalone_themes_emotion_does_not_label_a_keen_interviewee_negative(completed, db_session):
    """The bug this shape exists to prevent: concern language accumulating into a verdict.

    Every answer below is an enthusiastic buyer; two of them voice a concern, which is what
    a depth interview asks for. Scored as one blob the interviewee comes out "negative".
    """
    from src.persistence.models import Job
    from src.services.interview_scoring import classify_interview_transcript
    answers = [
        'A separate quiet studio signals that I am serious about my business.',
        'I worry about the inside of that little studio becoming an oven.',
        'If I could see a clear tangible return then I could justify it.',
        'I am concerned the neighborhood sounds would defeat the purpose.',
        'Having a separate space means I can step away and get into the zone.',
    ]
    messages = [{'role': 'assistant', 'content': a} for a in answers]
    assert classify_interview_transcript(messages)['emotional_classification'] == 'negative', (
        'the whole-transcript reading this design exists to avoid')

    client, url, batch, _, _, _ = completed
    job = db_session.scalars(select(Job).where(Job.public_id == batch['job_id'])).one()
    result = dict(job.result_json)
    transcripts = [dict(t) for t in result['transcripts']]
    transcripts[0] = {**transcripts[0], 'messages': messages}
    job.result_json = {**result, 'transcripts': transcripts}
    db_session.commit()

    entry = next(p for p in client.get(url).json()['data']['insights']['emotion']['personas']
                 if p['persona_id'] == transcripts[0]['persona_id'])
    assert entry['answers'] == len(answers)
    assert entry['negative'] == 2 and entry['neutral'] == 3
    assert entry['negative'] < entry['neutral'], 'two voiced concerns are not a negative person'


def test_standalone_themes_emotion_ignores_the_interviewer(completed, db_session):
    """The interviewer asks about objections for a living; their words are not the room's."""
    from src.persistence.models import Job
    client, url, batch, _, _, _ = completed
    job = db_session.scalars(select(Job).where(Job.public_id == batch['job_id'])).one()
    result = dict(job.result_json)
    transcripts = [dict(t) for t in result['transcripts']]
    transcripts[0] = {**transcripts[0], 'messages': [
        {'role': 'user', 'content': 'What worries you? Are you concerned or nervous about the noise?'},
        {'role': 'assistant', 'content': 'It would be useful for my work.'},
        {'role': 'user', 'content': 'Anything else that makes you anxious or skeptical?'},
    ]}
    job.result_json = {**result, 'transcripts': transcripts}
    db_session.commit()
    entry = next(p for p in client.get(url).json()['data']['insights']['emotion']['personas']
                 if p['persona_id'] == transcripts[0]['persona_id'])
    assert entry['answers'] == 1 and entry['negative'] == 0
