"""Read repository-owned turn instructions at runtime."""
import hashlib
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parent / 'prompts'


def names():
    return sorted(path.stem for path in ROOT.glob('*.md'))


def text(name):
    if not isinstance(name, str) or not re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*', name):
        raise ValueError(f'Invalid prompt name: {name!r}')
    try:
        content = (ROOT / f'{name}.md').read_text(encoding='utf-8')
    except (OSError, UnicodeError) as exc:
        raise RuntimeError(f'Cannot read prompt {name!r}: {exc}') from exc
    return content.removesuffix('\n')


def sha256(name):
    return hashlib.sha256(text(name).encode('utf-8')).hexdigest()
