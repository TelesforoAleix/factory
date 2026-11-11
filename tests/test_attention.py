import pytest
from cplane.attention import recipient


@pytest.mark.parametrize(('kind', 'body', 'repo', 'expected'), [
    ('escalation', 'failing check: test', 'other/repo', 'planner'),
    ('escalation', 'missing brief', 'other/repo', 'planner'),
    ('node-step', 'Manual work', 'other/repo', 'planner'),
    ('merge', 'Approve', 'other/repo', 'owner'),
    ('node-step', 'Install', 'owner/repo', 'owner'),
    ('escalation', 'Install failed', 'other/repo', 'owner'),
])
def test_recipient(monkeypatch, kind, body, repo, expected):
    monkeypatch.setenv('CPLANE_INSTALL_REPOS', 'owner/repo')
    item = {'repo': repo, 'attention': {'kind': kind, 'body': body}}
    assert recipient(item) == expected
    item['attention']['for'] = 'planner' if expected == 'owner' else 'owner'
    assert recipient(item) != expected
