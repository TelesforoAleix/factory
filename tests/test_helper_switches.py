"""Opt-in helper protocols with synthetic sockets and no login access."""

import json
import socket
import subprocess
import sys
from threading import Event, Thread
import time
from unittest.mock import Mock

import pytest

from cplane import eval_execution as runner
from cplane import deployer, fence, installation, launcher
from test_launcher_client import server as _server
from test_eval_execution import setup as _setup, NOW
from test_install import prepared_runner, SHA
from test_stores import pg_store as _pg_store


server = _server
setup = _setup
pg_store = _pg_store


class NoLogins:
    def __truediv__(self, other):
        raise AssertionError("login folder accessed")


@pytest.fixture
def launcher_mode(monkeypatch):
    monkeypatch.setenv("CPLANE_USAGE_SOURCE", "launcher")
    monkeypatch.setattr(fence, "LOGIN_ROOT", NoLogins())


@pytest.mark.parametrize(
    "content,reply,expected",
    [
        (b'{"primary":{"used_percent":42}}\n', {}, 42),
        (b"null\n", {}, None),
        (b"bad\n", {}, None),
        (b"[]\n", {}, None),
        (b'{"primary":{"used_percent":42}}\n', {"exit_code": 1}, None),
        (b"null\n", {"ok": False, "error": "unknown_profile"}, None),
    ],
)
def test_usage_socket(server, launcher_mode, content, reply, expected):
    requests, response, output = server
    output[:] = [content, b""]
    response.update(reply)
    assert runner.codex_usage() == expected
    assert len(requests) == 2
    run, stop = requests
    assert set(run) == {"op", "profile", "run_id"}
    assert run["profile"] == "usage"
    assert run["run_id"].startswith("usage-read-")
    assert len(run["run_id"]) <= 64
    assert stop == {"op": "stop", "run_id": run["run_id"]}


def test_unknown_stop_and_fresh_ids(server):
    requests, response, output = server
    output[:] = [b"null\n", b""]
    response.update(ok=False, error="unknown_run")
    launcher.usage()
    launcher.usage()
    assert requests[0]["run_id"] != requests[2]["run_id"]


def test_pass_shared_read_and_probe(setup, server, launcher_mode, monkeypatch):
    r, _, _ = setup
    server[2][:] = [b'{"primary":{"used_percent":20,"resets_at":9999999999}}\n', b'']
    probe = Mock()
    monkeypatch.setattr(runner, 'probe_codex_usage', probe)
    monkeypatch.setattr(runner.state, 'postgres', lambda: False)
    for _ in range(2):
        token = runner._USAGE_PASS.set({'runner': r})
        try:
            assert runner.codex_usage() == 20
            assert runner.codex_limits()[0]['used_percent'] == 20
        finally:
            runner._USAGE_PASS.reset(token)
    assert len(server[0]) == 4
    probe.assert_called_once()



@pytest.mark.parametrize("age,probe_count", [(1800, 0), (1801, 1), (0, 0)])
def test_launcher_age(setup, launcher_mode, monkeypatch, age, probe_count):
    r, _, _ = setup
    r.instant = NOW
    r._usage_probe_allowed = True
    monkeypatch.setattr(runner.state, "postgres", lambda: True)
    store = Mock()
    store.limit_show.return_value = {"executors": 2}
    store.run_record_list.return_value = [
        dict(tool="claude", started_at=NOW.isoformat(), seconds=0),
        dict(tool="codex", started_at=NOW.isoformat(), seconds=-age),
    ]
    monkeypatch.setattr(runner.state, "store", lambda _: store)
    probe = Mock()
    monkeypatch.setattr(runner, "probe_codex_usage", probe)
    r.prepare_launcher_usage()
    assert probe.call_count == probe_count


def test_probe_marker_newer_than_record_and_hourly(setup, launcher_mode, monkeypatch):
    r, _, _ = setup
    r.instant = NOW
    r._usage_probe_allowed = True
    r.runs.mkdir(parents=True)
    marker = r.runs / "usage-probe.json"
    probe = Mock()
    monkeypatch.setattr(runner, "probe_codex_usage", probe)
    for age in (0, 1801, 3599, 3600):
        marker.write_text(json.dumps({"at": NOW.timestamp() - age}))
        r.prepare_launcher_usage()
    probe.assert_called_once()


def test_launcher_probe_no_login_steps(tmp_path, launcher_mode, monkeypatch):
    monkeypatch.setenv("CPLANE_FENCE_COMMAND", "socket")
    work = tmp_path / "work"
    runs = tmp_path / "runs"
    work.mkdir()
    runs.mkdir()
    monkeypatch.setattr(fence, "WORK_ROOT", work)
    monkeypatch.setattr(fence, "own", Mock())
    monkeypatch.setattr(fence, "remove", Mock())
    command = Mock(
        return_value=subprocess.CompletedProcess(
            [], 0, '{"type":"thread.started","thread_id":"test-session"}\n'
        )
    )
    monkeypatch.setattr(runner.subprocess, "run", command)
    runner.probe_codex_usage(runs)
    assert command.call_args_list[0].args[0][3:6] == ["run", "--tool", "codex"]
    assert command.call_args_list[1].args[0][3] == "stop"
    assert not (runs / "usage-report.jsonl").exists()


@pytest.mark.parametrize("tool", ["codex", "claude"])
def test_resume_and_claude_no_logins(tmp_path, launcher_mode, monkeypatch, tool):
    monkeypatch.setattr(fence, "WORK_ROOT", tmp_path)
    copy = tmp_path / "copy"
    copy.mkdir()
    previous = dict(
        fence=True,
        repo=str(copy),
        repository="example/repo",
        branch="slice",
        base=SHA,
        default="main",
        tool=tool,
    )
    assert fence.Fence().resume(previous, "session")["repo"] == str(copy)
    assert runner.claude_usage() is None


@pytest.fixture
def deployer_server(tmp_path, monkeypatch):
    path = tmp_path / "deployer.sock"
    listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    listener.bind(str(path))
    listener.listen()
    listener.settimeout(0.1)
    monkeypatch.setenv("CPLANE_DEPLOYER_SOCKET", str(path))
    reply = dict(
        ok=True,
        application="factory",
        commit=SHA,
        result="installed",
        image_cleanup_failed=False,
    )
    requests = []
    release = Event()
    release.set()
    running = True

    def serve():
        while running:
            try:
                connection, _ = listener.accept()
            except socket.timeout:
                continue
            with connection:
                with connection.makefile("rb") as stream:
                    requests.append(json.loads(stream.readline(4097)))
                release.wait(10)
                connection.sendall(json.dumps(reply).encode() + b"\n")

    thread = Thread(target=serve)
    thread.start()
    yield str(path), reply, requests, release
    running = False
    thread.join(3)
    listener.close()
    assert not thread.is_alive()


@pytest.mark.parametrize(
    "reason",
    [
        None,
        "waits for the owner",
        "unknown caller",
        "migration failed",
        "switch failed",
        "health failed",
        "deployer unavailable",
        "guard change",
    ],
)
def test_deployer_protocol(deployer_server, reason):
    path, reply, requests, _ = deployer_server
    if reason:
        reply.update(ok=False, result=reason)
    if reason == "guard change":
        reply["paths"] = ["node/compose.yaml", "Dockerfile"]
    answer = deployer.install(path, "factory", SHA)
    assert requests == [dict(op="install", application="factory", sha=SHA)]
    if reason is None:
        assert answer == dict(ok=True, commit=SHA)
    elif reason == "waits for the owner":
        assert answer == dict(
            ok=False,
            error=f"Install waits for the owner: sudo homelab-deployer install factory {SHA}",
        )
    else:
        assert answer["error"] == "Install failed: " + reason + (
            "\nnode/compose.yaml\nDockerfile" if reason == "guard change" else ""
        )


def test_detached_install_and_no_replay(
    tmp_path, slice_data, deployer_server, monkeypatch
):
    r, entry, request = prepared_runner(tmp_path, slice_data)
    entry["repo"] = "example/factory"
    monkeypatch.setattr(
        installation.subprocess, "run", Mock(side_effect=AssertionError("systemd used"))
    )
    installation.process(r)
    directory = r.runs / "installs"
    result = directory / (request + ".json")
    assert (directory / (request + ".started")).exists()
    deadline = time.monotonic() + 10
    while not result.exists() and time.monotonic() < deadline:
        installation.process(r)
        time.sleep(0.01)
    assert json.loads(result.read_text()) == dict(ok=True, commit=SHA)
    installation.process(r)
    installation.process(r)
    assert len(deployer_server[2]) == 1
    assert entry["attention"]["answer"].startswith("Installed ")


def test_dead_child_never_replayed(tmp_path, slice_data, monkeypatch):
    monkeypatch.setenv("CPLANE_DEPLOYER_SOCKET", "/unused")
    r, entry, request = prepared_runner(tmp_path, slice_data)
    directory = r.runs / "installs"
    directory.mkdir(parents=True)
    (directory / (request + ".started")).write_text('{"deployer":true}')
    launch = Mock(side_effect=AssertionError("replayed"))
    monkeypatch.setattr(installation, "start_deployer", launch)
    installation.process(r)
    installation.process(r)
    assert (
        entry["attention"]["body"]
        == "Install ended without a result; inspect the deployer record"
    )
    assert not list(installation.pending(r.data))


def test_missing_deployer(tmp_path):
    assert deployer.install(str(tmp_path / "absent"), "factory", SHA) == dict(
        ok=False, error="Install failed: deployer unavailable"
    )


@pytest.mark.parametrize("setting", [None, "files", "LAUNCHER", ""])
def test_default_usage_paths(tmp_path, monkeypatch, setting):
    if setting is None:
        monkeypatch.delenv("CPLANE_USAGE_SOURCE", raising=False)
    else:
        monkeypatch.setenv("CPLANE_USAGE_SOURCE", setting)
    monkeypatch.setattr(fence, "LOGIN_ROOT", tmp_path)
    folder = tmp_path / "codex/sessions"
    folder.mkdir(parents=True)
    (folder / "synthetic.jsonl").write_text(
        '{"payload":{"rate_limits":{"primary":{"used_percent":12}}}}\n'
    )
    claude = tmp_path / "claude"
    claude.mkdir()
    (claude / "usage-now.json").write_text('{"synthetic":true}')
    assert runner.codex_usage() == 12
    assert runner.claude_usage() == {"synthetic": True}


def test_probe_respects_executor_capacity(setup, launcher_mode, monkeypatch):
    r, _, _ = setup
    r.instant = NOW
    r._usage_probe_allowed = True
    r.jobs = {"one": {"phase": "running"}, "two": {"phase": "running"}}
    probe = Mock()
    monkeypatch.setattr(runner, "probe_codex_usage", probe)
    r.prepare_launcher_usage()
    probe.assert_not_called()


def test_age_real_run_records(tmp_path, pg_store, monkeypatch):
    from cplane.runner import Runner
    r = runner.UsageContext(Runner(tmp_path / 'slices.json', runs=tmp_path / 'runs'))
    r.runs.mkdir(parents=True)
    (r.runs / "usage-probe.json").write_text(json.dumps({"at": NOW.timestamp() - 5000}))
    pg_store.run_record_add(
        "synthetic:old",
        kind="chat",
        tool="codex",
        started_at=NOW.isoformat(),
        seconds=30,
    )
    pg_store.run_record_add(
        "synthetic:new",
        kind="chat",
        tool="claude",
        started_at=NOW.isoformat(),
        seconds=900,
    )
    assert r.launcher_usage_at() == NOW.timestamp() + 30


def test_deployer_child_failure_result(tmp_path, slice_data, deployer_server):
    r, entry, request = prepared_runner(tmp_path, slice_data)
    entry["repo"] = "example/factory"
    deployer_server[1].update(ok=False, result="waits for the owner")
    installation.process(r)
    result = r.runs / "installs" / (request + ".json")
    deadline = time.monotonic() + 10
    while not result.exists() and time.monotonic() < deadline:
        time.sleep(0.01)
    assert (
        json.loads(result.read_text())["error"]
        == f"Install waits for the owner: sudo homelab-deployer install factory {SHA}"
    )
    installation.process(r)
    assert entry["attention"]["body"].startswith("Install waits for the owner:")
    assert len(deployer_server[2]) == 1


def test_install_pass_does_not_wait(tmp_path, slice_data, deployer_server):
    r, entry, request = prepared_runner(tmp_path, slice_data)
    entry["repo"] = "example/factory"
    deployer_server[3].clear()
    before = time.monotonic()
    installation.process(r)
    assert time.monotonic() - before < 1
    marker = r.runs / "installs" / (request + ".started")
    assert installation.deployer_running(marker)
    installation.process(r)
    assert list(installation.pending(r.data))
    deployer_server[3].set()
    result = marker.with_suffix(".json")
    deadline = time.monotonic() + 10
    while not result.exists() and time.monotonic() < deadline:
        time.sleep(0.01)
    installation.process(r)
    assert entry["attention"]["answer"].startswith("Installed ")
    assert len(deployer_server[2]) == 1


def test_actual_child_exit_without_result(tmp_path, slice_data, monkeypatch):
    monkeypatch.setenv("CPLANE_DEPLOYER_SOCKET", "/unused")
    r, entry, request = prepared_runner(tmp_path, slice_data)
    entry["repo"] = "example/factory"
    popen = subprocess.Popen
    children = []

    def start(args, **kwargs):
        assert (r.runs / "installs" / (request + ".started")).exists()
        assert kwargs["start_new_session"] is True
        child = popen([sys.executable, "-c", "import os; os._exit(1)"], **kwargs)
        children.append(child)
        return child

    monkeypatch.setattr(installation.subprocess, "Popen", start)
    installation.process(r)
    children[0].wait(timeout=10)
    installation.process(r)
    installation.process(r)
    assert len(children) == 1
    assert (
        entry["attention"]["body"]
        == "Install ended without a result; inspect the deployer record"
    )


def test_owner_guard_paths(deployer_server):
    path, reply, _, _ = deployer_server
    reply.update(ok=False, result="waits for the owner", paths=["node/compose.yaml"])
    assert (
        deployer.install(path, "factory", SHA)["error"]
        == f"Install waits for the owner: sudo homelab-deployer install factory {SHA}\nnode/compose.yaml"
    )


def test_legacy_marker_content_still_ignored(tmp_path, slice_data, monkeypatch):
    monkeypatch.delenv("CPLANE_DEPLOYER_SOCKET", raising=False)
    r, entry, request = prepared_runner(tmp_path, slice_data)
    directory = r.runs / "installs"
    directory.mkdir(parents=True)
    (directory / (request + ".started")).write_text("legacy")
    monkeypatch.setattr(
        installation.subprocess,
        "run",
        Mock(
            return_value=subprocess.CompletedProcess(
                [], 0, stdout="LoadState=not-found"
            )
        ),
    )
    installation.process(r)
    assert (
        entry["attention"]["body"]
        == "Install requires CPLANE_DEPLOYER_SOCKET; configure the platform deployer"
    )
