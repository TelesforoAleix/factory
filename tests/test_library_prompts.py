import hashlib

from cplane import prompts
from factory_ui import create_app


def test_prompt_endpoints_use_loader_and_reject_unknown_names(tmp_path, monkeypatch):
    (tmp_path / 'sample.md').write_bytes(b'Synthetic prompt.\n')
    monkeypatch.setattr(prompts, 'ROOT', tmp_path)
    client = create_app().test_client()
    expected = hashlib.sha256(b'Synthetic prompt.').hexdigest()
    assert client.get('/api/prompts').json == [dict(name='sample', sha256=expected)]
    assert client.get('/api/prompts/sample').json == dict(
        name='sample', sha256=prompts.sha256('sample'), text=prompts.text('sample'))
    assert client.get('/api/prompts/missing').status_code == 404
    assert client.get('/api/prompts/..%2Fsample').status_code == 404
    assert client.post('/api/prompts/sample', headers={'X-Factory-UI': '1'}).status_code == 405


def test_skill_endpoints_hash_original_file_bytes(tmp_path, monkeypatch):
    from cplane import skills

    raw = b'--- {"name": "example", "description": "Example"}\r\nInstructions.\r\n'
    (tmp_path / 'example.md').write_bytes(raw)
    monkeypatch.setattr(skills, 'ROOT', tmp_path)

    class Store:
        def skill_list(self):
            return [dict(**item, version='revision', projects=[]) for item in skills.catalog()]

    client = create_app(Store()).test_client()
    expected = hashlib.sha256(raw).hexdigest()
    assert client.get('/api/skills').json[0]['sha256'] == expected
    assert client.get('/api/skills/example').json['sha256'] == expected
