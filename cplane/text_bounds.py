"""Character limits for text persisted by the runner and compact command."""

LOG_LIMIT = 500
ATTENTION_LIMIT = 8_000
TAIL_LIMIT = 4_000


def marker(omitted, *, run_folder=False):
    suffix = "; full output in the run folder" if run_folder else ""
    return f"… [{omitted} characters omitted{suffix}]"


def cut(text, limit, *, run_folder=False):
    """Keep the beginning of text and mark the number of discarded characters."""
    if len(text) <= limit:
        return text
    omitted = len(text) - limit
    while True:
        mark = marker(omitted, run_folder=run_folder)
        keep = max(0, limit - len(mark) - 1)
        omitted = len(text) - keep
        mark = marker(omitted, run_folder=run_folder)
        result = text[:keep] + "\n" + mark
        if len(result) <= limit:
            return result


def cut_line(text, limit):
    if len(text) <= limit:
        return text
    omitted = len(text)
    while True:
        mark = marker(omitted)
        keep = max(0, limit - len(mark) - 1)
        omitted = len(text) - keep
        result = text[:keep] + " " + marker(omitted)
        if len(result) <= limit:
            return result


def failure_tail(summary, output):
    """Bound a failure tail while retaining its summary and the output's end."""
    if len(summary) >= TAIL_LIMIT:
        # The summary itself is generated from the first stderr line.
        summary = cut(summary, TAIL_LIMIT - 1)
    if not output:
        return summary
    available = TAIL_LIMIT - len(summary) - 1
    if len(output) <= available:
        return summary + "\n" + output
    omitted = len(output)
    while True:
        mark = marker(omitted, run_folder=True)
        keep = max(0, available - len(mark) - 1)
        omitted = len(output) - keep
        mark = marker(omitted, run_folder=True)
        result = summary + "\n" + mark + "\n" + output[-keep:] if keep else summary + "\n" + mark
        if len(result) <= TAIL_LIMIT:
            return result
