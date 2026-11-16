import importlib.machinery
import importlib.util
import os
from pathlib import Path


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
