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
    parser.add_argument('--http', action='store_true', help='Measure HTTP over 127.0.0.1')
    parser.add_argument('--projects', action='store_true', help='Include the project page')
    parser.add_argument('--profile', type=Path, help='Write one cProfile per endpoint to this directory')
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
                item = dict(id=f'factory/S{i}', repo='example/repo', feature='Synthetic', feature_id=features[0]['id'],
                            title=f'Synthetic slice {i}', state='ready', brief='briefs/synthetic.md',
                            executor=dict(tool='codex', model='synthetic'), stop_before_merge=True,
                            depends_on=[], slot=None, paused=False, session=None, pr=None, attention=None,
                            final=dict(kind='handover', body='Synthetic final message. ' * 100, at='2026-11-07T12:00:00+00:00'),
                            log=[dict(at='2026-11-07T12:00:00+00:00', actor='synthetic', event='Synthetic history. ' * 14) for _ in range(10)])
                slices.append(item)
            store.save(dict(version=1, slices=slices))
            sid = store.create_session('factory', 'Synthetic chat', 'codex', 'synthetic', [])
            for _ in range(4):
                store.session_messages('factory', sid, 'Synthetic owner text. ' * 20)
                turn = store.claim_session_turn()
                store.finish_session_turn(turn, 'Synthetic assistant text. ' * 20, 'synthetic-resume')
            client = create_app(store).test_client()
            server = None
            if args.http:
                from threading import Thread
                from urllib.request import build_opener, ProxyHandler
                local_http = build_opener(ProxyHandler({}))
                from werkzeug.serving import make_server, WSGIRequestHandler
                class QuietHandler(WSGIRequestHandler):
                    def log_request(self, *args, **kwargs):
                        pass
                server = make_server('127.0.0.1', 0, create_app(store), request_handler=QuietHandler)
                thread = Thread(target=server.serve_forever, daemon=True)
                thread.start()
            paths = ['/api/home', '/api/pipeline', '/api/pipeline/' + features[0]['id'], f'/api/factory/sessions/{sid}/messages']
            if args.projects:
                paths.append('/api/projects/FAC')
            result = {}
            for path in paths:
                measurements = []
                if args.profile:
                    import cProfile
                    args.profile.mkdir(parents=True, exist_ok=True)
                    profiler = cProfile.Profile()
                    profiler.runcall(client.get, path)
                    profiler.dump_stats(str(args.profile / (path.strip('/').replace('/', '_') + '.prof')))
                for _ in range(7):
                    started = time.perf_counter()
                    if server:
                        with local_http.open(f'http://127.0.0.1:{server.server_port}' + path, timeout=10) as response:
                            body = response.read()
                            status = response.status
                    else:
                        response = client.get(path)
                        body, status = response.data, response.status_code
                    measurements.append((time.perf_counter() - started) * 1000)
                    assert status == 200, (path, body)
                result[path] = dict(median_ms=round(statistics.median(measurements), 2), max_ms=round(max(measurements), 2), bytes=len(body))
            if server:
                server.shutdown()
                thread.join()
            print(json.dumps(result, indent=2))
        finally:
            conn.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(schema)))


if __name__ == '__main__':
    main()
