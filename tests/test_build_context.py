"""Keep tracked image inputs from disappearing behind build-context exclusions."""

import fnmatch
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INPUTS = ("cplane", "schema", "skills", "factory_ui", "ui")
# These UI test files are not inputs to the production build.
OMITTED = {
    "ui/src/chats.test.jsx",
    "ui/src/contrast.test.js",
    "ui/src/documents.test.jsx",
    "ui/src/evals.test.jsx",
    "ui/src/home-lab-settings.test.jsx",
    "ui/src/home.test.jsx",
    "ui/src/ideas.test.jsx",
    "ui/src/library.test.jsx",
    "ui/src/navigation.test.jsx",
    "ui/src/pipeline.test.jsx",
    "ui/src/polling.test.js",
    "ui/src/project-page.test.jsx",
    "ui/src/sessions.test.jsx",
    "ui/src/settings.test.jsx",
    "ui/src/slice-level.test.jsx",
    "ui/src/slice-order.test.jsx",
    "ui/src/theme.test.jsx",
}


def pattern_regex(pattern):
    """Translate Docker's path-component wildcards, including **, to a regex."""
    parts = pattern.strip("/").split("/")
    result = ""
    for index, part in enumerate(parts):
        if part == "**":
            result += ".*" if index == len(parts) - 1 else "(?:[^/]+/)*"
        else:
            result += fnmatch.translate(part)[4:-3]
            if index < len(parts) - 1:
                result += "/"
    return re.compile(result + r"\Z")


def included(path, rules):
    # Docker also matches rules against parent directories.
    parts = path.split("/")
    candidates = ["/".join(parts[:i]) for i in range(1, len(parts) + 1)]
    allowed = True
    for include, pattern in rules:
        if any(pattern.fullmatch(candidate) for candidate in candidates):
            allowed = include
    return allowed


def test_tracked_image_inputs_are_in_build_context():
    rules = []
    for line in (ROOT / ".dockerignore").read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            rules.append((line.startswith("!"), pattern_regex(line.removeprefix("!"))))
    tracked = set(
        subprocess.check_output(
            ["git", "ls-files", "-z", "--", *INPUTS], cwd=ROOT, text=True
        ).split("\0")
    ) - {""}
    # The Dockerfile copies these root files separately.
    tracked.update({"Dockerfile", "pyproject.toml", "uv.lock"})
    missing = {path for path in tracked if not included(path, rules)}
    assert missing == OMITTED, (
        f"unexpected omissions: {sorted(missing - OMITTED)}; now included: {sorted(OMITTED - missing)}"
    )
