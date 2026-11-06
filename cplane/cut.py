"""Build queue task files from a validated plan and unmodified brief rules."""
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
from importlib.resources import files

from jsonschema import Draft202012Validator

from .state import StateError

SCHEMA = json.loads(files("schema").joinpath("plan.schema.json").read_text())
VALIDATOR = Draft202012Validator(SCHEMA)
TEST_LINE = "Failing tests are in the repository and must pass; do not edit test files."


def sections(brief, slice_id):
    lines = brief.splitlines(keepends=True)
    starts = []
    headings = []
    fence = None
    heading = re.compile(r"^##[ \t]+(Fixed decisions|Do not)", re.IGNORECASE)
    for i, line in enumerate(lines):
        marker = re.match(r"^ {0,3}(`{3,}|~{3,})(.*)$", line.rstrip("\r\n"))
        if fence:
            if marker and marker[1][0] == fence[0] and len(marker[1]) >= len(fence) and not marker[2].strip():
                fence = None
            continue
        if marker:
            fence = marker[1]
            continue
        if re.match(r"^#{1,2}[ \t]+", line):
            headings.append(i)
        if heading.match(line.rstrip("\r\n")):
            starts.append(i)
    if not starts:
        raise StateError(f"{slice_id}: brief has neither Fixed decisions nor Do not section")
    result = []
    for start in starts:
        end = next((i for i in headings if i > start), len(lines))
        result.append("".join(lines[start:end]))
    return "\n\n".join(result)


def validate_plan(plan):
    error = next(VALIDATOR.iter_errors(plan), None)
    if error:
        path = list(error.absolute_path)
        location = "plan"
        if path and path[0] == "tickets":
            location = "tickets"
            if len(path) > 1 and isinstance(path[1], int):
                location += f" position {path[1] + 1}"
                if len(path) > 2:
                    location += f" {path[2]}"
            if error.validator == "required":
                missing = next((key for key in error.validator_value if key not in error.instance), "field")
                location += f" {missing}"
        elif path:
            location = str(path[0])
        elif error.validator == "required":
            location = next((key for key in error.validator_value if key not in error.instance), "plan")
        raise StateError(f"invalid plan: {location}")
    for name, paths in [("test_files", plan["test_files"])]+[(f"tickets position {i} files", ticket["files"]) for i, ticket in enumerate(plan["tickets"], 1)]:
        for path in paths:
            parsed = PurePosixPath(path)
            if parsed.is_absolute() or ".." in parsed.parts or path in (".", "") or "\\" in path or "\x00" in path:
                raise StateError(f"invalid plan: {name}")


def build_task_file(slice_id, repository, branch, base_commit, plan, brief):
    validate_plan(plan)
    if not isinstance(slice_id, str) or not slice_id.strip():
        raise StateError("invalid slice")
    if not re.fullmatch(r"[^/\s]+/[^/\s]+", repository):
        raise StateError("invalid repository")
    if not branch.strip():
        raise StateError("invalid branch")
    if not re.fullmatch(r"[0-9a-fA-F]{40,64}", base_commit):
        raise StateError("invalid base_commit")
    rules = sections(brief, slice_id)
    tasks = []
    for position, ticket in enumerate(plan["tickets"], 1):
        tasks.append({"position": position, "depends_on": [position - 1] if position > 1 else [],
                      "title": ticket["title"], "goal": f"{TEST_LINE}\n\n{ticket['change']}\n\nThe following rules bind this ticket:\n\n{rules}",
                      "allowed_files": ticket["files"], "check_command": ticket["check"],
                      "pinned_paths": plan["test_files"]})
    return {"slice": slice_id, "repository": repository, "branch": branch,
            "base_commit": base_commit, "tasks": tasks}


def submit(task_file):
    try:
        argv = json.loads(os.environ.get("CPLANE_TASK_SUBMIT", ""))
    except ValueError:
        raise StateError("CPLANE_TASK_SUBMIT must be a JSON argument list") from None
    if not isinstance(argv, list) or not argv or any(not isinstance(arg, str) or not arg for arg in argv):
        raise StateError("CPLANE_TASK_SUBMIT must be a JSON argument list")
    try:
        result = subprocess.run(argv, input=json.dumps(task_file), text=True, capture_output=True)
    except (OSError, ValueError):
        raise StateError("submit command could not run") from None
    if result.returncode:
        raise StateError("submit command refused task file")
    try:
        ids = json.loads(result.stdout)
    except ValueError:
        raise StateError("submit command returned invalid task ids; submission may have succeeded") from None
    if not isinstance(ids, list) or len(ids) != len(task_file["tasks"]) or any(not isinstance(x, (str, int)) or isinstance(x, bool) or str(x).strip() == "" for x in ids):
        raise StateError("submit command returned invalid task ids; submission may have succeeded")
    return ids


def skills_version(root=None):
    root = Path(root) if root is not None else Path(__file__).resolve().parent.parent
    # Do not accidentally use an enclosing checkout for an archive installation.
    if not (root / ".git").exists():
        try:
            revision = (root / "REVISION").read_text().strip()
        except OSError:
            raise StateError("skills version requires REVISION outside a git checkout") from None
        if not revision or "\n" in revision or "\r" in revision:
            raise StateError("invalid REVISION")
        return revision
    status = subprocess.run(["git", "-C", str(root), "status", "--porcelain", "--", "skills"], capture_output=True, text=True)
    revision = subprocess.run(["git", "-C", str(root), "log", "-1", "--format=%H", "HEAD", "--", "skills"], capture_output=True, text=True)
    if status.returncode or status.stdout or revision.returncode or not revision.stdout.strip():
        raise StateError("skills must be committed in a git checkout before submission")
    return revision.stdout.strip()


def status(slice_id):
    try:
        argv = json.loads(os.environ.get("CPLANE_TASK_STATUS", ""))
    except ValueError:
        raise StateError("CPLANE_TASK_STATUS must be a JSON argument list") from None
    if not isinstance(argv, list) or not argv or any(not isinstance(arg, str) or not arg for arg in argv):
        raise StateError("CPLANE_TASK_STATUS must be a JSON argument list")
    try:
        result = subprocess.run([*argv, slice_id], text=True, capture_output=True)
    except (OSError, ValueError):
        raise StateError("status command could not run") from None
    if result.returncode:
        raise StateError("status command failed")
    try:
        tickets = json.loads(result.stdout)
        if not isinstance(tickets, list):
            raise ValueError
        for position, ticket in enumerate(tickets, 1):
            if (not isinstance(ticket, dict) or ticket.get("position") != position
                    or isinstance(ticket.get("position"), bool)
                    or ticket.get("status") not in ("queued", "running", "done", "failed", "escalated")
                    or not isinstance(ticket.get("id"), (str, int)) or isinstance(ticket["id"], bool)
                    or not str(ticket["id"]).strip() or not isinstance(ticket.get("title"), str)
                    or "reason" not in ticket or not isinstance(ticket["reason"], (str, type(None)))):
                raise ValueError
    except (ValueError, TypeError):
        raise StateError("status command returned invalid tickets") from None
    return tickets
