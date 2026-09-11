"""Git and GitHub operations.

Two modes, per the design review:

- **local** (default): a disposable bare repository as the remote. Repeatable,
  credential-free, safe for tests. This is what the acceptance project uses
  unless told otherwise.
- **github**: uses the user's already-authenticated ``gh`` CLI. Workbench stores
  **no** GitHub token (ADR-035 §7).

``gh`` is ambient authority — it can reach every repository that account can
reach — which is why repository creation is approval-gated and visibility
defaults to private.

No automatic commits of anything outside the project worktree, and no broad
filesystem write path: Factory's own safety rules, adopted rather than
reinvented.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

from workbench.errors import ProtectedBranch, WorkbenchError

PROTECTED_BRANCHES = ("main", "master")


class GitError(WorkbenchError):
    pass


def run(args: list[str], cwd: Path, *, check: bool = True) -> str:
    """Run one git/gh command and return stdout.

    Never uses ``shell=True``: arguments come from record content, and a shell
    would make a branch name an injection point.
    """
    completed = subprocess.run(
        args, cwd=str(cwd), capture_output=True, text=True,
    )
    if check and completed.returncode != 0:
        raise GitError(
            f"{' '.join(args[:2])} failed in {cwd}: {completed.stderr.strip() or completed.stdout.strip()}"
        )
    return completed.stdout.strip()


def init_repo(path: Path, *, initial_branch: str = "main") -> None:
    path.mkdir(parents=True, exist_ok=True)
    run(["git", "init", "-q", "-b", initial_branch], cwd=path)
    run(["git", "config", "user.email", "workbench@factory.local"], cwd=path)
    run(["git", "config", "user.name", "Factory Workbench"], cwd=path)


def init_bare_remote(path: Path) -> str:
    """Create the disposable local bare remote used by default mode."""
    path.mkdir(parents=True, exist_ok=True)
    run(["git", "init", "-q", "--bare"], cwd=path)
    return str(path)


def add_remote(repo: Path, url: str, name: str = "origin") -> None:
    run(["git", "remote", "add", name, url], cwd=repo)


def current_branch(repo: Path) -> str:
    """The checked-out branch, including before the first commit.

    ``rev-parse --abbrev-ref HEAD`` is the usual incantation and it *fails* on a
    freshly initialised repository, because HEAD points at an unborn branch.
    ``branch --show-current`` answers correctly in both states, which matters
    here because project creation guards the branch before anything is committed.
    """
    return run(["git", "branch", "--show-current"], cwd=repo)


def has_commits(repo: Path) -> bool:
    return bool(run(["git", "rev-parse", "--verify", "-q", "HEAD"], cwd=repo, check=False))


def revision(repo: Path, ref: str = "HEAD") -> str:
    return run(["git", "rev-parse", ref], cwd=repo)


def create_branch(repo: Path, name: str) -> str:
    if name in PROTECTED_BRANCHES:
        raise ProtectedBranch(f"refusing to create a feature branch named {name!r}")
    run(["git", "checkout", "-q", "-b", name], cwd=repo)
    return name


def checkout(repo: Path, name: str) -> None:
    run(["git", "checkout", "-q", name], cwd=repo)


def guard_branch(repo: Path, *, actor_is_human: bool) -> str:
    """Refuse an agent write to a protected branch (acceptance step 11).

    The check is on the **branch**, not on intent. An agent that means well and
    happens to be on ``main`` is refused exactly like one that does not, which is
    the only version of this rule that is worth anything.
    """
    branch = current_branch(repo)
    if branch in PROTECTED_BRANCHES and not actor_is_human:
        raise ProtectedBranch(
            f"agents may not write to {branch!r}; create a feature branch first"
        )
    return branch


def commit_all(repo: Path, message: str, *, actor_is_human: bool = False) -> str:
    guard_branch(repo, actor_is_human=actor_is_human)
    run(["git", "add", "-A"], cwd=repo)
    status = run(["git", "status", "--porcelain"], cwd=repo)
    if not status and has_commits(repo):
        return revision(repo)
    run(["git", "commit", "-q", "-m", message], cwd=repo)
    return revision(repo)


def push(repo: Path, branch: str, *, remote: str = "origin", actor_is_human: bool = False) -> None:
    if branch in PROTECTED_BRANCHES and not actor_is_human:
        raise ProtectedBranch(f"agents may not push to {branch!r}")
    run(["git", "push", "-q", "-u", remote, branch], cwd=repo)


def merge(repo: Path, branch: str, *, into: str = "main", message: str | None = None) -> str:
    """Merge a reviewed branch. Callers must have checked an approval first."""
    checkout(repo, into)
    run(["git", "merge", "--no-ff", "-q", "-m",
         message or f"Merge: {branch}", branch], cwd=repo)
    return revision(repo)


def gh_available() -> bool:
    try:
        subprocess.run(["gh", "--version"], capture_output=True, check=True)
        return True
    except (FileNotFoundError, subprocess.CalledProcessError):
        return False


@dataclass(frozen=True)
class PullRequest:
    number: str
    url: str
    head_revision: str


def create_pull_request(repo: Path, *, branch: str, base: str, title: str, body: str) -> PullRequest:
    """Open a PR through the user's authenticated ``gh``. GitHub mode only."""
    if not gh_available():
        raise GitError("GitHub mode needs the `gh` CLI, which is not installed or not on PATH")
    url = run(["gh", "pr", "create", "--head", branch, "--base", base,
               "--title", title, "--body", body], cwd=repo)
    number = url.rstrip("/").rsplit("/", 1)[-1]
    return PullRequest(number=number, url=url, head_revision=revision(repo, branch))


def add_worktree(repo: Path, path: Path, branch: str) -> Path:
    """Create a disposable worktree on a new branch.

    **Why a worktree rather than a checkout.** A project holds its ``ops/``
    records in the same repository as its product. Switching the main checkout to
    a feature branch would take the live ``ops/`` directory with it — and a
    ``git reset --hard`` on that checkout deletes records written since the last
    commit. Both of those were observed during Phase 20.0 rather than reasoned
    about in advance.

    A worktree keeps product work on its own branch in its own directory while
    the main checkout stays on ``main`` with ``ops/`` intact. This is why the
    acceptance steps say "feature branch **or** disposable worktree".
    """
    if branch in PROTECTED_BRANCHES:
        raise ProtectedBranch(f"refusing to create a worktree on protected branch {branch!r}")
    path.parent.mkdir(parents=True, exist_ok=True)
    run(["git", "worktree", "add", "-q", "-b", branch, str(path)], cwd=repo)
    return path


def remove_worktree(repo: Path, path: Path) -> None:
    run(["git", "worktree", "remove", "--force", str(path)], cwd=repo, check=False)


def reset_hard(repo: Path, revision_id: str) -> None:
    """Reset a worktree to a revision.

    Only ever called on a **worktree**, never on a checkout holding ``ops/``.
    Hard-resetting live operational records destroys them, which is a lesson this
    phase learned the direct way.
    """
    run(["git", "reset", "--hard", "-q", revision_id], cwd=repo)
