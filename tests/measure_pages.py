"""Disposable node-shaped API benchmark. Run with --source to compare a checkout.

CPLANE_TEST_DATABASE_URL must point to disposable Postgres 17. No private inputs.
"""
import argparse
import json
import os
from pathlib import Path
import statistics
import sys
import time
import uuid


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    sys.path.insert(0, str(args.source.resolve()))
    import psycopg
    from psycopg import sql
    from psycopg.conninfo import make_conninfo
    from cplane.stores import PostgresStore
    from factory_ui import create_app

    url = os.environ['CPLANE_TEST_DATABASE_URL']
    schema = 'benchmark_' + uuid.uuid4().hex
    with psycopg.connect(url, autocommit=True) as conn:
        assert conn.info.server_version // 10000 == 17
        conn.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(schema)))
        try:
            store = PostgresStore(make_conninfo(url, options=f'-c search_path={schema}'))
            store.migrate()
            features = [store.feature_add('FAC', f'Synthetic feature {i}', stage='building' if i < 4 else 'shortlist') for i in range(24)]
            for f in features:
                store.feature_section(f['id'], 'Overview', 'Synthetic design text. ' * 180)
            slices = []
            for i in range(41):
                item = dict(id=f'factory/S{i}', repo='example/repo', feature='Synthetic', feature_id=features[i % 24]['id'],
                            title=f'Synthetic slice {i}', state='ready', brief='briefs/synthetic.md',
                            executor=dict(tool='codex', model='synthetic'), stop_before_merge=True,
                            depends_on=[], slot=None, paused=False, session=None, pr=None, attention=None,
                            log=[dict(at='2026-11-07T12:00:00+00:00', actor='synthetic', event='Synthetic history. ' * 14) for _ in range(10)])
                slices.append(item)
            store.save(dict(version=1, slices=slices))
            sid = store.create_session('factory', 'Synthetic chat', 'codex', 'synthetic', [])
            for _ in range(4):
                store.session_messages('factory', sid, 'Synthetic owner text. ' * 20)
                turn = store.claim_session_turn()
                store.finish_session_turn(turn, 'Synthetic assistant text. ' * 20, 'synthetic-resume')
            client = create_app(store).test_client()
            result = {}
            for path in ['/api/home', '/api/pipeline', '/api/pipeline/' + features[0]['id'], f'/api/factory/sessions/{sid}/messages']:
                measurements = []
                for _ in range(7):
                    started = time.perf_counter()
                    response = client.get(path)
                    measurements.append((time.perf_counter() - started) * 1000)
                    assert response.status_code == 200, (path, response.json)
                result[path] = dict(median_ms=round(statistics.median(measurements), 2), max_ms=round(max(measurements), 2), bytes=len(response.data))
            print(json.dumps(result, indent=2))
        finally:
            conn.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(schema)))


if __name__ == '__main__':
    main()
