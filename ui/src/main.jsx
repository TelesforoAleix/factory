import React, {useEffect, useState} from 'react';
import {createRoot} from 'react-dom/client';
import {BrowserRouter, Link, NavLink, Route, Routes, useParams} from 'react-router-dom';
import './style.css';
function Empty({title}) { return <><h1>{title}</h1><p className="muted">Nothing here yet.</p></>; }
function useSlices(id) {
  const [result, setResult] = useState({loading: true});
  useEffect(() => {
    const controller = new AbortController(); setResult({loading: true});
    fetch('/api/slices' + (id ? '/' + id.split('/').map(encodeURIComponent).join('/') : ''), {signal: controller.signal})
      .then(response => { if (!response.ok) throw new Error(); return response.json(); })
      .then(data => setResult({data})).catch(error => { if (error.name !== 'AbortError') setResult({error: true}); });
    return () => controller.abort();
  }, [id]); return result;
}
function Slices() {
  const result = useSlices();
  return <><h1>Slices</h1>{result.loading ? <p>Loading…</p> : result.error ? <p>Unable to load slices.</p> : !result.data.length ? <p className="muted">No slices yet.</p> : <div className="list">{result.data.map(item => <Link className="card" key={item.id} to={'/factory/slices/' + item.id.split('/').map(encodeURIComponent).join('/')}><span><strong>{item.title}</strong><small>{item.id}</small></span><span>{item.state}{item.paused ? ' · paused' : ''}</span></Link>)}</div>}</>;
}
function Detail() {
  const {project, slice} = useParams(); const result = useSlices(project + '/' + slice);
  if (result.loading) return <p>Loading…</p>; if (result.error) return <p>Unable to load slice.</p>;
  const item = result.data;
  return <><Link to="/factory/slices">← All slices</Link><h1>{item.title}</h1><p className="muted">{item.id} · {item.state}{item.paused ? ' · paused' : ''}</p><section><h2>Details</h2><dl><dt>Repository</dt><dd>{item.repo}</dd><dt>Feature</dt><dd>{item.feature}</dd><dt>Executor</dt><dd>{item.executor.tool} · {item.executor.model}</dd><dt>Dependencies</dt><dd>{item.depends_on.join(', ') || 'None'}</dd><dt>Scheduled</dt><dd>{item.slot || 'Not scheduled'}</dd><dt>Pull request</dt><dd>{item.pr ? '#' + item.pr : 'None'}</dd></dl></section><section><h2>Attention</h2>{item.attention ? <><strong>{item.attention.kind}</strong><p className="text">{item.attention.body}</p>{item.attention.answer && <p className="text">{item.attention.answer}</p>}</> : <p className="muted">No attention needed.</p>}</section><section><h2>Log</h2>{item.log.length ? <ul className="log">{item.log.map((entry, i) => <li key={i}><small>{entry.at} · {entry.actor}</small><div className="text">{entry.event}</div></li>)}</ul> : <p className="muted">No log entries.</p>}</section></>;
}
export function App() { return <div className="shell"><header><Link className="brand" to="/home-lab">Factory home</Link><nav aria-label="Areas"><NavLink to="/home-lab">Home Lab</NavLink><NavLink to="/factory">Factory</NavLink></nav></header><main><Routes><Route path="/" element={<Empty title="Home Lab"/>}/><Route path="/home-lab/*" element={<Empty title="Home Lab"/>}/><Route path="/factory" element={<Slices/>}/><Route path="/factory/slices" element={<Slices/>}/><Route path="/factory/slices/:project/:slice" element={<Detail/>}/><Route path="*" element={<Empty title="Not found"/>}/></Routes></main></div>; }
if (document.getElementById('root')) createRoot(document.getElementById('root')).render(<BrowserRouter><App/></BrowserRouter>);
