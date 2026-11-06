"""Record schemas, derived from ``templates/ops/`` and ``design/v0-operating-objects.md``.

A schema here is deliberately small: the object's collection directory, its
storage format, which fields must be present, and which fields are closed
vocabularies. It is not a general-purpose schema language, because Factory's
records are a fixed and short list and a validator that can express anything is
harder to read than the ten rules it encodes.

**What validation is for.** It refuses to write a malformed record. It does not
try to prove a record is *correct* — that a ticket references a task that exists
is a link-integrity question, checked separately by :func:`workbench.records.check_links`.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Schema:
    object_type: str
    collection: str
    fmt: str  # "yaml" | "json" | "markdown"
    required: tuple[str, ...]
    statuses: tuple[str, ...] = ()
    # Fields whose value must be one of a closed set, beyond `status`.
    enums: dict[str, tuple[str, ...]] = field(default_factory=dict)


_COMMON = ("template_version", "object_type", "id", "title", "status", "project_id")

RISK = ("low", "medium", "high", "critical")
PRIORITY = ("low", "medium", "high", "urgent")

SCHEMAS: dict[str, Schema] = {
    "task": Schema(
        object_type="task",
        collection="tasks",
        fmt="yaml",
        required=_COMMON + ("intent", "acceptance_criteria"),
        statuses=("inbox", "discovery", "ready", "assigned", "in_progress",
                  "blocked", "review", "release_ready", "shipped", "archived", "cancelled"),
        enums={"risk_level": RISK, "priority": PRIORITY},
    ),
    "ticket": Schema(
        object_type="ticket",
        collection="tickets",
        fmt="yaml",
        required=_COMMON + ("task_id", "objective", "acceptance_criteria"),
        statuses=("inbox", "ready", "assigned", "in_progress", "self_review",
                  "external_review", "testing", "revision", "blocked",
                  "release_ready", "shipped", "archived", "cancelled"),
        enums={"risk_level": RISK, "priority": PRIORITY},
    ),
    "run": Schema(
        object_type="run",
        collection="runs",
        fmt="json",
        required=("template_version", "object_type", "id", "status", "project_id"),
        statuses=("started", "in_progress", "succeeded", "failed", "refused", "aborted"),
    ),
    "founder_inbox_item": Schema(
        object_type="founder_inbox_item",
        collection="inbox",
        fmt="yaml",
        required=_COMMON + ("decision_needed",),
        statuses=("open", "answered", "superseded", "cancelled"),
        enums={"priority": PRIORITY},
    ),
    "approval": Schema(
        object_type="approval",
        collection="approvals",
        fmt="yaml",
        required=_COMMON + ("request_summary", "related_object_ids"),
        statuses=("requested", "approved", "rejected", "expired", "invalidated"),
    ),
    "review_record": Schema(
        object_type="review_record",
        collection="reviews",
        fmt="yaml",
        required=_COMMON + ("related_ticket_id",),
        statuses=("requested", "in_progress", "changes_requested", "approved", "rejected"),
        enums={"risk_level": RISK},
    ),
    "context_pack": Schema(
        object_type="context_pack",
        collection="context-packs",
        fmt="markdown",
        required=("template_version", "object_type", "id", "title", "project_id"),
    ),
    "release": Schema(
        object_type="release",
        collection="releases",
        fmt="markdown",
        required=("template_version", "object_type", "id", "title", "project_id"),
    ),
    "learning_candidate": Schema(
        object_type="learning_candidate",
        collection="learning",
        fmt="yaml",
        required=_COMMON,
    ),
    "interaction": Schema(
        object_type="interaction",
        collection="interactions",
        fmt="yaml",
        required=_COMMON,
    ),
}

# Collections a minimum valid ops/ must contain (acceptance step 3).
MINIMUM_COLLECTIONS = tuple(sorted({s.collection for s in SCHEMAS.values()})) + ("audit",)


def get(object_type: str) -> Schema:
    try:
        return SCHEMAS[object_type]
    except KeyError:
        known = ", ".join(sorted(SCHEMAS))
        raise KeyError(f"unknown object type {object_type!r}; known types: {known}") from None


def validate(record: dict) -> list[str]:
    """Return a list of problems. Empty means valid.

    Returns every problem rather than raising on the first, for the same reason
    ADR-034 §6 requires naming every missing capability: a caller that fixes one
    problem per round trip learns the shape of the schema very slowly.
    """
    problems: list[str] = []

    object_type = record.get("object_type")
    if not object_type:
        return ["missing 'object_type'"]
    try:
        schema = get(object_type)
    except KeyError as exc:
        return [str(exc)]

    for key in schema.required:
        if key not in record:
            problems.append(f"missing required field {key!r}")
        elif record[key] in (None, "", []):
            problems.append(f"required field {key!r} is empty")

    from workbench import ids  # local import keeps the schema module dependency-free

    object_id = record.get("id")
    if object_id and not ids.is_valid(str(object_id)):
        problems.append(f"id {object_id!r} is not <PREFIX>-<YEAR>-<NNNN>")
    elif object_id:
        prefix, _, _ = ids.parse(str(object_id))
        expected = ids.PREFIXES.get(object_type)
        if expected and prefix != expected:
            problems.append(f"id {object_id!r} does not use the {expected}- prefix for {object_type}")

    status = record.get("status")
    if schema.statuses and status is not None and status not in schema.statuses:
        problems.append(
            f"status {status!r} is not one of: {', '.join(schema.statuses)}"
        )

    for key, allowed in schema.enums.items():
        value = record.get(key)
        if value is not None and value not in allowed:
            problems.append(f"{key} {value!r} is not one of: {', '.join(allowed)}")

    return problems
