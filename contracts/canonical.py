"""The one canonical JSON form for every file the tool writes or compares."""
import json
from pathlib import Path


class ContractError(Exception):
    """A usage or input problem; the command exits 2."""


def dumps(value):
    return json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + '\n'


def parse(text, where):
    try:
        return json.loads(text)
    except ValueError as error:
        raise ContractError(f'{where}: not JSON: {error}') from None


def load(path):
    try:
        text = Path(path).read_text(encoding='utf-8')
    except (OSError, UnicodeDecodeError) as error:
        raise ContractError(f'{path}: {error}') from None
    return parse(text, path)


def canonical_file(path):
    return dumps(load(path))
