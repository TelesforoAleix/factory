"""Skill catalog, locked switches and workspace snapshots on synthetic data."""
import json
from pathlib import Path
import subprocess
from unittest.mock import Mock

import pytest

from cplane import cli, cut, run_records, skills, state
from factory_ui import create_app
from test_stores import pg_store


@pytest.fixture
def extra_skill(tmp_path, monkeypatch):
    root = tmp_path / 'skills'
    root.mkdir()
    for path in skills.ROOT.glob('*.md'):
        (root / path.name).write_text(path.read_text())
    (root / 'extra.md').write_text(
        '--- {"name": "extra", "description": "Synthetic optional skill."}\nExtra instructions.\n')
    monkeypatch.setattr(skills, 'ROOT', root)
    return root


def test_catalog_and_workspace_only_enabled(extra_skill, tmp_path):
    assert {s['name'] for s in skills.catalog()} == {*skills.DEFAULTS, 'extra'}
    folder = tmp_path / 'workspace'
    folder.mkdir()
    skills.install(folder, ['grilling', 'extra'])
    assert sorted(p.parent.name for p in folder.glob('.claude/skills/*/SKILL.md')) == ['extra', 'grilling']
    agent = (folder / 'AGENTS.md').read_text()
    assert '.claude/skills/grilling/SKILL.md' in agent
    assert '.claude/skills/cut/' not in agent
    text = (folder / '.claude/skills/extra/SKILL.md').read_text()
    assert text.startswith('---\nname: extra\ndescription: "Synthetic optional skill."\n---\n')
    assert text.endswith('Extra instructions.\n')
    with pytest.raises(state.StateError, match='Unknown skill'):
        skills.install(folder, ['../escape'])


def test_invalid_metadata_refused(extra_skill):
    (extra_skill / 'extra.md').write_text('--- {"name": "wrong", "description": "bad"}\n')
    with pytest.raises(state.StateError, match='frontmatter'):
        skills.catalog()


def test_version_is_repository_head_not_last_skill_commit(tmp_path):
    (tmp_path / 'skills').mkdir()
    (tmp_path / 'skills/a.md').write_text('fixture')
    def git(*args):
        return subprocess.check_output(['git', '-C', str(tmp_path), *args], text=True).strip()
    git('init', '-q')
    git('config', 'user.name', 'Test')
    git('config', 'user.email', 'test@example.test')
    git('add', '.')
    git('commit', '-qm', 'skills')
    first = cut.skills_version(tmp_path)
    git('commit', '--allow-empty', '-qm', 'code')
    assert cut.skills_version(tmp_path) == git('rev-parse', 'HEAD') != first


def test_switches_defaults_validation_and_api(pg_store, extra_skill, capsys):
    before = pg_store.skill_list()
    assert all(s['projects'] for s in before if s['name'] in skills.DEFAULTS)
    assert next(s for s in before if s['name'] == 'extra')['projects'] == []
    assert cli.main(['skill', 'on', 'extra', 'FAC']) == 0
    capsys.readouterr()
    assert {s['name'] for s in pg_store.skill_list('FAC')} == {*skills.DEFAULTS, 'extra'}
    assert cli.main(['skill', 'off', 'grilling', 'FAC']) == 0
    capsys.readouterr()
    assert 'grilling' not in {s['name'] for s in pg_store.skill_list('FAC')}
    assert 'grilling' in {s['name'] for s in pg_store.skill_list('LAB')}
    assert cli.main(['skill', 'list', '--project', 'FAC']) == 0
    assert 'extra' in {s['name'] for s in json.loads(capsys.readouterr().out)}
    snapshot = pg_store.skill_list()
    for name, project in [('missing', 'FAC'), ('extra', 'BAD'), ('../extra', 'FAC')]:
        with pytest.raises(state.StateError):
            pg_store.skill_set(name, project, True)
    assert pg_store.skill_list() == snapshot
    client = create_app(pg_store).test_client()
    response = client.get('/api/skills')
    assert response.status_code == 200
    assert response.json == snapshot
    assert set(response.json[0]) == {'name', 'description', 'version', 'projects'}
    assert client.post('/api/skills', json={}).status_code == 403
    pg_store.migrate()
    assert pg_store.skill_list() == snapshot


def test_session_project_resolution_and_snapshot(pg_store, extra_skill):
    pg_store.skill_set('extra', 'FAC', True)
    pg_store.skill_set('cut', 'FAC', False)
    sid = pg_store.create_session('factory', 'Synthetic', 'codex', 'model', ['owner/factory'])
    pg_store.session_messages('factory', sid, 'hello')
    turn = pg_store.claim_session_turn()
    session = turn['session']
    assert set(session['skill_names']) == {'grilling', 'slice-review', 'extra'}
    assert session['skill_version'] == cut.skills_version()
    pg_store.finish_session_turn(turn, 'reply', 'resume-id')
    pg_store.skill_set('extra', 'FAC', False)
    pg_store.session_messages('factory', sid, 'again')
    resumed = pg_store.claim_session_turn()
    assert resumed['session']['skill_names'] == session['skill_names']
    assert resumed['session']['skill_version'] == session['skill_version']
    assert pg_store.session_skills([])[0] == sorted(skills.DEFAULTS)
    assert pg_store.session_skills(['owner/unknown'])[0] == sorted(skills.DEFAULTS)
    assert pg_store.session_skills(['owner/factory', 'owner/homelab-v2'])[0] == sorted(skills.DEFAULTS)
    with pg_store.mutation():
        pg_store.connection.execute("UPDATE cplane_projects SET repository = 'factory' WHERE key = 'LAB'")
    assert pg_store.session_skills(['owner/factory'])[0] == sorted(skills.DEFAULTS)


def test_chat_records_snapshot_version():
    store = Mock()
    turn = dict(id=2, text='hello', session=dict(id=1, tool='claude',
                repositories=[], skill_version='saved-revision'))
    run_records.chat_record(store, turn, {'outcome': 'interrupted'})
    assert store.run_record_add.call_args.kwargs['skill_version'] == 'saved-revision'


def test_skill_commands_need_postgres(monkeypatch, capsys):
    monkeypatch.delenv('CPLANE_DATABASE_URL', raising=False)
    assert cli.main(['skill', 'list']) == 1
    assert 'require Postgres' in capsys.readouterr().err
