"""Host-only, narrowly scoped, one-way feature publication."""
import os
from pathlib import Path
import re
import shutil
import tempfile

from . import fence
from .backlog import generated_table
from .planning import Planning
from .state import StateError


class FeatureExport(Planning):
    def __init__(self):
        root = fence.trusted_directory(fence.CLEAN_ROOT)
        self.clean = Path(tempfile.mkdtemp(prefix='feature-export-', dir=root))

    def allowed(self, name, generated):
        return bool(re.fullmatch(r'features/[A-Z]{3}-F[1-9][0-9]*\.md', name)
                    or generated and name == 'backlog.md')

    def validate(self, generated):
        names = (self.git('diff', 'HEAD', '--name-only', '--no-renames', '-z').stdout
                 + self.git('ls-files', '--others', '--exclude-standard', '-z').stdout).split('\0')
        if any(not self.allowed(name, generated) for name in names if name):
            raise StateError('Feature export path refused')
        for entry in filter(None, self.git('ls-files', '--stage', '-z').stdout.split('\0')):
            mode, rest = entry.split(' ', 1)
            name = rest.split('\t', 1)[1]
            if self.allowed(name, generated) and mode not in ('100644', '100755'):
                raise StateError('Feature export requires regular files')

    def render(self, features, generated):
        directory = self.clean / 'features'
        if directory.is_symlink() or directory.exists() and not directory.is_dir():
            raise StateError('Feature directory refused')
        directory.mkdir(exist_ok=True)
        expected = set()
        for feature in features:
            name = f"features/{feature['id']}.md"
            if not self.allowed(name, False):
                raise StateError('Feature ID refused')
            expected.add(name)
            path = self.clean / name
            if path.is_symlink():
                raise StateError('Feature symlink refused')
            content = f"# {feature['title']}\n\nProject: {feature['project']}\nStage: {feature['stage']}\n"
            for section in feature['sections']:
                content += f"\n## {section['name']}\n\n{section['text']}\n"
            path.write_text(content, encoding='utf-8')
        for path in directory.glob('*.md'):
            if str(path.relative_to(self.clean)) not in expected:
                if not self.allowed(str(path.relative_to(self.clean)), False):
                    raise StateError('Feature export path refused')
                path.unlink()
        if generated:
            path = self.clean / 'backlog.md'
            if path.is_symlink():
                raise StateError('Backlog symlink refused')
            original = path.read_bytes().decode('utf-8')
            path.write_bytes(generated_table(original, features).encode('utf-8'))
        self.git('add', '--all', '--', 'features')
        if generated:
            self.git('add', '--', 'backlog.md')
        self.validate(generated)

    def publish(self, features, generated):
        remote = os.environ.get('CPLANE_PLANNING_REMOTE', '')
        if not re.fullmatch(r'git@github\.com:[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+(?:\.git)?', remote):
            raise StateError('Planning SSH remote unavailable or invalid')
        self.git('init', '--template=')
        self.git('remote', 'add', 'origin', remote)
        for attempt in range(2):
            self.git('fetch', '--no-tags', 'origin', '+refs/heads/main:refs/remotes/origin/main', network='fetch')
            self.git('checkout', '-B', 'export', 'refs/remotes/origin/main')
            self.render(features, generated)
            result = self.git('diff', '--cached', '--quiet', allow_failure=True)
            if result.returncode == 0:
                return
            if result.returncode != 1:
                raise StateError('Feature export diff failed')
            self.git('commit', '-m', 'Export features')
            result = self.git('push', '--porcelain', 'origin', 'HEAD:refs/heads/main', network='push', allow_failure=True)
            if result.returncode == 0:
                return
            # Only a non-fast-forward rejection gets the one fetch/re-render retry.
            if attempt or not any(reason in result.stdout + result.stderr
                                  for reason in ('[rejected]', 'non-fast-forward', 'fetch first')):
                raise StateError('Feature export push failed')
        raise StateError('Feature export push failed')


def export(features):
    adapter = FeatureExport()
    try:
        adapter.publish(features, os.environ.get('CPLANE_BACKLOG_GENERATED') == '1')
    finally:
        shutil.rmtree(adapter.clean)
