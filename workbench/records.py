"""Reading and writing ``ops/`` records. **The only parser in the system.**

ADR-036 §3: the server parses and serves JSON so the browser never parses a
record. That exists because ``dashboard/dashboard.js`` carried a hand-rolled
~25-line YAML subset parser which silently dropped nested maps, multi-line
strings and inline collections — returning incomplete data rather than an error.
Two parsers meant two definitions of "a valid record", and
``templates/ops/founder-inbox-item.yaml`` already nests, so they were already
capable of disagreeing.

Three storage formats, per ``v0-operating-objects.md``: YAML for most objects,
JSON for runs, and Markdown with YAML frontmatter for context packs and release
checklists. One file per object.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

from workbench import schema
from workbench.errors import ValidationError

_FRONTMATTER_FENCE = "---"


def _read_markdown(text: str) -> tuple[dict, str]:
    """Split Markdown-with-frontmatter into (fields, body).

    A file that opens with ``---`` but never closes it is an error rather than a
    document with no frontmatter: silently treating a truncated header as body
    is how a half-written record becomes an unreadable one.
    """
    if not text.startswith(_FRONTMATTER_FENCE):
        return {}, text
    parts = text.split("\n" + _FRONTMATTER_FENCE, 1)
    if len(parts) != 2:
        raise ValidationError("markdown frontmatter opened with '---' but never closed")
    header = parts[0][len(_FRONTMATTER_FENCE):]
    body = parts[1].lstrip("\n")
    fields = yaml.safe_load(header) or {}
    if not isinstance(fields, dict):
        raise ValidationError("markdown frontmatter must be a mapping")
    return fields, body


def _write_markdown(fields: dict, body: str) -> str:
    header = yaml.safe_dump(fields, sort_keys=False, allow_unicode=True).rstrip("\n")
    return f"{_FRONTMATTER_FENCE}\n{header}\n{_FRONTMATTER_FENCE}\n\n{body.rstrip()}\n"


def load(path: Path) -> dict:
    """Load one record. The body of a Markdown record lands in ``_body``."""
    text = path.read_text(encoding="utf-8")
    suffix = path.suffix.lower()
    try:
        if suffix == ".json":
            record = json.loads(text)
        elif suffix in (".yaml", ".yml"):
            record = yaml.safe_load(text)
        elif suffix == ".md":
            fields, body = _read_markdown(text)
            record = dict(fields)
            record["_body"] = body
        else:
            raise ValidationError(f"unsupported record format: {path.name}")
    except yaml.YAMLError as exc:
        raise ValidationError(f"{path.name} is not valid YAML: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise ValidationError(f"{path.name} is not valid JSON: {exc}") from exc

    if not isinstance(record, dict):
        raise ValidationError(f"{path.name} does not contain a record mapping")
    record["_path"] = str(path)
    return record


def dump(record: dict, fmt: str) -> str:
    """Serialise a record. ``_``-prefixed keys are internal and never written."""
    public = {k: v for k, v in record.items() if not k.startswith("_")}
    if fmt == "json":
        return json.dumps(public, indent=2, ensure_ascii=False, sort_keys=False) + "\n"
    if fmt == "markdown":
        return _write_markdown(public, record.get("_body", ""))
    return yaml.safe_dump(public, sort_keys=False, allow_unicode=True, default_flow_style=False)


def path_for(ops_dir: Path, record: dict) -> Path:
    """Where a record belongs: ``ops/<collection>/<ID>.<ext>``."""
    spec = schema.get(record["object_type"])
    extension = {"yaml": ".yaml", "json": ".json", "markdown": ".md"}[spec.fmt]
    return ops_dir / spec.collection / f"{record['id']}{extension}"


def validate_or_raise(record: dict) -> None:
    problems = schema.validate(record)
    if problems:
        raise ValidationError(
            f"{record.get('object_type', 'record')} {record.get('id', '(no id)')} is not valid",
            problems,
        )


def write(ops_dir: Path, record: dict) -> Path:
    """Validate, then write atomically.

    **Validation happens before any bytes move**, and the write goes to a
    temporary file that is renamed into place. A record that fails validation
    leaves ``ops/`` byte-identical — which is a thing the phase must prove, not
    assume, so it has its own test.
    """
    validate_or_raise(record)
    spec = schema.get(record["object_type"])
    target = path_for(ops_dir, record)
    target.parent.mkdir(parents=True, exist_ok=True)

    temporary = target.with_suffix(target.suffix + ".tmp")
    temporary.write_text(dump(record, spec.fmt), encoding="utf-8")
    temporary.replace(target)
    return target


def load_collection(ops_dir: Path, object_type: str) -> list[dict]:
    spec = schema.get(object_type)
    directory = ops_dir / spec.collection
    if not directory.is_dir():
        return []
    records = []
    for path in sorted(directory.iterdir()):
        if path.name.startswith(".") or path.suffix.lower() not in (".yaml", ".yml", ".json", ".md"):
            continue
        if path.name.upper().startswith("README"):
            continue
        records.append(load(path))
    return records


def load_all(ops_dir: Path) -> dict[str, list[dict]]:
    return {object_type: load_collection(ops_dir, object_type) for object_type in schema.SCHEMAS}


def find(ops_dir: Path, object_id: str) -> dict:
    for object_type in schema.SCHEMAS:
        for record in load_collection(ops_dir, object_type):
            if record.get("id") == object_id:
                return record
    raise ValidationError(f"no record with id {object_id!r} in {ops_dir}")


def check_links(ops_dir: Path) -> list[str]:
    """Report references to ids that do not exist.

    Separate from :func:`validate` on purpose: a record can be perfectly
    well-formed and still point at a ticket that was never created, and
    conflating the two would make every write depend on the whole corpus.
    """
    everything = load_all(ops_dir)
    known = {r["id"] for records in everything.values() for r in records if r.get("id")}
    link_fields = (
        "task_id", "related_ticket_id", "related_task_id", "context_pack_id",
        "required_context_pack_id", "release_id", "founder_inbox_item_id",
    )
    list_fields = (
        "ticket_ids", "run_ids", "review_ids", "approval_ids",
        "related_object_ids", "blocks_object_ids", "blocking_object_ids",
    )
    problems = []
    for records in everything.values():
        for record in records:
            for key in link_fields:
                value = record.get(key)
                if isinstance(value, str) and value and value not in known:
                    problems.append(f"{record.get('id')}: {key} -> unknown id {value}")
            for key in list_fields:
                for value in record.get(key) or []:
                    if isinstance(value, str) and value not in known:
                        problems.append(f"{record.get('id')}: {key} -> unknown id {value}")
    return problems
