"""Synthetic committed Markdown, public exports and owner notes only."""
import os
import subprocess
from unittest.mock import Mock

import pytest

from cplane.sessions import DocumentExporter
from factory_ui import create_app
from factory_ui.documents import Documents


@pytest.fixture
def published(tmp_path, monkeypatch):
    monkeypatch.setattr('cplane.fence.ROOT_UID', os.getuid())
    clone = tmp_path / 'clone'
    clone.mkdir(mode=0o700)
    subprocess.run(['git', 'init', '-q', str(clone)], check=True)
    (clone / 'folder').mkdir()
    (clone / 'folder/plan.md').write_text('---\nstatus: draft\ndate: 2026-11-01\n---\n# Plan\n\nA searchable document.\n<script>alert(1)</script>\n')
    (clone / 'backlog.md').write_text('# Backlog\n\n| Task | Status |\n| --- | --- |\n| Example | Planned |\n')
    (clone / 'private.json').write_text('never publish')
    (clone / 'folder/link.md').symlink_to('/etc/passwd')
    commit(clone)
    parent = tmp_path / 'public'
    parent.mkdir(mode=0o755)
    exporter = DocumentExporter(clone, parent / 'ui-docs')
    assert exporter.refresh()
    return clone, exporter, Documents(exporter.destination)


def commit(clone):
    subprocess.run(['git', '-C', str(clone), 'add', '.'], check=True)
    subprocess.run(['git', '-C', str(clone), '-c', 'user.name=Test', '-c',
                    'user.email=test@example.test', 'commit', '-qm', 'fixture'], check=True)


def test_committed_markdown_only_atomic_refresh(published):
    clone, exporter, docs = published
    root = exporter.destination
    assert {str(p.relative_to(root)) for p in root.rglob('*') if p.is_file()} == {'folder/plan.md', 'backlog.md'}
    assert not (root / 'folder/link.md').exists()
    assert root.stat().st_mode & 0o777 == 0o755
    assert (root / 'folder/plan.md').stat().st_mode & 0o777 == 0o644
    assert not exporter.refresh()
    (clone / 'folder/plan.md').unlink()
    (clone / 'new.md').write_text('# New')
    assert not exporter.refresh()  # uncommitted input never published
    assert docs.read('folder/plan.md')['status'] == 'draft'
    commit(clone)
    assert exporter.refresh()
    assert {d['path'] for d in docs.search()} == {'new.md', 'backlog.md'}
    assert not root.is_symlink()
    assert not list(root.parent.glob('.ui-docs-*'))


def test_failed_export_keeps_previous_generation(published, monkeypatch):
    clone, exporter, docs = published
    (clone / 'new.md').write_text('# New')
    commit(clone)
    monkeypatch.setattr('cplane.sessions.export_tree', Mock(side_effect=RuntimeError('synthetic failure')))
    with pytest.raises(RuntimeError):
        exporter.refresh()
    assert len(docs.search()) == 2
    assert docs.read('folder/plan.md')['title'] == 'Plan'


def client_for(published, store=None):
    app = create_app(store or Mock())
    app.config['DOCUMENT_ROOT'] = published[1].destination
    return app.test_client()


def test_document_search_and_metadata(published):
    client = client_for(published)
    result = client.get('/api/homelab/documents?q=SEARCHABLE')
    assert result.status_code == 200
    assert result.json == [dict(path='folder/plan.md', folder='folder', title='Plan', status='draft', date='2026-11-01')]
    result = client.get('/api/homelab/documents/folder/plan.md')
    assert result.status_code == 200
    assert result.json['markdown'].startswith('# Plan')
    assert '---' not in result.json['markdown']


@pytest.mark.parametrize('path', ['../secret.md', 'folder/../../secret.md', '/etc/passwd.md', 'folder/link.md', 'private.json', 'folder/./plan.md'])
def test_outside_export_refused(published, path):
    with pytest.raises(ValueError):
        published[2].read(path)
    if not path.startswith('/'):
        assert client_for(published).get('/api/homelab/documents/' + path).status_code == 404


def test_planted_symlink_components_refused(published, tmp_path):
    root = published[1].destination
    outside = tmp_path / 'outside'
    outside.mkdir()
    (outside / 'secret.md').write_text('private')
    (root / 'escape').symlink_to(outside, target_is_directory=True)
    (root / 'secret.md').symlink_to(outside / 'secret.md')
    for path in ('escape/secret.md', 'secret.md'):
        with pytest.raises(ValueError):
            published[2].read(path)
    assert len(published[2].search()) == 2


def test_swap_waits_for_readers_and_publishes_whole_tree(published, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event
    import fcntl
    from cplane import sessions

    clone, exporter, docs = published
    (clone / 'new.md').write_text('# New generation')
    (clone / 'backlog.md').unlink()
    commit(clone)
    swapping = Event()
    original = fcntl.flock

    def flock(fd, mode):
        if mode == fcntl.LOCK_EX:
            swapping.set()
        return original(fd, mode)

    monkeypatch.setattr(sessions.fcntl, 'flock', flock)
    with ThreadPoolExecutor(max_workers=1) as pool:
        with docs.snapshot() as fd:
            future = pool.submit(exporter.refresh)
            assert swapping.wait(5)
            assert not future.done()
            assert docs.read_at(fd, 'backlog.md')['title'] == 'Backlog'
            assert not (exporter.destination / 'new.md').exists()
        assert future.result(timeout=5)
    assert {d['path'] for d in docs.search()} == {'folder/plan.md', 'new.md'}
