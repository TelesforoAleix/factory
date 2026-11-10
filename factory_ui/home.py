"""Owner-facing Home projection; source records remain authoritative."""
import os
from datetime import datetime, timezone

from cplane.runner import stuck_since
from cplane.installation import pending, install_failure
from cplane.chats import public_chat_result


def home_data(store, board, clean, view):
    data = store.page_state() if hasattr(store, 'page_state') else store.load()
    slices = data['slices']
    chats = public_chat_result(store.chats(archived=False))
    notices = [n for _, n in (store.home_notices(slices, chats) if hasattr(store, 'home_notices') else store.notices())]
    features = board['features']
    by_feature = {f['id']: f for f in features}
    aliases = store.feature_links() if hasattr(store, 'feature_links') else {}
    linked = {s['id']: by_feature.get(aliases.get(s.get('feature_id'), s.get('feature_id'))) for s in slices}
    feature_chats = {c['feature']: c for c in chats if c.get('kind') == 'feature' and c.get('feature')}
    allowed = os.environ.get('CPLANE_INSTALL_REPOS', '').split(',')
    installing = {s['id'] for s, _ in pending(data)}
    attention = []

    def add(kind, identifier, since, **fields):
        attention.append(dict(kind=kind, id=identifier, since=since, **fields))

    owned = store.chat_attentions(slices) if hasattr(store, 'chat_attentions') else None
    stuck_notices = {(n.get('id'), n.get('since'), n.get('reason')) for n in notices if n.get('event') == 'stuck'}
    for s in slices:
        f = linked.get(s['id'])
        project = f['project'] if f else None
        chat = feature_chats.get(f['id']) if f else None
        a = owned.get(s['id'], s['attention']) if owned is not None else (store.chat_attention(s) if hasattr(store, 'chat_attention') else s['attention'])
        if a and s['state'] != 'accepted':
            base = dict(project=project, title=clean(s['title']), text=clean(a['body']),
                        feature=f['id'] if f else None, chat=chat['id'] if chat else None)
            if a['kind'] == 'merge' and not a['approved'] and a.get('review'):
                add('approval', s['id'], a['since'], **base, verdict=clean(a['review']['verdict']), pr=s['pr'])
            elif install_failure(a) and a['answer'] is None:
                add('failure', s['id'], a['since'], **base,
                    retry_install=a['kind'] == 'node-step' and s['repo'] in allowed,
                    installing=s['id'] in installing)
            elif a['kind'] == 'node-step' and a['answer'] is None:
                add('install', s['id'], a['since'], **base, installable=s['repo'] in allowed, installing=s['id'] in installing)
            elif a['kind'] in ('question', 'escalation') and a['answer'] is None and not a.get('chat_id'):
                # Install and runner failures are recognizable from the current escalation.
                failure = a['kind'] == 'escalation' and (a['body'].startswith('Install ') or ' failed:' in a['body'].split('\n')[0])
                add('failure' if failure else 'question', s['id'], a['since'], **base)
        approval_wait = a and a['kind'] == 'merge' and not a['approved'] and a.get('review')
        stalled = stuck_since(s, datetime.now(timezone.utc))
        if approval_wait and stalled and stalled[1] == 'no new log activity':
            stalled = None
        if stalled:
            since, reason = stalled
            if (s['id'], since.isoformat(), reason) in stuck_notices:
                add('stuck', s['id'], since.isoformat(), project=project, title=clean(s['title']), text=reason)
    by_chat = {c['id']: c for c in chats}
    paused_notices = {n.get('chat'): n for n in notices if n.get('event') == 'chat-paused'}
    for n in notices:
        c = by_chat.get(n.get('chat'))
        unread = c and (not c.get('last_read_at') or c['last_read_at'] < n['at'])
        decision = n.get('event') == 'owner-check' and unread
        paused = n.get('event') == 'chat-paused' and unread and c.get('auto_paused') and paused_notices[c['id']] is n
        if decision or paused:
            add('decision', c.get('feature') or str(c['id']), n['at'], project=c.get('project'), chat=c['id'], text=clean(n.get('text', '')))
    waiting = {f['id'] for s in slices if (f := linked.get(s['id'])) and f['stage'] == 'building'
               and s['attention'] and s['attention']['answer'] is None}
    limits = store.limit_show()
    if len(waiting) >= limits['waiting_limit']:
        since = min((s['attention']['since'] for s in slices if linked.get(s['id'])
                     and linked[s['id']]['id'] in waiting and s['attention'] and s['attention']['answer'] is None), default=None)
        add('limit', 'pipeline', since, project=None, text=f"Waiting limit full ({len(waiting)}/{limits['waiting_limit']})")
    if hasattr(store, 'testing_review_waits'):
        attention.extend({**a, 'title': clean(a['title']), 'text': clean(a['text'])} for a in store.testing_review_waits())
    order = {k: i for i, k in enumerate(('failure', 'approval', 'install', 'decision', 'question', 'testing-review', 'stuck', 'limit'))}
    attention.sort(key=lambda a: (order[a['kind']], a['since'] or ''))
    running = []
    for s in slices:
        if s['state'] == 'issued':
            f = linked.get(s['id'])
            issued = next((e['at'] for e in reversed(s['log']) if e['event'] in ('started', 'resumed', 'issued')), s['log'][0]['at'] if s['log'] else None)
            running.append(dict(id=s['id'], title=clean(s['title']), feature=f['id'] if f else clean(s['feature']), project=f['project'] if f else None, since=issued))
    quick_chats = [dict(id=c['id'], title='Development Orchestrator') for c in chats if c['kind'] == 'orchestrator']
    by_project = {c['project']: c for c in chats if c['kind'] == 'project'}
    quick_chats.extend(dict(id=by_project[p['key']]['id'], title=clean(p['name']))
                       for p in board['projects'] if p.get('active', True) and p['key'] in by_project)
    return dict(quick_chats=quick_chats, projects=board['projects'], features=features, attention=attention, running=running,
                chats=[{k: clean(v) if k == 'title' else v for k, v in c.items() if k in ('id', 'title', 'project', 'feature', 'waiting')} for c in chats if c['waiting']])
