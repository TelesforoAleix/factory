"""Offset-preserving ISO times and small local calendar expressions."""
import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

LOCAL = ZoneInfo("Europe/Copenhagen")


def now():
    return datetime.now(LOCAL)


def localize(value):
    """Reject nonexistent or ambiguous wall times; an explicit offset disambiguates."""
    first = value.replace(tzinfo=LOCAL, fold=0)
    second = value.replace(tzinfo=LOCAL, fold=1)
    roundtrip = first.astimezone(ZoneInfo("UTC")).astimezone(LOCAL).replace(tzinfo=None)
    if roundtrip != value:
        raise ValueError("local time does not exist; supply an explicit offset")
    if first.utcoffset() != second.utcoffset():
        raise ValueError("local time is ambiguous; supply an explicit offset")
    return first


def parse_when(text, reference=None):
    reference = (reference or now()).astimezone(LOCAL)
    try:
        value = datetime.fromisoformat(text)
    except ValueError:
        match = re.fullmatch(r"(today|tomorrow|Mon|Tue|Wed|Thu|Fri|Sat|Sun) (\d{2}):(\d{2})", text, re.I)
        if not match:
            raise ValueError("use an ISO 8601 time, 'Mon 03:00', or 'tomorrow 06:00'") from None
        day, hour, minute = match.groups()
        date = reference.date()
        if day.lower() == "tomorrow":
            date += timedelta(days=1)
        elif day.lower() != "today":
            weekday = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"].index(day.lower())
            date += timedelta(days=(weekday - date.weekday()) % 7)
            if date == reference.date() and (int(hour), int(minute)) <= (reference.hour, reference.minute):
                date += timedelta(days=7)
        value = datetime.combine(date, datetime.min.time()).replace(hour=int(hour), minute=int(minute))
    if value.tzinfo is None:
        value = localize(value)
    return value.isoformat()
