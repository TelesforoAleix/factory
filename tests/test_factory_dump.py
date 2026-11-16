import importlib.machinery
import importlib.util
import os
from pathlib import Path

import pytest


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


def test_default_uses_newest_existing_platform_backup(tmp_path, monkeypatch, capsys):
    module = load('factory-restore-check')
    assert module.DIRECTORY == Path('/srv/homelab/homelab-v2-data/originals/postgres')
    backups = tmp_path / 'backups'
    backups.mkdir()
    (backups / 'factory-2026-11-15.dump').write_bytes(b'older backup')
    newest = backups / 'factory-2026-11-16.dump'
    newest.write_bytes(b'newest backup')
    # Selection uses the date in the filename, not file modification time.
    os.utime(newest, (1, 1))
    (backups / 'other-2026-11-17.dump').write_bytes(b'other database')
    (backups / 'factory-2026-11-18.dump.partial').write_bytes(b'partial')
    (backups / 'factory-latest.dump').write_bytes(b'not dated')
    (backups / 'factory-2026-11-19.dump').mkdir()
    before = sorted(p.name for p in backups.iterdir())
    restored = tmp_path / 'restored'
    monkeypatch.setenv('RESTORED', str(restored))
    monkeypatch.setattr(module, 'DIRECTORY', backups)
    monkeypatch.setattr(module.sys, 'argv', ['factory-restore-check'])
    fake_docker(tmp_path, monkeypatch, '''case "$*" in
  *pg_restore*) cat > "$RESTORED" ;;
esac
''')
    assert module.main() == 0
    assert restored.read_bytes() == b'newest backup'
    assert sorted(p.name for p in backups.iterdir()) == before
    assert capsys.readouterr().out == 'restore check passed\n'


@pytest.mark.parametrize('directory_exists', [False, True])
def test_no_platform_backup_refuses_without_docker(tmp_path, monkeypatch, capsys, directory_exists):
    module = load('factory-restore-check')
    backups = tmp_path / 'backups'
    if directory_exists:
        backups.mkdir()
        (backups / 'other-2026-11-16.dump').write_bytes(b'other database')
    monkeypatch.setattr(module, 'DIRECTORY', backups)
    monkeypatch.setattr(module.sys, 'argv', ['factory-restore-check'])
    calls = tmp_path / 'calls'
    monkeypatch.setenv('CALLS', str(calls))
    fake_docker(tmp_path, monkeypatch, 'echo called >> "$CALLS"\n')
    assert module.main() == 1
    output = capsys.readouterr().out
    assert 'no Factory backup matching factory-YYYY-MM-DD.dump' in output
    assert str(backups) in output
    assert not calls.exists()
