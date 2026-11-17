from datetime import datetime, timedelta
from unittest.mock import Mock

from cplane import digest, state
from cplane.cli import main
from cplane.runner import Runner
from cplane.times import LOCAL


def test_digest_counts_and_content():
    end = datetime(2026, 10, 16, 7, tzinfo=LOCAL)
    at = (end - timedelta(hours=1)).isoformat()
    earlier = (end - timedelta(hours=25)).isoformat()
    def entry(event, when=at):
        return dict(at=when, event=event)
    data = {'slices': [
        dict(id='a/1', title='SECRET TITLE', state='issued', log=[
            entry('merged: abc'), entry('Installed abc'), entry('slice link: corrects x'),
            entry('merge: Approve PR #3: class 4 paths'), entry('merged: old', earlier)],
            attention=dict(kind='merge', approved=False, since=at, body='SECRET BODY')),
        dict(id='a/2', state='issued', log=[entry('escalation: Install failed; rollback attempted')],
             attention=None),
    ]}
    records = [dict(slice_id='a/1', started_at=earlier, change_class=2),
               dict(kind='task', started_at=at, cost=1.25)]
    text = digest.build(data, records, end)
    assert text.splitlines() == [
        'Merged: 1 (a/1)', 'Installed: 1 (a/1)', 'Install failed or rolled back: 1 (a/2)',
        'Corrections opened: 1 (a/1)', 'Class 2 merged: 1 (a/1)', 'Guard stops: 1 (a/1)',
        f'Waiting for owner: 1 (a/1 since {at})', 'Task spend: 1.25']
    assert 'SECRET' not in text
    assert digest.build({'slices': []}, [], end) == ''
    records[-1]['cost'] = None
    assert 'spend' not in digest.build(data, records, end)


def test_runner_daily_notice_and_cli_read_only(tmp_path, make_state, slice_data, capsys, monkeypatch):
    slice_data['state'] = 'planned'
    slice_data['slot'] = None
    path = make_state()
    from conftest import SyntheticStore
    backend = SyntheticStore(path)
    from cplane import eval_runner
    monkeypatch.setattr(eval_runner, 'collect', Mock())
    monkeypatch.setattr(eval_runner, 'start', Mock())
    backend.pipeline_step = lambda at: []
    backend.route_chat_events = lambda: None
    backend.ordered_slices = lambda items: items
    backend.run_record_list = lambda: []
    backend.run_record_export = lambda since: []
    monkeypatch.setattr(state, 'store', lambda path: backend)
    monkeypatch.setattr(state, 'postgres', lambda: True)
    clock = [datetime(2026, 10, 16, 6, 59, tzinfo=LOCAL)]
    def make_runner():
        return Runner(path, git=Mock(), clock=lambda: clock[0], runs=tmp_path / 'runs',
                      orders=Mock(collect=Mock(return_value=False)))
    runner = make_runner()
    runner.run()
    assert not state.store(path).notices()
    clock[0] += timedelta(minutes=1)
    runner.run()
    for _ in range(4):
        clock[0] += timedelta(minutes=5)
        make_runner().run()
    notices = state.store(path).notices()
    assert len(notices) == 1
    notice = notices[0][1]
    assert (notice['event'], notice['id'], notice['date']) == ('digest', 'digest', '2026-10-16')
    before = path.read_bytes(), Path_outbox(path).read_bytes()
    assert main(['digest', '--state', str(path), '--date', '2026-10-16']) == 0
    assert capsys.readouterr().out == notice['text'] + '\n'
    assert before == (path.read_bytes(), Path_outbox(path).read_bytes())
    clock[0] += timedelta(days=1)
    make_runner().run()
    assert len(state.store(path).notices()) == 2


def Path_outbox(path):
    from pathlib import Path
    return Path(str(path) + '.outbox.jsonl')
