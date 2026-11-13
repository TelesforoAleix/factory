"""Pin the instructions and the prompts passed to both supported CLIs."""
import hashlib
import json
from pathlib import Path

import pytest

from cplane import prompts, sessions


@pytest.fixture
def original_prompts():
    return json.loads((Path(__file__).parent / 'fixtures/prompts.json').read_text())


def test_prompt_catalog_and_hashes(original_prompts):
    assert prompts.names() == sorted(original_prompts)
    for name, expected in original_prompts.items():
        assert prompts.text(name) == expected
        assert prompts.sha256(name) == hashlib.sha256(expected.encode('utf-8')).hexdigest()


def test_missing_prompt_names_the_file(tmp_path, monkeypatch):
    monkeypatch.setattr(prompts, 'ROOT', tmp_path)
    with pytest.raises(RuntimeError, match="Cannot read prompt 'missing'"):
        prompts.text('missing')


@pytest.mark.parametrize('tool', ['codex', 'claude'])
@pytest.mark.parametrize('kind', [None, 'orchestrator', 'project', 'feature', 'secretary'])
@pytest.mark.parametrize('area', ['factory', 'homelab'])
def test_turn_prompt_preserves_original_instructions(tmp_path, original_prompts, tool, kind, area):
    turn = dict(id=7, text='Owner message', context='Context', role='system', session=dict(
        kind=kind, area=area, tool=tool, model='synthetic', effort='medium', cli_session_id=None))
    expected = 'Context\n\nCurrent message:\nWorkshop event: Owner message'
    if kind:
        expected += '\n\nCurrent message ID: 7\n\n' + original_prompts[
            'secretary' if kind == 'secretary' else 'chat']
    if area == 'homelab':
        expected += '\n\n' + original_prompts['homelab']
    assert sessions.turn_command(turn, tmp_path, [], tmp_path / 'run')[-1] == expected


def test_unreadable_prompt_names_the_file(tmp_path, monkeypatch):
    monkeypatch.setattr(prompts, 'ROOT', tmp_path)
    (tmp_path / 'chat.md').mkdir()
    with pytest.raises(RuntimeError, match="Cannot read prompt 'chat'"):
        prompts.sha256('chat')
