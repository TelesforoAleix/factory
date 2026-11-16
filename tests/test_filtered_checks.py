import json
from unittest.mock import Mock

import pytest

from cplane.runner import GitHub


@pytest.mark.parametrize(
    ("filtered_check", "expected"),
    [
        (None, ("green", "")),
        ({"name": "ui", "conclusion": "FAILURE"}, ("red", "ui")),
    ],
)
def test_filtered_workflow_check_states(filtered_check, expected):
    checks = [
        {"name": "test", "conclusion": "SUCCESS"},
        {"name": "image-gitleaks", "conclusion": "SUCCESS"},
    ]
    if filtered_check is not None:
        checks.append(filtered_check)
    gh = GitHub()
    gh.call = Mock(return_value=json.dumps({"statusCheckRollup": checks}))
    assert gh.checks("owner/repo", 1) == expected


@pytest.mark.parametrize(
    ("filtered_check", "expected"),
    [
        (None, ("green", "")),
        ({"name": "ui", "status": "completed", "conclusion": "failure"}, ("red", "ui")),
    ],
)
def test_filtered_workflow_check_states_for_head(filtered_check, expected):
    tip = "a" * 40
    jobs = [
        {"name": "test", "status": "completed", "conclusion": "success"},
        {"name": "image-gitleaks", "status": "completed", "conclusion": "success"},
    ]
    if filtered_check is not None:
        jobs.append(filtered_check)
    gh = GitHub()
    gh.call = Mock(
        side_effect=[
            json.dumps({"headRefOid": tip, "state": "OPEN"}),
            json.dumps({"workflow_runs": [{"id": 1, "status": "completed"}]}),
            json.dumps({"jobs": jobs}),
        ]
    )
    assert gh.checks("owner/repo", 1, tip) == expected
