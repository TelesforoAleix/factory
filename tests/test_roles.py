"""Execution levels replace external role-command lookup."""
import pytest
from cplane.cli import main, parser
from cplane.state import load
from cplane.roles import DEFAULT_LEVELS

ADD = ['add', '--id', 'new/W2', '--repo', 'example/repo', '--feature', 'f', '--title', 'T', '--no-feature', 'One-off']

@pytest.mark.parametrize('level', ['light', 'standard', 'strong'])
def test_file_level_snapshot_and_no_external_command(make_state, tmp_path, monkeypatch, level):
    path = make_state([])
    monkeypatch.setenv('CPLANE_RUNS', str(tmp_path / 'runs'))
    (tmp_path / 'roles-command').write_text('/must/never/run')
    assert main(['--state', str(path), *ADD, '--level', level]) == 0
    assert load(path)['slices'][0]['executor'] == DEFAULT_LEVELS[level]


def test_default_and_explicit_overrides(make_state):
    path = make_state([])
    assert main(['--state', str(path), *ADD, '--model', 'custom', '--effort', 'high']) == 0
    assert load(path)['slices'][0]['executor'] == dict(tool='codex', model='custom', effort='high')


def test_role_option_removed():
    with pytest.raises(SystemExit):
        parser().parse_args([*ADD, '--role', 'cutter'])
