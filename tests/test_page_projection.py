"""Slim lists and single-feature detail on disposable Postgres."""
import copy
from unittest.mock import Mock

from factory_ui import create_app
from test_stores import pg_store


def test_lists_are_bounded_and_detail_keeps_sections_and_slices(pg_store, slice_data, monkeypatch):
    features = [pg_store.feature_add('FAC', f'Card {i}', stage='building') for i in range(12)]
    for feature in features:
        pg_store.feature_section(feature['id'], 'Design', 'Private detail text ' * 500)
    items = []
    for i in range(41):
        item = copy.deepcopy(slice_data)
        item.update(id=f'factory/S{i}', feature_id=features[i % 12]['id'])
        item['log'] = [dict(at='2026-11-07T12:00:00+00:00', actor='tester', event='Detail history ' * 200)]
        items.append(item)
    items[0].update(state='issued', attention=dict(kind='question', body='Which?', since='2026-11-07T12:00:00+00:00', answer=None, approved=False))
    items[1]['state'] = 'accepted'
    pg_store.save(dict(version=1, slices=items))
    client = create_app(pg_store).test_client()
    with monkeypatch.context() as patch:
        patch.setattr(pg_store, 'feature_board', Mock(side_effect=AssertionError('Lists must not build detail')))
        for path in ('/api/home', '/api/pipeline'):
            response = client.get(path)
            assert response.status_code == 200
            assert len(response.data) < 40000
            for f in response.json['features']:
                assert not set(f) & {'slices', 'sections', 'moves', 'numbers', 'backlog', 'aliases'}
            first = next(f for f in response.json['features'] if f['id'] == features[0]['id'])
            assert first['waiting'] and first['open_attention'] == 1 and first['slice_count'] == 4
            assert first['extra'] == 'Waiting for you'
    with monkeypatch.context() as patch:
        patch.setattr(pg_store, 'feature_list', Mock(side_effect=AssertionError('Detail must not read all features')))
        response = client.get('/api/pipeline/' + features[0]['id'])
        assert response.status_code == 200
        assert response.json['sections'][0]['text'].startswith('Private detail text')
        assert len(response.json['slices']) == 4 and response.json['moves']
        assert response.json['project_name'] == 'factory'
        assert 'log' not in response.json['slices'][0]
        detail = client.get('/api/slices/' + response.json['slices'][0]['id'])
        assert detail.status_code == 200 and detail.json['log']
    # A moved feature remains addressable via its old alias and linked on Home.
    moved = pg_store.feature_move(features[0]['id'], 'LAB')
    assert client.get('/api/pipeline/' + features[0]['id']).json['id'] == moved['id']
    home = client.get('/api/home').json
    assert home['running'][0]['feature'] == moved['id']
    assert home['attention'][0]['project'] == 'LAB'


def test_cards_do_not_read_heavy_state_or_usage(pg_store, monkeypatch):
    pg_store.feature_add('FAC', 'Minimal')
    for method in ('load', 'feature_show', 'feature_list', 'run_record_list'):
        monkeypatch.setattr(pg_store, method, Mock(side_effect=AssertionError(method)))
    response = create_app(pg_store).test_client().get('/api/pipeline')
    assert response.status_code == 200 and response.json['features'][0]['title'] == 'Minimal'


def test_home_constructs_one_store_for_entire_request(pg_store, monkeypatch):
    # Production backend() constructs stores; nested independent locks would hang.
    monkeypatch.setenv('CPLANE_DATABASE_URL', pg_store._url)
    factory = Mock(return_value=pg_store)
    monkeypatch.setattr('factory_ui.PostgresStore', factory)
    assert create_app().test_client().get('/api/home').status_code == 200
    factory.assert_called_once()


def test_read_projections_match_validated_load_and_writes_still_validate(pg_store, slice_data, monkeypatch):
    import pytest
    from cplane.state import StateError
    feature = pg_store.feature_add('FAC', 'Synthetic feature', stage='building')
    item = copy.deepcopy(slice_data)
    item['feature_id'] = feature['id']
    pg_store.save(dict(version=1, slices=[item]))
    client = create_app(pg_store).test_client()
    paths = ('/api/home', '/api/pipeline/' + feature['id'])
    projected = [client.get(path).json for path in paths]
    with monkeypatch.context() as patch:
        patch.setattr(pg_store, 'page_state', pg_store.load)
        assert [client.get(path).json for path in paths] == projected
    item['paused'] = 'invalid'
    with pytest.raises(StateError, match='invalid state'):
        pg_store.save(dict(version=1, slices=[item]))
    assert pg_store.load()['slices'][0]['paused'] is False
