"""Read-only GitHub metadata replaces runner repository checkouts."""

import base64
import json
from unittest.mock import Mock

import pytest

from cplane.runner import GitHub, GitHubReadError


def test_default_tip_uses_repository_default_branch():
    gh = GitHub()
    gh.call = Mock(
        side_effect=[
            json.dumps({"default_branch": "trunk"}),
            json.dumps({"sha": "a" * 40}),
        ]
    )
    assert gh.default_tip("example/repo") == "a" * 40
    assert gh.call.call_args.args == (
        "example/repo",
        "api",
        "repos/example/repo/commits/trunk",
    )


def test_classification_pinned_policy_pagination_deletions_and_renames():
    gh = GitHub()
    gh.call = Mock(
        side_effect=[
            json.dumps({"tree": [{"path": ".github/change-classes", "sha": "c" * 40}]}),
            json.dumps({"content": base64.b64encode(b"4 /guard/**\n").decode()}),
            json.dumps(
                [{"filename": f"code/{i}", "status": "modified"} for i in range(99)]
                + [
                    {
                        "filename": "new",
                        "previous_filename": "guard/old",
                        "status": "renamed",
                    }
                ]
            ),
            json.dumps([{"filename": ".github/deleted", "status": "removed"}]),
        ]
    )
    assert gh.changes(
        {"repository": "example/repo", "base": "a" * 40, "tip": "b" * 40}, 12
    ) == (4, [".github/deleted", "guard/old"])
    assert "page=2" in gh.call.call_args.args[-1]
    assert "a" * 40 in gh.call.call_args_list[0].args[-1]


def test_installed_guard_drift_and_truncated_compare(monkeypatch):
    monkeypatch.setenv("CPLANE_REVISION", "c" * 40)
    gh = GitHub()
    job = {"repository": "TelesforoAleix/factory", "base": "a" * 40, "tip": "b" * 40}
    gh.call = Mock(
        side_effect=[
            json.dumps({"tree": []}),
            "[]",
            json.dumps({"files": [{"filename": "compose.yaml"}]}),
        ]
    )
    assert gh.changes(job, 12) == (4, ["compose.yaml"])
    gh.call = Mock(
        side_effect=[
            json.dumps({"tree": []}),
            "[]",
            json.dumps({"files": [{"filename": f"f{i}"} for i in range(300)]}),
        ]
    )
    with pytest.raises(GitHubReadError, match="exceeds"):
        gh.changes(job, 12)
