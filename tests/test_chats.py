"""Chat records and atomic lifecycle, with synthetic Postgres 17 data only."""
from concurrent.futures import ThreadPoolExecutor
import json
from unittest.mock import Mock

import pytest

from cplane.cli import main
from cplane.sessions import turn_command
from cplane.state import StateError
from cplane.stores import PostgresStore
from factory_ui import create_app
from test_stores import pg_store


def feature_chat(store, title='Feature', project='NEW'):
    feature = store.feature_add(project, title)
    store.feature_section(feature['id'], 'Problem', '# Synthetic problem')
    store.feature_stage(feature['id'], 'grilling', actor='chat:1')
    return feature['id'], store.chats(kind='feature')[-1]


def test_migration_carries_sessions_and_bootstraps_empty_database(pg_store):
    store = pg_store
    assert len(store.chats(kind='orchestrator')) == 1
    assert store.chats(kind='orchestrator')[0]['area'] == 'homelab'
    with store.mutation():
        store.connection.execute('DELETE FROM cplane_sessions')
        store.connection.execute('DROP TABLE cplane_chat_settings')
        store.connection.execute('DROP INDEX cplane_chat_latest_reply')
        store.connection.execute('ALTER TABLE cplane_sessions DROP COLUMN kind, DROP COLUMN project, '
                                 'DROP COLUMN feature, DROP COLUMN archived, DROP COLUMN last_read_at, '
                                 'DROP COLUMN tool_sessions, DROP COLUMN workspace_ready')
        store.connection.execute('ALTER TABLE cplane_session_messages DROP COLUMN automatic')
        store.connection.execute("DELETE FROM cplane_migrations WHERE name IN ('009_chats.sql', '010_chat_tool_sessions.sql')")
        factory = store.connection.execute(
            "INSERT INTO cplane_sessions (area,title,tool,model,cli_session_id,repositories) "
            "VALUES ('factory','Old code','claude','synthetic','saved','[\"owner/repo\"]') RETURNING id").fetchone()[0]
        lab = store.connection.execute(
            "INSERT INTO cplane_sessions (area,title,tool,model) "
            "VALUES ('homelab','Old planning','codex','synthetic') RETURNING id").fetchone()[0]
        other = store.connection.execute(
            "INSERT INTO cplane_sessions (area,title,tool,model) "
            "VALUES ('homelab','Other planning','claude','synthetic') RETURNING id").fetchone()[0]
        store.connection.execute(
            "INSERT INTO cplane_session_messages(session,role,text,status) VALUES (%s,'owner','old message','queued')", (factory,))
    store.migrate()
    store.migrate()
    chats = {c['id']: c for c in store.chats()}
    assert len(chats) == 3
    assert chats[lab]['kind'] == 'orchestrator'
    assert chats[other]['kind'] == chats[factory]['kind'] == 'legacy'
    assert chats[factory]['cli_session_id'] == 'saved'
    assert chats[factory]['workspace_ready']
    assert chats[factory]['repositories'] == ['owner/repo']
    assert store.session_messages('factory', factory)[0]['text'] == 'old message'
    assert store.claim_session_turn()['session']['cli_session_id'] == 'saved'
    with pytest.raises(StateError):
        with store.mutation():
            store.connection.execute(
                "INSERT INTO cplane_sessions(area,title,tool,model,kind) VALUES ('homelab','Duplicate','codex','synthetic','orchestrator')")


def test_feature_event_atomic_creation_order_and_reentry(pg_store, tmp_path):
    identifier, chat = feature_chat(pg_store)
    assert (chat['kind'], chat['project'], chat['feature'], chat['area']) == ('feature', 'NEW', identifier, 'factory')
    message = pg_store.session_messages('factory', chat['id'])[0]
    assert message['role'] == 'system' and message['automatic'] and message['status'] == 'queued'
    for text in (identifier, 'Feature', 'NEW', 'Problem', '# Synthetic problem', 'Run the grill'):
        assert text in message['text']
    pg_store.session_messages('factory', chat['id'], 'owner first')
    turn = pg_store.claim_session_turn()
    assert turn['role'] == 'owner' and turn['text'] == 'owner first'
    pg_store.finish_session_turn(turn, 'reply', 'synthetic-resume')
    turn = pg_store.claim_session_turn()
    assert turn['role'] == 'system'
    assert turn_command(turn, tmp_path, [], tmp_path)[-1].startswith('Workshop event: ' + message['text'])
    assert turn['session']['cli_session_id'] == 'synthetic-resume'
    pg_store.finish_session_turn(turn, 'grill reply', 'synthetic-resume')
    pg_store.feature_stage(identifier, 'shortlist')
    pg_store.feature_stage(identifier, 'grilling')
    assert len(pg_store.chats(kind='feature')) == 1
    assert len(pg_store.session_messages('factory', chat['id'])) == 4
    # Existing aliases continue to identify the same chat after a project move.
    moved = pg_store.feature_move(identifier, 'FAC')
    chat = pg_store.chats(kind='feature')[0]
    assert chat['project'] == 'FAC' and chat['feature'] == moved['id']


def test_chat_creation_failure_rolls_back_stage_and_event(pg_store, monkeypatch):
    identifier = pg_store.feature_add('NEW', 'Rollback')['id']
    before = pg_store.feature_show(identifier)
    monkeypatch.setattr(pg_store, '_create_chat', Mock(side_effect=StateError('synthetic failure')))
    with pytest.raises(StateError, match='synthetic failure'):
        pg_store.feature_stage(identifier, 'grilling')
    assert pg_store.feature_show(identifier) == before
    assert pg_store.chats(kind='feature') == []
    with pg_store.locked():
        assert pg_store.connection.execute('SELECT count(*) FROM cplane_feature_events').fetchone()[0] == 1


def test_archive_waiting_read_unread_and_reopen(pg_store):
    identifier, chat = feature_chat(pg_store)
    sid = chat['id']
    assert not chat['waiting']
    turn = pg_store.claim_session_turn()
    pg_store.finish_session_turn(turn, 'Question?', 'synthetic')
    assert pg_store.chats(kind='feature')[0]['waiting']
    assert not pg_store.chat_open(sid)['chat']['waiting']
    assert pg_store.chat_read(sid, unread=True)['waiting']
    assert not pg_store.chat_read(sid)['waiting']
    with pg_store.mutation():
        pg_store.connection.execute("UPDATE cplane_features SET stage = 'testing', review_passed = now() WHERE id = %s", (identifier,))
    pg_store.feature_stage(identifier, 'done')
    archived = pg_store.chats(kind='feature', archived=True)[0]
    assert archived['id'] == sid
    pg_store.system_message(sid, 'An archived event')
    assert pg_store.claim_session_turn() is None
    assert len(pg_store.chat_open(sid)['messages']) == 3
    assert pg_store.chats(kind='feature')[0]['archived']
    pg_store.session_messages('factory', sid, 'Reopen')
    assert not pg_store.chats(kind='feature')[0]['archived']
    assert pg_store.claim_session_turn()['text'] == 'Reopen'


def test_project_unique_defaults_and_configuration(pg_store):
    pg_store.project_add('XYZ', 'Synthetic project', repository='owner/repo')
    pg_store.chat_defaults('project', chat_tool='claude', chat_model='synthetic-a')
    with ThreadPoolExecutor(2) as pool:
        def create(_):
            try:
                return PostgresStore(pg_store._url).create_project_chat('XYZ')['id']
            except StateError:
                return None
        ids = list(pool.map(create, range(2)))
    assert len([sid for sid in ids if sid]) == 1
    chat = pg_store.chats(kind='project')[0]
    assert chat['repositories'] == ['owner/repo']
    assert chat['tool'] == 'claude' and chat['model'] == 'synthetic-a'
    pg_store.chat_defaults('project', chat_model='synthetic-b')
    assert pg_store.chats(kind='project')[0]['model'] == 'synthetic-a'
    assert pg_store.chat_configure(chat['id'], model='synthetic-c')['model'] == 'synthetic-c'
    for kwargs in (dict(tool='shell'), dict(model='--bad'), dict(model=''), dict(model=['bad'])):
        with pytest.raises(StateError):
            pg_store.chat_configure(chat['id'], **kwargs)
    pg_store.session_messages('factory', chat['id'], 'Run')
    pg_store.claim_session_turn()
    with pytest.raises(StateError, match='running'):
        pg_store.chat_configure(chat['id'], model='synthetic-d')
    assert pg_store.chats(kind='project')[0]['model'] == 'synthetic-c'


def test_routes_guard_defaults_and_cli(pg_store, capsys, monkeypatch):
    client = create_app(pg_store).test_client()
    headers = {'X-Factory-UI': '1'}
    pg_store.project_add('XYZ', 'Synthetic', repository='owner/repo')
    assert client.post('/api/chats/project', json={'project': 'XYZ'}).status_code == 403
    response = client.post('/api/chats/project', json={'project': 'XYZ'}, headers=headers)
    assert response.status_code == 201
    sid = response.json['id']
    assert 'cli_session_id' not in response.json
    assert client.post('/api/chats/project', json={'project': 'XYZ'}, headers=headers).status_code == 400
    assert client.get('/api/chats?kind=project&project=XYZ&archived=false').json[0]['id'] == sid
    assert client.get('/api/chats?archived=no').status_code == 400
    for suffix in ('open', 'read', 'unread'):
        assert client.post(f'/api/chats/{sid}/{suffix}').status_code == 403
        assert client.post(f'/api/chats/{sid}/{suffix}', headers=headers).status_code == 200
    assert client.patch(f'/api/chats/{sid}', json={'model': 'synthetic'}).status_code == 403
    assert client.patch(f'/api/chats/{sid}', json={'model': 'synthetic'}, headers=headers).json['model'] == 'synthetic'
    assert client.patch(f'/api/chats/{sid}', json={'repositories': []}, headers=headers).status_code == 400
    assert client.patch('/api/chats/defaults/feature', json={'chat_tool': 'claude', 'chat_model': 'synthetic'}, headers=headers).status_code == 200
    assert main(['chat', 'list', '--kind', 'project']) == 0
    assert json.loads(capsys.readouterr().out)[0]['id'] == sid
    for command in ('open', 'read', 'unread'):
        assert main(['chat', command, str(sid)]) == 0
        assert 'cli_session_id' not in capsys.readouterr().out
    assert main(['chat', 'configure', str(sid), '--model', 'synthetic-cli']) == 0
    assert json.loads(capsys.readouterr().out)['model'] == 'synthetic-cli'
    assert main(['chat', 'defaults', 'project', '--model', 'synthetic-default']) == 0
    assert json.loads(capsys.readouterr().out)['project']['chat_model'] == 'synthetic-default'
    assert main(['chat', 'project', 'NEW']) == 0
    assert json.loads(capsys.readouterr().out)['project'] == 'NEW'
    monkeypatch.delenv('CPLANE_DATABASE_URL')
    assert main(['chat', 'list']) == 1


def test_queue_prioritizes_owner_globally_and_serializes_shared_repository(pg_store):
    pg_store.project_add('XYZ', 'Synthetic', repository='owner/shared')
    chat = pg_store.create_project_chat('XYZ')
    feature, feature_chat_row = feature_chat(pg_store, project='XYZ')
    pg_store.session_messages('factory', chat['id'], 'Owner first')
    owner = pg_store.claim_session_turn()
    assert owner['session']['id'] == chat['id']
    assert pg_store.claim_session_turn() is None
    unrelated = pg_store.create_session('factory', 'Other', 'codex', 'synthetic', ['owner/other'])
    pg_store.session_messages('factory', unrelated, 'Independent')
    second = pg_store.claim_session_turn()
    assert second['session']['id'] == unrelated
    pg_store.finish_session_turn(owner, 'Done', 'synthetic')
    event = pg_store.claim_session_turn()
    assert event['session']['id'] == feature_chat_row['id']
    assert event['role'] == 'system'


def test_concurrent_feature_stage_creates_only_one_chat(pg_store):
    identifier = pg_store.feature_add('NEW', 'Concurrent')['id']
    def move(_):
        try:
            PostgresStore(pg_store._url).feature_stage(identifier, 'grilling')
            return True
        except StateError:
            return False
    with ThreadPoolExecutor(2) as pool:
        assert sorted(pool.map(move, range(2))) == [False, True]
    assert len(pg_store.chats(kind='feature')) == 1
    chat = pg_store.chats(kind='feature')[0]
    assert len(pg_store.session_messages('factory', chat['id'])) == 1


@pytest.mark.parametrize(('project', 'repository'), [('FAC', 'factory'), ('LAB', 'homelab-v2'), ('NEW', None)])
def test_seeded_projects_accept_plain_or_absent_repositories(pg_store, project, repository):
    chat = pg_store.create_project_chat(project)
    assert chat['repositories'] == ([] if repository is None else [repository])
    identifier, feature = feature_chat(pg_store, project=project)
    assert feature['repositories'] == chat['repositories']
    assert feature['feature'] == identifier
    if repository is None:
        assert pg_store.claim_session_turn()['session']['id'] == feature['id']
    else:
        assert pg_store.claim_session_turn() is None
        messages = pg_store.session_messages('factory', feature['id'])
        assert messages[0]['status'] == 'failed'
        assert messages[1]['role'] == 'system' and 'Repository is unknown' in messages[1]['text']


@pytest.mark.parametrize(('known', 'expected'), [
    ([], 'factory'),
    (['owner/factory'], 'owner/factory'),
    (['owner/another-repository'], 'owner/factory'),
    (['owner/factory', 'other/unrelated'], 'owner/factory'),
    (['owner/factory', 'other/factory'], 'factory'),
    (['owner/one', 'other/two'], 'factory'),
])
def test_project_repository_resolution_uses_unambiguous_factory_evidence(pg_store, known, expected):
    for repository in known:
        pg_store.create_session('factory', 'Existing', 'codex', 'synthetic', [repository])
    # Planning chats do not provide Factory repository-owner evidence.
    pg_store.create_session('homelab', 'Planning', 'codex', 'synthetic', ['planning/factory'])
    assert pg_store.create_project_chat('FAC')['repositories'] == [expected]
    _, feature = feature_chat(pg_store, project='FAC')
    assert feature['repositories'] == [expected]


def test_plain_name_resolves_before_claim_without_overlapping_running_repository(pg_store):
    _, feature = feature_chat(pg_store, project='FAC')
    assert feature['repositories'] == ['factory']
    legacy = pg_store.create_session('factory', 'Existing', 'codex', 'synthetic', ['owner/factory'])
    pg_store.session_messages('factory', legacy, 'Owner first')
    turn = pg_store.claim_session_turn()
    assert turn['session']['id'] == legacy
    assert pg_store.claim_session_turn() is None
    pg_store.finish_session_turn(turn, 'Reply', 'synthetic')
    turn = pg_store.claim_session_turn()
    assert turn['session']['id'] == feature['id']
    assert turn['session']['repositories'] == ['owner/factory']
    assert pg_store.chat_show(feature['id'])['repositories'] == ['owner/factory']


@pytest.mark.parametrize(('slice_repos', 'expected'), [
    (['owner/other'], 'owner/factory'),
    (['Owner/one', 'owner/two'], 'Owner/factory'),
    (['owner/one', 'other/two'], 'factory'),
])
def test_slice_repositories_supply_owner_evidence(pg_store, slice_repos, expected):
    from psycopg.types.json import Jsonb
    with pg_store.mutation():
        for i, repo in enumerate(slice_repos):
            pg_store.connection.execute(
                'INSERT INTO cplane_slices (id, position, document) VALUES (%s, %s, %s)',
                (str(i), i, Jsonb({'repo': repo})))
    assert pg_store.create_project_chat('FAC')['repositories'] == [expected]


def test_unresolved_message_fails_and_other_chat_runs(pg_store):
    chat = pg_store.create_project_chat('FAC')
    pg_store.session_messages('factory', chat['id'], 'Cannot resolve')
    other = pg_store.create_session('homelab', 'Other', 'codex', 'synthetic', [])
    pg_store.session_messages('homelab', other, 'Can run')
    turn = pg_store.claim_session_turn()
    assert turn['session']['id'] == other
    messages = pg_store.session_messages('factory', chat['id'])
    assert [(m['role'], m['status']) for m in messages] == [('owner', 'failed'), ('system', 'done')]
    assert messages[1]['automatic'] and 'Repository is unknown' in messages[1]['text']
    assert pg_store.chat_show(chat['id'])['state'] == 'idle'
    pg_store.finish_session_turn(turn, 'Done')
    assert pg_store.claim_session_turn() is None
    assert len(pg_store.session_messages('factory', chat['id'])) == 2


def test_invalid_project_repository_does_not_create_chat(pg_store):
    pg_store.project_add('XYZ', 'Invalid', repository='../outside')
    with pytest.raises(StateError, match='Invalid project repository'):
        pg_store.create_project_chat('XYZ')
    assert not pg_store.chats(kind='project')


def test_tool_switch_keeps_separate_resume_ids_and_original_skill_snapshot(pg_store, tmp_path):
    sid = pg_store.create_session('factory', 'Switch providers', 'codex', 'synthetic', [])
    pg_store.session_messages('factory', sid, 'First')
    first = pg_store.claim_session_turn()
    pg_store.finish_session_turn(first, 'Codex reply', 'codex-saved')
    switched = pg_store.chat_configure(sid, tool='claude', model='synthetic-claude')
    assert switched['cli_session_id'] is None and switched['workspace_ready']
    assert switched['skill_names'] == first['session']['skill_names']
    pg_store.session_messages('factory', sid, 'Claude turn')
    second = pg_store.claim_session_turn()
    assert '--resume' not in turn_command(second, tmp_path, [], tmp_path)
    assert second['session']['skill_version'] == first['session']['skill_version']
    pg_store.finish_session_turn(second, 'Claude reply', 'claude-saved')
    # Another store instance must recover both provider IDs after a restart.
    store = PostgresStore(pg_store._url)
    assert store.chat_configure(sid, tool='codex', model='synthetic-codex')['cli_session_id'] == 'codex-saved'
    store.session_messages('factory', sid, 'Codex again')
    third = store.claim_session_turn()
    args = turn_command(third, tmp_path, [], tmp_path)
    assert args[args.index('resume') + 1] == 'codex-saved'
    store.finish_session_turn(third, 'Reply', 'codex-saved')
    assert store.chat_configure(sid, tool='claude', model='synthetic-claude')['cli_session_id'] == 'claude-saved'
    response = create_app(store).test_client().get(f'/api/chats/{sid}')
    for private in ('tool_sessions', 'cli_session_id', 'workspace_ready', 'codex-saved', 'claude-saved'):
        assert private not in response.get_data(as_text=True)


def test_existing_resumed_chat_upgrades_without_resnapshotting_skills(pg_store):
    sid = pg_store.create_session('factory', 'Old session', 'codex', 'synthetic', [])
    with pg_store.mutation():
        pg_store.connection.execute('ALTER TABLE cplane_sessions DROP COLUMN tool_sessions, DROP COLUMN workspace_ready')
        pg_store.connection.execute('UPDATE cplane_sessions SET cli_session_id = %s WHERE id = %s', ('old-codex', sid))
        pg_store.connection.execute("DELETE FROM cplane_migrations WHERE name = '010_chat_tool_sessions.sql'")
    pg_store.migrate()
    assert pg_store.chat_show(sid)['workspace_ready']
    assert pg_store.chat_configure(sid, tool='claude', model='synthetic')['cli_session_id'] is None
    pg_store.session_messages('factory', sid, 'Switch')
    turn = pg_store.claim_session_turn()
    assert turn['session']['skill_names'] is None
    assert turn['session']['skill_version'] is None
    pg_store.finish_session_turn(turn, 'Reply', 'new-claude')
    assert pg_store.chat_configure(sid, tool='codex')['cli_session_id'] == 'old-codex'


@pytest.mark.parametrize('installable', [True, False])
def test_node_step_wakes_only_installable_and_keeps_home_card(pg_store, slice_data, monkeypatch, installable):
    identifier, chat = feature_chat(pg_store)
    monkeypatch.setenv('CPLANE_INSTALL_REPOS', 'example/repo' if installable else 'other/repo')
    slice_data.update(feature_id=identifier, state='awaiting handover', attention=dict(kind='node-step',
        body='Install the change', since='2026-01-01T00:00:00Z', answer=None, approved=False))
    pg_store.save(dict(version=1, slices=[slice_data]))
    pg_store.route_chat_events()
    pg_store.route_chat_events()
    events = [m for m in pg_store.session_messages('factory', chat['id']) if 'Event: node-step' in m['text']]
    assert len(events) == int(installable)
    cards = create_app(pg_store).test_client().get('/api/home').get_json()['attention']
    card = next(a for a in cards if a['kind'] == 'install')
    assert card['installable'] == installable and not card['installing']


def test_install_failure_remains_on_home_and_phone(pg_store, slice_data):
    identifier, chat = feature_chat(pg_store)
    body = 'Install failed; inspect the root install unit'
    slice_data.update(feature_id=identifier, state='escalated', attention=dict(kind='escalation',
        body=body, since='2026-01-01T00:00:00Z', answer=None, approved=False))
    notice = dict(at=slice_data['attention']['since'], id=slice_data['id'], event='escalation', text=body)
    pg_store.save(dict(version=1, slices=[slice_data]), [notice])
    pg_store.route_chat_events()
    assert not any('Event: escalation' in m['text'] for m in pg_store.session_messages('factory', chat['id']))
    assert notice in [n for _, n in pg_store.notices()]
    cards = create_app(pg_store).test_client().get('/api/home').get_json()['attention']
    assert any(a['kind'] == 'failure' and a['id'] == slice_data['id'] for a in cards)


def prepare_testing_turn(store, identifier, chat, number):
    # Synthetic stage setup, then the real transition and event delivery.
    with store.mutation():
        store.connection.execute("UPDATE cplane_features SET stage = 'building' WHERE id = %s", (identifier,))
    store.feature_stage(identifier, 'testing', actor='runner')
    store.route_chat_events()
    turn = store.claim_session_turn()
    assert turn and 'Event: testing' in turn['text']
    store.feature_section(identifier, f'Testing review {number}', 'What changed. Where to look. Checks. What to try.', actor=f"chat:{chat['id']}")
    store.finish_session_turn(turn, 'Please test and reply in open text.')
    return turn


def test_testing_review_wait_lifecycle_and_once_only_phone(pg_store):
    from cplane.runner import BOT_EVENTS
    identifier, chat = feature_chat(pg_store)
    pg_store.finish_session_turn(pg_store.claim_session_turn(), 'Grill completed.')
    turn = prepare_testing_turn(pg_store, identifier, chat, 1)
    client = create_app(pg_store).test_client()
    def reviews():
        return [a for a in client.get('/api/home').get_json()['attention'] if a['kind'] == 'testing-review']
    assert len(reviews()) == 1
    assert reviews()[0]['id'] == identifier and reviews()[0]['chat'] == chat['id']
    assert reviews()[0]['since']
    pg_store.chat_open(chat['id'])
    assert len(reviews()) == 1
    with pg_store.mutation():
        pg_store.finish_testing_review(turn)
    assert len([n for _, n in pg_store.notices() if n['event'] == 'testing-review']) == 1
    assert 'testing-review' in BOT_EVENTS
    pg_store.session_messages('factory', chat['id'], 'The button is broken; also an idea.')
    assert reviews() == []
    owner_turn = pg_store.claim_session_turn()
    pg_store.finish_session_turn(owner_turn, 'defect: button\nidea: later')
    assert reviews() == []
    pg_store.feature_stage(identifier, 'building', actor=f"chat:{chat['id']}")
    prepare_testing_turn(pg_store, identifier, chat, 2)
    assert len(reviews()) == 1
    assert len([n for _, n in pg_store.notices() if n['event'] == 'testing-review']) == 2
    pg_store.feature_mark(identifier, 'review', actor=f"chat:{chat['id']}")
    pg_store.feature_stage(identifier, 'done', actor=f"chat:{chat['id']}")
    assert reviews() == []


def test_testing_reply_without_review_or_failed_turn_does_not_request_testing(pg_store):
    identifier, chat = feature_chat(pg_store)
    pg_store.finish_session_turn(pg_store.claim_session_turn(), 'Grill completed.')
    with pg_store.mutation():
        pg_store.connection.execute("UPDATE cplane_features SET stage = 'building' WHERE id = %s", (identifier,))
    pg_store.feature_stage(identifier, 'testing', actor='runner')
    pg_store.route_chat_events()
    turn = pg_store.claim_session_turn()
    pg_store.finish_session_turn(turn, 'Still checking installs.')
    assert pg_store.testing_review_waits() == []
    pg_store.system_message(chat['id'], 'Continue review')
    turn = pg_store.claim_session_turn()
    pg_store.feature_section(identifier, 'Testing review 1', 'Review text')
    pg_store.finish_session_turn(turn, 'Turn failed', failed=True)
    assert pg_store.testing_review_waits() == []


def test_owner_message_during_review_turn_clears_wait(pg_store):
    identifier, chat = feature_chat(pg_store)
    pg_store.finish_session_turn(pg_store.claim_session_turn(), 'Grill completed.')
    with pg_store.mutation():
        pg_store.connection.execute("UPDATE cplane_features SET stage = 'building' WHERE id = %s", (identifier,))
    pg_store.feature_stage(identifier, 'testing', actor='runner')
    pg_store.route_chat_events()
    turn = pg_store.claim_session_turn()
    pg_store.feature_section(identifier, 'Testing review 1', 'Review')
    pg_store.session_messages('factory', chat['id'], 'Already tested; the button fails.')
    pg_store.finish_session_turn(turn, 'Please test.')
    assert pg_store.testing_review_waits() == []


def test_old_review_append_cannot_start_new_testing_wait(pg_store):
    identifier, chat = feature_chat(pg_store)
    pg_store.finish_session_turn(pg_store.claim_session_turn(), 'Grill completed.')
    prepare_testing_turn(pg_store, identifier, chat, 1)
    pg_store.feature_stage(identifier, 'building', actor=f"chat:{chat['id']}")
    assert pg_store.testing_review_waits() == []
    pg_store.feature_stage(identifier, 'testing', actor='runner')
    pg_store.route_chat_events()
    turn = pg_store.claim_session_turn()
    pg_store.feature_section(identifier, 'Testing review 1', 'Old review\nIdeas from testing\nAnother idea')
    pg_store.finish_session_turn(turn, 'Saved an idea.')
    assert pg_store.testing_review_waits() == []


def test_preexisting_install_failure_ownership_cannot_hide_owner_notice(pg_store, slice_data):
    identifier, chat = feature_chat(pg_store)
    body = 'Install unit disappeared; inspect the node before retrying'
    at = '2026-01-01T00:00:00Z'
    slice_data.update(feature_id=identifier, state='escalated', attention=dict(kind='escalation',
        body=body, since=at, answer=None, approved=False))
    pg_store.save(dict(version=1, slices=[slice_data]))
    # A delivered record left by the previous implementation is no longer chat-owned.
    with pg_store.mutation():
        feature = pg_store._feature(identifier)['feature']
        pg_store._chat_event(feature, slice_data['id'], 'escalation', body, at)
        pg_store.connection.execute("UPDATE cplane_chat_events SET delivered = true, chat = %s WHERE kind = 'escalation'", (chat['id'],))
    notice = dict(at=at, id=slice_data['id'], event='escalation', text='escalation: ' + body)
    pg_store.append_notices([notice])
    assert notice in [n for _, n in pg_store.notices()]
    assert 'chat_id' not in pg_store.chat_attention(slice_data)


def test_owner_message_processed_before_testing_event_does_not_clear_new_wait(pg_store):
    identifier, chat = feature_chat(pg_store)
    pg_store.finish_session_turn(pg_store.claim_session_turn(), 'Grill completed.')
    with pg_store.mutation():
        pg_store.connection.execute("UPDATE cplane_features SET stage = 'building' WHERE id = %s", (identifier,))
    pg_store.feature_stage(identifier, 'testing', actor='runner')
    pg_store.route_chat_events()
    pg_store.session_messages('factory', chat['id'], 'What is the current status?')
    owner = pg_store.claim_session_turn()
    assert owner['role'] == 'owner'
    pg_store.finish_session_turn(owner, 'Preparing the review.')
    turn = pg_store.claim_session_turn()
    assert turn['role'] == 'system' and turn['id'] < owner['id']
    pg_store.feature_section(identifier, 'Testing review 1', 'Review')
    pg_store.finish_session_turn(turn, 'Please test.')
    assert len(pg_store.testing_review_waits()) == 1
