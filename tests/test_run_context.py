"""Instruction identities use synthetic workspaces and disposable Postgres schemas."""
from datetime import datetime, timezone
import hashlib
from importlib.resources import files
import json
import os
import subprocess
from unittest.mock import Mock
import uuid

import pytest

from cplane import prompts, run_records, sessions, skills
from cplane.cli import main
from test_runner import setup
from test_stores import pg_store


def entry(kind, name, content):
    return dict(kind=kind, name=name, sha256=hashlib.sha256(content).hexdigest())


@pytest.mark.parametrize('populated', [False, True])
def test_context_migration_empty_and_existing_records(pg_store, populated):
    import psycopg
    from psycopg import sql
    from psycopg.types.json import Jsonb
    name = 'context_' + uuid.uuid4().hex
    # Start with all migrations through 026, without removing any columns.
    with psycopg.connect(pg_store._url, autocommit=True) as connection:
        connection.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(name)))
        try:
            connection.execute(sql.SQL('SET search_path TO {}').format(sql.Identifier(name)))
            for migration in sorted(files('cplane').joinpath('migrations').iterdir(), key=lambda p: p.name):
                if migration.name.endswith('.sql') and migration.name < '027_run_context.sql':
                    connection.execute(migration.read_text())
            if populated:
                connection.execute("INSERT INTO cplane_run_records (turn_key,kind,tool) VALUES ('old','chat','codex')")
            connection.execute(files('cplane').joinpath('migrations/027_run_context.sql').read_text())
            assert connection.execute('SELECT context FROM cplane_run_records').fetchall() == ([(None,)] if populated else [])
            column = connection.execute(
                "SELECT data_type, is_nullable, column_default FROM information_schema.columns "
                "WHERE table_schema = %s AND table_name = 'cplane_run_records' AND column_name = 'context'", (name,)).fetchone()
            assert column == ('jsonb', 'YES', None)
            connection.execute("INSERT INTO cplane_run_records (turn_key,kind,tool,context) VALUES ('new','slice','claude',%s)", (Jsonb([]),))
            for invalid in ({}, 'text', None):
                with pytest.raises(psycopg.errors.CheckViolation):
                    connection.execute("UPDATE cplane_run_records SET context = %s WHERE turn_key = 'new'", (Jsonb(invalid),))
            assert connection.execute("SELECT context FROM cplane_run_records WHERE turn_key = 'new'").fetchone() == ([],)
            if populated:
                assert connection.execute("SELECT context FROM cplane_run_records WHERE turn_key = 'old'").fetchone() == (None,)
        finally:
            connection.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(name)))


@pytest.mark.parametrize('tool', ['codex', 'claude'])
@pytest.mark.parametrize('kind', ['project', 'secretary'])
@pytest.mark.parametrize('resume', [False, True])
def test_chat_prompt_and_installed_skills_snapshot(pg_store, tmp_path, tool, kind, resume):
    skills.install(tmp_path, ['testing-review', 'brief'])
    installed = tmp_path / '.claude/skills/brief/SKILL.md'
    # The installed bytes, including converted frontmatter, define the identity.
    installed.write_bytes(installed.read_bytes() + b'\nSynthetic installed revision\r\n')
    session = dict(id=2, tool=tool, model='synthetic', effort='medium', kind=kind,
                   area='homelab', cli_session_id='resume-id' if resume else None,
                   skill_names=['testing-review', 'brief'])
    turn = dict(id=7, text='Synthetic message', session=session)
    accounting = {}
    command = sessions.turn_command(turn, tmp_path, [], tmp_path / 'run', accounting=accounting)
    prompt_name = 'secretary' if kind == 'secretary' else 'chat'
    expected = [dict(kind='prompt', name=name, sha256=prompts.sha256(name))
                for name in sorted([prompt_name, 'homelab'])]
    expected += [entry('skill', name, (tmp_path / '.claude/skills' / name / 'SKILL.md').read_bytes())
                 for name in ['brief', 'testing-review']]
    assert prompts.text(prompt_name) in command[-1]
    assert accounting['context'] == expected
    installed.write_bytes(b'changed during execution')
    run_records.chat_record(pg_store, turn, accounting)
    row, = pg_store.run_record_list()
    assert row['context'] == expected
    assert pg_store.run_record_show(row['id'])['context'] == expected


def test_context_missing_skill_and_failed_prompt_are_partial(tmp_path, monkeypatch, capsys):
    skills.install(tmp_path, ['brief'])
    original = prompts.sha256
    def hash_prompt(name):
        if name != 'chat':
            raise OSError('PRIVATE')
        return original(name)
    monkeypatch.setattr(prompts, 'sha256', hash_prompt)
    context = run_records.chat_context(tmp_path, dict(skill_names=['missing', 'brief']), ['homelab', 'chat'])
    assert [(e['kind'], e['name']) for e in context] == [('prompt', 'chat'), ('skill', 'brief')]
    assert capsys.readouterr().err == ('cplane: run context prompt unreadable\n'
                                      'cplane: run context skill unreadable\n')


def test_sort_order_and_legacy_installed_skill_discovery(tmp_path):
    skills.install(tmp_path, ['testing-review', 'brief'])
    context = run_records.chat_context(tmp_path, {}, ['homelab', 'chat'])
    assert [(e['kind'], e['name']) for e in context] == [
        ('prompt', 'chat'), ('prompt', 'homelab'), ('skill', 'brief'), ('skill', 'testing-review')]


@pytest.mark.parametrize('replacement', ['link', 'fifo'])
def test_untrusted_skill_is_skipped(tmp_path, replacement, capsys):
    path = tmp_path / 'SKILL.md'
    if replacement == 'link':
        path.symlink_to(tmp_path / 'private')
    else:
        os.mkfifo(path)
    assert run_records.context(skill_files=[('brief', path)]) == []
    assert capsys.readouterr().err == 'cplane: run context skill unreadable\n'


def test_installed_skill_ancestor_link_is_skipped(tmp_path, capsys):
    skills.install(tmp_path, ['brief'])
    directory = tmp_path / '.claude/skills'
    directory.rename(tmp_path / 'replaced')
    directory.symlink_to(tmp_path / 'replaced', target_is_directory=True)
    assert run_records.chat_context(tmp_path, dict(skill_names=['brief']), []) == []
    assert capsys.readouterr().err == 'cplane: run context skill unreadable\n'


@pytest.mark.parametrize('mode', ['ordinary', 'cut', 'review', 'resume'])
def test_slice_launch_records_only_loaded_files(setup, monkeypatch, mode):
    runner, processes, _ = setup
    runner.run()
    item = runner.data['slices'][0]
    # Test a subsequent launch with the first synthetic process completed.
    runner.jobs[item['id']]['phase'] = 'collected'
    if mode in ('cut', 'resume'):
        item['flow'] = 'tickets'
    if mode in ('review', 'resume'):
        item['session']['id'] = 'resume-id'
        previous = runner.jobs[item['id']]
        previous.update(brief='Synthetic brief', context=[dict(kind='skill', name='cut', sha256='old')])
    if mode == 'review':
        monkeypatch.setattr('cplane.runner.reviewer.prepare', lambda *args: {
            key: previous[key] for key in ('repo', 'branch', 'base', 'repository')})
    assert runner.launch(item, 'Synthetic brief', review=mode == 'review', resume=mode == 'resume')
    job = processes.started[-1]
    if mode in ('ordinary', 'resume'):
        assert job['context'] == []
    else:
        name = 'cut' if mode == 'cut' else 'slice-review'
        assert skills.instructions(name) in job['prompt']
        assert job['context'] == [entry('skill', name, (skills.ROOT / (name + '.md')).read_bytes())]
    store = Mock()
    run_records.slice_record(store, item, job)
    assert store.run_record_add.call_args.kwargs['context'] == job['context']


def test_execute_turn_passes_snapshot_to_record(tmp_path, monkeypatch):
    skills.install(tmp_path, ['brief'])
    turn = dict(id=7, text='Synthetic', session=dict(id=2, tool='codex', model='synthetic',
                effort='medium', cli_session_id=None, area='homelab'))
    monkeypatch.setattr(sessions, 'workspace', lambda _: (tmp_path, []))
    monkeypatch.setattr(sessions, 'trusted_directory', lambda _: None)
    monkeypatch.setattr(sessions, 'RUNS', tmp_path)
    def execute(*args, **kwargs):
        (tmp_path / '.claude/skills/brief/SKILL.md').unlink()
        return subprocess.CompletedProcess(args, 124, '', '')
    expected = run_records.chat_context(tmp_path, turn['session'], ['homelab'])
    monkeypatch.setattr(sessions.subprocess, 'run', execute)
    store = Mock()
    sessions.execute_turn(turn, store)
    assert store.run_record_add.call_args.kwargs['context'] == expected
    # Service recovery uses the saved identity after the workspace has changed.
    recovered = run_records.saved_context(tmp_path / 'session-turn-7')
    assert recovered == expected
    run_records.chat_record(store, turn, dict(outcome='interrupted', context=recovered))
    assert store.run_record_add.call_args.kwargs['context'] == expected


def test_context_snapshot_failures_are_harmless(tmp_path, capsys):
    run_records.save_context(tmp_path / 'missing', [])
    assert run_records.saved_context(tmp_path / 'missing') == []
    assert capsys.readouterr().err == ('cplane: run context snapshot failed\n'
                                      'cplane: run context snapshot unreadable\n')


def test_context_in_existing_reads(pg_store, capsys):
    context = [dict(kind='prompt', name='chat', sha256=prompts.sha256('chat'))]
    pg_store.run_record_add('context', kind='slice', tool='codex', slice_id='factory/context',
                            started_at=datetime.now(timezone.utc), context=context)
    row, = pg_store.run_record_list()
    assert row['context'] == context
    for args in (['run', 'list', '--json'], ['run', 'show', str(row['id'])]):
        assert main(args) == 0
        result = json.loads(capsys.readouterr().out)
        assert (result[0] if isinstance(result, list) else result)['context'] == context
    assert pg_store.run_record_export(datetime(2000, 1, 1, tzinfo=timezone.utc))[0]['context'] == context
