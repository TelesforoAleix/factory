"""Settings contracts, using synthetic output at the fenced process boundary."""
import copy
import json
import os
import subprocess
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import Mock

import pytest

from cplane import models, sessions, state
from cplane.cli import main
from cplane.executors import command
from cplane.runner import Runner
from cplane.stores import PostgresStore
from cplane.workshop import Workshop, TOOLS
from factory_ui import create_app
from test_stores import pg_store
from conftest import seed_model_choices

HEADERS = {'X-Factory-UI': '1'}
VISIBLE = dict(slug='gpt-6.1-sol', visibility='list',
               supported_reasoning_levels=[dict(effort='low'), dict(effort='medium'), dict(effort='ultra')])
CODEX = dict(models=[VISIBLE, {**VISIBLE, 'slug': 'hidden', 'visibility': 'hide'}])


@pytest.fixture
def programs(tmp_path, monkeypatch):
    work = tmp_path / 'work'
    runs = tmp_path / 'runs'
    work.mkdir()
    runs.mkdir()
    from cplane import fence
    monkeypatch.setattr(fence, 'WORK_ROOT', work)
    monkeypatch.setattr(fence, 'ROOT_UID', os.getuid())
    monkeypatch.setattr(sessions, 'RUNS', runs)
    monkeypatch.setattr(models.os, 'chown', Mock())
    # This fixture substitutes direct ownership; real privilege checks have separate coverage.
    monkeypatch.setattr('cplane.fence.require_ownership_support', lambda: None)
    calls = []

    def run(argv, **kwargs):
        if argv[:2] == ['factory-cli', 'session-cleanup']:
            return subprocess.CompletedProcess(argv, 0, '', '')
        assert argv[:2] == ['factory-cli', 'run']
        assert int(argv[argv.index('--session-turn') + 1]) > 2**128
        assert kwargs['stdin'] == subprocess.DEVNULL
        assert kwargs['capture_output'] and kwargs['text']
        assert not any('TOKEN' in key or 'LOGIN' in key for key in kwargs['env'])
        args = argv[argv.index('--') + 1:]
        calls.append(args)
        if args[0] == 'codex':
            assert args == ['codex', 'debug', 'models']
            stdout = json.dumps(CODEX)
        else:
            assert args[:2] == ['claude', '-p']
            alias = args[args.index('--model') + 1]
            assert '--output-format' in args and args[-1] == 'Reply only: OK'
            stdout = json.dumps(dict(modelUsage={f'claude-{alias}-synthetic': {}}, result='OK'))
        return subprocess.CompletedProcess(argv, 0, stdout, '')
    monkeypatch.setattr(models.subprocess, 'run', run)
    return calls


def test_catalog_updates_run_only_on_request_and_keep_tool_rows(pg_store, programs, capsys):
    assert pg_store.model_list() == []
    assert programs == []
    assert main(['models', 'update', 'codex']) == 0
    assert len(programs) == 1
    rows = pg_store.model_list()
    assert [(r['model'], r['efforts']) for r in rows] == [('gpt-6.1-sol', ['low', 'medium', 'ultra'])]
    assert rows[0]['refreshed_at']
    assert main(['models', 'update', 'claude']) == 0
    assert len(programs) == 5
    assert [p[p.index('--model') + 1] for p in programs[1:]] == list(models.ALIASES)
    rows = pg_store.model_list()
    claude = [r for r in rows if r['tool'] == 'claude']
    assert len(claude) == 4
    assert all(r['efforts'] == models.CLAUDE_EFFORTS for r in claude)
    assert {r['model'] for r in claude} == {f'claude-{a}-synthetic' for a in models.ALIASES}
    assert main(['models', 'list']) == 0
    pg_store.model_choice('codex', 'gpt-6.1-sol', 'ultra')
    pg_store.role_set('strong', 'codex', 'gpt-6.1-sol', 'ultra')
    assert len(programs) == 5
    assert 'hidden' not in capsys.readouterr().out


@pytest.mark.parametrize('fault', ['exit', 'timeout', 'json', 'empty', 'effort', 'claude_partial'])
def test_failed_update_retains_previous_rows_and_fixed_reason(pg_store, programs, monkeypatch, fault):
    assert pg_store.models_update('codex')['status'] == 'completed'
    assert pg_store.models_update('claude')['status'] == 'completed'
    before = pg_store.model_list()
    original = models.subprocess.run
    count = 0
    def fail(argv, **kwargs):
        nonlocal count
        if argv[:2] == ['factory-cli', 'session-cleanup']:
            return subprocess.CompletedProcess(argv, 0, '', '')
        count += 1
        if fault == 'claude_partial' and count == 1:
            return original(argv, **kwargs)
        if fault == 'timeout':
            raise subprocess.TimeoutExpired('private', 1, output='private token')
        output = {'json': 'private token', 'empty': '{"models":[]}',
                  'effort': json.dumps(dict(models=[{**VISIBLE, 'supported_reasoning_levels': [dict(effort='bad')]}]))}.get(fault, '{}')
        return subprocess.CompletedProcess(argv, 1 if fault in ('exit', 'claude_partial') else 0, output, 'private token')
    monkeypatch.setattr(models.subprocess, 'run', fail)
    tool = 'claude' if fault == 'claude_partial' else 'codex'
    assert pg_store.models_update(tool) == dict(tool=tool, status='failed', reason=models.FAILURE)
    assert pg_store.model_list() == before


def test_database_insert_failure_rolls_back_whole_replacement(pg_store, programs):
    pg_store.models_update('codex')
    before = pg_store.model_list()
    with pg_store.mutation():
        pg_store.connection.execute("CREATE FUNCTION refuse_model() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'synthetic'; END $$")
        pg_store.connection.execute('CREATE TRIGGER refuse BEFORE INSERT ON cplane_models FOR EACH ROW EXECUTE FUNCTION refuse_model()')
    assert pg_store.models_update('codex')['status'] == 'failed'
    assert pg_store.model_list() == before


@pytest.mark.parametrize('refusal', [dict(is_error=True, modelUsage={}, result='private refusal'),
                                    dict(is_error=True, modelUsage={'private-model': {}}),
                                    dict(modelUsage={}), {}, dict(modelUsage=None)])
def test_claude_catalog_skips_refusal_or_missing_model(refusal):
    calls = []
    def run(argv):
        alias = argv[argv.index('--model') + 1]
        calls.append(alias)
        return json.dumps(refusal if alias == 'fable' else
                          dict(modelUsage={f'claude-{alias}-synthetic': {}}, result='private output'))
    rows = models.catalog('claude', run)
    assert calls == list(models.ALIASES)
    assert rows == [dict(model=f'claude-{a}-synthetic', label=a, efforts=models.CLAUDE_EFFORTS)
                    for a in models.ALIASES if a != 'fable']


@pytest.mark.parametrize('payload', [dict(is_error=True, modelUsage={}, result='private refusal'),
                                   dict(modelUsage={}), {}])
def test_claude_catalog_all_refuse_or_missing_model_fails(payload):
    with pytest.raises(ValueError, match='empty or duplicate catalog'):
        models.catalog('claude', lambda argv: json.dumps(payload))


@pytest.mark.parametrize('all_refuse', [False, True])
def test_claude_update_reports_skips_and_preserves_rows_on_all_refuse(
        pg_store, programs, monkeypatch, capsys, all_refuse):
    assert pg_store.models_update('codex')['status'] == 'completed'
    assert pg_store.models_update('claude')['status'] == 'completed'
    before = pg_store.model_list()
    original = models.subprocess.run
    def probe(argv, **kwargs):
        if argv[:2] == ['factory-cli', 'run'] and argv[argv.index('--tool') + 1] == 'claude':
            alias = argv[argv.index('--model') + 1]
            if all_refuse or alias == 'fable':
                return subprocess.CompletedProcess(argv, 0, json.dumps(dict(
                    is_error=True, modelUsage={}, result='private refusal')), '')
        return original(argv, **kwargs)
    monkeypatch.setattr(models.subprocess, 'run', probe)
    assert main(['models', 'update', 'claude']) == (1 if all_refuse else 0)
    result = json.loads(capsys.readouterr().out)
    if all_refuse:
        assert result == dict(status='failed', tool='claude', reason=models.FAILURE)
        assert pg_store.model_list() == before
    else:
        assert result == dict(status='completed', tool='claude', skipped=['fable'],
                              reason='Skipped aliases: fable.')
        rows = pg_store.model_list()
        assert [r for r in rows if r['tool'] == 'codex'] == [r for r in before if r['tool'] == 'codex']
        assert {r['label'] for r in rows if r['tool'] == 'claude'} == {'opus', 'sonnet', 'haiku'}
        pg_store.models_request('claude')
        assert pg_store.models_process_one()
        update = pg_store.models_status()['updates'][0]
        assert update['status'] == 'completed'
        assert update['reason'] == 'Skipped aliases: fable.'
        assert 'private' not in json.dumps(pg_store.models_status())


def test_seven_roles_and_default_limits(pg_store):
    roles = {r['role']: r for r in pg_store.role_list()}
    assert set(roles) == {'orchestrator', 'project', 'feature', 'secretary', 'light', 'standard', 'strong'}
    assert roles['light']['model'] == 'gpt-6-luna' and roles['light']['effort'] == 'low'
    assert roles['standard']['model'] == 'gpt-6.1-terra'
    assert roles['strong']['model'] == 'gpt-6.1-sol'
    assert all(roles[k]['effort'] == 'medium' for k in ('orchestrator', 'project', 'feature', 'standard', 'strong'))
    assert roles['secretary']['effort'] == 'low'
    assert pg_store.limit_show() == dict(building_limit=3, waiting_limit=3, chat_auto_turns=5, executors=2, repository_runs=1)


def test_role_inheritance_overrides_removal_and_resume_ids(pg_store):
    seed_model_choices(pg_store)
    with pg_store.mutation():
        pg_store.connection.execute("UPDATE cplane_projects SET repository = 'owner/repo' WHERE key = 'FAC'")
    sid = pg_store.create_project_chat('FAC')['id']
    pg_store.session_messages('factory', sid, 'First')
    first = pg_store.claim_session_turn()
    pg_store.finish_session_turn(first, 'reply', 'codex-saved')
    pg_store.role_set('project', 'claude', 'synthetic-a', 'xhigh')
    pg_store.session_messages('factory', sid, 'Second')
    second = pg_store.claim_session_turn()
    assert (second['session']['tool'], second['session']['model'], second['session']['effort']) == ('claude', 'synthetic-a', 'xhigh')
    assert second['session']['cli_session_id'] is None
    pg_store.finish_session_turn(second, 'reply', 'claude-saved')
    pg_store.chat_configure(sid, model='synthetic-b', effort='low')
    pg_store.role_set('project', 'claude', 'synthetic-c', 'max')
    assert pg_store.chat_show(sid)['model'] == 'synthetic-b'
    assert pg_store.chat_show(sid)['effort'] == 'low'
    pg_store.chat_configure(sid, model=None, effort=None)
    assert pg_store.chat_show(sid)['model'] == 'synthetic-c'
    pg_store.role_set('project', 'codex', 'synthetic', 'high')
    assert pg_store.chat_show(sid)['cli_session_id'] == 'codex-saved'
    with pg_store.mutation():
        pg_store.connection.execute('DELETE FROM cplane_models')
    assert not pg_store.chat_show(sid)['in_list']
    assert not next(r for r in pg_store.role_list() if r['role'] == 'project')['in_list']
    pg_store.session_messages('factory', sid, 'Still works')
    assert pg_store.claim_session_turn()['session']['model'] == 'synthetic'


@pytest.mark.parametrize('tool', ['codex', 'claude'])
@pytest.mark.parametrize('effort', ['low', 'xhigh', 'max'])
def test_every_chat_and_executor_command_passes_effort(tool, effort, tmp_path):
    turn = dict(id=1, text='Synthetic', session=dict(tool=tool, model='synthetic', effort=effort, cli_session_id=None))
    argv = sessions.turn_command(turn, tmp_path, [], tmp_path)
    job = dict(tool=tool, model='synthetic', effort=effort, run=str(tmp_path), repo=str(tmp_path), prompt='Synthetic')
    job['fence'] = True
    for args in (argv, command(job)):
        if tool == 'codex':
            assert f'model_reasoning_effort="{effort}"' in args
        else:
            assert args[args.index('--effort') + 1] == effort


def test_slice_level_resolves_at_launch_and_explicit_fields_win(pg_store, tmp_path):
    seed_model_choices(pg_store)
    add = ['add', '--id', 'new/W2', '--repo', 'owner/repo', '--feature', 'Synthetic', '--title', 'Task', '--level', 'light']
    assert main(add) == 0
    item = pg_store.load()['slices'][0]
    assert 'level' not in item  # v1 document contract retained
    assert pg_store.slice_policy(item['id']) == dict(level='light', overrides={})
    assert pg_store.slice_executor(item) == dict(tool='codex', model='gpt-6-luna', effort='low')
    pg_store.role_set('light', 'claude', 'synthetic', 'high')
    runner = Runner(tmp_path / 'state', codex_reader=lambda: 0,
                    claude_reader=lambda: {'at': 1, 'rate_limits': {'five_hour': {'used_percentage': 0, 'resets_at': 2}}})
    runner.jobs = {}
    from datetime import datetime, timezone
    runner.instant = datetime.fromtimestamp(1, timezone.utc)
    assert runner.choose(item) == ('claude', 'synthetic')
    assert runner.execution(item)['effort'] == 'high'
    assert main(['edit', item['id'], '--model', 'synthetic-a', '--effort', 'low']) == 0
    pg_store.role_set('light', 'claude', 'synthetic-b', 'max')
    assert pg_store.slice_executor(pg_store.load()['slices'][0]) == dict(tool='claude', model='synthetic-a', effort='low')
    assert main(['state', item['id'], 'ready']) == 1  # brief gate unchanged


@pytest.mark.parametrize('name,value', [('executors', 0), ('executors', 5), ('executors', True), ('repository_runs', 2), ('repository_runs', 0), ('waiting_limit', 0), ('chat_auto_turns', 1.5), ('unknown', 1)])
def test_invalid_limits_are_atomic(pg_store, name, value):
    before = pg_store.limit_show()
    with pytest.raises(state.StateError):
        pg_store.limit_set(name, value)
    assert pg_store.limit_show() == before


def test_runner_reads_limits_again_and_counts_missing_sessions(pg_store, slice_data, tmp_path):
    runner = Runner(tmp_path / 'state')
    runner.jobs = {}
    active = copy.deepcopy(slice_data)
    active['state'] = 'issued'
    active['repo'] = 'owner/busy'
    runner.data = dict(slices=[active])
    candidate = {**slice_data, 'id': 'new/W2', 'repo': 'owner/idle'}
    assert runner.room(candidate) is None
    pg_store.limit_set('executors', 1)
    assert 'executor limit' in runner.room(candidate)
    pg_store.limit_set('executors', 4)
    assert runner.room(candidate) is None
    candidate['repo'] = 'OWNER/BUSY'
    assert 'repository busy' in runner.room(candidate)


def test_api_queues_root_refresh_and_guards_all_writes(pg_store, programs):
    client = create_app(pg_store).test_client()
    for path, payload in [('/models/update', dict(tool='codex')),
                          ('/roles', dict(role='strong', tool='codex', model='gpt-6.1-sol', effort='ultra')),
                          ('/limits', dict(name='executors', value=4))]:
        assert client.post('/api/settings' + path, json=payload).status_code == 403
    assert client.post('/api/settings/models/update', json=dict(tool='shell'), headers=HEADERS).status_code == 400
    response = client.post('/api/settings/models/update', json=dict(tool='codex'), headers=HEADERS)
    assert response.status_code == 202 and response.json['status'] == 'queued'
    assert client.post('/api/settings/models/update', json=dict(tool='codex'), headers=HEADERS).json == response.json
    assert programs == []
    assert pg_store.models_process_one()
    assert not pg_store.models_process_one()
    assert client.get('/api/settings/models').json['updates'][0]['status'] == 'completed'
    assert len(programs) == 1
    assert client.post('/api/settings/roles', json=dict(role='strong', tool='codex', model='gpt-6.1-sol', effort='ultra'), headers=HEADERS).status_code == 200
    assert client.post('/api/settings/roles', json=dict(role='strong', tool='codex', model='gpt-6.1-sol', effort='high'), headers=HEADERS).status_code == 400
    assert client.post('/api/settings/limits', json=dict(name='executors', value=4), headers=HEADERS).status_code == 200
    limits = client.get('/api/settings/limits').json
    assert len(limits) == 5 and all(r['description'] for r in limits)
    sid = pg_store.chats(kind='orchestrator')[0]['id']
    assert client.patch(f'/api/chats/{sid}', json=dict(model='gpt-6.1-sol', effort='ultra'), headers=HEADERS).status_code == 200
    assert client.patch(f'/api/chats/{sid}', json=dict(effort='high'), headers=HEADERS).status_code == 400
    assert len(programs) == 1
    assert not any('settings' in t['name'] or t['name'] in ('roles', 'models', 'limits') for t in TOOLS)


def test_interrupted_update_is_failed_without_replacing_list(pg_store):
    request = pg_store.models_request('claude')
    with pg_store.mutation():
        pg_store.connection.execute("UPDATE cplane_model_updates SET status = 'running' WHERE id = %s", (request['id'],))
    pg_store.models_recover()
    assert pg_store.models_status()['updates'][0]['reason'] == models.FAILURE


@pytest.mark.parametrize('role,tool,model,effort', [
    ('invalid', 'codex', 'synthetic', 'medium'),
    ('strong', 'shell', 'synthetic', 'medium'),
    ('strong', 'codex', 'missing', 'medium'),
    ('strong', 'claude', 'synthetic', 'ultra'),
    ('strong', 'codex', 'synthetic', 'invalid'),
])
def test_invalid_role_choices_preserve_policy(pg_store, role, tool, model, effort):
    seed_model_choices(pg_store)
    before = pg_store.role_list()
    with pytest.raises(state.StateError):
        pg_store.role_set(role, tool, model, effort)
    assert pg_store.role_list() == before


def test_issued_title_edit_does_not_change_executor_or_level(pg_store, slice_data):
    seed_model_choices(pg_store)
    item = copy.deepcopy(slice_data)
    item['state'] = 'issued'
    pg_store.save(dict(version=1, slices=[item]))
    pg_store.slice_level(item['id'], 'light', {})
    assert main(['edit', item['id'], '--title', 'New title']) == 0
    updated = pg_store.load()['slices'][0]
    assert updated['executor'] == item['executor']
    assert pg_store.slice_policy(item['id']) == dict(level='light', overrides={})
    assert main(['edit', item['id'], '--model', 'synthetic']) == 1
    assert updated['executor'] == item['executor']


def test_invalid_slice_choice_rolls_back_metadata_and_document(pg_store):
    add = ['add', '--id', 'new/W2', '--repo', 'owner/repo', '--feature', 'Synthetic', '--title', 'Task']
    assert main([*add, '--model', 'missing']) == 1
    assert pg_store.load()['slices'] == []
    assert pg_store.slice_policy('new/W2') is None


def test_legacy_session_creation_also_validates_stored_choices(pg_store):
    client = create_app(pg_store).test_client()
    payload = dict(title='Synthetic', tool='codex', model='missing')
    assert client.post('/api/factory/sessions', json=payload, headers=HEADERS).status_code == 400
    seed_model_choices(pg_store)
    payload.update(model='synthetic', effort='high')
    response = client.post('/api/factory/sessions', json=payload, headers=HEADERS)
    assert response.status_code == 201
    assert pg_store.chat_show(response.json['id'])['effort'] == 'high'


def test_model_queue_requests_are_serialized(pg_store):
    with ThreadPoolExecutor(2) as pool:
        requests = list(pool.map(lambda _: PostgresStore(pg_store._url).models_request('codex'), range(2)))
    assert requests[0] == requests[1]


def test_restart_cleans_only_catalog_runs(programs, tmp_path):
    from cplane import fence
    token = 'a' * 32
    folder = fence.WORK_ROOT / ('models-' + token)
    folder.mkdir()
    output = sessions.RUNS / folder.name
    output.mkdir()
    (sessions.RUNS / 'models-unrelated').mkdir()
    models.recover_catalog_runs()
    assert not output.exists() and not folder.exists()
    assert (sessions.RUNS / 'models-unrelated').exists()
    assert programs == []


def test_021_upgrade_preserves_installed_defaults_overrides_and_sessions(pg_store, slice_data):
    # Reconstruct the previous migration boundary in this test-owned schema.
    with pg_store.mutation():
        pg_store.connection.execute(
            "CREATE TABLE cplane_chat_settings AS SELECT role AS kind, tool AS chat_tool, model AS chat_model "
            "FROM cplane_roles WHERE role IN ('orchestrator','project','feature','secretary')")
        pg_store.connection.execute(
            "INSERT INTO cplane_chat_settings SELECT 'legacy', chat_tool, chat_model FROM cplane_chat_settings WHERE kind = 'project'")
        secretary = pg_store.chats(kind='secretary')[0]['id']
        pg_store.connection.execute("UPDATE cplane_sessions SET tool = 'claude', model = 'custom-old', cli_session_id = 'saved-claude' WHERE id = %s", (secretary,))
        pg_store.connection.execute("UPDATE cplane_chat_settings SET chat_model = 'installed-default' WHERE kind = 'project'")
        inherited = pg_store.connection.execute(
            "INSERT INTO cplane_sessions (area,title,tool,model,kind,project) "
            "VALUES ('factory','Inherited','codex','installed-default','project','FAC') RETURNING id").fetchone()[0]
        item = copy.deepcopy(slice_data)
        item['executor'] = dict(tool='codex', model='gpt-6-luna')
        pg_store.save(dict(version=1, slices=[item]))
        pg_store.connection.execute('DROP TABLE cplane_models, cplane_roles, cplane_slice_levels, cplane_model_updates')
        pg_store.connection.execute('ALTER TABLE cplane_sessions DROP COLUMN effort, DROP COLUMN role_overrides')
        pg_store.connection.execute("DELETE FROM cplane_settings WHERE name IN ('executors','repository_runs')")
        pg_store.connection.execute("DELETE FROM cplane_migrations WHERE name = '021_model_settings.sql'")
    pg_store.migrate()
    pg_store.migrate()
    assert pg_store.model_list() == []
    assert pg_store.role_get('project')['model'] == 'installed-default'
    chat = pg_store.chat_show(secretary)
    assert (chat['tool'], chat['model'], chat['effort'], chat['cli_session_id']) == ('claude', 'custom-old', 'low', 'saved-claude')
    assert pg_store.chat_show(inherited)['overrides'] == {}
    assert pg_store.slice_executor(item) == dict(tool='codex', model='gpt-6-luna', effort='low')
    assert pg_store.load()['slices'][0] == item


def test_role_change_during_turn_waits_until_next_claim(pg_store):
    seed_model_choices(pg_store)
    sid = pg_store.chats(kind='orchestrator')[0]['id']
    pg_store.session_messages('homelab', sid, 'First')
    first = pg_store.claim_session_turn()
    pg_store.role_set('orchestrator', 'claude', 'synthetic', 'high')
    running = pg_store.chat_show(sid)
    assert (running['tool'], running['model'], running['effort']) == (
        first['session']['tool'], first['session']['model'], first['session']['effort'])
    assert pg_store.interrupted_session_turns()[0]['session']['tool'] == 'codex'
    pg_store.finish_session_turn(first, 'Reply', 'saved-codex')
    pg_store.session_messages('homelab', sid, 'Second')
    second = pg_store.claim_session_turn()
    assert (second['session']['tool'], second['session']['effort']) == ('claude', 'high')
    assert second['session']['cli_session_id'] is None


def test_configured_fence_command_for_catalog_and_recovery(programs, tmp_path, monkeypatch):
    from cplane import fence
    monkeypatch.setenv('CPLANE_FENCE_COMMAND', 'homelab-fence')
    calls = []

    def run(argv, **kwargs):
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 0, json.dumps(CODEX), '')

    monkeypatch.setattr(models.subprocess, 'run', run)
    assert models.refresh_catalog('codex')
    assert [call[:2] for call in calls] == [
        ['homelab-fence', 'run'], ['homelab-fence', 'session-cleanup']]
    token = 'a' * 32
    (fence.WORK_ROOT / ('models-' + token)).mkdir()
    (sessions.RUNS / ('models-' + token)).mkdir()
    models.recover_catalog_runs()
    assert calls[-1][:2] == ['homelab-fence', 'session-cleanup']


def test_fence_command_defaults_and_rolls_back(monkeypatch):
    from cplane import fence
    monkeypatch.delenv('CPLANE_FENCE_COMMAND', raising=False)
    assert fence.fence_command() == ['factory-cli']
    monkeypatch.setenv('CPLANE_FENCE_COMMAND', 'homelab-fence')
    assert fence.fence_command() == ['homelab-fence']
    monkeypatch.delenv('CPLANE_FENCE_COMMAND')
    assert fence.fence_command() == ['factory-cli']
