import importlib.machinery
import importlib.util
import os
from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[1]


def load(name):
    path = ROOT / 'node' / 'bin' / name
    loader = importlib.machinery.SourceFileLoader(name, str(path))
    spec = importlib.util.spec_from_loader(name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def fake_docker(tmp_path, monkeypatch, script):
    docker = tmp_path / 'docker'
    docker.write_text('#!/bin/sh\n' + script)
    docker.chmod(0o755)
    monkeypatch.setenv('PATH', str(tmp_path) + os.pathsep + os.environ['PATH'])


def test_failed_dump_removes_partial_file(tmp_path, monkeypatch):
    module = load('factory-dump')
    monkeypatch.setattr(module, 'DIRECTORY', tmp_path)
    fake_docker(tmp_path, monkeypatch, "printf partial\nexit 1\n")
    assert module.main() == 1
    assert not list(tmp_path.glob('*.dump'))
    assert not list(tmp_path.glob('.factory-dump-*'))


def test_missing_directory_is_not_created(tmp_path, monkeypatch, capsys):
    module = load('factory-dump')
    missing = tmp_path / 'missing' / 'db'
    monkeypatch.setattr(module, 'DIRECTORY', missing)
    assert module.main() == 1
    assert not missing.parent.exists()
    assert len(capsys.readouterr().err.splitlines()) == 1


def test_retention_and_permissions(tmp_path, monkeypatch):
    module = load('factory-dump')
    monkeypatch.setattr(module, 'DIRECTORY', tmp_path)
    fake_docker(tmp_path, monkeypatch, 'printf backup\n')
    for day in range(1, 10):
        (tmp_path / f'factory-2000-01-{day:02}.dump').write_text('old')
    assert module.main() == 0
    dumps = sorted(tmp_path.glob('*.dump'))
    assert len(dumps) == 7
    assert dumps[-1].read_bytes() == b'backup'
    assert dumps[-1].stat().st_mode & 0o777 == 0o640
    assert not (tmp_path / 'factory-2000-01-03.dump').exists()


def test_restore_mismatch_fails_and_removes_container(tmp_path, monkeypatch, capsys):
    module = load('factory-restore-check')
    dump = tmp_path / 'backup.dump'
    dump.write_bytes(b'backup')
    calls = tmp_path / 'calls'
    monkeypatch.setenv('CALLS', str(calls))
    fake_docker(tmp_path, monkeypatch, '''printf '%s\\n' "$*" >> "$CALLS"
case "$*" in
  *pg_isready*) exit 0 ;;
  *pg_restore*) cat >/dev/null ;;
  *pg_class*) printf 'public\\twidgets\\n' ;;
  *'SELECT count(*)'*)
    case "$*" in *homelab-postgres-1*) echo 2 ;; *) echo 1 ;; esac ;;
esac
''')
    monkeypatch.setattr(module.sys, 'argv', ['factory-restore-check', str(dump)])
    assert module.main() == 1
    output = capsys.readouterr().out
    assert 'public.widgets: live=2 restored=1' in output
    assert output.splitlines()[-1] == 'restore check failed'
    assert any(line.startswith('rm -f factory-restore-check-') for line in calls.read_text().splitlines())
