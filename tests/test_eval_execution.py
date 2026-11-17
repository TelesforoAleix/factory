"""Legacy eval capacity/probes remain isolated from platform slice execution."""

from datetime import UTC, datetime
from unittest.mock import Mock

import pytest

from cplane.eval_execution import Context
from cplane.runner import Runner

NOW = datetime(2026, 10, 16, 10, tzinfo=UTC)


@pytest.fixture
def setup(tmp_path, make_state):
    r = Context(Runner(make_state(), runs=tmp_path / "runs", git=Mock()))
    r.instant = NOW
    r.jobs = {}
    r.data = {"slices": []}
    return r, Mock(), Mock()
