from datetime import datetime

import pytest

from cplane.times import LOCAL, parse_when


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
def test_time_forms(text, reference, expected):
    assert parse_when(text, datetime.fromisoformat(reference).astimezone(LOCAL)) == expected


@pytest.mark.parametrize("text", ["tomorrow 25:00", "tomorrow 06:80", "foo", "2026-03-29T02:30", "2026-10-25T02:30"])
def test_invalid_or_ambiguous_times(text):
    with pytest.raises(ValueError):
        parse_when(text)
