"""Startup settings are exercised in fresh interpreters like service processes."""
import os
import subprocess
import sys
import textwrap



SETTINGS = ('FACTORY_UI_HOST', 'CPLANE_INTAKE_GID', 'CPLANE_SESSIONS_LOCK',
            'CPLANE_SESSION_RUNS', 'CPLANE_UI_DOCS')


def process(code, **settings):
    env = {key: value for key, value in os.environ.items() if key not in SETTINGS}
    env.update(settings)
    return subprocess.run([sys.executable, '-c', textwrap.dedent(code)], env=env,
                          capture_output=True, text=True, check=True)


def test_ui_host():
    code = '''
        from unittest.mock import patch
        from factory_ui import serve
        with patch.object(serve, 'create_app'), patch.object(serve, 'serve') as run:
            serve.main()
            assert run.call_args.kwargs['host'] == EXPECTED
            assert run.call_args.kwargs['port'] == 8300
    '''
    process('EXPECTED = "127.0.0.1"\n' + textwrap.dedent(code))
    process('EXPECTED = "0.0.0.0"\n' + textwrap.dedent(code), FACTORY_UI_HOST='0.0.0.0')


def test_intake_gid():
    code = '''
        from unittest.mock import patch, MagicMock
        from cplane import intake
        server = MagicMock()
        with patch.object(intake.grp, 'getgrnam') as lookup, \\
             patch.object(intake.Path, 'unlink'), \\
             patch.object(intake, 'IntakeServer', return_value=server) as create:
            lookup.return_value.gr_gid = 321
            intake.main()
            assert create.call_args.args[2] == EXPECTED
            assert lookup.call_count == LOOKUPS
    '''
    process('EXPECTED = 321\nLOOKUPS = 1\n' + textwrap.dedent(code))
    process('EXPECTED = 1234\nLOOKUPS = 0\n' + textwrap.dedent(code), CPLANE_INTAKE_GID='1234')
    for value in ('0', '-1', 'abc', ''):
        env = {**os.environ, 'CPLANE_INTAKE_GID': value}
        result = subprocess.run([sys.executable, '-c', 'import cplane.intake'], env=env,
                                capture_output=True, text=True)
        assert result.returncode != 0
        assert 'must be a positive integer' in result.stderr


def test_sessions_lock(tmp_path):
    code = '''
        from unittest.mock import patch
        from cplane import sessions
        assert str(sessions.LOCK) == EXPECTED
        with patch.object(sessions, 'database_url'), patch('builtins.open', side_effect=RuntimeError) as opened:
            try:
                sessions.main()
            except RuntimeError:
                pass
            else:
                assert False
            assert str(opened.call_args.args[0]) == EXPECTED
    '''
    process('EXPECTED = "/run/factory-sessions.lock"\n' + textwrap.dedent(code))
    path = str(tmp_path / 'sessions.lock')
    process(f'EXPECTED = {path!r}\n' + textwrap.dedent(code), CPLANE_SESSIONS_LOCK=path)


def test_session_runs(tmp_path):
    code = '''
        import json
        from pathlib import Path
        from unittest.mock import Mock, patch
        from cplane import sessions, models, fence
        assert str(sessions.RUNS) == EXPECTED
        if CHECK_RUNS:
            root = sessions.RUNS
            root.mkdir()
            work = root.parent / 'work'
            work.mkdir()
            turn = {'id': 7, 'session': {'tool': 'codex'}}
            store = Mock()
            with patch.object(sessions, 'workspace', return_value=(work, [])), \\
                 patch.object(sessions, 'trusted_directory'), \\
                 patch.object(sessions, 'turn_command', return_value=[]), \\
                 patch.object(sessions.subprocess, 'run', return_value=Mock(returncode=1, stdout='')):
                sessions._execute_turn(turn, store, {})
            assert (root / 'session-turn-7').is_dir()
            seen = []
            def run(argv, **kwargs):
                output = Path(argv[argv.index('--run') + 1])
                assert output.is_dir()
                seen.append(output)
                return Mock(returncode=0, stdout=json.dumps({'models': [{'visibility': 'list', 'slug': 'test', 'supported_reasoning_levels': [{'effort': 'low'}]}]}))
            with patch.object(fence, 'WORK_ROOT', work), patch.object(fence, 'trusted_directory'), \\
                 patch.object(fence, 'own'), patch.object(fence, 'remove'), \\
                 patch.object(fence, 'socket_enabled', return_value=False), \\
                 patch.object(models, 'cleanup_runs'), patch.object(models.subprocess, 'run', side_effect=run):
                models.refresh_catalog('codex')
            assert len(seen) == 1 and seen[0].parent.parent == root
    '''
    process('EXPECTED = "/srv/factory/runs"\nCHECK_RUNS = False\n' + textwrap.dedent(code))
    path = str(tmp_path / 'sessions')
    process(f'EXPECTED = {path!r}\nCHECK_RUNS = True\n' + textwrap.dedent(code), CPLANE_SESSION_RUNS=path)


def test_ui_docs(tmp_path):
    code = '''
        from pathlib import Path
        from unittest.mock import Mock, patch
        from factory_ui import create_app
        from factory_ui.documents import Documents
        from cplane import sessions
        root = Path(EXPECTED)
        assert create_app(Mock()).config['DOCUMENT_ROOT'] == root == sessions.UI_DOCS
        assert sessions.DocumentExporter().destination == root
        if CHECK_EXPORT:
            def export(clone, tree, head, **kwargs):
                tree.mkdir()
                (tree / 'test.md').write_text('# Test')
            with patch.object(sessions, 'trusted_directory'), \\
                 patch.object(sessions.subprocess, 'run', return_value=Mock(stdout='head')), \\
                 patch.object(sessions, 'export_tree', side_effect=export):
                sessions.DocumentExporter().refresh()
            assert (root.parent / '.ui-docs.lock').is_file()
            assert Documents(root).read('test.md')['title'] == 'Test'
    '''
    process('EXPECTED = "/var/lib/factory/ui-docs"\nCHECK_EXPORT = False\n' + textwrap.dedent(code))
    path = str(tmp_path / 'documents')
    process(f'EXPECTED = {path!r}\nCHECK_EXPORT = True\n' + textwrap.dedent(code), CPLANE_UI_DOCS=path)
