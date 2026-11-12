from contextlib import nullcontext
from datetime import datetime, timezone

from cplane.planner import new_slice
from factory_ui.home import home_data


def test_home_now_projection():
    at = '2026-01-01T00:00:00+00:00'
    def item(identifier, state, feature=None, reason=None):
        s = new_slice(identifier)
        s.update(title=identifier, state=state, feature_id=feature)
        s['log'] = [dict(at=at, actor='runner', event='started')]
        if reason:
            s['no_feature'] = reason
        return s
    slices = [item('run', 'issued', 'old'), item('drop', 'dropped', 'F1'),
              item('done', 'accepted', 'F1'), item('free', 'ready', reason='Maintenance'),
              item('free2', 'planned'), item('closed', 'dropped')]
    slices[0]['log'].append(dict(at=at, actor='owner', event='install requested: abc'))
    features = [dict(id='F2', title='Second', stage='building', project='P'),
                dict(id='F1', title='First', stage='building', project='P'),
                dict(id='N', title='Next', stage='next', project='P')]
    class Connection:
        def execute(self, query):
            return [(7, datetime.fromisoformat(at), None)]
    class Store:
        connection = Connection()
        def load(self): return dict(slices=slices)
        def chats(self, **kwargs): return [dict(id=7, kind='project', project='P', title='Planning', feature=None, waiting=False)]
        def notices(self): return []
        def feature_links(self): return {'old': 'F1', 'F1': 'F1'}
        def ordered_slices(self, entries): return list(reversed(entries))
        def limit_show(self): return dict(waiting_limit=3)
    result = home_data(Store(), dict(features=features, projects=[]), lambda x: x, None)
    assert [(r['kind'], r['id']) for r in result['running']] == [('slice', 'run'), ('install', 'run'), ('chat', 7)]
    assert all(r['since'] == at for r in result['running'])
    assert [f['id'] for f in result['building']] == ['F2', 'F1']
    assert (result['building'][1]['done'], result['building'][1]['total']) == (2, 3)
    assert [s['id'] for s in result['building'][1]['slices']] == ['done', 'drop', 'run']
    assert [f['id'] for f in result['features'] if f['stage'] == 'next'] == ['N']
    assert [(s['id'], s['no_feature']) for s in result['unlinked']] == [('free2', None), ('free', 'Maintenance')]
