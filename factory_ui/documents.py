"""Read only the public Markdown export, never the planning clone."""
from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import os
from pathlib import Path, PurePosixPath
import re
import stat


class DocumentNotFound(ValueError):
    pass


def document_path(value):
    if not isinstance(value, str) or not value or '\\' in value or '\x00' in value:
        raise DocumentNotFound('Invalid document path')
    path = PurePosixPath(value)
    if path.is_absolute() or any(p in ('', '.', '..') for p in value.split('/')) or path.suffix != '.md':
        raise DocumentNotFound('Invalid document path')
    return path


def parse_document(path, text, modified):
    """Read scalar display fields; leave the Markdown body to the renderer.

    No YAML objects, tags or expressions are evaluated. Unknown/complex fields
    stay out of the metadata display.
    """
    fields = {}
    lines = text.splitlines(keepends=True)
    if lines and lines[0].strip() == '---':
        end = next((i for i in range(1, len(lines)) if lines[i].strip() in ('---', '...')), None)
        if end is not None:
            for line in lines[1:end]:
                match = re.fullmatch(r'(title|status|date|updated):\s*(.*?)\s*\n?', line)
                if match:
                    value = match[2]
                    if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
                        value = value[1:-1]
                    elif value.startswith(('[', '{', '|', '>', '&', '*', '!')):
                        continue
                    else:
                        value = value.split(' #', 1)[0].strip()
                    fields[match[1]] = value
            text = ''.join(lines[end + 1:])
    heading = re.search(r'^#\s+(.+)$', text, re.M)
    return dict(path=str(path), folder=str(path.parent),
                title=fields.get('title') or (heading[1] if heading else path.stem),
                status=fields.get('status') or 'Unspecified',
                date=fields.get('updated') or fields.get('date') or datetime.fromtimestamp(modified, timezone.utc).date().isoformat(),
                markdown=text)


class Documents:
    def __init__(self, root):
        self.root = Path(root)

    @contextmanager
    def snapshot(self):
        with (self.root.parent / '.ui-docs.lock').open('rb') as lock:
            fcntl.flock(lock, fcntl.LOCK_SH)
            fd = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            try:
                yield fd
            finally:
                os.close(fd)

    def read_at(self, root_fd, value):
        path = document_path(value)
        fd = os.dup(root_fd)
        try:
            for part in path.parts[:-1]:
                child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                os.close(fd)
                fd = child
            child = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
            with os.fdopen(child, 'r', encoding='utf-8', errors='replace') as source:
                info = os.fstat(source.fileno())
                if not stat.S_ISREG(info.st_mode):
                    raise DocumentNotFound('Invalid document')
                return parse_document(path, source.read(), info.st_mtime)
        except OSError:
            raise DocumentNotFound('Document not found') from None
        finally:
            os.close(fd)

    def read(self, value):
        document_path(value)
        with self.snapshot() as fd:
            return self.read_at(fd, value)

    def search(self, query=''):
        with self.snapshot() as fd:
            result = []
            for directory, _, filenames, _ in os.fwalk('.', dir_fd=fd, follow_symlinks=False):
                for name in sorted(filenames):
                    if not name.endswith('.md'):
                        continue
                    path = str(PurePosixPath(directory) / name)
                    try:
                        doc = self.read_at(fd, path)
                    except DocumentNotFound:
                        continue
                    if query.casefold() in '\n'.join(str(v) for v in doc.values()).casefold():
                        result.append({k: v for k, v in doc.items() if k != 'markdown'})
            return sorted(result, key=lambda d: (d['folder'], d['path']))
