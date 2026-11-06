import json
import subprocess
import sys

import pytest

from cplane import cli, cut, state


BRIEF = "# Task\n\n## Fixed decisions (do not reopen)\nKeep this exact.\n\n## Do not — ever\nNever do that.\n\n## Handover\nOther text.\n"
PLAN = {"tickets": [{"title": "SECRET TITLE", "files": ["src/a.py"], "change": "SECRET CHANGE", "check": "pytest -k a"},
                    {"title": "Next", "files": ["src/b.py"], "change": "Do next", "check": "pytest -k b"}],
        "test_files": ["tests/test_a.py"]}


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
    assert result.keys() == {"slice", "repository", "branch", "base_commit", "tasks"}
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
    plan.write_text(json.dumps({"tickets": [{"title": "SECRET TITLE", "files": [], "change": "SECRET CHANGE", "check": "x"}], "test_files": ["tests/t.py"]}))
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
