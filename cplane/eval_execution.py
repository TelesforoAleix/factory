"""Legacy subscription eval adapter; slice turns use the platform exclusively."""

import json
import os
import re
import shutil
import subprocess
import time
import uuid
from contextvars import ContextVar
from datetime import UTC, datetime, timedelta
from pathlib import Path

from . import fence, state
from .executors import Processes, atomic_json

_USAGE_PASS = ContextVar("usage_pass", default=None)


def codex_usage(folder=None):
    windows = codex_limits(folder)
    if not windows:
        return None
    used = []
    for window in windows:
        if window.get("resets_at") is not None and window["resets_at"] <= time.time():
            used.append(0)
        elif isinstance(window.get("used_percent"), (int, float)):
            used.append(window["used_percent"])
    return max(used) if used else None


def codex_report(folder=None, *, paths=None):
    """The non-null windows (5-hour primary, weekly secondary) of the newest report."""
    if fence.launcher_usage():
        from .launcher import usage

        cache = _USAGE_PASS.get()
        if cache is None:
            limits = usage()
        else:
            if "limits" not in cache:
                cache["runner"].prepare_launcher_usage()
                cache["limits"] = usage()
            limits = cache["limits"]
        windows = (
            [
                limits[k]
                for k in ("primary", "secondary")
                if isinstance(limits.get(k), dict)
            ]
            if limits
            else []
        )
        reported = cache["runner"].launcher_usage_at() if cache is not None else 0
        return (windows, reported) if windows else None
    root = fence.LOGIN_ROOT / "codex/sessions"
    if paths is None:
        paths = list(Path(folder or root).rglob("*.jsonl"))
        if folder is None:
            runs = Path(os.environ.get("CPLANE_RUNS", "/srv/factory/runs"))
            paths.extend(runs.glob("*/usage-report.jsonl"))
    newest_first = sorted(paths, key=lambda p: p.stat().st_mtime_ns, reverse=True)
    for session in newest_first:
        # Walk backwards: the last non-null capacity report is the current one.
        for line in reversed(session.read_text(errors="replace").splitlines()):
            try:
                event = json.loads(line)
                limits = event.get("payload", {}).get("rate_limits")
                windows = (
                    [
                        limits[k]
                        for k in ("primary", "secondary")
                        if isinstance(limits.get(k), dict)
                    ]
                    if limits
                    else []
                )
                if windows:
                    stamp = event.get("timestamp")
                    reported = (
                        datetime.fromisoformat(stamp).timestamp()
                        if isinstance(stamp, str)
                        else session.stat().st_mtime
                    )
                    return windows, reported
            except (ValueError, KeyError, TypeError, AttributeError):
                continue
    return None


def codex_limits(folder=None):
    report = codex_report(folder)
    return report[0] if report else None


def probe_codex_usage(runs):
    """Discard the probe workspace and output; retain only normal usage telemetry."""
    fence.trusted_directory(fence.WORK_ROOT)
    fence.trusted_directory(runs)
    token = uuid.uuid4().hex
    work = fence.WORK_ROOT / ("usage-" + token)
    output = runs / ("usage-" + token)
    turn = (2 << 128) + int(token, 16)
    work.mkdir(mode=0o700)
    output.mkdir(mode=0o700)
    fence.own(work, "work")
    options = (
        ["--run-id", "usage-" + token]
        if fence.socket_enabled()
        else ["--session-turn", str(turn)]
    )
    session, transcript = None, ""
    try:
        result = subprocess.run(
            [
                *fence.fence_command(),
                "run",
                "--tool",
                "codex",
                "--repo",
                str(work),
                "--run",
                str(output),
                *options,
                "--",
                "codex",
                "exec",
                "-m",
                "gpt-6-luna",
                "-c",
                'model_reasoning_effort="low"',
                "--skip-git-repo-check",
                "-c",
                'history.persistence="none"',
                "-c",
                'sqlite_home="/tmp/cplane-usage"',
                "-c",
                'log_dir="/tmp/cplane-usage"',
                "--json",
                "--",
                "Reply only: OK",
            ],
            check=False,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            text=True,
            stderr=subprocess.DEVNULL,
            timeout=120,
            env=fence.host_environment(),
        )
        transcript = result.stdout
    except subprocess.TimeoutExpired as error:
        transcript = error.stdout or ""
        if isinstance(transcript, bytes):
            transcript = transcript.decode(errors="replace")
        raise
    finally:
        for line in transcript.splitlines():
            try:
                event = json.loads(line)
                if event.get("type") == "thread.started" and re.fullmatch(
                    r"[A-Za-z0-9-]+", event.get("thread_id", "")
                ):
                    session = event["thread_id"]
            except (ValueError, AttributeError):
                continue
        cleanup = (
            ["stop", "usage-" + token]
            if fence.socket_enabled()
            else ["session-cleanup", str(turn)]
        )
        subprocess.run(
            [*fence.fence_command(), *cleanup],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env=fence.host_environment(),
        )
        try:
            if session and not fence.launcher_usage():
                root = fence.LOGIN_ROOT / "codex/sessions"
                paths = [
                    p
                    for p in root.rglob("*.jsonl")
                    if p.name == session + ".jsonl"
                    or p.name.endswith("-" + session + ".jsonl")
                ]
                try:
                    report = codex_report(paths=paths) if paths else None
                    windows = report[0] if report else None
                    if windows:
                        limits = {
                            name: {
                                k: window[k]
                                for k in ("used_percent", "resets_at")
                                if isinstance(window.get(k), (int, float))
                            }
                            for name, window in zip(("primary", "secondary"), windows)
                        }
                        atomic_json(
                            runs / "usage-report.jsonl",
                            {"payload": {"rate_limits": limits}},
                        )
                finally:
                    for path in paths:
                        path.unlink()
        finally:
            fence.remove(work, "work")
            shutil.rmtree(output)


def usage_limit_message(tail):
    for line in tail.splitlines():
        try:
            event = json.loads(line)
        except (ValueError, TypeError):
            continue
        if event.get("type") != "turn.failed":
            continue
        error = event.get("error")
        message = error.get("message", "") if isinstance(error, dict) else ""
        if isinstance(message, str) and re.search(
            r"usage limit", message, re.IGNORECASE
        ):
            return message
    return None


def probe_claude_usage(runs):
    """Read only Claude's last rate-limit windows from a disposable fenced turn."""
    fence.trusted_directory(fence.WORK_ROOT)
    fence.trusted_directory(runs)
    token = uuid.uuid4().hex
    run_id = "claude-usage-" + token
    work, output = fence.WORK_ROOT / run_id, runs / run_id
    turn = (2 << 128) + int(token, 16)
    work.mkdir(mode=0o700)
    output.mkdir(mode=0o700)
    try:
        fence.own(work, "work")
        options = (
            ["--run-id", run_id]
            if fence.socket_enabled()
            else ["--session-turn", str(turn)]
        )
        result = subprocess.run(
            [
                *fence.fence_command(),
                "run",
                "--tool",
                "claude",
                "--repo",
                str(work),
                "--run",
                str(output),
                *options,
                "--",
                "claude",
                "-p",
                "--model",
                "haiku",
                "--output-format",
                "stream-json",
                "--verbose",
                "Reply with: ok",
            ],
            check=False,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=120,
            env=fence.host_environment(),
        )
        if result.returncode != 0:
            return
        windows = None
        for line in result.stdout.splitlines():
            try:
                event = json.loads(line)
                if isinstance(event, dict) and event.get("type") == "rate_limit_event":
                    windows = None
                    windows = event.get("rate_limit_info", {}).get("unifiedWindows")
            except (ValueError, AttributeError):
                continue
        try:
            limits = {}
            for name in ("five_hour", "seven_day"):
                window = windows[name]
                used, reset = window["utilization"], window["resetsAt"]
                if (
                    type(used) not in (int, float)
                    or not 0 <= used <= 1
                    or type(reset) not in (int, float)
                    or not 0 < reset < float("inf")
                ):
                    return
                limits[name] = {"used_percentage": used * 100, "resets_at": reset}
            atomic_json(
                runs / "claude-usage.json", {"at": time.time(), "rate_limits": limits}
            )
        except (KeyError, TypeError):
            return
    finally:
        cleanup = (
            ["stop", run_id]
            if fence.socket_enabled()
            else ["session-cleanup", str(turn)]
        )
        try:
            subprocess.run(
                [*fence.fence_command(), *cleanup],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                env=fence.host_environment(),
            )
        finally:
            try:
                fence.remove(work, "work")
            finally:
                shutil.rmtree(output)


def claude_usage(path=None):
    try:
        if fence.launcher_usage():
            cache = _USAGE_PASS.get()
            runs = (
                cache["runner"].runs
                if cache is not None
                else Path(os.environ.get("CPLANE_RUNS", "/srv/factory/runs"))
            )
            default = runs / "claude-usage.json"
        else:
            default = fence.LOGIN_ROOT / "claude/usage-now.json"
        return json.loads(Path(path or default).read_text())
    except (OSError, ValueError):
        return None


class Context:
    def __init__(self, runner):
        self.parent = runner
        self.path, self.runs = runner.path, runner.runs
        self.processes = Processes()
        self.fence = fence.Fence()
        self.codex_reader, self.claude_reader = codex_usage, claude_usage
        self._usage_probe_allowed = True

    def collect(self, store):
        from . import eval_runner

        self.cache = {"runner": self}
        token = _USAGE_PASS.set(self.cache)
        try:
            return eval_runner.collect(self, store)
        finally:
            _USAGE_PASS.reset(token)

    def start(self, store):
        from . import eval_runner

        token = _USAGE_PASS.set(self.cache)
        try:
            return eval_runner.start(self, store)
        finally:
            _USAGE_PASS.reset(token)

    def __getattr__(self, name):
        return getattr(self.parent, name)

    def room(self, item):
        limits = state.store(self.path).limit_show()
        # Platform slice requests never reserve local eval fence capacity.
        running = {
            key: j.get("repository", "")
            for key, j in self.jobs.items()
            if not j.get("requests") and j["phase"] == "running" and key != item["id"]
        }
        for other in self.data.get("slices", []):
            if (
                other["id"] not in self.jobs
                and other["state"] in ("issued", "awaiting handover")
                and not other.get("attention")
            ):
                running[other["id"]] = other["repo"]
        if len(running) >= limits["executors"]:
            return "executor limit"
        if limits["repository_runs"] == 1 and any(
            repo.casefold() == item["repo"].casefold() for repo in running.values()
        ):
            return "repository busy"
        return None

    def limit_reset(self, message):
        """The reset time named in a usage-limit message, if it is still ahead."""
        match = re.search(
            r"try again at (?:([A-Za-z]{3}) (\d{1,2})(?:st|nd|rd|th)?, (\d{4}) )?"
            r"(\d{1,2}:\d{2}\s*[AP]M)",
            message,
            re.IGNORECASE,
        )
        if not match:
            return None
        try:
            instant = self.instant.astimezone(UTC)
            clock = datetime.strptime(
                match[4].upper().replace(" ", ""), "%I:%M%p"
            ).time()
            if match[1]:
                day = datetime.strptime(
                    f"{match[1].title()} {match[2]} {match[3]}", "%b %d %Y"
                )
                retry = instant.replace(
                    year=day.year,
                    month=day.month,
                    day=day.day,
                    hour=clock.hour,
                    minute=clock.minute,
                    second=0,
                    microsecond=0,
                )
            else:
                retry = instant.replace(
                    hour=clock.hour, minute=clock.minute, second=0, microsecond=0
                )
                if retry <= instant:
                    retry += timedelta(days=1)
        except ValueError:
            return None
        return retry.timestamp() if retry > instant else None

    def launcher_usage_at(self):
        stamps = []
        try:
            stamps.append(
                float(json.loads((self.runs / "usage-probe.json").read_text())["at"])
            )
        except (OSError, ValueError, KeyError, TypeError):
            pass
        if state.postgres():
            for record in state.store(self.path).run_record_list():
                if (
                    record["tool"] == "codex"
                    and record.get("started_at")
                    and record.get("seconds") is not None
                ):
                    stamps.append(
                        datetime.fromisoformat(record["started_at"]).timestamp()
                        + record["seconds"]
                    )
        return max(stamps, default=0)

    def prepare_launcher_usage(self, tool="codex"):
        if not getattr(self, "_usage_probe_allowed", False):
            return
        # The warm-up is an executor too. Reserve capacity for live and
        # unrecovered slice turns before starting it in its fresh workspace.
        jobs = getattr(self, "jobs", {})
        active = {
            key
            for key, job in jobs.items()
            if not job.get("requests")
            and (
                job["phase"] == "running"
                or job.get("pr_review", {}).get("phase") == "running"
            )
        }
        active.update(
            item["id"]
            for item in getattr(self, "data", {}).get("slices", [])
            if item["id"] not in jobs
            and item["state"] in ("issued", "awaiting handover")
            and not item.get("attention")
        )
        limits = (
            state.store(self.path).limit_show()
            if state.postgres()
            else {"executors": 2}
        )
        if len(active) >= limits["executors"]:
            return
        attempted_at = (self.clock() if tool == "claude" else self.instant).timestamp()
        if tool == "claude":
            usage = claude_usage(self.runs / "claude-usage.json")
            try:
                reported = float(usage["at"])
            except (KeyError, TypeError, ValueError):
                reported = 0
        else:
            reported = self.launcher_usage_at()
        if attempted_at - reported <= 1800:
            return
        self.runs.mkdir(parents=True, mode=0o700, exist_ok=True)
        fence.trusted_directory(self.runs)
        marker = self.runs / (
            "claude-usage-probe.json" if tool == "claude" else "usage-probe.json"
        )
        try:
            last = json.loads(marker.read_text())["at"]
        except (OSError, ValueError, KeyError, TypeError):
            last = 0
        if attempted_at - last < 3600:
            return
        atomic_json(marker, {"at": attempted_at})
        try:
            if tool == "claude":
                probe_claude_usage(self.runs)
            else:
                probe_codex_usage(self.runs)
        except (OSError, subprocess.SubprocessError):
            pass
