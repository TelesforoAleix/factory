"""Injected clocks and waits: loop tests never sleep or start an executor."""
from datetime import datetime, timedelta
import json
from pathlib import Path
import signal
from unittest.mock import Mock

import pytest

from cplane import runner, state
from cplane.cli import main
from test_stores import pg_store


def stop(sig=signal.SIGTERM):
    signal.raise_signal(sig)


@pytest.mark.parametrize('sig', [signal.SIGTERM, signal.SIGINT])
@pytest.mark.parametrize('in_pass', [False, True])
def test_two_passes_and_signal_stop(sig, in_pass):
    previous = {s: signal.getsignal(s) for s in (signal.SIGTERM, signal.SIGINT)}
    calls = []
    waits = []
    def run():
        calls.append('pass')
        if in_pass and len(calls) == 2:
            stop(sig)
    def wait(seconds):
        waits.append(seconds)
        if len(calls) == 2:
            stop(sig)
    runner.run_loop(None, 60, pass_once=run, wait=wait,
                    clock=lambda: datetime(2026, 11, 12, 2), daily=Mock(), hourly=Mock())
    assert calls == ['pass', 'pass']
    assert waits == ([60] if in_pass else [60, 60])
    assert {s: signal.getsignal(s) for s in previous} == previous


def test_raising_pass_does_not_end_loop(capsys):
    run = Mock(side_effect=[RuntimeError('private diagnostic'), None])
    def wait(seconds):
        if run.call_count == 2:
            stop()
    runner.run_loop(None, 1, pass_once=run, wait=wait,
                    clock=lambda: datetime(2026, 11, 12, 2), daily=Mock(), hourly=Mock())
    assert run.call_count == 2
    assert capsys.readouterr().err == 'cplane: run failed\n'


@pytest.mark.parametrize('fail', [False, True])
def test_exports_due_once_with_retry_at_next_due_time(fail, capsys):
    instants = [datetime(2026, 11, 12, 3, 44), datetime(2026, 11, 12, 3, 45),
                datetime(2026, 11, 12, 3, 46), datetime(2026, 11, 12, 4),
                datetime(2026, 11, 13, 3, 44), datetime(2026, 11, 13, 3, 45)]
    ticks = iter(instants)
    daily = Mock(side_effect=RuntimeError('private') if fail else None)
    hourly = Mock(side_effect=RuntimeError('private') if fail else None)
    passes = Mock()
    def wait(seconds):
        if passes.call_count == len(instants):
            stop()
    runner.run_loop('synthetic', 1, pass_once=passes, wait=wait,
                    clock=lambda: next(ticks), daily=daily, hourly=hourly)
    assert [c.args for c in daily.call_args_list] == [
        ('synthetic', instants[1].date()), ('synthetic', instants[-1].date())]
    assert hourly.call_count == 3
    captured = capsys.readouterr()
    assert captured.out == ''
    assert captured.err == (('Factory feature export failed\n'
                             'cplane: daily export failed\n'
                             'Factory feature export failed\n'
                             'Factory feature export failed\n'
                             'cplane: daily export failed\n') if fail else '')


@pytest.mark.parametrize('interval', [0, -1, float('nan'), float('inf')])
def test_invalid_interval(interval):
    with pytest.raises(state.StateError, match='positive finite'):
        runner.run_loop(None, interval)


def test_cli_single_pass_and_every(make_state, monkeypatch):
    run = Mock()
    loop = Mock()
    monkeypatch.setattr(runner, 'Runner', run)
    monkeypatch.setattr(runner, 'run_loop', loop)
    path = make_state()
    assert main(['--state', str(path), '--actor', 'runner', 'run']) == 0
    run.return_value.run.assert_called_once_with()
    loop.assert_not_called()
    assert main(['--state', str(path), '--actor', 'runner', 'run', '--every', '60']) == 0
    loop.assert_called_once_with(path, 60)


def test_daily_export_rotation_modes_and_names(make_state, tmp_path, monkeypatch):
    path = make_state()
    outbox = Path(str(path) + '.outbox.jsonl')
    outbox.write_text(json.dumps(dict(text='Synthetic notice')) + '\n')
    folder = tmp_path / 'exports'
    folder.mkdir()
    monkeypatch.setenv('CPLANE_EXPORT_DIR', str(folder))
    day = datetime(2026, 11, 12).date()
    for days in range(1, 11):
        old = folder / f'factory-{day - timedelta(days=days)}.json'
        old.write_text('old')
        Path(str(old) + '.outbox.jsonl').write_text('old notices')
    unrelated = folder / 'factory-other.json'
    unrelated.write_text('keep')
    runner.daily_export(path, day)
    states = sorted(p for p in folder.glob('factory-*.json') if p != unrelated)
    assert len(states) == 7
    assert states[0].name == f'factory-{day - timedelta(days=6)}.json'
    assert len(list(folder.glob('*.outbox.jsonl'))) == 7
    destination = folder / f'factory-{day}.json'
    assert json.loads(destination.read_text()) == state.load(path)
    assert Path(str(destination) + '.outbox.jsonl').read_bytes() == outbox.read_bytes()
    for p in (destination, Path(str(destination) + '.outbox.jsonl')):
        assert p.stat().st_mode & 0o777 == 0o600
    assert unrelated.read_text() == 'keep'
    assert not list(folder.glob('.factory-export.*'))


def test_daily_export_failure_keeps_existing_files(make_state, tmp_path, monkeypatch):
    folder = tmp_path / 'exports'
    folder.mkdir()
    existing = folder / 'factory-2026-11-12.json'
    existing.write_text('old')
    monkeypatch.setenv('CPLANE_EXPORT_DIR', str(folder))
    path = make_state()
    monkeypatch.setattr(runner.json, 'dumps', Mock(side_effect=RuntimeError('private')))
    with pytest.raises(RuntimeError):
        runner.daily_export(path, datetime(2026, 11, 12).date())
    assert {p.name: p.read_text() for p in folder.iterdir()} == {existing.name: 'old'}


def test_hourly_export_suppresses_output(monkeypatch, capsys):
    from cplane import feature_export
    backend = Mock()
    monkeypatch.setattr(state, 'store', Mock(return_value=backend))
    def export(data):
        print('private')
        print('private', file=runner.sys.stderr)
        assert data is backend.feature_export_snapshot.return_value
    monkeypatch.setattr(feature_export, 'export', export)
    runner.hourly_export(None)
    assert capsys.readouterr() == ('', '')


@pytest.mark.parametrize('configured', [False, True])
def test_daily_export_requires_existing_directory(tmp_path, monkeypatch, configured):
    monkeypatch.delenv('CPLANE_EXPORT_DIR', raising=False)
    missing = tmp_path / 'missing'
    if configured:
        monkeypatch.setenv('CPLANE_EXPORT_DIR', str(missing))
    with pytest.raises(state.StateError, match='Export directory unavailable'):
        runner.daily_export(None, datetime(2026, 11, 12).date())
    assert not missing.exists()


def test_signal_unwinds_active_pass_lock(monkeypatch):
    from contextlib import contextmanager
    entered, exited = [], []
    @contextmanager
    def locked(path):
        entered.append(path)
        try:
            yield
        finally:
            exited.append(path)
    monkeypatch.setattr(state, 'locked', locked)
    def run():
        with state.locked('synthetic'):
            stop()
    runner.run_loop(None, 60, pass_once=run, wait=Mock())
    assert entered == exited == ['synthetic']


def test_signal_rolls_back_postgres_pass(pg_store):
    before = pg_store.snapshot()
    def run():
        with state.locked(None) as backend:
            backend.save(dict(version=1, slices=[]), [dict(event='synthetic')])
            stop()
    runner.run_loop(None, 60, pass_once=run, wait=Mock())
    assert pg_store.snapshot() == before


def test_daily_export_cleans_first_temporary_file_when_second_fails(make_state, tmp_path, monkeypatch):
    path = make_state()
    folder = tmp_path / 'exports'
    folder.mkdir()
    old = folder / 'factory-2026-11-12.json'
    old.write_text('old state')
    Path(str(old) + '.outbox.jsonl').write_text('old notices')
    before = {p.name: p.read_bytes() for p in folder.iterdir()}
    monkeypatch.setenv('CPLANE_EXPORT_DIR', str(folder))
    create = runner.tempfile.NamedTemporaryFile
    calls = []
    def fail_second(**kwargs):
        calls.append(kwargs)
        if len(calls) == 2:
            raise OSError('synthetic write failure')
        return create(**kwargs)
    monkeypatch.setattr(runner.tempfile, 'NamedTemporaryFile', fail_second)
    with pytest.raises(OSError):
        runner.daily_export(path, datetime(2026, 11, 12).date())
    assert len(calls) == 2
    assert {p.name: p.read_bytes() for p in folder.iterdir()} == before
