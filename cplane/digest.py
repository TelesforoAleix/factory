"""Content-free daily summaries over existing scheduler history."""
from datetime import datetime, time, timedelta, timezone

from .times import LOCAL


def build(data, records, end):
    """Summarize the 24 elapsed hours ending at an aware instant."""
    end = end.astimezone(timezone.utc)
    start = end - timedelta(hours=24)

    def instant(value):
        try:
            result = datetime.fromisoformat(value)
            return result.astimezone(timezone.utc) if result.utcoffset() is not None else None
        except (TypeError, ValueError):
            return None

    def in_window(value):
        at = instant(value)
        return at is not None and start <= at < end

    groups = {name: set() for name in ('Merged', 'Installed', 'Install failed or rolled back',
                                        'Corrections opened', 'Class 2 merged', 'Guard stops')}
    waiting = []
    for item in data['slices']:
        identifier = item['id']
        for entry in item['log']:
            if not in_window(entry['at']):
                continue
            event = entry['event']
            if event.startswith(('merged: ', 'merged as ')):
                groups['Merged'].add(identifier)
                eligible = [r for r in records if r.get('slice_id') == identifier
                            and r.get('change_class') in (1, 2, 4)
                            and instant(r.get('started_at')) is not None
                            and instant(r['started_at']) <= instant(entry['at'])]
                if eligible and max(eligible, key=lambda r: instant(r['started_at']))['change_class'] == 2:
                    groups['Class 2 merged'].add(identifier)
            if event.startswith('Installed '):
                groups['Installed'].add(identifier)
            if event.startswith('escalation: Install failed'):
                groups['Install failed or rolled back'].add(identifier)
            if event.startswith('slice link: corrects '):
                groups['Corrections opened'].add(identifier)
            if event.startswith('merge: Approve PR #') and ': class 4 paths' in event:
                groups['Guard stops'].add(identifier)
        attention = item.get('attention')
        if item.get('state') != 'accepted' and attention:
            kind = attention['kind']
            if ((kind == 'merge' and not attention.get('approved')) or
                (kind in ('question', 'escalation', 'node-step') and attention.get('answer') is None) or
                kind in ('owner-check', 'testing-review')):
                waiting.append((identifier, attention['since']))
    lines = [f"{name}: {len(ids)} ({', '.join(sorted(ids))})" for name, ids in groups.items() if ids]
    if waiting:
        lines.append(f"Waiting for owner: {len(waiting)} (" + ', '.join(
            f'{identifier} since {since}' for identifier, since in sorted(waiting)) + ')')
    tasks = [r for r in records if r.get('kind') == 'task' and in_window(r.get('started_at'))]
    if tasks and all(isinstance(r.get('cost'), (int, float)) and not isinstance(r['cost'], bool) for r in tasks):
        lines.append(f"Task spend: {sum(r['cost'] for r in tasks):.2f}")
    return '\n'.join(lines)


def boundary(day):
    return datetime.combine(day, time(7), LOCAL)
