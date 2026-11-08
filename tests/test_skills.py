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
    assert set(session['skill_names']) == {'grilling', 'slice-review', 'brief', 'testing-review', 'extra'}
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


@pytest.mark.parametrize('tool', ['codex', 'claude'])
def test_private_service_umask_installs_readable_instructions(tmp_path, tool):
    import os
    import stat
    from cplane.sessions import turn_command

    folder = tmp_path / 'workspace'
    folder.mkdir(mode=0o700)
    # Unrelated workspace data must retain the service's private permissions.
    previous = os.umask(0o077)
    try:
        (folder / 'private').write_text('private')
        skills.install(folder, sorted(skills.DEFAULTS))
    finally:
        os.umask(previous)
    assert stat.S_IMODE((folder / 'private').stat().st_mode) == 0o600
    assert stat.S_IMODE(folder.stat().st_mode) == 0o700
    paths = [folder / 'AGENTS.md', *folder.glob('.claude/skills/*/SKILL.md')]
    for path in paths:
        # Installation retains its trusted creator's ownership (root in service),
        # rather than recursively transferring or opening the rest of the tree.
        assert path.stat().st_uid == os.geteuid()
        assert path.stat().st_gid == os.getegid()
        assert stat.S_IMODE(path.stat().st_mode) == 0o644
    for path in [folder / '.claude', folder / '.claude/skills', *(p.parent for p in paths[1:])]:
        assert stat.S_IMODE(path.stat().st_mode) == 0o755
    if os.geteuid() == 0:
        # Match the actual service-to-container boundary on root-capable hosts.
        os.chown(folder, 21000, 21000)
        for ancestor in (tmp_path, tmp_path.parent, tmp_path.parent.parent):
            ancestor.chmod(0o755)
        process = dict(user=21000, group=21000, extra_groups=[])
    else:
        process = {}
    script = 'from pathlib import Path; import sys; [Path(p).read_text() for p in sys.argv[1:]]'
    result = subprocess.run(['python3', '-c', script, *map(str, paths)], capture_output=True, **process)
    assert result.returncode == 0, result.stderr
    turn = dict(id=1, text='Read skills', session=dict(tool=tool, model='synthetic', cli_session_id=None))
    command = turn_command(turn, folder, [], tmp_path / 'run')
    assert command[command.index('--repo') + 1] == str(folder)
    assert '--read-only-path' not in command


def test_resumed_skill_modes_repaired_without_refresh_or_extra_access(tmp_path, monkeypatch):
    import os
    import stat
    folder = tmp_path / 'workspace'
    folder.mkdir()
    skills.install(folder, ['brief', 'testing-review'])
    paths = [folder / 'AGENTS.md', *folder.glob('.claude/skills/*/SKILL.md')]
    original = {p: p.read_bytes() for p in paths}
    for path in paths:
        path.chmod(0o600)
    directories = [folder / '.claude', folder / '.claude/skills', *(p.parent for p in paths[1:])]
    for path in directories:
        path.chmod(0o700)
    private = folder / 'private'
    private.write_text('Private workspace data')
    private.chmod(0o600)
    # Model the root service's ownership on non-root CI/test hosts.
    original_fstat = os.fstat
    def root_owned(fd):
        values = list(original_fstat(fd))
        values[4:6] = [0, 0]
        return os.stat_result(values)
    monkeypatch.setattr(skills.os, 'fstat', root_owned)
    skills.ensure_readable(folder, ['brief', 'testing-review'])
    assert all(p.read_bytes() == original[p] and stat.S_IMODE(p.stat().st_mode) == 0o644 for p in paths)
    assert all(stat.S_IMODE(p.stat().st_mode) == 0o755 for p in directories)
    assert stat.S_IMODE(private.stat().st_mode) == 0o600
    skills.ensure_readable(folder, ['brief', 'testing-review'])  # Repeat is harmless.


@pytest.mark.parametrize('replacement', ['symlink', 'hardlink', 'agent-owned', 'writable'])
def test_resume_skill_repair_refuses_replacements_before_chmod(tmp_path, monkeypatch, replacement):
    import os
    folder = tmp_path / 'workspace'
    folder.mkdir()
    skills.install(folder, ['brief'])
    agents = folder / 'AGENTS.md'
    agents.chmod(0o600)
    target = folder / '.claude/skills/brief/SKILL.md'
    outside = tmp_path / 'outside'
    outside.write_text('Never open access to this file')
    outside.chmod(0o600)
    original_fstat = os.fstat
    def synthetic_owner(fd):
        info = original_fstat(fd)
        values = list(info)
        values[4:6] = [21000 if replacement == 'agent-owned' and info.st_ino == target.stat().st_ino else 0, 0]
        return os.stat_result(values)
    monkeypatch.setattr(skills.os, 'fstat', synthetic_owner)
    if replacement in ('symlink', 'hardlink'):
        target.unlink()
        if replacement == 'symlink':
            target.symlink_to(outside)
        else:
            os.link(outside, target)
    elif replacement == 'writable':
        target.chmod(0o666)
    with pytest.raises((OSError, state.StateError)):
        skills.ensure_readable(folder, ['brief'])
    assert agents.stat().st_mode & 0o777 == 0o600
    assert outside.stat().st_mode & 0o777 == 0o600


def test_resume_with_no_enabled_skills_or_legacy_snapshot(tmp_path, monkeypatch):
    import os
    folder = tmp_path / 'workspace'
    folder.mkdir()
    skills.ensure_readable(folder, None)
    skills.install(folder, [])
    assert not (folder / '.claude').exists()
    original_fstat = os.fstat
    def root_owned(fd):
        values = list(original_fstat(fd))
        values[4:6] = [0, 0]
        return os.stat_result(values)
    monkeypatch.setattr(skills.os, 'fstat', root_owned)
    skills.ensure_readable(folder, [])
    assert not (folder / '.claude').exists()
