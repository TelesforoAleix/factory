"""Role defaults for `cplane add`, read from a local command's JSON output.

The command lives in the local file `roles-command`, beside `orders-url`. Its output is
untrusted: only a validated tool, model and effort are used.
"""
import json
import os
from pathlib import Path
import shlex
import subprocess

TOOLS = ("codex", "claude")
EFFORTS = ("low", "medium", "high", "xhigh", "max", "ultra")


def command_file():
    base = Path(os.environ.get("CPLANE_RUNS", "~/Library/Application Support/cplane/runs")).expanduser().resolve()
    return base.parent / "roles-command"


def lookup(role, path):
    """Return (route, None) for the role's first cli route, or (None, reason)."""
    try:
        argv = shlex.split(Path(path).read_text())
    except FileNotFoundError:
        return None, "no roles-command"
    except (OSError, ValueError):
        return None, "roles-command unreadable"
    if not argv:
        return None, "roles-command is empty"
    try:
        result = subprocess.run(argv, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=10)
    except subprocess.TimeoutExpired:
        return None, "roles-command timed out"
    except (OSError, ValueError):
        return None, "roles-command could not run"
    if result.returncode:
        return None, "roles-command failed"
    try:
        table = json.loads(result.stdout)
    except ValueError:
        return None, "roles-command output is not valid"
    routes = table.get(role) if isinstance(table, dict) else None
    if not isinstance(routes, list):
        return None, f"no routes for role {role}"
    route = next((r for r in routes if isinstance(r, dict) and r.get("kind") == "cli"), None)
    if route is None:
        return None, f"role {role} has no cli route"
    tool, model, effort = route.get("tool"), route.get("model"), route.get("effort")
    if (tool not in TOOLS or not isinstance(model, str) or not model.strip()
            or (effort is not None and effort not in EFFORTS)):
        return None, f"route for role {role} is not valid"
    chosen = {"tool": tool, "model": model}
    if effort is not None:
        chosen["effort"] = effort
    return chosen, None
