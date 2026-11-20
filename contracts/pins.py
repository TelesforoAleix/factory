"""A pin: a folder with the provider's `schema.json` and `pin.json` naming its origin."""
import hashlib
import re
from pathlib import Path

from .canonical import ContractError, dumps, load

KEYS = ('commit', 'contract', 'provider', 'sha256')
PATTERNS = {
    'contract': r'[a-z0-9]+(?:-[a-z0-9]+)*',
    'provider': r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+',
    'commit': r'[0-9a-f]{40}',
    'sha256': r'[0-9a-f]{64}',
}


def _check(record):
    errors = []
    if not isinstance(record, dict) or sorted(record) != sorted(KEYS):
        return [f'pin.json must have exactly the keys {", ".join(KEYS)}']
    for key in KEYS:
        value = record[key]
        if not isinstance(value, str) or not re.fullmatch(PATTERNS[key], value):
            errors.append(f'pin.json: invalid {key}')
    return errors


def write(contract, provider, commit, schema, out):
    text = dumps(load(schema)).encode()
    record = dict(contract=contract, provider=provider, commit=commit,
                  sha256=hashlib.sha256(text).hexdigest())
    errors = _check(record)
    if errors:
        raise ContractError('; '.join(errors))
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    (out / 'schema.json').write_bytes(text)
    (out / 'pin.json').write_text(dumps(record), encoding='utf-8')
    return record


def verify(folder):
    """The pin's problems, empty when it is valid."""
    folder = Path(folder)
    try:
        raw = (folder / 'pin.json').read_bytes()
        schema = (folder / 'schema.json').read_bytes()
    except OSError as error:
        return [str(error)]
    try:
        record = load(folder / 'pin.json')
    except ContractError as error:
        return [str(error)]
    errors = _check(record)
    if raw != dumps(record).encode():
        errors.append('pin.json is not in canonical form')
    if not errors and hashlib.sha256(schema).hexdigest() != record['sha256']:
        errors.append('schema.json does not match the sha256 in pin.json')
    if not errors:
        try:
            if schema != dumps(load(folder / 'schema.json')).encode():
                errors.append('schema.json is not in canonical form')
        except ContractError as error:
            errors.append(str(error))
    return errors


def schema(folder):
    errors = verify(folder)
    if errors:
        raise ContractError(f'{folder}: ' + '; '.join(errors))
    return load(Path(folder) / 'schema.json')
