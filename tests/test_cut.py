import json
import subprocess
import sys

import pytest

from cplane import cli, cut, state


BRIEF = "# Task\n\n## Fixed decisions (do not reopen)\nKeep this exact.\n\n## Do not — ever\nNever do that.\n\n## Handover\nOther text.\n"
PLAN = {"tickets": [{"title": "SECRET TITLE", "files": ["src/a.py"], "change": "SECRET CHANGE", "check": "pytest -k a"},
                    {"title": "Next", "files": ["src/b.py"], "change": "Do next", "check": "pytest -k b"}],
        "test_files": ["tests/test_a.py"], "node_steps": "Install the merged commit"}


@pytest.fixture
def setup(tmp_path, make_state, monkeypatch):
    path = make_state()
    (tmp_path / "briefs").mkdir()
    (tmp_path / "briefs/W1.md").write_text(BRIEF)
    plan = tmp_path / "plan.json"
    plan.write_text(json.dumps(PLAN))
    repo = tmp_path / "source"
    (repo / "skills").mkdir(parents=True)
    (repo / "cplane").mkdir()
    (repo / "skills/cut.md").write_text("instructions")
    for args in (["init", "-q"], ["config", "user.email", "test@example.com"], ["config", "user.name", "Test"], ["add", "skills"], ["commit", "-qm", "skills"]):
        subprocess.run(["git", "-C", str(repo), *args], check=True)
    monkeypatch.setattr(cli, "__file__", str(repo / "cplane/cli.py"))
    capture = tmp_path / "capture.json"
    fake = tmp_path / "fake.py"
    fake.write_text("import json,sys\nfrom pathlib import Path\nx=json.load(sys.stdin)\nPath(sys.argv[1]).write_text(json.dumps(x))\nprint(json.dumps(['id-1','id-2']))\n")
    monkeypatch.setenv("CPLANE_TASK_SUBMIT", json.dumps([sys.executable, str(fake), str(capture)]))
    args = ["--state", str(path), "cut-submit", "voice/W1", str(plan), "--repository", "owner/repo", "--branch", "work", "--base", "a" * 40, "--actor", "planner"]
    return path, plan, capture, args, repo


def test_build_copies_rules_and_chains():
    result = cut.build_task_file("voice/W1", "owner/repo", "work", "a" * 40, PLAN, BRIEF)
    assert result.keys() == {"slice", "repository", "branch", "base_commit", "node_steps", "tasks"}
    assert result["node_steps"] == PLAN["node_steps"]
    for i, task in enumerate(result["tasks"]):
        assert "## Fixed decisions (do not reopen)\nKeep this exact.\n\n" in task["goal"]
        assert "## Do not — ever\nNever do that.\n\n" in task["goal"]
        assert task["goal"].startswith(cut.TEST_LINE + "\n\n" + PLAN["tickets"][i]["change"])
        assert task["depends_on"] == ([] if i == 0 else [i])
        assert task["pinned_paths"] == PLAN["test_files"]
        assert task["allowed_files"] == PLAN["tickets"][i]["files"]


def test_missing_sections_names_slice():
    with pytest.raises(state.StateError, match="voice/W1"):
        cut.sections("## Other\nNo rules", "voice/W1")
    assert "yes" in cut.sections("## fixed decisions suffix\nyes\n", "s")


def test_submit_and_notice(setup):
    path, _, capture, args, repo = setup
    assert cli.main(args) == 0
    payload = json.loads(capture.read_text())
    assert payload == cut.build_task_file("voice/W1", "owner/repo", "work", "a" * 40, PLAN, BRIEF)
    log = state.load(path)["slices"][0]["log"][-1]
    revision = subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"], text=True).strip()
    assert log["actor"] == "planner" and log["event"] == "cut-submit: skills " + revision
    notice = json.loads(path.with_name(path.name + ".outbox.jsonl").read_text())
    assert "2 tickets" in notice["text"] and "id-1" in notice["text"] and "id-2" in notice["text"]
    assert "SECRET" not in json.dumps(log)


def test_invalid_plan_does_not_submit(setup, capsys):
    path, plan, capture, args, _ = setup
    plan.write_text(json.dumps({"tickets": [{"title": "SECRET TITLE", "files": [], "change": "SECRET CHANGE", "check": "x"}], "test_files": ["tests/t.py"], "node_steps": None}))
    before = path.read_bytes()
    assert cli.main(args) == 1
    assert "position 1 files" in capsys.readouterr().err
    assert not capture.exists() and path.read_bytes() == before


def test_refused_submit_preserves_state_and_hides_output(setup, monkeypatch, capsys):
    path, _, _, args, _ = setup
    monkeypatch.setenv("CPLANE_TASK_SUBMIT", json.dumps([sys.executable, "-c", "import sys; print('SECRET CHANGE', file=sys.stderr); sys.exit(1)"]))
    before = path.read_bytes()
    assert cli.main(args) == 1
    assert "SECRET" not in capsys.readouterr().err
    assert path.read_bytes() == before
    assert not path.with_name(path.name + ".outbox.jsonl").exists()


def test_prompt(setup, capsys):
    path, _, _, _, _ = setup
    assert cli.main(["--state", str(path), "cut-prompt", "voice/W1"]) == 0
    assert capsys.readouterr().out.endswith(BRIEF)


@pytest.mark.parametrize('marker', ['```', '~~~~'])
def test_sections_skip_fenced_headings(marker):
    rules = f'## Fixed decisions\nKeep.\n{marker}text\n# embedded heading\n## Do not fake\n{marker}\nStill fixed.\n'
    brief = f'{marker}\n## Do not outside\n{marker}\n' + rules + '## Handover\nOther.'
    assert cut.sections(brief, 's') == rules


def test_archive_revision_used_for_submission(setup, monkeypatch):
    path, _, capture, args, repo = setup
    import shutil
    shutil.rmtree(repo / '.git')
    (repo / 'REVISION').write_text('archive-revision\n')
    monkeypatch.setenv('CPLANE_REVISION', 'a' * 40)
    assert cli.main(args) == 0
    assert capture.exists()
    assert state.load(path)['slices'][0]['log'][-1]['event'] == 'cut-submit: skills archive-revision'


def test_archive_revision_missing_refuses(setup, capsys, monkeypatch):
    _, _, capture, args, repo = setup
    import shutil
    shutil.rmtree(repo / '.git')
    monkeypatch.delenv('CPLANE_REVISION', raising=False)
    assert cli.main(args) == 1
    assert 'REVISION' in capsys.readouterr().err
    assert not capture.exists()


def test_archive_environment_revision(tmp_path, monkeypatch):
    monkeypatch.setenv('CPLANE_REVISION', 'a1' * 20)
    assert cut.skills_version(tmp_path) == 'a1' * 20


@pytest.mark.parametrize('revision', ['', 'a' * 39, 'a' * 41, 'A' * 40, 'g' * 40, 'a' * 40 + '\n'])
def test_archive_invalid_environment_revision_refuses(tmp_path, monkeypatch, revision):
    monkeypatch.setenv('CPLANE_REVISION', revision)
    with pytest.raises(state.StateError, match='requires REVISION'):
        cut.skills_version(tmp_path)


def test_dirty_skills_refuse_even_with_revision(setup, capsys):
    _, _, capture, args, repo = setup
    (repo / 'skills/cut.md').write_text('dirty')
    (repo / 'REVISION').write_text('must-not-override-checkout')
    assert cli.main(args) == 1
    assert 'committed' in capsys.readouterr().err
    assert not capture.exists()


def test_status_argv_and_unknown_slice(tmp_path, monkeypatch):
    fake = tmp_path / 'status.py'
    fake.write_text('import json,sys\nassert sys.argv[1] == "voice/W1"\nprint("[]")\n')
    monkeypatch.setenv('CPLANE_TASK_STATUS', json.dumps([sys.executable, str(fake)]))
    assert cut.status('voice/W1') == []


@pytest.mark.parametrize('output', ['SECRET malformed', '{}', '[{"id":"x"}]',
                                  '[{"id":"x","position":1,"title":"t","status":"unknown","reason":null}]'])
def test_invalid_status_is_redacted(monkeypatch, output):
    from unittest.mock import Mock
    monkeypatch.setenv('CPLANE_TASK_STATUS', '["synthetic-status"]')
    monkeypatch.setattr(cut.subprocess, 'run', Mock(return_value=subprocess.CompletedProcess([], 0, output, 'SECRET')))
    with pytest.raises(state.StateError, match='invalid tickets') as error:
        cut.status('voice/W1')
    assert output not in str(error.value) and 'SECRET' not in str(error.value)


@pytest.mark.parametrize('outcome', ['queued', 'running', 'done', 'failed', 'escalated'])
def test_status_accepts_queue_records(monkeypatch, outcome):
    from unittest.mock import Mock
    records = [dict(id='id-1', position=1, title='Ticket', status=outcome, reason=None)]
    monkeypatch.setenv('CPLANE_TASK_STATUS', '["synthetic-status", "--json"]')
    run = Mock(return_value=subprocess.CompletedProcess([], 0, json.dumps(records), ''))
    monkeypatch.setattr(cut.subprocess, 'run', run)
    assert cut.status('voice/W1') == records
    assert run.call_args.args[0] == ['synthetic-status', '--json', 'voice/W1']


@pytest.mark.parametrize('command', ['', '{}', '[]', '[1]'])
def test_invalid_status_command_refuses(monkeypatch, command):
    monkeypatch.setenv('CPLANE_TASK_STATUS', command)
    with pytest.raises(state.StateError, match='JSON argument list'):
        cut.status('voice/W1')


def test_poll_records_each_attempt_after_validation(monkeypatch):
    from unittest.mock import Mock
    records = [dict(id='id-1', position=1, title='PRIVATE TITLE', status='running', reason=None,
                    attempt=2, tokens=17, seconds=1.5, cost=0.01, prompt='PRIVATE PROMPT')]
    store = Mock()
    monkeypatch.setattr(state, 'postgres', lambda: True)
    monkeypatch.setattr(state, 'store', lambda _: store)
    monkeypatch.setenv('CPLANE_TASK_STATUS', '["synthetic-status"]')
    run = Mock(return_value=subprocess.CompletedProcess([], 0, json.dumps(records), ''))
    monkeypatch.setattr(cut.subprocess, 'run', run)
    assert cut.status('voice/W1') == records
    assert cut.status('voice/W1') == records
    assert store.task_record_poll.call_count == 2
    store.task_record_poll.assert_called_with('voice/W1', records)
    store.task_record_poll.side_effect = RuntimeError('PRIVATE accounting failure')
    assert cut.status('voice/W1') == records


@pytest.mark.parametrize('field,value', [('attempt', 0), ('attempt', True), ('attempt', 1.5),
    ('tokens', -1), ('tokens', 1.5), ('seconds', float('nan')), ('seconds', float('inf')),
    ('cost', -0.1), ('cost', 'PRIVATE'), ('tokens', True)])
def test_invalid_accounting_is_not_recorded(monkeypatch, field, value):
    from unittest.mock import Mock
    store = Mock()
    monkeypatch.setattr(state, 'postgres', lambda: True)
    monkeypatch.setattr(state, 'store', lambda _: store)
    monkeypatch.setenv('CPLANE_TASK_STATUS', '["synthetic-status"]')
    record = dict(id='id-1', position=1, title='PRIVATE', status='running', reason=None)
    record[field] = value
    monkeypatch.setattr(cut.subprocess, 'run', Mock(return_value=
        subprocess.CompletedProcess([], 0, json.dumps([record]), '')))
    with pytest.raises(state.StateError, match='invalid tickets'):
        cut.status('voice/W1')
    store.task_record_poll.assert_not_called()
