import React, {useEffect, useState} from 'react';
import {visiblePolling} from './polling';

const value = v => typeof v === 'string' && v ? v : '—';

export function HomeLabSettings() {
  const [data, setData] = useState({routes: null, providers: null});
  const [unavailable, setUnavailable] = useState(false);
  useEffect(() => {
    let live = true;
    async function poll() {
      const results = await Promise.allSettled(['routes', 'providers'].map(async kind => {
        const response = await fetch('/api/settings/home-lab/' + kind);
        if (!response.ok) throw Error();
        return response.json();
      }));
      if (!live) return;
      setData(previous => {
        const next = {...previous};
        ['routes', 'providers'].forEach((kind, i) => {
          if (results[i].status === 'fulfilled') next[kind] = results[i].value;
        });
        return next;
      });
      setUnavailable(results.some(result => result.status === 'rejected'));
    }
    const stop = visiblePolling(poll, 30000);
    return () => {live = false; stop();};
  }, []);
  const routes = Array.isArray(data.routes?.routes) ? data.routes.routes : [];
  const providers = Array.isArray(data.providers?.providers) ? data.providers.providers : [];
  return <div className="home-lab-settings"><a href="/settings">← Settings</a><h1>Home Lab</h1><p>Execution roles are on the <a href="/settings#roles">Settings page</a>.</p>{unavailable && <p role="status">Home Lab unavailable. Showing the last available data.</p>}
    <section><h2>Routes</h2>{data.routes === null ? <p>Loading routes…</p> : routes.length === 0 ? <p>No routes.</p> : routes.map((row, i) => <details className="home-lab-row" key={i}><summary><strong>{value(row?.purpose)}</strong><span>{row?.live ? <>{value(row.live.provider)} · {value(row.live.model)}</> : 'No live route'}</span><span>{value(row?.health)}</span></summary><ol>{(Array.isArray(row?.routes) ? row.routes : []).map((route, j) => <li key={j}>{value(route?.provider)} · {value(route?.model)} · {route?.enabled === true ? 'enabled' : route?.enabled === false ? 'disabled' : '—'}</li>)}</ol></details>)}</section>
    <section><h2>Providers</h2>{data.providers === null ? <p>Loading providers…</p> : providers.length === 0 ? <p>No providers.</p> : providers.map((provider, i) => <div className="home-lab-provider" key={i}><strong>{value(provider?.name)}</strong><span>{value(provider?.kind)} · {value(provider?.state)}</span><span>{Array.isArray(provider?.purposes) ? provider.purposes.filter(p => typeof p === 'string').join(', ') || '—' : '—'}</span></div>)}</section>
  </div>;
}
