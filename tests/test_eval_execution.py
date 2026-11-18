"""Retained usage telemetry helpers remain isolated from run API execution."""

from datetime import UTC, datetime
from unittest.mock import Mock

import pytest

from cplane.eval_execution import UsageContext
from cplane.runner import Runner

NOW = datetime(2026, 10, 16, 10, tzinfo=UTC)


@pytest.fixture
def setup(tmp_path, make_state):
    r = UsageContext(Runner(make_state(), runs=tmp_path / "runs", git=Mock()))
    r.instant = NOW
    r.jobs = {}
    r.data = {"slices": []}
    return r, Mock(), Mock()
