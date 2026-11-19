import os
import subprocess
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

import cplane.times as times
from cplane.times import parse_when


@pytest.fixture
def local_zone(monkeypatch):
    monkeypatch.setenv("FACTORY_TIME_ZONE", "Europe/Copenhagen")
    monkeypatch.setattr(times, "LOCAL", ZoneInfo(os.environ["FACTORY_TIME_ZONE"]))


@pytest.mark.parametrize("text,reference,expected", [
    ("Mon 03:00", "2026-10-15T12:00:00+02:00", "2026-10-19T03:00:00+02:00"),
    ("tomorrow 06:00", "2026-10-15T23:30:00+02:00", "2026-10-16T06:00:00+02:00"),
    ("Mon 03:00", "2026-10-19T04:00:00+02:00", "2026-10-26T03:00:00+01:00"),
    ("Mon 03:00", "2026-10-19T02:00:00+02:00", "2026-10-19T03:00:00+02:00"),
    ("today 06:00", "2026-10-15T01:00:00+02:00", "2026-10-15T06:00:00+02:00"),
    ("tomorrow 06:00", "2026-10-24T12:00:00+02:00", "2026-10-25T06:00:00+01:00"),
    ("2026-12-01T08:30", "2026-10-15T12:00:00+02:00", "2026-12-01T08:30:00+01:00"),
    ("2026-10-16T06:00:00-05:00", "2026-10-15T12:00:00+02:00", "2026-10-16T06:00:00-05:00"),
    ("2026-10-16T06:00:00Z", "2026-10-15T12:00:00+02:00", "2026-10-16T06:00:00+00:00"),
])
def test_time_forms(text, reference, expected, local_zone):
    assert parse_when(text, datetime.fromisoformat(reference).astimezone(times.LOCAL)) == expected


@pytest.mark.parametrize("text", ["tomorrow 25:00", "tomorrow 06:80", "foo", "2026-03-29T02:30", "2026-10-25T02:30"])
def test_invalid_or_ambiguous_times(text, local_zone):
    with pytest.raises(ValueError):
        parse_when(text)


def test_default_zone_is_utc():
    env = os.environ.copy()
    env.pop("FACTORY_TIME_ZONE", None)
    result = subprocess.run([sys.executable, "-c",
                             "from cplane.times import parse_when; print(parse_when('2026-12-01T08:30'))"],
                            env=env, text=True, capture_output=True, check=True)
    assert result.stdout.strip() == "2026-12-01T08:30:00+00:00"


def test_invalid_zone_fails_at_startup():
    env = {**os.environ, "FACTORY_TIME_ZONE": "Invalid/Zone"}
    result = subprocess.run([sys.executable, "-c", "import cplane.times"],
                            env=env, text=True, capture_output=True)
    assert result.returncode != 0
    assert "Invalid FACTORY_TIME_ZONE" in result.stderr
    assert "Invalid/Zone" in result.stderr


def test_configured_zone_at_startup():
    env = {**os.environ, "FACTORY_TIME_ZONE": "Europe/Copenhagen"}
    result = subprocess.run([sys.executable, "-c",
                             "from cplane.times import parse_when; print(parse_when('2026-12-01T08:30'))"],
                            env=env, text=True, capture_output=True, check=True)
    assert result.stdout.strip() == "2026-12-01T08:30:00+01:00"
