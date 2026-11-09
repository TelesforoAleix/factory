"""Project page projection, sharing Home's owner attention policy."""
from cplane.chats import public_chat_result
from cplane.features import STAGES


def project_data(store, project, home, clean):
    key = project['key']
    features = [f for f in home['features'] if f['project'] == key]
    chats = [dict(id=c['id'], title=clean(c['title']), kind=c['kind'], feature=c.get('feature'))
             for c in public_chat_result(store.chats(project=key))
             if c['kind'] == 'project' or c['kind'] == 'feature' and not c['archived']]
    chats.sort(key=lambda c: (c['kind'] != 'project', c['id']))
    return dict(project=project, attention=[a for a in home['attention'] if a.get('project') == key],
                features=features, running=[r for r in home['running'] if r.get('project') == key],
                stages={s: sum(f['stage'] == s for f in features) for s in STAGES},
                chats=chats, usage=store.project_usage(key))
