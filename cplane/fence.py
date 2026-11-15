"""Host side of fenced delivery. Agent copies are data, never Git working directories."""

from contextvars import ContextVar
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import stat
import subprocess
import sys
import tempfile

from .state import StateError
from . import deny, github_app

ROOT_UID = 0
CLI_UID = CLI_GID = 21000
WORK_ROOT = Path("/srv/factory/work")
CLEAN_ROOT = Path("/srv/factory/clean")
LOGIN_ROOT = Path("/srv/factory/logins")
TOKEN = Path("/etc/factory/github-token")


def fence_command():
    if socket_enabled():
        return [sys.executable, "-m", "cplane.launcher"]
    return [os.environ.get("CPLANE_FENCE_COMMAND", "factory-cli")]


def launcher_usage():
    return os.environ.get("CPLANE_USAGE_SOURCE") == "launcher"


def socket_enabled():
    return os.environ.get("CPLANE_FENCE_COMMAND") == "socket"


def require_ownership_support():
    if os.geteuid() != 0 and not socket_enabled():
        raise StateError(
            "Non-root ownership changes require CPLANE_FENCE_COMMAND=socket"
        )


def own(path, role, *, recursive=False):
    require_ownership_support()
    if socket_enabled():
        from .launcher import manage

        manage("own", role, path)
        return
    if recursive:
        for directory, folders, files in os.walk(path, followlinks=False):
            for name in [*folders, *files]:
                os.chown(
                    Path(directory) / name, CLI_UID, CLI_GID, follow_symlinks=False
                )
    os.chown(path, CLI_UID, CLI_GID)


def remove(path, role):
    if socket_enabled():
        from .launcher import manage

        manage("remove", role, path)
    else:
        shutil.rmtree(path)


def host_environment():
    # A credential is added only for the one authenticated git/gh call.
    return {
        **{
            key: os.environ[key]
            for key in ("PATH", "LANG", "PYTHONPATH", "CPLANE_LAUNCHER_SOCKET")
            if key in os.environ
        },
        "HOME": "/nonexistent",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": "/dev/null",
        "GIT_TERMINAL_PROMPT": "0",
    }


github_calls = ContextVar("github_calls", default=0)
github_logins = ContextVar("github_logins", default=0)


def record_github_call():
    github_calls.set(github_calls.get() + 1)


def github_environment(repositories=None):
    env = host_environment()
    auth = os.environ.get("CPLANE_GITHUB_AUTH", "token")
    if auth == "app":
        from . import github_app

        if not repositories:
            raise StateError("GitHub App needs the repository of the call")
        env["GH_TOKEN"] = github_app.installation_token(repositories)
        github_logins.set(github_logins.get() + 1)
        return env
    if auth != "token":
        raise StateError("CPLANE_GITHUB_AUTH must be token or app")
    if os.environ.get("CPLANE_GITHUB_READ_ONLY") == "1":
        raise StateError(
            "CPLANE_GITHUB_READ_ONLY=1 requires CPLANE_GITHUB_AUTH=app; "
            "token mode cannot be narrowed"
        )
    fd = os.open(TOKEN, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd) as stream:
        info = os.fstat(stream.fileno())
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid != ROOT_UID
            or stat.S_IMODE(info.st_mode) != 0o600
        ):
            raise StateError(
                "GitHub token must be a root-owned regular file with mode 0600"
            )
        token = stream.read().strip()
    if not token or any(c.isspace() for c in token):
        raise StateError("GitHub token is missing or invalid")
    env["GH_TOKEN"] = token
    return env


def git_options():
    helper = "!" + shlex.join([sys.executable, "-m", "cplane.fence", "credential"])
    return [
        "-c",
        "core.hooksPath=/dev/null",
        "-c",
        "core.fsmonitor=false",
        "-c",
        "core.sshCommand=/bin/false",
        "-c",
        "credential.helper=",
        "-c",
        "credential.helper=" + helper,
        "-c",
        "protocol.ext.allow=never",
        "-c",
        "transfer.fsckObjects=true",
    ]


def trusted_directory(path):
    """Only root- or service-managed ancestors; never resolve agent-planted links."""
    for part in [*reversed(path.parents), path]:
        info = part.lstat()
        if not stat.S_ISDIR(info.st_mode):
            raise StateError("trusted directory contains a link or non-directory")
        # Sticky system temporary roots are needed by synthetic fixtures only.
        if part != path and info.st_mode & stat.S_ISVTX and info.st_uid == 0:
            continue
        if info.st_uid not in (0, os.geteuid()) or info.st_mode & 0o022:
            raise StateError(
                "trusted directory must be owned by root or the service and not writable by others"
            )
    return path


def snapshot_bundle(folder):
    """Snapshot offline export data without following agent-owned links."""
    # Snapshot an untrusted regular file before giving it to Git. No symlink,
    # FIFO, hardlink or later path replacement can redirect the host's read.
    directory = os.open(folder / "io", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        fd = os.open(
            "branch.bundle",
            os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
            dir_fd=directory,
        )
        with (
            os.fdopen(fd, "rb") as source,
            (folder / "export.bundle").open("wb") as target,
        ):
            info = os.fstat(source.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                raise StateError("bundle export must be a regular file with one link")
            shutil.copyfileobj(source, target)
    finally:
        os.close(directory)
    bundle = folder / "export.bundle"
    bundle.chmod(0o600)
    return bundle


class Fence:
    def __init__(self, *, clean_root=None):
        self.clean_root = Path(
            os.path.abspath(CLEAN_ROOT if clean_root is None else clean_root)
        )
        self.begin_pass()

    def begin_pass(self):
        self.visibility = {}

    def is_public(self, repo):
        if repo not in self.visibility:
            public = True
            try:
                env = github_environment([repo])
                record_github_call()
                result = subprocess.run(
                    ["gh", "api", f"repos/{repo}"],
                    cwd="/",
                    capture_output=True,
                    text=True,
                    env=env,
                    timeout=30,
                )
                if result.returncode == 0:
                    public = json.loads(result.stdout).get("private") is not True
            except github_app.GitHubAppTransientError:
                raise
            except Exception:
                # Authentication, network and malformed responses all fail closed.
                pass
            self.visibility[repo] = public
        return self.visibility[repo]

    def check_request(self, repo, request):
        if self.is_public(repo):
            deny.Check().request(request)

    def resume(self, previous, session):
        if not previous or not previous.get("fence"):
            raise StateError("fenced resume metadata unavailable; needs attention")
        if not session or not re.fullmatch(r"[A-Za-z0-9-]+", session):
            raise StateError("fenced resume session unavailable; needs attention")
        copy = Path(previous["repo"])
        if copy.parent != WORK_ROOT or copy.is_symlink() or not copy.is_dir():
            raise StateError("fenced resume copy unavailable; needs attention")
        tool = previous["tool"]
        if launcher_usage():
            found = True
        elif tool == "codex":
            found = any(
                (
                    path.name.endswith("-" + session + ".jsonl")
                    or path.name == session + ".jsonl"
                )
                and path.is_file()
                and not path.is_symlink()
                for path in (LOGIN_ROOT / "codex/sessions").rglob("*.jsonl")
            )
        else:
            path = LOGIN_ROOT / "claude/projects/-work" / (session + ".jsonl")
            found = path.is_file() and not path.is_symlink()
        if not found:
            raise StateError("fenced resume cannot find its session; needs attention")
        return {
            key: previous[key]
            for key in ("repo", "repository", "branch", "base", "default")
        }

    def clean(self, repo):
        if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo) or any(
            part in (".", "..") for part in repo.split("/")
        ):
            raise StateError("invalid GitHub repository")
        trusted_directory(self.clean_root)
        owner, name = repo.split("/")
        parent = self.clean_root / owner
        parent.mkdir(mode=0o700, exist_ok=True)
        trusted_directory(parent)
        return parent / (name + ".git")

    def git(self, clean, *args, auth=False, allow_failure=False, index=None):
        # This is the only host Git entry point for delivery. Never accept a work copy.
        clean = Path(os.path.abspath(clean))
        if not clean.is_relative_to(self.clean_root) or clean == self.clean_root:
            raise StateError("host Git refused outside clean clones")
        trusted_directory(clean)
        repo = clean.parent.name + "/" + clean.name.removesuffix(".git")
        command = [
            "git",
            "-C",
            str(clean),
            *git_options(),
            "-c",
            "protocol.file.allow=always",
            *map(str, args),
        ]
        try:
            env = github_environment([repo]) if auth else host_environment()
            if index is not None:
                env["GIT_INDEX_FILE"] = str(index)
            if auth:
                record_github_call()
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="surrogateescape",
                env=env,
            )
        except OSError:
            raise StateError("fenced Git could not run") from None
        if result.returncode and not allow_failure:
            # Like the DB adapter, suppress diagnostics, which can echo credentials.
            raise StateError("fenced Git operation failed")
        return result

    def prepare(self, repo, branch, copy_id):
        clean = self.clean(repo)
        if not clean.exists():
            clean.mkdir(mode=0o700)
            self.git(clean, "init", "--bare", "--template=")
            self.git(clean, "remote", "add", "origin", f"https://github.com/{repo}.git")
        self.git(clean, "check-ref-format", "refs/heads/" + branch)
        self.git(
            clean,
            "fetch",
            "--prune",
            "origin",
            "+refs/heads/*:refs/remotes/origin/*",
            auth=True,
        )
        head = self.git(
            clean, "ls-remote", "--symref", "origin", "HEAD", auth=True
        ).stdout
        match = re.search(r"^ref: refs/heads/([^\s]+)\s+HEAD$", head, re.M)
        if not match:
            raise StateError("GitHub default branch unavailable")
        default = match[1]
        if branch == default:
            raise StateError("slice branch must not be the default branch")
        base = self.git(
            clean, "rev-parse", "--verify", f"refs/remotes/origin/{default}^{{commit}}"
        ).stdout.strip()
        self.git(clean, "update-ref", f"refs/heads/{branch}", base)
        trusted_directory(WORK_ROOT)
        copy = WORK_ROOT / copy_id
        if copy.exists() or copy.is_symlink():
            raise StateError("work copy already exists")
        # All Git executes in the clean clone. Destination has no hooks, templates,
        # global config, hardlinks, or credentialed URL, and is not yet agent-owned.
        self.git(
            clean,
            "clone",
            "--no-hardlinks",
            "--template=",
            "--single-branch",
            "--branch",
            branch,
            "--config",
            "core.hooksPath=/dev/null",
            "--config",
            "user.name=Factory",
            "--config",
            "user.email=factory@localhost",
            str(clean),
            str(copy),
        )
        copy.chmod(0o700)
        own(copy, "work", recursive=True)
        return {
            "repo": str(copy),
            "repository": repo,
            "branch": branch,
            "base": base,
            "default": default,
        }

    def prepare_eval(self, repo, base, copy_id):
        """Fresh detached copy from a fetched clean clone; no slice ref is touched."""
        if not re.fullmatch(r"[0-9a-fA-F]{40}", base):
            raise StateError("invalid eval base commit")
        if not re.fullmatch(r"[a-f0-9]{32}", copy_id):
            raise StateError("invalid eval copy id")
        clean = self.clean(repo)
        if not clean.exists():
            clean.mkdir(mode=0o700)
            self.git(clean, "init", "--bare", "--template=")
            self.git(clean, "remote", "add", "origin", f"https://github.com/{repo}.git")
        self.git(
            clean,
            "fetch",
            "--prune",
            "origin",
            "+refs/heads/*:refs/remotes/origin/*",
            auth=True,
        )
        base = self.git(
            clean, "rev-parse", "--verify", base + "^{commit}"
        ).stdout.strip()
        trusted_directory(WORK_ROOT)
        copy = WORK_ROOT / copy_id
        if copy.exists() or copy.is_symlink():
            raise StateError("work copy already exists")
        branch = "factory-eval-" + copy_id
        try:
            self.git(clean, "update-ref", "refs/heads/" + branch, base)
            self.git(
                clean,
                "clone",
                "--no-hardlinks",
                "--template=",
                "--single-branch",
                "--branch",
                branch,
                "--config",
                "core.hooksPath=/dev/null",
                str(clean),
                str(copy),
            )
            # Still trusted: detach before handing ownership to the CLI.
            (copy / ".git/HEAD").write_text(base + "\n")
            # The non-root runner reads this copy as data through group 21000.
            # Clone inherits the service's restrictive umask, so grant read and
            # directory traversal before transfer, without following links.
            for directory, folders, files in os.walk(copy, followlinks=False):
                Path(directory).chmod(0o750)
                for name in files:
                    path = Path(directory) / name
                    if not path.is_symlink():
                        path.chmod(stat.S_IMODE(path.stat().st_mode) | stat.S_IRGRP)
            own(copy, "work", recursive=True)
        except Exception:
            if copy.exists():
                remove(copy, "work")
            raise
        finally:
            self.git(clean, "update-ref", "-d", "refs/heads/" + branch)
        return dict(repo=str(copy), repository=repo, base=base)

    def eval_diff(self, job):
        """Diff a data-only snapshot, never run host Git in the agent's repository.

        Ignore all agent Git metadata. Open files relative to directory FDs,
        refusing devices and hardlinks, and preserve symlinks as link text.
        A private index includes ignored and untracked files, including binaries.
        """
        clean = self.clean(job["repository"])
        with tempfile.TemporaryDirectory(
            dir=Path(job["run"]), prefix="snapshot-"
        ) as temporary:
            root = Path(temporary)
            tree = root / "tree"
            tree.mkdir(mode=0o700)
            fd = os.open(job["repo"], os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)

            def unreadable(error):
                raise error

            try:
                for directory, folders, files, directory_fd in os.fwalk(
                    ".", dir_fd=fd, follow_symlinks=False, onerror=unreadable
                ):
                    destination = tree / directory
                    folders[:] = [name for name in folders if name != ".git"]
                    for name in [*folders, *files]:
                        if name == ".git":
                            continue
                        info = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
                        target = destination / name
                        if stat.S_ISLNK(info.st_mode):
                            target.symlink_to(os.readlink(name, dir_fd=directory_fd))
                        elif stat.S_ISDIR(info.st_mode):
                            target.mkdir(mode=0o700)
                        elif stat.S_ISREG(info.st_mode):
                            source = os.open(
                                name,
                                os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                                dir_fd=directory_fd,
                            )
                            with os.fdopen(source, "rb") as stream:
                                actual = os.fstat(stream.fileno())
                                if (
                                    not stat.S_ISREG(actual.st_mode)
                                    or actual.st_nlink != 1
                                ):
                                    raise StateError("invalid eval output file")
                                with target.open("wb") as output:
                                    shutil.copyfileobj(stream, output)
                            target.chmod(
                                0o700 if actual.st_mode & stat.S_IXUSR else 0o600
                            )
                        else:
                            raise StateError("invalid eval output file")
            finally:
                os.close(fd)
            args = (
                "-c",
                "core.bare=false",
                "-c",
                "core.fileMode=true",
                "--work-tree=" + str(tree),
            )
            index = root / "index"
            self.git(clean, *args, "read-tree", job["base"], index=index)
            self.git(clean, *args, "add", "--all", "--force", "--", ".", index=index)
            return self.git(
                clean,
                *args,
                "diff",
                "--cached",
                "--binary",
                "--no-ext-diff",
                "--no-textconv",
                job["base"],
                "--",
                index=index,
            ).stdout

    def publish_eval_starts(self, repo, pr, base, count, bundle):
        """Validate the whole measured chain before publishing only ticket starts."""
        if not re.fullmatch(r"[0-9a-fA-F]{40}", base):
            raise StateError("invalid eval base commit")
        clean = self.clean(repo)
        if not clean.exists():
            clean.mkdir(mode=0o700)
            self.git(clean, "init", "--bare", "--template=")
            self.git(clean, "remote", "add", "origin", f"https://github.com/{repo}.git")
        self.git(
            clean,
            "fetch",
            "--prune",
            "origin",
            "+refs/heads/*:refs/remotes/origin/*",
            auth=True,
        )
        if self.git(
            clean, "cat-file", "-e", base + "^{commit}", allow_failure=True
        ).returncode:
            raise StateError("bundle refused: case base commit unavailable")
        with tempfile.TemporaryDirectory(dir=clean, prefix="eval-starts-") as temporary:
            # Snapshot a regular local input; Git never reads a replaceable source path.
            snapshot = Path(temporary) / "starts.bundle"
            fd = os.open(bundle, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
            with os.fdopen(fd, "rb") as source, snapshot.open("wb") as target:
                if not stat.S_ISREG(os.fstat(source.fileno()).st_mode):
                    raise StateError("bundle refused: expected a regular file")
                os.fchmod(target.fileno(), 0o600)
                shutil.copyfileobj(source, target)
            if self.git(
                clean, "bundle", "verify", snapshot, allow_failure=True
            ).returncode:
                raise StateError("bundle refused: verification failed")
            heads = self.git(
                clean, "bundle", "list-heads", snapshot
            ).stdout.splitlines()
            if len(heads) != 1:
                raise StateError("bundle refused: expected a single ref")
            _, ref = heads[0].split(" ", 1)
            if not ref.startswith("refs/heads/"):
                raise StateError("bundle refused: expected a head ref")
            imported = "refs/factory/eval-starts/" + Path(temporary).name
            try:
                self.git(
                    clean,
                    "fetch",
                    "--no-tags",
                    "--no-write-fetch-head",
                    snapshot,
                    f"+{ref}:{imported}",
                )
                tip = self.git(
                    clean, "rev-parse", "--verify", imported + "^{commit}"
                ).stdout.strip()
                commits = self.git(
                    clean, "rev-list", "--first-parent", "--reverse", f"{base}..{tip}"
                ).stdout.splitlines()
                if len(commits) != count + 1:
                    raise StateError(
                        f"bundle refused: expected tests and {count} ticket commits; got {len(commits)} commits"
                    )
                parent = base.lower()
                for index, commit in enumerate(commits):
                    expected = "tests" if index == 0 else f"ticket {index}"
                    parents = (
                        self.git(clean, "show", "-s", "--format=%P", commit)
                        .stdout.strip()
                        .split()
                    )
                    if parents != [parent]:
                        raise StateError(
                            f"bundle refused: {expected} must have only the expected parent (case base for tests)"
                        )
                    message = self.git(
                        clean, "show", "-s", "--format=%B", commit
                    ).stdout
                    if message.rstrip("\n") != expected:
                        raise StateError(
                            f"bundle refused: expected {expected} at position {index + 1}"
                        )
                    parent = commit
                paths = self.git(
                    clean,
                    "diff-tree",
                    "-r",
                    "--no-renames",
                    "--no-commit-id",
                    "--name-only",
                    "-z",
                    base,
                    commits[0],
                ).stdout.split("\0")
                paths = sorted(path for path in paths if path)
                starts = [
                    {
                        "start_commit": commit,
                        "start_branch": f"eval/pr{pr}-t{n}",
                        "pinned_paths": paths,
                    }
                    for n, commit in enumerate(commits[:-1], 1)
                ]
                public = self.is_public(repo)
                check = deny.Check() if public else None
                # Check every start, including intermediate additions later removed.
                for start in starts:
                    branch = start["start_branch"]
                    if check:
                        check.request({"branch": branch})
                        check.commits(
                            lambda *args: self.git(clean, *args),
                            base,
                            start["start_commit"],
                        )
                    head = self.git(
                        clean, "ls-remote", "--symref", "origin", "HEAD", auth=True
                    ).stdout
                    match = re.search(
                        r"^ref: refs/heads/([^\s]+)\s+HEAD$", head, re.MULTILINE
                    )
                    if not match:
                        raise StateError("GitHub default branch unavailable")
                    if branch == match[1]:
                        raise StateError(
                            "bundle refused: eval start branch is the default branch"
                        )
                    expected = "refs/heads/" + branch
                    remote = self.git(
                        clean, "ls-remote", "--refs", "origin", expected, auth=True
                    ).stdout.split()
                    if remote:
                        if remote[0] != start["start_commit"]:
                            raise StateError(
                                f"bundle refused: {branch} already exists at another commit"
                            )
                        continue
                    # Creation-only lease also refuses a concurrent conflicting branch.
                    self.git(
                        clean,
                        "push",
                        "--porcelain",
                        "--force-with-lease=" + expected + ":",
                        "origin",
                        f"{start['start_commit']}:{expected}",
                        auth=True,
                    )
                return starts
            finally:
                self.git(clean, "update-ref", "-d", imported)

    def publish(self, job, request):
        if request["branch"] != job["branch"] or job["branch"] == job["default"]:
            raise StateError(
                "bundle refused: branch is not the slice branch or is the default branch"
            )
        clean = self.clean(job["repository"])
        folder = trusted_directory(Path(job["run"]))
        result = subprocess.run(
            [
                *fence_command(),
                "bundle",
                "--repo",
                job["repo"],
                "--run",
                str(folder / "io"),
                "--branch",
                job["branch"],
            ],
            cwd=folder,
            capture_output=True,
            env=host_environment(),
        )
        if result.returncode:
            raise StateError("fenced bundle export failed")
        bundle = snapshot_bundle(folder)
        heads = self.git(clean, "bundle", "list-heads", bundle).stdout.splitlines()
        refs = dict(line.split(" ", 1)[::-1] for line in heads)
        expected = "refs/heads/" + job["branch"]
        if set(refs) != {"HEAD", expected} or refs["HEAD"] != refs[expected]:
            raise StateError("bundle refused: wrong branch or HEAD")
        self.git(clean, "bundle", "verify", bundle)
        imported = "refs/factory/import/" + folder.name
        self.git(
            clean,
            "fetch",
            "--no-tags",
            "--no-write-fetch-head",
            bundle,
            f"+{expected}:{imported}",
        )
        tip = self.git(
            clean, "rev-parse", "--verify", imported + "^{commit}"
        ).stdout.strip()
        if self.git(
            clean, "merge-base", "--is-ancestor", job["base"], tip, allow_failure=True
        ).returncode:
            raise StateError(
                "bundle refused: branch does not descend from the base commit"
            )
        # Recheck the current remote default before any push, too.
        head = self.git(
            clean, "ls-remote", "--symref", "origin", "HEAD", auth=True
        ).stdout
        match = re.search(r"^ref: refs/heads/([^\s]+)\s+HEAD$", head, re.M)
        if not match:
            raise StateError("GitHub default branch unavailable")
        if match[1] == job["branch"]:
            raise StateError("bundle refused: slice branch is now the default branch")
        if self.is_public(job["repository"]):
            check = deny.Check()
            check.request(request)
            check.commits(lambda *args: self.git(clean, *args), job["base"], tip)
        result = self.git(
            clean,
            "push",
            "--porcelain",
            "origin",
            f"{tip}:{expected}",
            auth=True,
            allow_failure=True,
        )
        if result.returncode:
            if re.search(
                r"\[rejected\].*(?:non-fast-forward|fetch first)", result.stdout
            ):
                raise StateError("branch was rewritten; merge main instead of rebasing")
            raise StateError("fenced Git operation failed")
        return tip


if __name__ == "__main__":
    # Git's helper protocol: the token is returned only to Git, never persisted.
    if sys.argv[1:] == ["credential", "get"]:
        print("username=x-access-token")
        print("password=" + os.environ["GH_TOKEN"])
