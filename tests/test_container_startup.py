"""Synthetic SSH and cross-service ownership regressions for container startup."""

import os
import shlex
import stat
import subprocess
from pathlib import Path
from unittest.mock import Mock

import pytest

from cplane import fence, planning, runner, sessions, state


@pytest.mark.parametrize("override", [False, True])
def test_briefs_pull_ssh_environment(tmp_path, monkeypatch, override):
    clone = tmp_path / "briefs"
    clone.mkdir()
    (clone / ".git").mkdir()
    for name in ("CPLANE_BRIEFS_KEY", "CPLANE_BRIEFS_KNOWN_HOSTS"):
        monkeypatch.delenv(name, raising=False)
        if override:
            monkeypatch.setenv(name, str(tmp_path / (name + " quote's space")))
    execute = Mock(return_value=subprocess.CompletedProcess([], 0, "", ""))
    monkeypatch.setattr(runner.subprocess, "run", execute)
    runner.Git().pull(clone / "slices.json")
    command = execute.call_args.args[0]
    assert command[-2:] == ["pull", "--ff-only"]
    ssh = shlex.split(execute.call_args.kwargs["env"]["GIT_SSH_COMMAND"])
    key = os.environ.get("CPLANE_BRIEFS_KEY", str(planning.READ_KEY))
    hosts = os.environ.get("CPLANE_BRIEFS_KNOWN_HOSTS", str(planning.KNOWN_HOSTS))
    assert ssh == [
        "ssh",
        "-F",
        "/dev/null",
        "-i",
        key,
        "-o",
        "IdentitiesOnly=yes",
        "-o",
        "BatchMode=yes",
        "-o",
        "StrictHostKeyChecking=yes",
        "-o",
        "UserKnownHostsFile=" + hosts,
    ]


def test_pull_overrides_clone_ssh_command(tmp_path, monkeypatch):
    clone = tmp_path / "briefs"
    subprocess.run(["git", "init", "-q", str(clone)], check=True)
    for args in (
        ["remote", "add", "origin", "git@github.com:example/synthetic.git"],
        ["config", "core.sshCommand", "/bin/false"],
    ):
        subprocess.run(["git", "-C", str(clone), *args], check=True)
    log = tmp_path / "ssh-args"
    ssh = tmp_path / "ssh"
    ssh.write_text(
        f'#!/bin/sh\nprintf "%s\\n" "$@" > {shlex.quote(str(log))}\nexit 1\n'
    )
    ssh.chmod(0o700)
    monkeypatch.setenv("PATH", str(tmp_path) + os.pathsep + os.environ["PATH"])
    monkeypatch.setenv("CPLANE_BRIEFS_KEY", "/run/secrets/briefs-key")
    monkeypatch.setenv("CPLANE_BRIEFS_KNOWN_HOSTS", "/run/secrets/briefs-known-hosts")
    with pytest.raises(state.StateError, match="fast-forward pull failed"):
        runner.Git().pull(clone / "slices.json")
    args = log.read_text().splitlines()
    assert "/run/secrets/briefs-key" in args
    assert "UserKnownHostsFile=/run/secrets/briefs-known-hosts" in args


def synthetic_owners(monkeypatch, overrides):
    original = Path.lstat

    def info(path):
        result = original(path)
        values = list(result)
        values[4] = 0
        if path in overrides:
            uid, mode = overrides[path]
            values[4] = uid
            values[0] = stat.S_IFMT(result.st_mode) | mode
        return os.stat_result(values)

    monkeypatch.setattr(Path, "lstat", info)
    monkeypatch.setattr(fence.os, "geteuid", lambda: 21011)


@pytest.mark.parametrize(
    "mode,uid,accepted",
    [
        (0o1733, 0, True),
        (0o0770, 0, False),
        (0o0733, 0, False),
        (0o1733, 21010, False),
        (0o0700, 21010, False),
    ],
)
def test_shared_runs_root(tmp_path, monkeypatch, mode, uid, accepted):
    runs = tmp_path / "runs"
    child = runs / "sessions"
    child.mkdir(parents=True)
    monkeypatch.setenv("CPLANE_RUNS", str(runs))
    synthetic_owners(monkeypatch, {runs: (uid, mode), child: (21011, 0o700)})
    for path in (runs, child):
        if accepted:
            assert fence.trusted_directory(path) == path
        else:
            with pytest.raises(state.StateError):
                fence.trusted_directory(path)


@pytest.mark.parametrize(
    "setting,uid,mode,accepted",
    [
        ("21010", 21010, 0o755, True),
        ("21010", 21012, 0o755, False),
        (None, 21010, 0o755, False),
        ("21010", 21010, 0o775, False),
        ("invalid", 21010, 0o755, False),
        ("", 21010, 0o755, False),
    ],
)
def test_document_clone_owner(tmp_path, monkeypatch, setting, uid, mode, accepted):
    clone = tmp_path / "briefs"
    subprocess.run(["git", "init", "-q", str(clone)], check=True)
    (clone / "plan.md").write_text("# Synthetic plan\n")
    subprocess.run(["git", "-C", str(clone), "add", "."], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(clone),
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.test",
            "commit",
            "-qm",
            "fixture",
        ],
        check=True,
    )
    parent = tmp_path / "public"
    parent.mkdir()
    if setting is None:
        monkeypatch.delenv("CPLANE_BRIEFS_OWNER_UID", raising=False)
    else:
        monkeypatch.setenv("CPLANE_BRIEFS_OWNER_UID", setting)
    synthetic_owners(monkeypatch, {clone: (uid, mode)})
    environment = sessions.host_environment
    monkeypatch.setattr(
        sessions,
        "host_environment",
        lambda: {**environment(), "GIT_TEST_ASSUME_DIFFERENT_OWNER": "1"},
    )
    execute = Mock(wraps=subprocess.run)
    monkeypatch.setattr(sessions.subprocess, "run", execute)
    exporter = sessions.DocumentExporter(clone, parent / "ui-docs")
    if accepted:
        assert exporter.refresh()
        assert (exporter.destination / "plan.md").read_text() == "# Synthetic plan\n"
        assert len(execute.call_args_list) == 2
        for call in execute.call_args_list:
            assert f"safe.directory={clone}" in call.args[0]
        # Neither general session exports nor the directory fence inherit trust.
        with pytest.raises(state.StateError):
            sessions.export_tree(clone, tmp_path / "other", "HEAD")
        with pytest.raises(state.StateError):
            fence.trusted_directory(clone)
    else:
        with pytest.raises(state.StateError):
            exporter.refresh()
        execute.assert_not_called()
