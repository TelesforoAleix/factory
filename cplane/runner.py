"""One locked scheduling pass. Adapters keep external effects fakeable."""

import hashlib
import io
import json
import math
import os
import re
import signal
import subprocess
import sys
import tempfile
import time
import traceback
from contextlib import redirect_stderr, redirect_stdout
from datetime import UTC, datetime, timedelta
from pathlib import Path

from . import cut as cutter
from . import deny, fence, github_app, run_platform, run_records, state
from . import review as reviewer
from .eligibility import eligibility
from .executors import atomic_json
from .orders import Collector
from .planning import ssh_command
from .text_bounds import ATTENTION_LIMIT, LOG_LIMIT, cut, cut_line
from .times import now

BOT_EVENTS = frozenset(
    {
        "question",
        "escalation",
        "merge",
        "owner-check",
        "stuck",
        "chat-paused",
        "testing-review",
        "digest",
    }
)
BOT_ACCEPTED_FIELDS = frozenset(
    {"id", "repo", "title", "state", "pr", "feature", "paused", "attention"}
)


def platform_paths(paths):
    """Translate path scopes into the forms accepted by the platform."""
    if paths is None:
        return None
    translated = []
    for path in paths:
        directory = path
        if path.endswith("/**"):
            directory = path[:-3]
        elif path.endswith("/*"):
            directory = path[:-2]
        if any(char in directory for char in "*?["):
            raise state.StateError("Platform cannot express path: " + path)
        translated.append(directory)
    return translated


def stuck_since(item, instant):
    """Return the start and reason of a current stalled interval, if any."""
    if item["state"] != "issued" or not item["log"]:
        return None
    entries = item["log"]
    last = datetime.fromisoformat(entries[-1]["at"])
    candidates = []
    if instant - last >= timedelta(minutes=20):
        candidates.append((last, "no new log activity"))
    pending = None
    for entry in reversed(entries):
        event = entry["event"]
        if event in ("checks: pending", "approval checks: pending"):
            pending = datetime.fromisoformat(entry["at"])
        elif event.startswith(("checks: ", "approval checks: ")):
            break
    if pending is not None and instant - pending > timedelta(minutes=10):
        candidates.append((pending, "checks pending"))
    return min(candidates) if candidates else None


def export_bot(path):
    directory = os.environ.get("CPLANE_BOT_EXPORT")
    if not directory:
        return
    try:
        folder = Path(directory)
        if not folder.is_absolute():
            raise ValueError("export directory must be absolute")
        fence.trusted_directory(folder)
        with state.locked(path) as backend:
            data, notices = backend.load(), backend.notices()
            data["slices"] = [
                {
                    key: value
                    for key, value in item.items()
                    if (
                        key in BOT_ACCEPTED_FIELDS
                        if item["state"] in ("accepted", "dropped")
                        else key != "log"
                    )
                }
                for item in data["slices"]
            ]
            payload = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
            outbox = "".join(
                json.dumps(notice, ensure_ascii=False) + "\n"
                for _, notice in notices
                if notice.get("event") in BOT_EVENTS
            )
            outbox_path = folder / "slices.json.outbox.jsonl"
            if outbox_path.exists() and not outbox.startswith(
                outbox_path.read_text(encoding="utf-8")
            ):
                raise ValueError("notice history changed")
            gid = folder.stat().st_gid
            for destination, content in (
                (outbox_path, outbox),
                (folder / "slices.json", payload),
            ):
                name = None
                try:
                    with tempfile.NamedTemporaryFile(
                        mode="w",
                        encoding="utf-8",
                        dir=folder,
                        prefix=".cplane-bot-",
                        delete=False,
                    ) as stream:
                        name = stream.name
                        os.fchown(stream.fileno(), -1, gid)
                        os.fchmod(stream.fileno(), 0o640)
                        stream.write(content)
                    os.replace(name, destination)
                finally:
                    if name is not None and os.path.exists(name):
                        os.unlink(name)
    except Exception:
        print("cplane: bot export failed", file=sys.stderr)


def daily_export(path, day):
    """Publish the same private state/outbox pair and rotation as factory-export."""
    directory = os.environ.get("CPLANE_EXPORT_DIR")
    if not directory or not Path(directory).is_dir():
        raise state.StateError("Export directory unavailable")
    folder = Path(directory)
    names = []
    try:
        # Finish both private temporary files before publishing either one.
        with state.locked(path) as backend:
            payload = json.dumps(backend.load(), indent=2, ensure_ascii=False) + "\n"
            outbox = "".join(
                json.dumps(notice, ensure_ascii=False) + "\n"
                for _, notice in backend.notices()
            )
        for content in (payload, outbox):
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=folder,
                prefix=".factory-export.",
                delete=False,
            ) as stream:
                names.append(Path(stream.name))
                os.fchmod(stream.fileno(), 0o600)
                stream.write(content)
        destination = folder / f"factory-{day.isoformat()}.json"
        os.replace(names[1], Path(str(destination) + ".outbox.jsonl"))
        os.replace(names[0], destination)
        exports = sorted(
            (
                p
                for p in folder.iterdir()
                if p.is_file()
                and re.fullmatch(r"factory-[0-9]{4}-[0-9]{2}-[0-9]{2}\.json", p.name)
            ),
            reverse=True,
        )
        for old in exports[7:]:
            old.unlink()
            Path(str(old) + ".outbox.jsonl").unlink(missing_ok=True)
    finally:
        for name in names:
            name.unlink(missing_ok=True)


def hourly_export(path):
    from .feature_export import export

    # Match the timer wrapper: neither success output nor private diagnostics.
    with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
        export(state.store(path).feature_export_snapshot())


class _StopLoop(BaseException):
    pass


def run_loop(
    path,
    every,
    *,
    clock=None,
    wait=time.sleep,
    pass_once=None,
    daily=daily_export,
    hourly=hourly_export,
):
    """Run sequential passes and wall-clock jobs, restoring signal handlers on exit."""
    if not math.isfinite(every) or every <= 0:
        raise state.StateError("--every must be a positive finite number of seconds")
    clock = clock or (lambda: datetime.now().astimezone())
    pass_once = pass_once or (lambda: Runner(path).run())
    last_day = last_hour = None

    def stop(signum, frame):
        # Unwind an active pass so locks/transactions close just as on timer stop.
        raise _StopLoop

    previous = {}
    try:
        for sig in (signal.SIGTERM, signal.SIGINT):
            previous[sig] = signal.signal(sig, stop)
        while True:
            try:
                pass_once()
            except Exception:
                print("cplane: run failed", file=sys.stderr)
            instant = clock()
            day = instant.date()
            hour = (day, instant.hour)
            if (instant.hour, instant.minute) >= (3, 45) and day != last_day:
                last_day = day
                try:
                    daily(path, day)
                except Exception:
                    print("cplane: daily export failed", file=sys.stderr)
            if hour != last_hour:
                last_hour = hour
                try:
                    hourly(path)
                except Exception:
                    print("Factory feature export failed", file=sys.stderr)
            wait(every)
    except _StopLoop:
        pass
    finally:
        for sig, handler in previous.items():
            signal.signal(sig, handler)


class Git:
    def tidy(self, path, *, now=None):
        return

    def pull(self, path):
        if (path.parent / ".git").exists():
            fence.trusted_directory(path.parent)
            env = fence.host_environment()
            env["GIT_SSH_COMMAND"] = ssh_command()
            result = subprocess.run(
                [
                    "git",
                    "-C",
                    str(path.parent),
                    "-c",
                    "core.hooksPath=/dev/null",
                    "-c",
                    "core.fsmonitor=false",
                    "pull",
                    "--ff-only",
                ],
                capture_output=True,
                text=True,
                env=env,
            )
            if result.returncode:
                raise state.StateError("briefs fast-forward pull failed")

    def commit(self, path):
        state.commit_state(path, Path(str(path) + ".outbox.jsonl"), "run", "pass")

    def branch(self, path):
        raise state.StateError("host branch read refused in fenced mode")


class BlockedPR(state.StateError):
    pass


class BranchConflict(state.StateError):
    pass


class GitHubReadError(state.StateError):
    pass


def check_merge_info(info, expected=None):
    if expected and info["headRefOid"] != expected:
        raise state.StateError("PR head differs from platform branch tip")
    if info.get("state") != "MERGED" and (
        info.get("isDraft")
        or re.match(
            r"(?:\[blocked\]|blocked:|draft:|\[draft\])",
            info.get("title", ""),
            re.IGNORECASE,
        )
        or re.search(
            r"DO NOT MERGE|MERGE BLOCKER",
            info.get("title", "") + "\n" + (info.get("body") or ""),
            re.IGNORECASE,
        )
    ):
        raise BlockedPR("PR marked not for merging")


OWNER_LOGIN = "TelesforoAleix"


class GitHub:
    def is_public(self, repo):
        value = json.loads(self.call(repo, "api", f"repos/{repo}"))
        return value.get("visibility") != "private"

    def default_tip(self, repo):
        metadata = json.loads(self.call(repo, "api", f"repos/{repo}"))
        return self.branch_tip(repo, metadata["default_branch"])

    def branch_tip(self, repo, branch):
        from urllib.parse import quote

        result = json.loads(
            self.call(repo, "api", f"repos/{repo}/commits/{quote(branch, safe='')}")
        )
        sha = result.get("sha")
        if not isinstance(sha, str) or not re.fullmatch("[0-9a-f]{40}", sha):
            raise GitHubReadError("GitHub branch tip unavailable")
        return sha

    def changes(self, job, number):
        """Read paths and pinned policy with Factory's App, without a checkout."""
        import base64

        from . import classes

        repo = job["repository"]
        # A git tree listing distinguishes an absent policy from a failed read.
        root = json.loads(
            self.call(repo, "api", f"repos/{repo}/git/trees/{job['base']}?recursive=1")
        )
        if root.get("truncated"):
            raise GitHubReadError("Pinned policy tree listing truncated")
        policy = None
        blob = next(
            (
                entry
                for entry in root["tree"]
                if entry["path"] == ".github/change-classes"
            ),
            None,
        )
        if blob:
            value = json.loads(
                self.call(repo, "api", f"repos/{repo}/git/blobs/{blob['sha']}")
            )
            policy = base64.b64decode(value["content"], validate=False).decode("utf-8")
        paths, deleted = [], []
        page = 1
        while True:
            entries = json.loads(
                self.call(
                    repo,
                    "api",
                    f"repos/{repo}/pulls/{number}/files?per_page=100&page={page}",
                )
            )
            for entry in entries:
                paths.append(entry["filename"])
                if entry["status"] == "removed":
                    deleted.append(entry["filename"])
                if entry.get("previous_filename"):
                    paths.append(entry["previous_filename"])
                    deleted.append(entry["previous_filename"])
            if len(entries) < 100:
                break
            page += 1
            if page > 30:
                raise GitHubReadError("PR path listing exceeds GitHub limit")
        level, guards = classes.classify(paths, policy, deleted=deleted)
        installed = os.environ.get("CPLANE_REVISION")
        if installed and repo == "TelesforoAleix/factory":
            compared = json.loads(
                self.call(
                    repo, "api", f"repos/{repo}/compare/{installed}...{job['tip']}"
                )
            )
            entries = compared.get("files", [])
            # GitHub's compare endpoint returns at most 300 files. Fail closed
            # rather than silently omit an uninstalled guard path.
            if len(entries) >= 300:
                raise GitHubReadError(
                    "Installed revision comparison exceeds GitHub limit"
                )
            drift = [entry["filename"] for entry in entries]
            drift.extend(
                entry["previous_filename"]
                for entry in entries
                if entry.get("previous_filename")
            )
            _, installed_guards = classes.classify(drift, policy)
            guards = sorted(set(guards) | set(installed_guards))
            if guards:
                level = 4
        return level, guards

    successful_reads = 0

    def repository(self, path):
        raise state.StateError("host origin read refused in fenced mode")

    def call(self, repo, *args):
        options = {"env": fence.github_environment([repo]), "cwd": "/"}
        command = (
            ["gh", *args] if args and args[0] == "api" else ["gh", *args, "-R", repo]
        )
        update = (
            args[:3] == ("api", "-X", "PUT")
            and len(args) > 3
            and re.fullmatch(r"repos/[^/]+/[^/]+/pulls/\d+/update-branch", args[3])
        )
        read = args[:2] in (("pr", "view"), ("pr", "list")) or (
            args[:1] == ("api",) and not update
        )
        attempts = 3 if read else 1
        for attempt in range(attempts):
            fence.record_github_call()
            result = subprocess.run(command, text=True, capture_output=True, **options)
            if not result.returncode:
                if read:
                    self.successful_reads += 1
                return result.stdout.strip()
            if attempt + 1 < attempts:
                time.sleep(5)
        if (
            update
            and re.search(r"\b422\b", result.stderr)
            and re.search(r"conflict", result.stderr, re.IGNORECASE)
        ):
            raise BranchConflict("PR conflicts with main; needs a new slice from main")
        if read:
            raise GitHubReadError("gh operation failed")
        raise state.StateError("gh operation failed")

    def open(self, repo, request):
        # Recover an already-created PR if a previous pass stopped before saving its number.
        existing = json.loads(
            self.call(
                repo,
                "pr",
                "list",
                "--head",
                request["branch"],
                "--state",
                "open",
                "--json",
                "number",
            )
        )
        if existing:
            number = existing[0]["number"]
            try:
                self.call(
                    repo,
                    "pr",
                    "edit",
                    str(number),
                    "--title",
                    request["title"],
                    "--body",
                    request["body"],
                )
            except state.StateError as error:
                raise state.StateError("PR edit failed") from error
            return number
        url = self.call(
            repo,
            "pr",
            "create",
            "--head",
            request["branch"],
            "--title",
            request["title"],
            "--body",
            request["body"],
        )
        return int(url.rstrip("/").split("/")[-1])

    def find_pr(self, repo, branch):
        if not branch:
            return None
        prs = json.loads(
            self.call(
                repo,
                "pr",
                "list",
                "--head",
                branch,
                "--state",
                "all",
                "--json",
                "number,createdAt",
            )
        )
        if not prs:
            return None
        newest = max(prs, key=lambda pr: pr.get("createdAt", ""))
        return newest["number"]

    def checks(self, repo, number, expected=None):
        if expected:
            info = json.loads(
                self.call(
                    repo,
                    "pr",
                    "view",
                    str(number),
                    "--json",
                    "headRefOid,state,title,body,isDraft,mergeStateStatus,mergeable",
                )
            )
            self.check_info = info
            if info["headRefOid"] != expected:
                raise state.StateError("PR head differs from platform branch tip")
            if info.get("state") == "MERGED":
                # Let the runner record the final merge without polling old CI.
                return "merged", ""
            info = json.loads(
                self.call(
                    repo,
                    "api",
                    f"repos/{repo}/actions/runs?head_sha={expected}&per_page=100",
                )
            )
            runs = info["workflow_runs"]
            jobs = []
            for run in runs:
                info = json.loads(
                    self.call(
                        repo,
                        "api",
                        f"repos/{repo}/actions/runs/{run['id']}/jobs?per_page=100",
                    )
                )
                jobs.extend(info["jobs"])
            passed = {
                job["name"]
                for job in jobs
                if job["status"] == "completed" and job["conclusion"] == "success"
            }
            pending = (
                not runs
                or not passed
                or any(run["status"] != "completed" for run in runs)
            )
            for job in jobs:
                if job["status"] != "completed":
                    pending = True
                    continue
                conclusion = job["conclusion"]
                if conclusion == "cancelled" and job["name"] in passed:
                    continue
                if conclusion in (
                    "failure",
                    "cancelled",
                    "timed_out",
                    "action_required",
                    "startup_failure",
                ):
                    return "red", job["name"]
                if conclusion not in ("success", "neutral", "skipped"):
                    pending = True
            return ("pending" if pending else "green"), ""
        info = json.loads(
            self.call(
                repo,
                "pr",
                "view",
                str(number),
                "--json",
                "statusCheckRollup,headRefOid",
            )
        )
        self.check_sha = info.get("headRefOid")
        pending = False
        rollup = info["statusCheckRollup"]
        # A stalled hosted runner is cancelled on one of two runs; the other run may pass.
        passed = {
            c.get("name")
            for c in rollup
            if c.get("name") and (c.get("conclusion") or c.get("state")) == "SUCCESS"
        }
        for check in rollup:
            conclusion = check.get("conclusion") or check.get("state")
            if conclusion == "CANCELLED" and check.get("name") in passed:
                continue
            if conclusion in (
                "FAILURE",
                "ERROR",
                "CANCELLED",
                "TIMED_OUT",
                "ACTION_REQUIRED",
                "STARTUP_FAILURE",
            ):
                return "red", check.get("name") or check.get("context", "check")
            if conclusion not in ("SUCCESS", "NEUTRAL", "SKIPPED"):
                pending = True
        return ("pending" if pending else "green"), ""

    def is_open(self, repo, number):
        info = json.loads(self.call(repo, "pr", "view", str(number), "--json", "state"))
        return info["state"] == "OPEN"

    def owner_approval(self, repo, number, tip):
        pages = json.loads(
            self.call(
                repo,
                "api",
                f"repos/{repo}/pulls/{number}/reviews?per_page=100",
                "--paginate",
                "--slurp",
            )
        )
        reviews = [
            review
            for page in pages
            for review in page
            if review.get("user", {}).get("login") == OWNER_LOGIN
            and review.get("state") in ("APPROVED", "CHANGES_REQUESTED", "DISMISSED")
        ]
        newest = max(reviews, key=lambda review: review["id"], default=None)
        if newest and newest["state"] == "APPROVED" and newest.get("commit_id") == tip:
            return newest["id"]
        return None

    def merge_info(self, repo, number, expected=None):
        info = json.loads(
            self.call(
                repo,
                "pr",
                "view",
                str(number),
                "--json",
                "state,mergeCommit,title,body,isDraft,headRefOid,mergeStateStatus,mergeable",
            )
        )
        check_merge_info(info, expected)
        return info

    def update_branch(self, repo, number, expected):
        self.call(
            repo,
            "api",
            "-X",
            "PUT",
            f"repos/{repo}/pulls/{number}/update-branch",
            "-f",
            f"expected_head_sha={expected}",
        )
        deadline = time.monotonic() + 120
        while True:
            head = self.merge_info(repo, number)["headRefOid"]
            if head != expected:
                return head
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise state.StateError("gh operation failed")
            time.sleep(min(5, remaining))

    def merge(self, repo, number, expected=None):
        info = self.merge_info(repo, number, expected)
        if info["state"] != "MERGED":
            self.call(
                repo,
                "pr",
                "merge",
                str(number),
                "--squash",
                *(["--match-head-commit", expected] if expected else []),
            )
            info = json.loads(
                self.call(
                    repo, "pr", "view", str(number), "--json", "state,mergeCommit"
                )
            )
        return info["mergeCommit"]["oid"]


class Runner:
    def log(self, item, event, notice=False, *, actor="runner"):
        event = cut_line(event, LOG_LIMIT)
        item["log"].append({"at": self.at, "actor": actor, "event": event})
        if notice:
            self.notices.append(
                {
                    "at": self.at,
                    "id": item["id"],
                    "event": event.split(":")[0],
                    "text": event,
                }
            )

    def defer(self, item, reason):
        if not item["log"] or item["log"][-1]["event"] != reason:
            self.log(item, reason)

    def attention(self, item, kind, body):
        run_records.owner_wait(self, item, close=True)
        body = cut(body, ATTENTION_LIMIT)
        item["attention"] = {
            "kind": kind,
            "body": body,
            "since": self.at,
            "answer": None,
            "approved": False,
        }
        if kind == "escalation":
            item["state"] = "escalated"
        run_records.owner_wait(self, item)
        first_line = body.partition("\n")[0]
        self.log(item, f"{kind}: {first_line}", True)

    def slice_failure(self, item, stage):
        if isinstance(sys.exception(), fence.deny.Denied):
            self.attention(item, "escalation", str(sys.exception()))
            return
        lines = traceback.format_exc().strip().splitlines()
        summary = f"{stage} failed: {lines[-1] if lines else 'unknown error'}"
        body = summary + ("\n" + "\n".join(lines[-8:]) if lines else "")
        existing = item.get("attention")
        if (
            not existing
            or existing["kind"] != "escalation"
            or existing["body"] != cut(body, ATTENTION_LIMIT)
        ):
            self.attention(item, "escalation", body)

    def github_repo(self, item):
        return item["repo"]

    def save_job(self, job):
        atomic_json(Path(job["run"]) / "job.json", job)

    def merge_ready(self, item, job, info=None):
        try:
            if info is None:
                info = self.github.merge_info(
                    self.github_repo(item), item["pr"], expected=job["tip"]
                )
            else:
                check_merge_info(info, job["tip"])
            if info.get("state") == "MERGED":
                self.merge(item, job, ready=True, merged=info)
                return False
            if (
                info.get("mergeStateStatus") == "BEHIND"
                and info.get("mergeable") == "MERGEABLE"
            ):
                job["tip"] = self.github.update_branch(
                    self.github_repo(item), item["pr"], job["tip"]
                )
                if job.get("github_approval_tip") != job["tip"] and job.pop(
                    "github_approval_tip", None
                ):
                    approval = item["attention"]
                    if approval and approval["kind"] == "merge":
                        approval["approved"] = False
                job["updated_head"] = True
                self.save_job(job)
                self.log(item, "checks: pending")
                return False
        except (BlockedPR, BranchConflict) as error:
            self.attention(item, "escalation", str(error))
            return False
        return True

    def merge(self, item, job, *, ready=False, merged=None):
        if merged is None and not self.cli_review(item, job):
            return
        if not ready and not self.merge_ready(item, job):
            return
        change_class, guards = self.github.changes(job, item["pr"])
        job["change_class"] = change_class
        self.save_job(job)
        run_records.class_record(self, job, change_class)
        approval = item["attention"]
        if (
            merged is None
            and (guards or item["stop_before_merge"])
            and not (approval and approval["kind"] == "merge" and approval["approved"])
        ):
            body = f"Approve PR #{item['pr']}"
            if guards:
                body += ": class 4 paths\n" + "\n".join(
                    json.dumps(path, ensure_ascii=False) for path in guards[:20]
                )
                if len(guards) > 20:
                    body += f"\n{len(guards) - 20} more class 4 paths"
            self.attention(item, "merge", body)
            return
        options = {"expected": job["tip"]}
        try:
            if merged is not None:
                sha = merged["mergeCommit"]["oid"]
                self.log(item, f"PR #{item['pr']} merged outside the runner", True)
            else:
                sha = self.github.merge(self.github_repo(item), item["pr"], **options)
        except BlockedPR as error:
            self.attention(item, "escalation", str(error))
            return
        run_records.owner_wait(self, item, job, close=True)
        job["phase"], job["sha"], job["pr"] = "merged", sha, item["pr"]
        self.save_job(job)
        self.log(item, f"merged: {sha}", True)
        item["attention"] = None
        if job["request"]["node_steps"] is not None:
            self.attention(item, "node-step", job["request"]["node_steps"])
            job["phase"] = "node-step"
            self.save_job(job)

    def deliver(self, item):
        job = self.jobs.get(item["id"])
        if item["state"] == "ready" and job and self.restartable(job, item):
            return
        run_records.owner_wait(self, item, job)
        if item["paused"]:
            return
        attention = item["attention"]
        if job and job["phase"] == "review-ready":
            if attention and attention["answer"] is not None:
                item["attention"] = attention = None
            if not attention and not item["paused"]:
                self.launch(item, job["brief"], review=True)
            return
        if item["paused"]:
            return
        if job and job["phase"] in (
            "cut-ready",
            "submitting",
            "submit-failed",
            "tickets",
        ):
            return
        if attention and attention["answer"] is not None:
            if not item["session"] or not item["session"]["id"] or not job:
                self.defer(item, "deferred: session unavailable")
            else:
                self.launch(item, attention["answer"], resume=True)
            return
        if attention and attention["kind"] == "merge":
            if job and not self.cli_review(item, job):
                return
            if not job or not item["pr"]:
                self.defer(item, "deferred: PR metadata unavailable")
                return
            if not self.merge_ready(item, job):
                return
            if not attention["approved"]:
                if item["stop_before_merge"] and "review" not in attention:
                    return
                review_id = self.github.owner_approval(
                    self.github_repo(item), item["pr"], job["tip"]
                )
                if review_id is None:
                    return
                attention["approved"] = True
                job["github_approval_tip"] = job["tip"]
                self.save_job(job)
                self.log(
                    item,
                    f"Approved merge for {item['id']} by GitHub review {review_id} "
                    f"from {OWNER_LOGIN} on {job['tip']}",
                    True,
                    actor="owner",
                )
            options = {"expected": job["tip"]}
            status, failing = self.github.checks(
                self.github_repo(item), item["pr"], **options
            )
            if status == "merged":
                self.merge_ready(item, job)
                return
            run_records.ci_record(self, item, job, status, failing)
            self.log(item, "approval checks: " + status)
            if status == "red":
                self.attention(item, "escalation", "failing check: " + failing)
                return
            if status != "green":
                return
            self.merge(item, job)
        if job and job["phase"] == "merged" and item["session"]["id"]:
            self.launch(item, "merged as " + job["sha"], resume=True)

    def pr_checks(self, item, job):
        if job["phase"] != "pr" or item["paused"]:
            return
        if item["attention"] and item["attention"]["kind"] != "merge":
            return
        # Recover PR number if creation succeeded but saving state did not.
        if item["pr"] is None:
            item["pr"] = self.open_pr(self.github_repo(item), job["request"])
        if item["attention"]:
            self.merge_ready(item, job)
            return
        options = {"expected": job["tip"]}
        status, failing = self.github.checks(
            self.github_repo(item), item["pr"], **options
        )
        if status == "merged":
            self.merge_ready(item, job)
            return
        run_records.ci_record(self, item, job, status, failing)
        self.log(item, "checks: " + status)
        # The head read used for CI also carries live merge metadata. Reuse that
        # same observation instead of inserting another read before CI history.
        info = getattr(self.github, "check_info", None)
        if not self.merge_ready(item, job, info if isinstance(info, dict) else None):
            return
        if status == "red":
            self.attention(item, "escalation", "failing check: " + failing)
        elif status == "green":
            self.merge(item, job, ready=True)

    def start(self, item):
        reason = self.room(item)
        if reason:
            self.defer(item, reason)
            return
        if item.get("brief_id"):
            try:
                prompt = state.store(self.path).stored_brief(item["brief_id"])
                self.launch(item, prompt)
            except run_platform.Unavailable:
                self.defer(item, "deferred: platform run API unavailable")
            except Exception:
                self.slice_failure(item, "start")
            return
        if item["brief"] is None:
            self.attention(item, "escalation", "missing brief")
            return
        brief = Path(item["brief"])
        if not brief.is_absolute():
            brief = self.path.parent / brief
        try:
            with brief.open(encoding="utf-8", newline="") as stream:
                prompt = stream.read()
            lines = prompt.splitlines(keepends=True)
            if lines and lines[0].rstrip("\r\n") == "---":
                closing = next(
                    (
                        i
                        for i in range(1, len(lines))
                        if lines[i].rstrip("\r\n") == "---"
                    ),
                    None,
                )
                if closing is not None:
                    prompt = "".join(lines[closing + 1 :])
            self.launch(item, prompt)
        except run_platform.Unavailable:
            self.defer(item, "deferred: platform run API unavailable")
        except Exception:
            self.slice_failure(item, "start")

    def __init__(
        self,
        path,
        *,
        run_client=None,
        github=None,
        git=None,
        clock=now,
        runs=None,
        orders=None,
        repos=None,
    ):
        self.path = Path(path).expanduser().resolve()
        self.orders = orders or Collector()
        self._client = run_client
        self.github, self.git, self.clock = github or GitHub(), git or Git(), clock
        base = (
            Path(runs or os.environ.get("CPLANE_RUNS", "/srv/factory/runs"))
            .expanduser()
            .resolve()
        )
        self.runs = base / hashlib.sha256(str(self.path).encode()).hexdigest()[:20]
        self.notices = []
        self.repos = (
            Path(repos or os.environ.get("CPLANE_REPOS", "~/Code"))
            .expanduser()
            .resolve()
        )

    @property
    def client(self):
        if self._client is None:
            self._client = run_platform.Client()
        return self._client

    def open_pr(self, repo, request):
        if self.github.is_public(repo):
            deny.Check().request(request)
        return self.github.open(repo, request)

    def execution(self, item):
        policy = (
            state.store(self.path).slice_policy(item["id"])
            if state.postgres()
            else None
        )
        return (
            policy["level"]
            if policy
            else next(
                (
                    entry["event"].removeprefix("level: ")
                    for entry in reversed(item["log"])
                    if entry["event"].startswith("level: ")
                ),
                "standard",
            )
        )

    def eligibility_data(self, *, resources_only=False):
        return {
            **self.data,
            "_eligibility": {"jobs": self.jobs, "resources_only": resources_only},
        }

    def room(self, item):
        result = eligibility(item, self.eligibility_data(resources_only=True))
        if result["status"] == "resource busy":
            return (
                "deferred: "
                + result["reason"]
                + " ("
                + ", ".join(result.get("ids", []))
                + ")"
            )
        return None

    @staticmethod
    def restartable(job, item=None):
        # A planner reset retires even a resumable escalation. The existing log
        # carries the intent across cancellation retries without changing v1 state.
        if item and item["state"] == "ready":
            for log in reversed(item["log"]):
                if log["event"] == "started":
                    break
                if log["event"].startswith("restart requested: "):
                    target = log["event"].removeprefix("restart requested: ")
                    if any(target in (entry.get("run_id"), entry["request"]["request_id"])
                           for entry in job["requests"].values()):
                        return True
                    break
        entry = job["requests"][job.get("attention_run", job["active"])]
        record = entry.get("record") or {}
        return record.get("status") in (
            "failed",
            "escalated",
            "cancelled",
            "done",
        ) and not record.get("resumable")

    def request_id(self, item, job, purpose):
        # Hash the attempt with the slice identity, keeping IDs <=64 characters.
        # Jobs predating attempts keep their original identity for message retries.
        identity = item["id"]
        if "attempt" in job:
            identity += ":" + str(job["attempt"])
        return (
            "factory-"
            + hashlib.sha256(identity.encode()).hexdigest()[:24]
            + "-"
            + purpose
        )

    def new_request(
        self,
        item,
        job,
        purpose,
        role,
        goal,
        *,
        base=None,
        after=(),
        allowed_files=None,
        pinned_paths=(),
        check_command=None,
    ):
        if purpose not in job["requests"]:
            body = {
                "contract": 1,
                "request_id": self.request_id(item, job, purpose),
                "attribution": {"slice": item["id"][:120]},
                "repository": item["repo"],
                "base_commit": base or job["base"],
                "branch": job["branch"],
                "mode": "read" if role == "review" else "write",
                "role": role,
                "level": job["level"],
                "work": {
                    "goal": goal,
                    "allowed_files": platform_paths(allowed_files),
                    "pinned_paths": platform_paths(pinned_paths),
                    "check_command": check_command,
                },
                "assets": [],
                "after": list(after),
                "priority": 0,
            }
            context = []
            if role in ("cut", "review"):
                from .skills import ROOT

                name = "cut" if role == "cut" else "slice-review"
                context = run_records.context(
                    skill_files=[(name, ROOT / (name + ".md"))]
                )
            if role == "review":
                body["work"]["history"] = "full"
            job["requests"][purpose] = {
                "request": body,
                "run_id": None,
                "record": None,
                "turn": 0,
                "context": context,
            }
            self.save_job(job)
        return job["requests"][purpose]

    def send_request(self, job, entry):
        if entry["run_id"] is None:
            # Intent and exact body were saved by new_request, before this POST.
            entry["run_id"] = self.client.submit(entry["request"])
            self.save_job(job)
        return entry["run_id"]

    def session(self, item, job):
        entry = job["requests"][job["active"]]
        record = entry.get("record") or {}
        harness = (record.get("executor") or {}).get("harness", "codex")
        # v1's executor/session fields are legacy display metadata, never policy.
        item["session"] = {
            "tool": harness if harness in ("codex", "claude") else "codex",
            "id": entry["run_id"] or entry["request"]["request_id"],
            "folder": str(job["run"]),
        }

    def launch(self, item, prompt, resume=False, review=False):
        if item["paused"]:
            return False
        previous = self.jobs.get(item["id"])
        if resume:
            self.send_message(
                item,
                previous,
                prompt,
                "merged"
                if prompt.startswith("merged as ")
                else "answer-"
                + hashlib.sha256(
                    (item["attention"]["since"] + prompt).encode()
                ).hexdigest()[:20],
            )
            return True
        if review:
            self.launch_review(
                item, previous, record_only=item.get("flow", "cli") == "cli"
            )
            return True
        if previous:
            if not self.restartable(previous, item):
                entry = previous["requests"][
                    previous.get("attention_run", previous["active"])
                ]
                if (entry.get("record") or {}).get("resumable"):
                    self.send_message(
                        item,
                        previous,
                        prompt,
                        "start-" + str(entry["turn"] + 1),
                    )
                else:
                    self.session(item, previous)
                    item["state"] = "issued"
                return True
            # Queued successors and resumable predecessors belong to the old
            # attempt. Release them before requesting work on the same branch.
            self.abandon(previous)
            if any(
                not entry.get("cancelled") for entry in previous["requests"].values()
            ):
                self.defer(item, "deferred: previous attempt cancellation pending")
                return False
        if self.room(item):
            self.defer(item, self.room(item))
            return False
        branch = previous["branch"] if previous else "slice/" + item["id"].replace("/", "-")
        base = self.github.default_tip(item["repo"])
        if not re.fullmatch("[0-9a-f]{40}", base):
            raise state.StateError("Default branch tip unavailable")
        attempt = previous.get("attempt", 1) + 1 if previous else 1
        folder = self.runs / (
            hashlib.sha256(item["id"].encode()).hexdigest()[:24]
            + "-attempt-"
            + str(attempt)
        )
        folder.mkdir(mode=0o700, parents=True, exist_ok=True)
        job = {
            "id": item["id"],
            "attempt": attempt,
            "run": str(folder),
            "repository": item["repo"],
            "branch": branch,
            "base": base,
            "brief": prompt,
            "level": self.execution(item),
            "started_ns": max(
                time.time_ns(), previous["started_ns"] + 1 if previous else 0
            ),
            "requests": {},
            "active": "cut" if item.get("flow", "cli") == "tickets" else "slice",
            "phase": "running",
            "skills": cutter.skills_version(),
        }
        role = job["active"]
        goal = prompt + self.assignment(job, write=True)
        if role == "cut":
            from .skills import instructions

            goal = (
                instructions("cut")
                + goal
                + '\nCommit the failing tests. End with kind "handover" and the fenced JSON plan.'
            )
        else:
            goal += (
                '\nFor this run, end with kind "handover" (superseding any brief final kind). Begin the body with a fenced JSON object '
                "with branch, title, body (PR description) and node_steps (text or null). "
                "Factory opens the PR, checks CI, obtains required approval, and merges it. "
                'A message "merged as <sha>" asks you for your final handover.'
            )
        entry = self.new_request(
            item, job, role, role, goal, allowed_files=item.get("allowed_files")
        )
        self.jobs[item["id"]] = job
        item["state"], item["attention"] = "issued", None
        item["pr"] = None
        item.pop("final", None)
        self.session(item, job)
        self.send_request(job, entry)
        self.session(item, job)
        self.log(item, "started", True)
        return True

    @staticmethod
    def assignment(job, *, write=False):
        assignment = (
            f"\n\nRunner assignment: use branch {job['branch']}. "
            "This assigned branch overrides any branch named in the brief. "
            f"The pinned base commit is {job['base']}."
        )
        if write:
            assignment += (
                " Commit all of your work on this branch, in one or more commits with plain messages, before you end. "
                "Do not push and do not open a PR: the platform delivers your commits, and Factory opens the PR."
            )
        return assignment

    @staticmethod
    def ticket_assignment():
        return (
            "\n\nTicket assignment: Before you finish, review your diff against this ticket "
            "and its check, and correct anything that does not match. Do not commit or push; "
            "the platform runs the check, commits and pushes."
        )

    def send_message(self, item, job, text, purpose):
        if item["paused"]:
            return
        target = job.get("attention_run", job["active"])
        entry = job["requests"][target]
        message_id = self.request_id(item, job, purpose)
        if entry.get("last_message_id") == message_id:
            item["attention"], item["state"] = None, "issued"
            return
        if not (entry.get("record") or {}).get("resumable") and not entry.get(
            "message"
        ):
            self.defer(item, "deferred: platform run is not resumable")
            return
        if not entry.get("message"):
            entry.pop("completion_final", None)
            entry["post_merge"] = bool(job.get("sha"))
            entry["turn"] += 1
            entry["message"] = {"contract": 1, "message_id": message_id, "text": text}
            if purpose.startswith("answer-"):
                entry["message_answer"] = {
                    "at": self.instant.isoformat(),
                    "question": item["attention"]["body"],
                    "answer": text,
                }
            job["phase"] = "pr" if target == job.get("pr_review") else "running"
            if target == job.get("pr_review"):
                job["review_requested_at"] = self.instant.timestamp()
            self.save_job(job)
        self.retry_message(item, job, entry)

    def retry_message(self, item, job, entry):
        if item["paused"]:
            return
        result = self.client.message(entry["run_id"], entry["message"])
        entry["record"] = result
        entry["last_message_id"] = entry.pop("message")["message_id"]
        if "message_answer" in entry:
            job.setdefault("answers", []).append(entry.pop("message_answer"))
        self.save_job(job)
        attention_entry = job["requests"].get(job.get("attention_run"))
        if (
            entry is job["requests"][job["active"]] or entry is attention_entry
        ) and not entry.get("completion_final"):
            run_records.owner_wait(self, item, close=True)
            item["attention"], item["state"] = None, "issued"
            job.pop("attention_run", None)
            self.save_job(job)
            self.log(item, "resumed", True)

    def collect(self, item, job):
        # Poll all known runs, including queued successors and record-only reviews.
        for entry in job["requests"].values():
            restarting = item["state"] == "ready" and self.restartable(job, item)
            if entry["run_id"] is None:
                if item["paused"] or restarting:
                    continue
                self.send_request(job, entry)
            entry["record"] = self.client.get(entry["run_id"])
            # Observe a finished turn before retrying a saved message: a reset
            # must be able to retire an attempt whose continuation failed too.
            restarting = item["state"] == "ready" and self.restartable(job, item)
            if entry.get("message") and not restarting and not item["paused"]:
                self.retry_message(item, job, entry)
                entry["record"] = self.client.get(entry["run_id"])
            if (
                entry["record"].get("status") == "waiting"
                and entry["record"].get("status_reason") == "usage_limit"
            ):
                self.defer(
                    item,
                    "waiting: usage_limit until "
                    + str(entry["record"].get("resume_at")),
                )
            if state.postgres() and entry["record"].get("status") not in (
                "queued",
                "running",
            ):
                run_records.platform_record(state.store(self.path), item, job, entry)
        self.save_job(job)
        if item["state"] == "ready" and self.restartable(job, item):
            if not item["paused"]:
                self.abandon(job)
                item["attention"] = None
                job["phase"] = "restart-ready"
                self.save_job(job)
            return
        self.apply_record(item, job)

    def apply_record(self, item, job):
        self.session(item, job)
        if item["state"] == "ready":
            item["state"] = "issued"
        if item["paused"]:
            return
        entry = job["requests"][job["active"]]
        record = entry.get("record") or {}
        status = record.get("status")
        if status == "waiting" and record.get("status_reason") == "usage_limit":
            self.defer(
                item, "waiting: usage_limit until " + str(record.get("resume_at"))
            )
            return
        if status in ("queued", "running"):
            return
        marker = "collected turn: " + job["active"] + ":" + str(entry["turn"])
        if "attempt" in job:
            marker = "attempt " + str(job["attempt"]) + ": " + marker
        if any(log["event"] == marker for log in item["log"]):
            return
        job["final"] = (
            entry.get("completion_final")
            if record.get("status") == "done" and entry.get("completion_final")
            else run_records.run_final(record)
        )
        job["phase"] = "ended"
        job["ended_at"] = self.instant.timestamp()
        self.save_job(job)
        final = job.get("final")
        if (
            isinstance(final, dict)
            and isinstance(final.get("body"), str)
            and isinstance(final.get("kind"), str)
        ):
            item["final"] = {
                **final,
                "body": cut(final["body"], ATTENTION_LIMIT),
                "at": self.at,
            }
        if status in ("failed", "cancelled"):
            self.attention(
                item,
                "escalation",
                "Platform run " + status + ": " + str(record.get("status_reason")),
            )
        elif status in ("question", "escalated"):
            final = run_records.run_final(record) or {}
            self.attention(
                item,
                "question" if status == "question" else "escalation",
                final.get("body") or str(record.get("status_reason")),
            )
        else:
            self.apply_final(item, job)
        self.log(item, marker)
        if (
            item["state"] == "in review"
            and (job.get("final") or {}).get("kind") == "handover"
            and state.postgres()
        ):
            state.store(self.path).chat_handover(item, job["final"]["body"])
        if job["phase"] == "ended":
            job["phase"] = "collected"
        self.save_job(job)

    def apply_final(self, item, job):
        entry = job["requests"][job["active"]]
        record = entry["record"]
        final = job.get("final")
        if not isinstance(final, dict) or not isinstance(final.get("body"), str):
            raise state.StateError("Platform run ended without a final message")
        item["final"] = {
            **final,
            "body": cut(final["body"], ATTENTION_LIMIT),
            "at": self.at,
        }
        if record.get("commits") and job["active"] != "slice":
            job["tip"] = record["commits"][-1]
        if not job.get("sha") and record["status"] == "waiting":
            needs_completion = False
            if job["active"] == "cut":
                cutter.parse_plan(final["body"])
                cutter.sections(job["brief"], item["id"])
                needs_completion = True
            elif job["active"].startswith("review-"):
                reviewer.validate(reviewer.parse(final["body"]))
                needs_completion = True
            elif job["active"] == "slice" and final["body"].lstrip().startswith("```"):
                self.pr_request(final["body"], job["branch"])
                needs_completion = True
            if needs_completion:
                self.complete_entry(item, job, entry)
                return
        if job.get("sha") and not entry.get("post_merge"):
            self.restore_merge(item, job)
            job["phase"] = (
                "node-step" if job["request"]["node_steps"] is not None else "merged"
            )
        elif entry.get("post_merge"):
            if final["kind"] == "handover":
                self.finished(item, final["body"])
            else:
                steps = final["body"].strip()
                if steps.startswith(("```", "{")):
                    request = (
                        reviewer.parse(steps)
                        if steps.startswith("```")
                        else json.loads(steps)
                    )
                    steps = request.get("node_steps")
                    if steps is not None and not isinstance(steps, str):
                        raise state.StateError("invalid post-merge node_steps")
                if steps:
                    job["phase"] = "node-step"
                    self.attention(item, "node-step", steps)
                else:
                    self.finished(item, final["body"])
        elif job["active"].startswith("review-"):
            self.apply_review(item, job, final["body"])
        elif "ticket-" in job["active"]:
            if (
                record["status"] == "waiting"
                and record.get("status_reason") == "client_step"
            ):
                self.attention(item, "node-step", final["body"])
            else:
                job["phase"] = "tickets"
        elif job["active"] == "cut":
            plan = cutter.parse_plan(final["body"])
            cutter.sections(job["brief"], item["id"])
            if not job.get("task_file"):
                job["tip"] = self.github.branch_tip(item["repo"], job["branch"])
                job["task_file"] = cutter.build_task_file(
                    item["id"],
                    item["repo"],
                    job["branch"],
                    job["tip"],
                    plan,
                    job["brief"],
                )
            job["phase"] = "cut-ready"
            self.save_job(job)
            self.submit_tickets(item, job)
        elif final["body"].lstrip().startswith("```"):
            request = self.pr_request(final["body"], job["branch"])
            self.review_head(item, job, self.github.branch_tip(item["repo"], job["branch"]))
            if job["tip"] == job["base"]:
                self.attention(item, "question", final["body"])
                return
            job["request"], job["phase"] = request, "pr"
            self.save_job(job)
            item["pr"] = self.open_pr(item["repo"], request)
            self.log(item, f"opened PR: {item['pr']}", True)
            self.cli_review(item, job)
        elif final["kind"] == "handover":
            self.finished(item, final["body"])
        else:
            self.attention(item, "node-step", final["body"])

    @staticmethod
    def pr_request(body, branch):
        request = reviewer.parse(body)
        if (
            not isinstance(request, dict)
            or set(request) != {"branch", "title", "body", "node_steps"}
            or any(
                not isinstance(request[k], str) or not request[k]
                for k in ("branch", "title", "body")
            )
            or request["node_steps"] is not None
            and not isinstance(request["node_steps"], str)
        ):
            raise state.StateError(
                "invalid PR request: expected branch, title, body, node_steps"
            )
        if request["branch"] != branch:
            raise state.StateError("PR branch differs from assigned branch")
        return request

    def complete_entry(self, item, job, entry):
        if entry.get("completion_final"):
            raise state.StateError(
                "Platform run did not finish after result acknowledgment"
            )
        entry["completion_final"] = run_records.run_final(entry["record"])
        entry["turn"] += 1
        purpose = (
            "complete-"
            + next(key for key, value in job["requests"].items() if value is entry)
            + "-"
            + str(entry["turn"])
        )
        entry["message"] = {
            "contract": 1,
            "message_id": self.request_id(item, job, purpose),
            "text": (
                'Factory recorded your result. End with kind "handover" now, without changing files. '
                "No further work is requested in this turn."
            ),
        }
        if entry is job["requests"][job["active"]]:
            job["phase"] = "running"
        self.save_job(job)
        self.retry_message(item, job, entry)

    def restore_merge(self, item, job):
        item["pr"] = job.get("pr", item["pr"])
        if not any(e["event"] == "merged: " + job["sha"] for e in item["log"]):
            self.log(item, "merged: " + job["sha"], True)
            item["attention"] = None
            if job["request"]["node_steps"] is not None:
                self.attention(item, "node-step", job["request"]["node_steps"])
            job["phase"] = (
                "node-step" if job["request"]["node_steps"] is not None else "merged"
            )

    def finished(self, item, body):
        item["state"], item["attention"] = "in review", None
        self.log(item, "finished", True)

    def launch_review(self, item, job, *, record_only=False):
        if item["paused"]:
            return
        number = (
            (job.get("review_number", 0) + 1)
            if record_only
            else (2 if job.get("repair") else 1)
        )
        job["review_number"] = number
        job["review_tip"] = job["tip"]
        purpose = "review-" + str(number)
        from .skills import instructions

        goal = instructions("slice-review") + job["brief"]
        if job.get("answers"):
            goal += "\n\nAnswers given during the slice (they replace the brief where they differ):"
            for answer in job["answers"]:
                goal += f"\n\nQuestion: {answer['question']}\nAnswer: {answer['answer']}"
        goal += self.assignment(job)
        # The skill names waiting; either final kind carries the same verdict.
        goal += '\nFor this run, end with kind "handover" (superseding the skill final kind). Return the verdict JSON first; prose may follow.'
        previous = job["requests"][job["active"]]["request"]["request_id"]
        after = (
            [job["ticket_purposes"][-1]] if job.get("ticket_purposes") else [previous]
        )
        if record_only:
            job["pr_review"] = purpose
        else:
            job["active"], job["phase"] = purpose, "running"
        entry = self.new_request(
            item, job, purpose, "review", goal, base=job["tip"], after=after
        )
        self.save_job(job)
        self.send_request(job, entry)

    def review_head(self, item, job, tip):
        """Retire a PR review when slice work moves, retaining its original run."""
        purpose = job.get("pr_review")
        if tip != job.get("tip") and isinstance(purpose, str):
            entry = job["requests"][purpose]
            # Use the existing log and request ledger for supersession history;
            # the review's request base remains the commit it actually reviewed.
            reviewed = job.get("review_tip", entry["request"]["base_commit"])
            event = f"review: superseded {purpose} on {reviewed} by {tip}"
            if not any(log["event"] == event for log in item["log"]):
                self.log(item, event)
            entry["cancel_pending"] = True
            self.cancel_entry(job, entry)
            self.clear_review_attention(item, job)
            for key in ("pr_review", "review_verdict", "review_findings",
                        "review_requested_at", "review_ended_at"):
                job.pop(key, None)
        job["tip"] = tip

    def clear_review_attention(self, item, job):
        if job.get("attention_run") == job.get("pr_review") and "attention_run" in job:
            run_records.owner_wait(self, item, close=True)
            item["attention"] = None
            if item["state"] == "escalated":
                item["state"] = "issued"
            job.pop("attention_run", None)

    def cli_review(self, item, job):
        if item["paused"]:
            return False
        # Legacy blocking ticket reviews may finish through their saved path.
        # A completed legacy review is not converted into another review on load.
        if (
            item.get("flow", "cli") == "tickets"
            and not job.get("pr_review")
            and (job.get("review_verdict") or job["active"].startswith("review-"))
        ):
            return True
        self.review_head(item, job, self.github.branch_tip(item["repo"], job["branch"]))
        if job.get("review_verdict"):
            return True
        requested = job.setdefault("review_requested_at", self.instant.timestamp())
        timeout = max(1, int(os.environ.get("CPLANE_REVIEW_TIMEOUT_SECONDS", "1200")))
        if "pr_review" not in job:
            self.save_job(job)
            self.launch_review(item, job, record_only=True)
            return False
        entry = job["requests"][job["pr_review"]]
        record = entry.get("record") or {}
        answer = None
        status = record.get("status")
        expired = self.instant.timestamp() - requested >= timeout
        if status in ("question", "escalated") and not expired:
            marker = (entry["turn"], status, record.get("updated_at"))
            if entry.get("attention_marker") != list(marker):
                entry["attention_marker"] = list(marker)
                body = (run_records.run_final(record) or {}).get("body")
                job["attention_run"] = job["pr_review"]
                self.attention(
                    item,
                    "question" if status == "question" else "escalation",
                    body or str(record.get("status_reason")),
                )
                self.save_job(job)
            if status in ("question", "escalated") and record.get("resumable"):
                return False
        if record.get("status") in ("queued", "running") or not record:
            if not expired:
                return False
        elif (
            record.get("status") == "waiting"
            and record.get("status_reason") == "usage_limit"
            and not expired
        ):
            return False
        if not expired:
            try:
                final = run_records.run_final(record) or {}
                if record.get("status") in ("done", "waiting") and final.get(
                    "kind"
                ) in ("handover", "waiting"):
                    answer = reviewer.parse(final["body"])
                    reviewer.validate(answer)
            except (ValueError, KeyError, state.StateError):
                answer = None
        if expired:
            entry["cancel_pending"] = True
            self.cancel_entry(job, entry)
        if (
            record.get("status") in ("question", "escalated")
            or record.get("status") == "waiting"
            and record.get("status_reason") == "client_step"
        ):
            entry["cancel_pending"] = True
            self.cancel_entry(job, entry)
        verdict = answer["verdict"] if answer else "missing"
        findings = (
            {k: answer[k] for k in ("title", "body")}
            if answer and verdict == "pass"
            else answer["tickets"]
            if answer
            else None
        )
        self.clear_review_attention(item, job)
        job.update(
            review_verdict=verdict,
            review_findings=findings,
            review_ended_at=self.instant.timestamp(),
        )
        self.save_job(job)
        self.log(item, "review: " + verdict)
        run_records.review_outcome(self, job, item=item)
        return True

    def apply_review(self, item, job, body):
        answer = reviewer.parse(body)
        run_records.review_record(self, job, answer)
        if answer["verdict"] == "pass":
            job["request"] = {
                "branch": job["branch"],
                "title": answer["title"],
                "body": answer["body"],
                "node_steps": None,
            }
            job["phase"] = "pr"
            self.save_job(job)
            item["pr"] = self.open_pr(item["repo"], job["request"])
            self.log(item, f"opened PR: {item['pr']}", True)
        elif job.get("repair"):
            self.attention(
                item,
                "escalation",
                "slice review still needs fixes after repair:\n" + json.dumps(answer),
            )
        else:
            job["repair"] = True
            job["task_file"] = cutter.build_task_file(
                item["id"] + "/repair",
                item["repo"],
                job["branch"],
                job["tip"],
                {k: answer[k] for k in ("tickets", "test_files")},
                job["brief"],
            )
            job["phase"] = "cut-ready"
            self.save_job(job)
            self.submit_tickets(item, job)

    def submit_tickets(self, item, job):
        if item["paused"]:
            return
        previous = job["requests"][job["active"]]["request"]["request_id"]
        purposes = []
        for task in job["task_file"]["tasks"]:
            platform_paths(task["allowed_files"])
            platform_paths(task["pinned_paths"])
        for task in job["task_file"]["tasks"]:
            purpose = (
                ("repair-" if job.get("repair") else "")
                + "ticket-"
                + str(task["position"])
            )
            entry = self.new_request(
                item,
                job,
                purpose,
                "ticket",
                task["goal"] + self.ticket_assignment(),
                base=job["task_file"]["base_commit"],
                after=[previous],
                allowed_files=task["allowed_files"],
                pinned_paths=task["pinned_paths"],
                check_command=task["check_command"],
            )
            self.send_request(job, entry)
            previous = entry["request"]["request_id"]
            purposes.append(previous)
        job["ticket_purposes"], job["phase"] = purposes, "tickets"
        self.save_job(job)
        self.log(item, f"Submitted {len(purposes)} tickets", True)

    def follow_tickets(self, item, job, tickets=None):
        if item["paused"]:
            return
        entries = [
            entry
            for entry in job["requests"].values()
            if entry["request"]["request_id"] in job["ticket_purposes"]
        ]
        for entry in entries:
            record = entry.get("record") or {}
            status = record.get("status")
            if status in ("question", "escalated", "failed", "cancelled") or (
                status == "waiting" and record.get("status_reason") == "client_step"
            ):
                job["active"] = next(
                    k for k, v in job["requests"].items() if v is entry
                )
                job["phase"] = "running"
                self.save_job(job)
                self.apply_record(item, job)
                return
            if status == "waiting" and record.get("status_reason") == "usage_limit":
                self.defer(
                    item, "waiting: usage_limit until " + str(record.get("resume_at"))
                )
        if entries and all(
            (entry.get("record") or {}).get("status") == "done" for entry in entries
        ):
            job["tip"] = self.github.branch_tip(item["repo"], job["branch"])
            if job.get("repair"):
                job["phase"] = "review-ready"
                self.save_job(job)
                return
            job["request"] = {
                "branch": job["branch"], "title": item["title"],
                "body": "\n\n".join(
                    f"- {task['title']}\n  Check: {task['check_command']}"
                    for task in job["task_file"]["tasks"]
                ),
                "node_steps": None,
            }
            job["phase"] = "pr"
            self.save_job(job)
            item["pr"] = self.open_pr(item["repo"], job["request"])
            self.log(item, f"opened PR: {item['pr']}", True)

    def cancel_entry(self, job, entry):
        if entry.get("cancelled"):
            return
        if entry["run_id"] is None:
            # Lookup avoids creating any new work for an abandoned slice.
            entry["run_id"] = self.client.find(entry["request"]["request_id"])
            if entry["run_id"] is None:
                entry["cancelled"] = True
                self.save_job(job)
                return
        record = self.client.get(entry["run_id"])
        if record.get("status") in (
            "failed",
            "escalated",
            "cancelled",
            "done",
        ) and not record.get("resumable"):
            entry["cancelled"] = True
        else:
            try:
                record = self.client.cancel(entry["run_id"])
                entry["cancelled"] = (
                    record.get("status") == "cancelled"
                    or not record.get("resumable")
                    and record.get("status") not in ("queued", "running")
                )
            except run_platform.NotResumable:
                entry["cancel_pending"] = True
        entry["record"] = record
        if entry.get("cancelled"):
            entry.pop("cancel_pending", None)
        self.save_job(job)

    def abandon(self, job):
        for entry in job["requests"].values():
            self.cancel_entry(job, entry)

    def run(self):
        self._run_pass()
        export_bot(self.path)

    def _run_pass(self):
        with state.locked(self.path):
            self.git.pull(self.path)
            orders_changed = self.orders.collect(self)
            pipeline_order = []
            self.instant = self.clock()
            self.at = self.instant.isoformat()
            if state.postgres():
                try:
                    pipeline_order = state.store(self.path).pipeline_step(self.at)
                except Exception:
                    print("pipeline step failed", file=sys.stderr)
            self.data = state.load(self.path)
            if state.postgres():
                state.store(self.path).route_chat_events()
                self.data = state.load(self.path)
            state_before = json.dumps(
                self.data, ensure_ascii=False, separators=(",", ":")
            )
            self.notices = []
            self.jobs = {}
            for path in sorted(self.runs.glob("*/job.json")):
                job = json.loads(path.read_text())
                if "requests" not in job or job.get("record_only"):
                    continue
                previous = self.jobs.get(job["id"])
                if previous is None or previous["started_ns"] < job["started_ns"]:
                    self.jobs[job["id"]] = job
            if state.postgres():
                from . import eval_execution

                self.evals = eval_execution.Context(self)
                self.evals.collect(state.store(self.path))
            read_failures, read_successes, login_failures, login_successes = (
                set(),
                set(),
                set(),
                set(),
            )
            for item in self.data["slices"]:
                job = self.jobs.get(item["id"])
                if not job:
                    continue
                if item["state"] == "in review":
                    continue
                if item["state"] in ("accepted", "dropped"):
                    try:
                        self.abandon(job)
                    except Exception as error:  # noqa: BLE001
                        print(
                            f"cplane: abandon failed {item['id']}: {type(error).__name__}",
                            file=sys.stderr,
                        )
                    continue
                read_start = (
                    self.github.successful_reads
                    if isinstance(self.github, GitHub)
                    else 0
                )
                login_start = fence.github_logins.get()
                fence.github_calls.set(0)
                try:
                    if job.get("sha") and not (
                        item["state"] == "ready" and self.restartable(job, item)
                    ):
                        self.restore_merge(item, job)
                    self.collect(item, job)
                    if item["paused"] or (
                        item["state"] == "ready" and self.restartable(job, item)
                    ):
                        continue
                    if job["phase"] == "cut-ready":
                        self.submit_tickets(item, job)
                    if job["phase"] == "tickets":
                        self.follow_tickets(item, job)
                    if job["phase"] == "pr":
                        self.cli_review(item, job)
                        self.pr_checks(item, job)
                    for entry in job["requests"].values():
                        if entry.get("cancel_pending"):
                            self.cancel_entry(job, entry)
                except run_platform.Unavailable:
                    self.defer(item, "deferred: platform run API unavailable")
                except GitHubReadError:
                    read_failures.add(item["id"])
                except github_app.GitHubAppTransientError:
                    read_failures.add(item["id"])
                    login_failures.add(item["id"])
                except Exception:
                    self.slice_failure(item, "collect/deliver")
                finally:
                    if fence.github_logins.get() > login_start:
                        login_successes.add(item["id"])
                    if (
                        isinstance(self.github, GitHub)
                        and self.github.successful_reads > read_start
                    ):
                        read_successes.add(item["id"])
            from . import installation

            installation.process(self)
            for item in self.data["slices"]:
                read_start = (
                    self.github.successful_reads
                    if isinstance(self.github, GitHub)
                    else 0
                )
                login_start = fence.github_logins.get()
                if (
                    item["state"] not in ("accepted", "dropped", "in review")
                    and item["id"] not in read_failures
                ):
                    fence.github_calls.set(0)
                    try:
                        self.deliver(item)
                    except run_platform.Unavailable:
                        self.defer(item, "deferred: platform run API unavailable")
                    except github_app.GitHubAppTransientError:
                        if fence.github_calls.get():
                            self.slice_failure(item, "delivery")
                        else:
                            read_failures.add(item["id"])
                            login_failures.add(item["id"])
                    except GitHubReadError:
                        read_failures.add(item["id"])
                    except Exception:
                        self.slice_failure(item, "delivery")
                    finally:
                        if fence.github_logins.get() > login_start:
                            login_successes.add(item["id"])
                        if (
                            isinstance(self.github, GitHub)
                            and self.github.successful_reads > read_start
                        ):
                            read_successes.add(item["id"])
                job = self.jobs.get(item["id"])
                if job and item["id"] in read_failures:
                    job.setdefault("github_read_failure_since", self.at)
                    job["github_read_failure_kind"] = (
                        "login" if item["id"] in login_failures else "read"
                    )
                    job.pop("github_read_failures", None)
                    self.save_job(job)
                    self.log(item, "checks: pending")
                    if self.instant - datetime.fromisoformat(
                        job["github_read_failure_since"]
                    ) >= timedelta(seconds=1500):
                        self.attention(
                            item,
                            "escalation",
                            (
                                "GitHub App login"
                                if item["id"] in login_failures
                                else "GitHub reads"
                            )
                            + " failed continuously for 25 minutes",
                        )
                elif (
                    job
                    and (
                        item["id"] in read_successes
                        or (
                            item["id"] in login_successes
                            and job.get("github_read_failure_kind") == "login"
                        )
                    )
                    and (
                        job.get("github_read_failure_since")
                        or job.get("github_read_failures")
                    )
                ):
                    job.pop("github_read_failure_since", None)
                    job.pop("github_read_failure_kind", None)
                    job.pop("github_read_failures", None)
                    self.save_job(job)
            by_id = {s["id"]: s for s in self.data["slices"]}
            start_order = [by_id[key] for key in pipeline_order]
            start_order.extend(
                s for s in self.data["slices"] if s["id"] not in pipeline_order
            )
            if state.postgres():
                start_order = state.store(self.path).ordered_slices(start_order)
            for item in start_order:
                if (
                    item["state"] == "ready"
                    and not item["paused"]
                    and item["slot"]
                    and datetime.fromisoformat(item["slot"]) <= self.instant
                ):
                    result = eligibility(item, self.eligibility_data())
                    if result["status"] != "ready":
                        if result["status"] == "resource busy":
                            self.defer(
                                item,
                                "deferred: capacity unavailable"
                                if result["reason"] == "provider away"
                                else self.room(item),
                            )
                        continue
                    self.start(item)
            if state.postgres():
                self.evals.start(state.store(self.path))
            previous_notices = state.store(self.path).notices()
            seen = {
                (notice.get("id"), notice.get("since"), notice.get("reason"))
                for _, notice in previous_notices
                if notice.get("event") == "stuck"
            }
            for item in self.data["slices"]:
                records = [
                    entry.get("record") or {}
                    for entry in self.jobs.get(item["id"], {})
                    .get("requests", {})
                    .values()
                ]
                if any(
                    record.get("status") == "waiting"
                    and record.get("status_reason") == "usage_limit"
                    for record in records
                ):
                    continue
                stalled = stuck_since(item, self.instant)
                if stalled:
                    since, reason = stalled
                    key = (item["id"], since.isoformat(), reason)
                    if key not in seen:
                        self.notices.append(
                            {
                                "at": self.at,
                                "id": item["id"],
                                "event": "stuck",
                                "text": f"Stuck: {reason}",
                                "since": key[1],
                                "reason": reason,
                            }
                        )
            from . import digest

            local = self.instant.astimezone(digest.LOCAL)
            day = local.date()
            if (
                state.postgres()
                and hasattr(state.store(self.path), "run_record_list")
                and local >= digest.boundary(day)
                and not any(
                    n.get("event") == "digest" and n.get("date") == day.isoformat()
                    for _, n in previous_notices
                )
            ):
                end = digest.boundary(day)
                backend = state.store(self.path)
                records = backend.run_record_list() + [
                    r
                    for r in backend.run_record_export(
                        end.astimezone(UTC) - timedelta(hours=24)
                    )
                    if r["kind"] == "task"
                ]
                self.notices.append(
                    {
                        "at": self.at,
                        "id": "digest",
                        "event": "digest",
                        "date": day.isoformat(),
                        "text": digest.build(self.data, records, end),
                    }
                )
            changed = (
                json.dumps(self.data, ensure_ascii=False, separators=(",", ":"))
                != state_before
            )
            if changed or self.notices:
                if state.postgres():
                    backend = state.store(self.path)
                    backend.save(self.data)
                    backend.route_chat_events()
                    backend.append_notices(self.notices)
                else:
                    state.save(self.path, self.data, self.notices)
            if orders_changed or changed or self.notices:
                self.git.commit(self.path)
