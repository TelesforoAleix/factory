"""Event delivery, ownership, turn limits and scoped slice tools on synthetic PG17."""
from concurrent.futures import ThreadPoolExecutor
import copy

import pytest

from cplane import state
from cplane.stores import PostgresStore
from cplane.workshop import Workshop
from factory_ui import create_app
from test_stores import pg_store
from test_runner import setup as runner_setup, assert_prompt
from test_pipeline import runner_board
from test_workshop import context, call, value, refused

AT = '2026-11-07T12:00:00+00:00'


def linked(store, feature, slice_data, **fields):
    item = copy.deepcopy(slice_data)
    item.update(feature_id=feature, **fields)
    item['log'].insert(0, dict(at=AT, actor='chat:1', event='add_slice'))
    store.save(dict(version=1, slices=[item]))
    return item


def question(body='Which choice?', kind='question', since=AT):
    return dict(kind=kind, body=body, since=since, answer=None, approved=False)


@pytest.mark.parametrize('kind,body', [('question', 'Which choice?'), ('escalation', 'Needs a decision'),
                                      ('escalation', 'failing check: test')])
def test_delivery_once_and_phone_home_ownership(context, slice_data, kind, body):
    store, _, chats, own, *_ = context
    item = linked(store, own, slice_data, attention=question(body, kind), state='issued')
    store.route_chat_events()
    store.route_chat_events()
    messages = store.session_messages('factory', chats['feature']['id'])
    events = [m for m in messages if 'Event:' in m['text']]
    assert len(events) == 1
    assert events[0]['role'] == 'system' and events[0]['automatic']
    assert all(text in events[0]['text'] for text in [item['id'], body, kind])
    assert store.chat_attention(item)['chat_id'] == chats['feature']['id']
    # A distinct ownership projection preserves the exact version 1 state.
    assert store.load()['slices'][0] == item
    store.append_notices([dict(at=AT, id=item['id'], event=kind, text=body),
                          dict(at=AT, id=item['id'], event='merge', text='Owner approves')])
    assert [n['event'] for _, n in store.notices()] == ['merge']
    home = create_app(store).test_client().get('/api/home').get_json()
    assert not any(a['kind'] in ('question', 'failure') for a in home['attention'])


def test_fallback_and_alias_identity(context, slice_data):
    store, _, chats, own, other, outside, _ = context
    for feature, expected in [(other, chats['project']), (outside, chats['orchestrator'])]:
        linked(store, feature, slice_data, attention=question())
        store.route_chat_events()
        assert store.chat_attention(store.load()['slices'][0])['chat_id'] == expected['id']
        store.save(dict(version=1, slices=[]))
    store.feature_move(own, 'LAB')
    item = linked(store, own, slice_data, attention=question())
    store.route_chat_events()
    assert store.chat_attention(item)['chat_id'] == chats['feature']['id']


def test_reviews_distinct_transitions_and_testing(context, slice_data):
    store, _, chats, own, *_ = context
    item = linked(store, own, slice_data, state='issued')
    item['state'] = 'in review'
    item['log'].append(dict(at=AT, actor='runner', event='finished'))
    with store.mutation():
        store.chat_handover(item, 'Synthetic handover: tests passed')
        store.save(dict(version=1, slices=[item]))
    store.route_chat_events()
    store.route_chat_events()
    events = [m for m in store.session_messages('factory', chats['feature']['id']) if 'Event: in review' in m['text']]
    assert len(events) == 1 and 'Synthetic handover' in events[0]['text'] and item['brief'] in events[0]['text']
    item['state'] = 'issued'
    store.save(dict(version=1, slices=[item]))
    item['state'] = 'in review'
    item['log'].append(dict(at=AT, actor='runner', event='finished'))
    store.save(dict(version=1, slices=[item]))
    store.route_chat_events()
    events = [m for m in store.session_messages('factory', chats['feature']['id']) if 'Event: in review' in m['text']]
    assert len(events) == 2
    # Exercise the actual stage hook in the same mutation as the stage update.
    with store.mutation():
        store.connection.execute("UPDATE cplane_features SET stage = 'building' WHERE id = %s", (own,))
    item['state'] = 'accepted'
    store.save(dict(version=1, slices=[item]))
    store.feature_stage(own, 'testing', actor='runner')
    store.route_chat_events()
    events = store.session_messages('factory', chats['feature']['id'])
    assert sum('Event: testing' in m['text'] for m in events) == 1
    assert item['id'] in events[-1]['text']


@pytest.mark.parametrize('kind', ['merge', 'node-step', 'owner-check'])
def test_owner_attention_never_routes(context, slice_data, kind):
    store, _, chats, own, *_ = context
    linked(store, own, slice_data, attention=question(kind=kind))
    store.route_chat_events()
    assert len(store.session_messages('factory', chats['feature']['id'])) == 1


def test_limit_pause_pending_owner_priority_and_resume(context, slice_data):
    store, _, chats, own, *_ = context
    sid = chats['feature']['id']
    store.limit_set('chat_auto_turns', 2)
    # Opening grill is an automatic turn too.
    first = store.claim_session_turn()
    store.finish_session_turn(first, 'One')
    store.system_message(sid, 'Second event')
    store.system_message(sid, 'Already queued')
    second = store.claim_session_turn()
    store.finish_session_turn(second, 'Two')
    assert store.claim_session_turn() is None
    item = linked(store, own, slice_data, attention=question())
    store.route_chat_events()
    store.route_chat_events()
    assert 'chat_id' not in store.chat_attention(item)
    notices = [n for _, n in store.notices() if n['event'] == 'chat-paused']
    assert len(notices) == 1
    store.chat_open(sid)
    home = create_app(store).test_client().get('/api/home').get_json()
    assert not any(a.get('chat') == sid and 'paused' in a.get('text', '') for a in home['attention'])
    assert store.claim_session_turn() is None
    store.session_messages('factory', sid, 'Continue with my decision')
    store.route_chat_events()
    owner = store.claim_session_turn()
    assert owner['role'] == 'owner'
    store.finish_session_turn(owner, 'Owner reply')
    assert store.claim_session_turn()['text'] == 'Already queued'
    assert store.chat_attention(item)['chat_id'] == sid


def test_events_and_ownership_rollback_together(context, slice_data):
    store, _, chats, own, *_ = context
    before = store.snapshot()
    with pytest.raises(RuntimeError):
        with store.mutation():
            linked(store, own, slice_data, attention=question())
            store.route_chat_events()
            raise RuntimeError('Synthetic rollback')
    assert store.snapshot() == before
    assert len(store.session_messages('factory', chats['feature']['id'])) == 1


def test_concurrent_delivery_is_once(context, slice_data):
    store, _, chats, own, *_ = context
    linked(store, own, slice_data, attention=question())
    def deliver(_):
        PostgresStore(store._url).route_chat_events()
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(deliver, range(2)))
    assert sum('Event:' in m['text'] for m in store.session_messages('factory', chats['feature']['id'])) == 1


@pytest.mark.parametrize('chat_kind', ['feature', 'project', 'orchestrator'])
@pytest.mark.parametrize('operation', ['answer_slice', 'accept_slice', 'return_slice'])
def test_slice_tool_scope_and_transitions(context, slice_data, chat_kind, operation):
    store, workshops, chats, own, other, outside, _ = context
    for feature, allowed in [(own, True), (other, chat_kind != 'feature'), (outside, chat_kind == 'orchestrator')]:
        fields = dict(state='in review', session=dict(tool='codex', id='synthetic', folder='/synthetic'))
        if operation == 'answer_slice':
            fields.update(state='issued', attention=question())
        item = linked(store, feature, slice_data, **fields)
        args = dict(slice=item['id'])
        if operation == 'answer_slice': args['text'] = 'Use the agreed design'
        if operation == 'return_slice': args['note'] = 'Fix the missing acceptance check'
        before = store.load()
        result = call(workshops[chat_kind], operation, **args)
        if not allowed:
            refused(result, 'can only write')
            assert store.load() == before
            continue
        value(result)
        saved = store.load()['slices'][0]
        assert saved['log'][-1]['actor'] == f"chat:{chats[chat_kind]['id']}"
        if operation == 'answer_slice': assert saved['attention']['answer'] == args['text']
        if operation == 'accept_slice': assert saved['state'] == 'accepted'
        if operation == 'return_slice':
            assert saved['state'] == 'issued' and saved['attention']['answer'] == args['note']


@pytest.mark.parametrize('attention_kind', ['merge', 'node-step'])
def test_slice_tools_refuse_owner_attention(context, slice_data, attention_kind):
    store, workshops, _, own, *_ = context
    linked(store, own, slice_data, state='in review', attention=question(kind=attention_kind))
    before = store.load()
    for operation, extra in [('answer_slice', dict(text='no')), ('accept_slice', {}), ('return_slice', dict(note='no'))]:
        assert call(workshops['feature'], operation, slice=slice_data['id'], **extra)['isError']
    assert store.load() == before


def test_slice_tools_refuse_unlinked_and_wrong_state(context, slice_data):
    store, workshops, _, own, *_ = context
    store.save(dict(version=1, slices=[slice_data]))
    refused(call(workshops['orchestrator'], 'accept_slice', slice=slice_data['id']), 'linked')
    linked(store, own, slice_data)
    refused(call(workshops['feature'], 'accept_slice', slice=slice_data['id']), 'not in review')
    refused(call(workshops['feature'], 'return_slice', slice=slice_data['id'], note='fix'), 'not in review')
    refused(call(workshops['feature'], 'answer_slice', slice=slice_data['id'], text='reply'), 'no unanswered')


def test_runner_handover_wakes_once_and_return_resumes(pg_store, runner_setup, slice_data):
    runner, processes, _ = runner_setup
    runner_board(pg_store, runner, slice_data, [('building', {})])
    data = pg_store.load()
    for s in data['slices']:
        s['log'].insert(0, dict(at=AT, actor='chat:1', event='add_slice'))
    pg_store.save(data)
    runner.run()
    processes.finish(kind='handover', body='Full synthetic handover with validation')
    runner.run()
    chat = pg_store.chats(kind='orchestrator')[0]
    messages = pg_store.session_messages(chat['area'], chat['id'])
    events = [m for m in messages if 'Event: in review' in m['text']]
    assert len(events) == 1 and 'Full synthetic handover' in events[0]['text']
    workshop = Workshop(pg_store, chat['id'], None)
    value(call(workshop, 'return_slice', slice='synthetic/0', note='Fix synthetic validation'))
    assert len(processes.started) == 1
    runner.run()
    assert len(processes.started) == 2
    assert_prompt(processes.started[-1], 'Fix synthetic validation')


def test_runner_question_is_taken_before_phone_notice(pg_store, runner_setup, slice_data):
    runner, processes, _ = runner_setup
    runner_board(pg_store, runner, slice_data, [('building', {})])
    data = pg_store.load()
    for s in data['slices']:
        s['log'].insert(0, dict(at=AT, actor='chat:1', event='add_slice'))
    pg_store.save(data)
    runner.run()
    processes.finish(kind='question', body='Synthetic question for chat')
    runner.run()
    item = pg_store.load()['slices'][0]
    assert pg_store.chat_attention(item)['chat_id'] == pg_store.chats(kind='orchestrator')[0]['id']
    assert not any(n['event'] == 'question' for _, n in pg_store.notices())


def test_long_event_is_bounded_without_losing_ownership(context, slice_data):
    store, _, chats, own, *_ = context
    item = linked(store, own, slice_data, attention=question('Long event\n' + 'x' * 40000))
    store.route_chat_events()
    message = store.session_messages('factory', chats['feature']['id'])[-1]
    assert len(message['text']) <= 32000 and 'characters omitted' in message['text']
    assert store.chat_attention(item)['chat_id'] == chats['feature']['id']
    projected = store.feature_board()['features']
    own_feature = next(f for f in projected if f['id'] == own)
    assert own_feature['slices'][0]['attention']['chat_id'] == chats['feature']['id']


def test_failed_delivery_remains_pending(context, slice_data, monkeypatch):
    store, _, chats, own, *_ = context
    item = linked(store, own, slice_data, attention=question())
    original = store.system_message
    def fail(*args):
        raise state.StateError('Synthetic delivery failure')
    monkeypatch.setattr(store, 'system_message', fail)
    with pytest.raises(state.StateError, match='Synthetic delivery failure'):
        store.route_chat_events()
    assert 'chat_id' not in store.chat_attention(item)
    monkeypatch.setattr(store, 'system_message', original)
    store.route_chat_events()
    assert sum('Event:' in m['text'] for m in store.session_messages('factory', chats['feature']['id'])) == 1


def test_return_without_session_uses_existing_runner_deferral(context, slice_data):
    store, workshops, _, own, *_ = context
    item = linked(store, own, slice_data, state='in review', session=None)
    value(call(workshops['feature'], 'return_slice', slice=item['id'], note='Repair the acceptance gap'))
    saved = store.load()['slices'][0]
    assert saved['state'] == 'issued' and saved['session'] is None
    assert saved['attention']['answer'] == 'Repair the acceptance gap'


@pytest.mark.parametrize('actor,event', [('owner', 'add_slice'), ('planner', 'add'), ('chat:1', 'edit')])
@pytest.mark.parametrize('kind', ['question', 'escalation', 'in review'])
def test_non_chat_slices_never_wake_chats(context, slice_data, actor, event, kind):
    store, _, chats, own, *_ = context
    item = copy.deepcopy(slice_data)
    item.update(feature_id=own, state='ready')
    item['log'] = [dict(at=AT, actor=actor, event=event)]
    store.save(dict(version=1, slices=[item]))
    if kind == 'in review':
        item['state'] = 'in review'
    else:
        item.update(state='issued', attention=question('failing check: synthetic' if kind == 'escalation' else 'Choice?', kind))
    store.save(dict(version=1, slices=[item]))
    # Also skip a previously captured but undelivered event from before the upgrade.
    with store.mutation():
        store._chat_event(store._feature(own)['feature'], item['id'], kind, 'Old queued event')
    store.route_chat_events()
    assert not any('Event:' in m['text'] for m in store.session_messages('factory', chats['feature']['id']))
    assert 'chat_id' not in (store.chat_attention(item) or {})
    # Past delivery stays recorded but no longer hides an owner/planner question.
    with store.mutation():
        store.connection.execute('UPDATE cplane_chat_events SET chat = %s WHERE slice_id = %s',
                                 (chats['feature']['id'], item['id']))
    assert 'chat_id' not in (store.chat_attention(item) or {})
    if kind in ('question', 'escalation'):
        notice = dict(at=AT, id=item['id'], event=kind, text='Owner still receives this')
        store.append_notices([notice])
        assert notice in [n for _, n in store.notices()]


def test_event_summary_names_each_slice(context, slice_data):
    store, _, chats, own, *_ = context
    first = copy.deepcopy(slice_data)
    first.update(id='factory/SD1', feature_id=own, state='issued')
    first['log'] = [dict(at=AT, actor='chat:1', event='add_slice')]
    second = copy.deepcopy(first)
    second['id'] = 'factory/SD2'
    store.save(dict(version=1, slices=[first, second]))
    for item in (first, second):
        item['state'] = 'in review'
    store.save(dict(version=1, slices=[first, second]))
    store.route_chat_events()
    summaries = [m['text'].splitlines()[0] for m in store.session_messages('factory', chats['feature']['id']) if 'Event: in review' in m['text']]
    assert summaries == ['Event: in review · factory/SD1', 'Event: in review · factory/SD2']


def test_real_chat_add_slice_routes_its_question(context):
    from test_workshop import repository, slice_args
    store, workshops, chats, own, *_ = context
    repository(store)
    created = value(call(workshops['feature'], 'add_slice', **slice_args(own)))
    data = store.load()
    data['slices'][0].update(state='issued', attention=question())
    store.save(data)
    store.route_chat_events()
    messages = store.session_messages('factory', chats['feature']['id'])
    assert messages[-1]['text'].startswith(f'Event: question · {created["id"]}\n')
    assert store.chat_attention(store.load()['slices'][0])['chat_id'] == chats['feature']['id']


def test_old_queued_owner_slice_event_is_preserved_without_running(context, slice_data):
    store, _, chats, own, *_ = context
    sid = chats['feature']['id']
    opening = store.claim_session_turn()
    store.finish_session_turn(opening, 'Grill reply', 'synthetic-resume')
    item = copy.deepcopy(slice_data)
    item.update(feature_id=own, state='in review')
    store.save(dict(version=1, slices=[item]))
    old_event = store.system_message(sid, f'Event: in review\nSlice: {item["id"]}\n\nOld event')
    assert store.claim_session_turn() is None
    message = next(m for m in store.session_messages('factory', sid) if m['id'] == old_event)
    assert message['status'] == 'done' and message['text'].endswith('Old event')
    store.system_message(sid, 'Event: testing\nSlice: (feature event)\n\nFeature event')
    assert store.claim_session_turn()['text'].endswith('Feature event')
