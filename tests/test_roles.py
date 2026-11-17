"""Slices select levels; model choices are exclusively platform policy."""
import pytest
from cplane.cli import main, parser
from cplane.state import load
from cplane.runner import Runner

ADD = ['add', '--id', 'new/W2', '--repo', 'example/repo', '--feature', 'f', '--title', 'T', '--no-feature', 'One-off']

@pytest.mark.parametrize('level', ['light', 'standard', 'strong'])
def test_level_uses_locked_mutation_path(make_state, level):
    path = make_state([])
    assert main(['--state', str(path), '--actor', 'planner', *ADD, '--level', level]) == 0
    item = load(path)['slices'][0]
    assert Runner(path).execution(item) == level
    assert any(e['actor'] == 'planner' and e['event'] == 'level: ' + level for e in item['log'])

@pytest.mark.parametrize('option', ['--tool', '--model', '--effort', '--role'])
def test_slice_executor_options_removed(option):
    with pytest.raises(SystemExit):
        parser().parse_args([*ADD, option, 'custom'])
