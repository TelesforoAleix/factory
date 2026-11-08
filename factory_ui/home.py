"""Owner-facing Home projection; source records remain authoritative."""
import os
from datetime import datetime, timezone

from cplane.runner import stuck_since
from cplane.installation import pending
from cplane.chats import public_chat_result


def home_data(store, board, clean, view):
    data = store.load()
    slices = data['slices']
    notices = [n for _, n in store.notices()]
    chats = public_chat_result(store.chats(archived=False))
    features = board['features']
    linked = {s['id']: f for f in features for s in f['slices']}
    feature_chats = {c['feature']: c for c in chats if c.get('kind') == 'feature' and c.get('feature')}
    allowed = os.environ.get('CPLANE_INSTALL_REPOS', '').split(',')
    installing = {s['id'] for s, _ in pending(data)}
    attention = []

    def add(kind, identifier, since, **fields):
        attention.append(dict(kind=kind, id=identifier, since=since, **fields))

    for s in slices:
        f = linked.get(s['id'])
        project = f['project'] if f else None
        chat = feature_chats.get(f['id']) if f else None
        a = store.chat_attention(s) if hasattr(store, 'chat_attention') else s['attention']
        if a and s['state'] != 'accepted':
            base = dict(project=project, title=clean(s['title']), text=clean(a['body']),
                        feature=f['id'] if f else None, chat=chat['id'] if chat else None)
            if a['kind'] == 'merge' and not a['approved'] and a.get('review'):
                add('approval', s['id'], a['since'], **base, verdict=clean(a['review']['verdict']), pr=s['pr'])
            elif a['kind'] == 'node-step' and a['answer'] is None:
                add('install', s['id'], a['since'], **base, installable=s['repo'] in allowed, installing=s['id'] in installing)
            elif a['kind'] in ('question', 'escalation') and a['answer'] is None and not a.get('chat_id'):
                # Install and runner failures are recognizable from the current escalation.
                failure = a['kind'] == 'escalation' and (a['body'].startswith('Install ') or ' failed:' in a['body'].split('\n')[0])
                add('failure' if failure else 'question', s['id'], a['since'], **base)
        stalled = stuck_since(s, datetime.now(timezone.utc))
        if stalled:
            since, reason = stalled
            if any(n.get('event') == 'stuck' and n.get('id') == s['id'] and n.get('since') == since.isoformat() and n.get('reason') == reason for n in notices):
                add('stuck', s['id'], since.isoformat(), project=project, title=clean(s['title']), text=reason)
    by_chat = {c['id']: c for c in chats}
    paused_notices = {n.get('chat'): n for n in notices if n.get('event') == 'chat-paused'}
    for n in notices:
        c = by_chat.get(n.get('chat'))
        decision = n.get('event') == 'owner-check' and c and (not c.get('last_read_at') or c['last_read_at'] < n['at'])
        paused = n.get('event') == 'chat-paused' and c and c.get('auto_paused') and paused_notices[c['id']] is n
        if decision or paused:
            add('decision', c.get('feature') or str(c['id']), n['at'], project=c.get('project'), chat=c['id'], text=clean(n.get('text', '')))
    waiting = [f for f in features if f['stage'] == 'building' and any(s['attention'] and s['attention']['answer'] is None for s in f['slices'])]
    limits = store.limit_show()
    if len(waiting) >= limits['waiting_limit']:
        add('limit', 'pipeline', min((s['attention']['since'] for f in waiting for s in f['slices'] if s['attention'] and s['attention']['answer'] is None), default=None), project=None, text=f"Waiting limit full ({len(waiting)}/{limits['waiting_limit']})")
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
    return dict(projects=board['projects'], features=features, attention=attention, running=running,
                chats=[{k: clean(v) if k == 'title' else v for k, v in c.items() if k in ('id', 'title', 'project', 'feature', 'waiting')} for c in chats if c['waiting']])
