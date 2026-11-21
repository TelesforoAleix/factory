"""The drain check that gates a contract step, and unknown-field findings.

A contract step removes an old shape. It may start only when the old shape's
usage counter has been zero for the agreed period and no work created before
the expand change merged is still open (skills/expand-contract.md). The check
fails closed: anything it cannot read means it does not pass. Results name
only Factory's own facts (slice ids, dates, reasons), never a Home Lab value.
"""

import hashlib
import json
import os
import re
import sys
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from . import planner, state
from .executors import atomic_json
from .text_bounds import ATTENTION_LIMIT, cut

USAGE_PATH = '/v1/contracts/usage'
CATALOG_FILE = 'contracts-catalog.json'
SEEN_FILE = 'contracts-usage-state.json'
DEFAULT_QUIET_DAYS = 7
NOT_CONFIGURED = 'run platform not configured'
CLOSED = ('accepted', 'dropped')
OPEN_RECORDS = ('queued', 'running', 'waiting', 'question')
# Names only; a row whose names do not fit is skipped, never echoed.
NAME = re.compile(r'[A-Za-z0-9_.:/{}\[\] -]{1,120}')


def parse_step(text):
    """Parse `contract=<name>,shape=<shape>,expand=<id>[,quiet_days=<n>]`."""
    values = {}
    for part in text.split(','):
        key, sep, value = part.partition('=')
        key, value = key.strip(), value.strip()
        if not sep or key not in ('contract', 'shape', 'expand', 'quiet_days') or key in values or not value:
            raise ValueError('--contract-step takes contract=<name>,shape=<shape>,'
                             'expand=<slice id>[,quiet_days=<n>]')
        values[key] = value
    if not {'contract', 'shape', 'expand'} <= set(values):
        raise ValueError('--contract-step requires contract, shape and expand')
    if 'quiet_days' in values:
        if not values['quiet_days'].isdigit() or int(values['quiet_days']) < 1:
            raise ValueError('--contract-step quiet_days must be a whole number from 1')
        values['quiet_days'] = int(values['quiet_days'])
    return values


def state_dir(context):
    path = context.get('state_path') or os.environ.get('CPLANE_STATE') or 'slices.json'
    return Path(path).parent


def read_usage():
    from . import run_platform
    try:
        value = run_platform.Connection().request(USAGE_PATH)
    except run_platform.Unavailable as error:
        # Our own client message: "Platform run HTTP <code>", never a response body.
        status = str(error).removeprefix('Platform run ')
        if status.startswith('settings') or status.startswith('key file'):
            return None, NOT_CONFIGURED
        if status == 'HTTP 404':
            return None, 'usage endpoint not served (HTTP 404)'
        if re.fullmatch(r'HTTP [0-9]{3}', status):
            return None, 'usage endpoint answered ' + status
        return None, 'usage endpoint unavailable'
    if not isinstance(value, dict):
        return None, 'usage answer unreadable'
    return value, None


def usage(context):
    """One endpoint read per pass when the caller supplies a cache dict."""
    cache = context.get('usage_cache')
    if cache is not None and 'value' in cache:
        return cache['value'], cache['error']
    value, error = read_usage()
    if cache is not None:
        cache.update(value=value, error=error)
    return value, error


def _merged_at(item):
    times = [entry['at'] for entry in item['log']
             if entry['event'].startswith('merged: ')
             and entry['event'].removeprefix('merged: ').strip()]
    return max((_instant(at) for at in times), default=None)


def _instant(text):
    value = datetime.fromisoformat(text)
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def _day(text):
    if not isinstance(text, str):
        raise ValueError
    return date.fromisoformat(text[:10])


def _repositories(context, contract):
    """Repositories the catalog lists as a user or the provider of a contract."""
    try:
        entries = json.loads((state_dir(context) / CATALOG_FILE).read_text())
        repositories = set()
        for entry in entries:
            if entry['contract'] == contract:
                repositories.add(entry['provider'].casefold())
                repositories.update(user['repository'].casefold() for user in entry['users'])
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return None, 'contract catalog unreadable'
    if not repositories:
        return None, 'contract not in the catalog'
    return repositories, None


def _running(job):
    records = [entry.get('record') or {} for entry in (job.get('requests') or {}).values()]
    return job.get('phase') == 'running' or any(
        record.get('status') in OPEN_RECORDS for record in records)


def drain(item, data):
    """Return passed, expand_merged_at, shape_last_seen, open_work and reason."""
    step = item['contract_step']
    context = data.get('_eligibility', {})
    result = dict(passed=False, expand_merged_at=None, shape_last_seen=None, open_work=[], reason=None)
    now = context.get('now') or datetime.now(UTC)
    by_id = {s['id']: s for s in data['slices']}
    expand = by_id.get(step['expand'])
    merged = _merged_at(expand) if expand else None
    if merged is None:
        result['reason'] = 'expand slice has not merged'
        return result
    result['expand_merged_at'] = merged.isoformat()

    value, error = usage(context)
    if error:
        result['reason'] = error
        return result
    quiet = step.get('quiet_days', DEFAULT_QUIET_DAYS)
    window = now.astimezone(UTC).date() - timedelta(days=quiet - 1)
    try:
        if value.get('contract') != step['contract'] or not isinstance(value.get('shapes'), list):
            result['reason'] = 'usage answer is for another contract or unreadable'
            return result
        since = _day(value.get('since'))
        days = [_day(row['day']) for row in value['shapes']
                if row['shape'] == step['shape'] and int(row['count']) > 0]
    except (ValueError, KeyError, TypeError, AttributeError):
        result['reason'] = 'usage answer unreadable'
        return result
    last = max(days, default=None)
    result['shape_last_seen'] = last.isoformat() if last else None
    if last is not None and last >= window:
        result['reason'] = f'old shape used within the last {quiet} days'
        return result
    if since > window:
        result['reason'] = f'usage counter covers fewer than {quiet} days'
        return result

    repositories, error = _repositories(context, step['contract'])
    if error:
        result['reason'] = error
        return result
    skip = {item['id'], step['expand']}
    open_work = []
    for other in data['slices']:
        if other['id'] in skip or other['state'] in CLOSED:
            continue
        if other['repo'].casefold() not in repositories:
            continue
        try:
            created = _instant(other['log'][0]['at']) if other['log'] else None
        except (ValueError, KeyError, TypeError):
            created = None
        # Unknown creation counts as old: fail closed.
        if created is None or created < merged:
            open_work.append(other['id'])
    merged_ns = (merged - datetime(1970, 1, 1, tzinfo=UTC)) // timedelta(microseconds=1) * 1000
    for job in (context.get('jobs') or {}).values():
        if job.get('id') in skip or not _running(job):
            continue
        if not isinstance(job.get('started_ns'), int) or job['started_ns'] < merged_ns:
            open_work.append(job.get('id') or 'unknown job')
    result['open_work'] = sorted(set(open_work))
    if result['open_work']:
        result['reason'] = 'work created before the expand change is still open'
        return result
    result.update(passed=True, reason='drained')
    return result


def _finding_id(contract, provider, application, operation, field):
    digest = hashlib.sha256('\0'.join((contract, application, operation, field)).encode()).hexdigest()
    return f"{provider.split('/')[-1]}/contract-{contract}-field-{digest[:10]}"


def _provider(context, contract):
    entries = json.loads((state_dir(context) / CATALOG_FILE).read_text())
    return next(entry['provider'] for entry in entries if entry['contract'] == contract)


def record_finding(path, contract, provider, application, operation, field):
    """One planner notice for a new unknown field, on the validated update path."""
    identifier = _finding_id(contract, provider, application, operation, field)
    event = 'unknown field reported'
    body = cut(f'Planner: the {contract} provider reports unknown field {field!r} in '
               f'{operation} from application {application!r}', ATTENTION_LIMIT)
    with state.locked(path):
        existing = next((s for s in state.load(path)['slices'] if s['id'] == identifier), None)
        if existing and any(log['event'] == event for log in existing['log']):
            return

        def change(item, data, at):
            if existing is None:
                item.update(repo=provider, feature='Contracts',
                            title=f'Review an unknown {contract} field',
                            no_feature='Contract usage finding needs planner review')
            item['attention'] = dict(kind='contract-change', body=body, since=at, answer=None,
                                     approved=False, **{'for': 'planner'})
            return f'Needs planner attention: {body}', None

        state.update_locked(path, identifier, 'contract-change', 'runner', change,
                            create=(lambda: planner.new_slice(identifier)) if existing is None else None,
                            event=event)


def findings(runner):
    """Raise a notice for each unknown-field row not seen before. Best effort."""
    try:
        _findings(runner)
    except Exception as error:  # noqa: BLE001
        print(f'cplane: contract usage findings failed: {type(error).__name__}', file=sys.stderr)


def _findings(runner):
    context = dict(state_path=runner.path, usage_cache=getattr(runner, 'usage_cache', None))
    value, error = usage(context)
    if error == NOT_CONFIGURED:
        return  # Like the update job without App settings: nothing to read.
    if error:
        print(f'cplane: contract usage findings skipped: {error}', file=sys.stderr)
        return
    contract = value['contract']
    rows = [(row['application'], row['operation'], row['field'])
            for row in value.get('unknown_fields') or []]
    if not isinstance(contract, str) or not NAME.fullmatch(contract):
        raise ValueError
    path = state_dir(context) / SEEN_FILE
    saved = json.loads(path.read_text()) if path.exists() else {}
    first = contract not in saved
    seen = {tuple(key) for key in saved.get(contract, [])}
    new = [key for key in dict.fromkeys(rows) if key not in seen]
    failed = None
    if new and not first:
        provider = _provider(context, contract)
        for key in new:
            if not all(isinstance(name, str) and NAME.fullmatch(name) for name in key):
                # Never echo an unreadable name; record it so it logs only once.
                failed = 'unreadable row'
                seen.add(key)
                continue
            try:
                record_finding(runner.path, contract, provider, *key)
            except Exception as error:  # noqa: BLE001
                failed = type(error).__name__
                continue
            seen.add(key)
    else:
        seen.update(new)
    if new or first:
        saved[contract] = sorted([list(key) for key in seen], key=json.dumps)
        atomic_json(path, saved)
    if failed:
        print(f'cplane: contract usage finding failed: {failed}', file=sys.stderr)
