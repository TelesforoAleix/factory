"""Owner-facing Home projection; source records remain authoritative."""
import os
import re
from datetime import datetime, timedelta, timezone

from cplane.runner import stuck_since
from cplane.attention import recipient
from cplane.installation import pending, install_failure, chat_requested, REQUEST
from cplane.chats import public_chat_result


# Event texts written by the planner, runner, installer, and feature pipeline.
MOVE_PATTERNS = [
    r'^state: ', r'^started$', r'^finished$', r'^merged: ',
    r'^install (requested|proposed|started|finished): ', r'^Installed ',
    r'^rollback\b', r'^escalation: Install ', r'^answer$', r'^stage .+ to ',
]


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
    orchestrator_count = 0
    owner_waiting = []

    def add(kind, identifier, since, **fields):
        attention.append(dict(kind=kind, id=identifier, since=since, **fields))

    owned = store.chat_attentions(slices) if hasattr(store, 'chat_attentions') else None
    stuck_notices = {(n.get('id'), n.get('since'), n.get('reason')) for n in notices if n.get('event') == 'stuck'}
    for s in slices:
        f = linked.get(s['id'])
        project = f['project'] if f else None
        chat = feature_chats.get(f['id']) if f else None
        a = owned.get(s['id'], s['attention']) if owned is not None else (store.chat_attention(s) if hasattr(store, 'chat_attention') else s['attention'])
        open_item = (a and s['state'] != 'accepted' and
                     ((a['kind'] == 'merge' and not a['approved']) or
                      (a['kind'] in ('node-step', 'question', 'escalation') and a['answer'] is None)))
        if open_item and recipient(s, a) == 'planner':
            orchestrator_count += 1
        if open_item and recipient(s, a) == 'owner':
            owner_waiting.append((s, a))
            base = dict(project=project, title=clean(s['title']), text=clean(a['body']),
                        feature=f['id'] if f else None, chat=chat['id'] if chat else None)
            if a['kind'] == 'merge' and not a['approved'] and a.get('review'):
                add('approval', s['id'], a['since'], **base, verdict=clean(a['review']['verdict']), pr=s['pr'])
            elif install_failure(a) and a['answer'] is None:
                add('failure', s['id'], a['since'], **base,
                    retry_install=a['kind'] == 'node-step' and s['repo'] in allowed,
                    installing=s['id'] in installing)
            elif a['kind'] == 'node-step' and a['answer'] is None:
                add('install', s['id'], a['since'], **base, installable=s['repo'] in allowed, installing=s['id'] in installing,
                    label='proposed by chat' if chat_requested(s) and s['id'] not in installing else None)
            elif a['kind'] in ('question', 'escalation') and a['answer'] is None:
                # Install and runner failures are recognizable from the current escalation.
                failure = a['kind'] == 'escalation' and (a['body'].startswith('Install ') or ' failed:' in a['body'].split('\n')[0])
                add('failure' if failure else 'question', s['id'], a['since'], **base)
        approval_wait = a and a['kind'] == 'merge' and not a['approved'] and a.get('review')
        stalled = stuck_since(s, datetime.now(timezone.utc))
        if approval_wait and stalled and stalled[1] == 'no new log activity':
            stalled = None
        if stalled and not (open_item and recipient(s, a) == 'planner'):
            since, reason = stalled
            if (s['id'], since.isoformat(), reason) in stuck_notices:
                add('stuck', s['id'], since.isoformat(), project=project, title=clean(s['title']), text=reason)
    by_chat = {c['id']: c for c in chats}
    paused_notices = {n.get('chat'): n for n in notices if n.get('event') == 'chat-paused'}
    for n in notices:
        c = by_chat.get(n.get('chat'))
        unread = (c and n.get('event') in ('owner-check', 'chat-paused')
                  and (not c.get('last_read_at')
                       or datetime.fromisoformat(c['last_read_at']) < datetime.fromisoformat(n['at'])))
        decision = n.get('event') == 'owner-check' and unread
        needs_help = c and c['kind'] in ('project', 'orchestrator')
        paused = (n.get('event') == 'chat-paused' and c and c.get('auto_paused')
                  and (needs_help or unread) and paused_notices[c['id']] is n)
        if decision or paused:
            fields = dict(text=clean(n.get('text', '')))
            if paused:
                fields['reactivate'] = True
                if needs_help:
                    fields.update(title=f"{clean(c['title'])} needs help",
                                  text='Chat paused after automatic turns; reactivate to continue.')
            add('decision', c.get('feature') or str(c['id']), n['at'], project=c.get('project'), chat=c['id'], **fields)
    waiting = {f['id'] for s, a in owner_waiting if (f := linked.get(s['id'])) and f['stage'] == 'building'}
    limits = store.limit_show()
    if len(waiting) >= limits['waiting_limit']:
        since = min((a['since'] for s, a in owner_waiting if linked.get(s['id'])
                     and linked[s['id']]['id'] in waiting), default=None)
        add('limit', 'pipeline', since, project=None, text=f"Waiting limit full ({len(waiting)}/{limits['waiting_limit']})")
    if hasattr(store, 'testing_review_waits'):
        attention.extend({**a, 'title': clean(a['title']), 'text': clean(a['text'])} for a in store.testing_review_waits())
    for feature in features:
        if feature['stage'] == 'acceptance':
            add('acceptance', feature['id'], None, project=feature['project'],
                title=clean(feature['title']), text='Run the checks')
    order = {k: i for i, k in enumerate(('acceptance', 'failure', 'approval', 'install', 'decision', 'question', 'testing-review', 'stuck', 'limit'))}
    attention.sort(key=lambda a: (order[a['kind']], a['since'] or ''))
    ordered = store.ordered_slices(slices) if hasattr(store, 'ordered_slices') else slices
    def slice_summary(s):
        return dict(id=s['id'], title=clean(s['title']), state=s['state'],
                    no_feature=clean(s.get('no_feature')) if s.get('no_feature') else None)
    building = []
    for feature in features:
        if feature['stage'] == 'building':
            group = [slice_summary(s) for s in ordered if linked[s['id']] is feature]
            building.append(dict(id=feature['id'], title=clean(feature.get('title', feature['id'])), project=feature['project'],
                                 slices=group, done=sum(s['state'] in ('accepted', 'dropped') for s in group), total=len(group)))
    unlinked = [slice_summary(s) | dict(project=None) for s in ordered
                if not s.get('feature_id') and s['state'] not in ('accepted', 'dropped')]
    running = []
    for s in slices:
        if s['state'] == 'issued':
            f = linked.get(s['id'])
            issued = next((e['at'] for e in reversed(s['log']) if e['event'] in ('started', 'resumed', 'issued', 'state: issued')), s['log'][0]['at'] if s['log'] else None)
            running.append(dict(id=s['id'], title=clean(s['title']), feature=f['id'] if f else clean(s['feature']), project=f['project'] if f else None, since=issued))
    running_now = [dict(item, kind='slice') for item in running]
    for s, request in pending(data):
        f = linked.get(s['id'])
        since = next(e['at'] for e in s['log'] if e['actor'] == 'owner' and e['event'] == REQUEST + request)
        running_now.append(dict(kind='install', id=s['id'], title=clean(s['title']), project=f['project'] if f else None, since=since))
    if hasattr(store, 'connection'):
        # Message time is the persisted enqueue time; run records can supply a later start.
        rows = store.connection.execute("SELECT m.session, m.time, (SELECT max(r.started_at) FROM cplane_run_records r WHERE r.kind = 'chat' AND r.session_id = m.session::text AND r.started_at >= m.time) FROM cplane_session_messages m JOIN cplane_sessions s ON s.id = m.session WHERE m.status = 'running' AND s.area = 'factory'")
        all_chats = {c['id']: c for c in public_chat_result(store.chats())}
        for chat_id, queued, started in rows:
            c = all_chats.get(chat_id)
            if c:
                running_now.append(dict(kind='chat', id=chat_id, title=clean(c['title']), project=c.get('project'), since=(started or queued).isoformat()))
    quick_chats = [dict(id=c['id'], title='Development Orchestrator') for c in chats if c['kind'] == 'orchestrator']
    by_project = {c['project']: c for c in chats if c['kind'] == 'project'}
    quick_chats.extend(dict(id=by_project[p['key']]['id'], title=clean(p['name']))
                       for p in board['projects'] if p.get('active', True) and p['key'] in by_project)
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=24)
    moves = []
    def move(kind, identifier, at, actor, event):
        instant = datetime.fromisoformat(at) if isinstance(at, str) else at
        if kind == 'slice' and (event.startswith(f'Answered {identifier}: ') or event == 'answer_slice'):
            event = f'Answered {identifier}'
            matched = True
        else:
            matched = any(re.search(pattern, event) for pattern in MOVE_PATTERNS)
        if cutoff <= instant <= now and matched:
            text = clean(event)
            moves.append((instant, dict(kind=kind, id=identifier, at=instant.isoformat(), actor=actor,
                                        event=text if len(text) <= 80 else text[:79] + '…')))
    for s in slices:
        for entry in s['log']:
            move('slice', s['id'], entry['at'], entry['actor'], entry['event'])
    if hasattr(store, 'connection'):
        rows = store.connection.execute(
            "SELECT f.id, e.time, e.actor, e.event FROM cplane_feature_events e "
            "JOIN cplane_features f ON f.feature = e.feature "
            "WHERE e.time >= now() - interval '24 hours' AND e.event LIKE 'stage %' "
            "AND e.event NOT LIKE '% slice %'")
        for identifier, at, actor, event in rows:
            move('feature', identifier, at, actor, event)
    moves.sort(key=lambda entry: entry[0], reverse=True)
    log = dict(moves=[entry for _, entry in moves[:200]], truncated=len(moves) > 200)
    return dict(log=log, quick_chats=quick_chats, projects=board['projects'], features=features, attention=attention, orchestrator_count=orchestrator_count, running=running, running_now=running_now, building=building, unlinked=unlinked,
                chats=[{k: clean(v) if k == 'title' else v for k, v in c.items() if k in ('id', 'title', 'project', 'feature', 'waiting')} for c in chats if c['waiting']])
