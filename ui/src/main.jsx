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
  const [result, setResult] = useState(null);
  useEffect(() => { fetch('/api/pending').then(r => { if (!r.ok) throw Error(); return r.json(); }).then(setResult).catch(() => setResult({error: true})); }, []);
  if (!result) return <p>Loading…</p>;
  if (result.error) return <p>Unable to load slices.</p>;
  const groups = Array.isArray(result) ? {} : result;
  return <><h1>Factory</h1>{!Object.values(groups).some(items => items.length) && <p className="muted">No slices yet.</p>}{Object.entries(groups).map(([name, items]) => <section key={name}><h2>{name === 'needs attention' ? 'Needs your attention' : name}</h2>{items.length ? <div className="list">{items.map(item => <Link className="card" key={item.id} to={'/factory/slices/' + item.id.split('/').map(encodeURIComponent).join('/')}><span><strong>{item.title}</strong><small>{item.id}{item.attention ? ' · ' + item.attention.kind : ''}</small></span><span>{item.state}{item.paused ? ' · paused' : ''}</span></Link>)}</div> : <p className="muted">None.</p>}</section>)}</>;
}
function Detail() {
  const {project, slice} = useParams(); const id = project + '/' + slice;
  const result = useSlices(id);
  const [item, setItem] = useState(null); const [message, setMessage] = useState(''); const [answer, setAnswer] = useState(''); const [verdict, setVerdict] = useState(''); const [confirm, setConfirm] = useState(false);
  useEffect(() => { if (result.data) setItem(result.data); }, [result.data]);
  async function act(command, payload = {}) {
    try {
      const response = await fetch('/api/actions/' + command + '/' + id.split('/').map(encodeURIComponent).join('/'), {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Factory-UI': '1'}, body: JSON.stringify(payload)});
      setMessage(await response.text()); setConfirm(false);
      const fresh = await fetch('/api/slices/' + id.split('/').map(encodeURIComponent).join('/')); if (fresh.ok) setItem(await fresh.json());
    } catch { setMessage('Request failed'); }
  }
  if (!item) return <p>{result.error ? 'Unable to load slice.' : 'Loading…'}</p>;
  return <><Link to="/factory/slices">← All slices</Link><h1>{item.title}</h1><p className="muted">{item.id} · {item.state}{item.paused ? ' · paused' : ''}</p><section><h2>Actions</h2><div className="actions"><button onClick={() => act('start')}>Start</button><button onClick={() => act('pause')}>Pause</button><button onClick={() => act('resume')}>Resume</button></div>{item.attention && ['question','escalation','node-step'].includes(item.attention.kind) && <form onSubmit={e => {e.preventDefault(); act('answer', {value: answer});}}><label>Answer<textarea value={answer} onChange={e => setAnswer(e.target.value)} required /></label><button>Send answer</button></form>}{item.attention?.kind === 'merge' && <><form onSubmit={e => {e.preventDefault(); act('review', {value: verdict});}}><label>Review<textarea value={verdict} onChange={e => setVerdict(e.target.value)} required /></label><button>Record review</button></form><p>Pull request: {item.pr ? '#' + item.pr : 'not recorded'}</p>{item.pr && (confirm ? <div><p>Confirm approval of PR #{item.pr}?</p><button onClick={() => act('approve', {pr: item.pr, confirmed: true})}>Confirm approval</button> <button onClick={() => setConfirm(false)}>Cancel</button></div> : <button onClick={() => setConfirm(true)}>Approve PR #{item.pr}</button>)}</>}{message && <p role="status" className="text">{message}</p>}</section><section><h2>Details</h2><dl><dt>Repository</dt><dd>{item.repo}</dd><dt>Feature</dt><dd>{item.feature}</dd><dt>Executor</dt><dd>{item.executor.tool} · {item.executor.model}</dd><dt>Dependencies</dt><dd>{item.depends_on.join(', ') || 'None'}</dd><dt>Scheduled</dt><dd>{item.slot || 'Not scheduled'}</dd><dt>Pull request</dt><dd>{item.pr ? '#' + item.pr : 'None'}</dd><dt>Cost</dt><dd>not recorded</dd></dl></section><section><h2>Attention</h2>{item.attention ? <><strong>{item.attention.kind}</strong><p className="text">{item.attention.body}</p>{item.attention.answer && <p className="text">{item.attention.answer}</p>}{item.attention.review && <p className="text">Review: {item.attention.review.verdict}</p>}</> : <p className="muted">No attention needed.</p>}</section><section><h2>Final message</h2>{item.final ? <><strong>{item.final.kind}</strong><p className="text">{item.final.body}</p><small>{item.final.at}</small></> : <p className="muted">not recorded</p>}</section><section><h2>Log</h2>{item.log.length ? <ul className="log">{item.log.map((entry, i) => <li key={i}><small>{entry.at} · {entry.actor}</small><div className="text">{entry.event}</div></li>)}</ul> : <p className="muted">No log entries.</p>}</section></>;
}
function Sessions({area}) {
  const [sessions, setSessions] = useState([]), [selected, setSelected] = useState('');
  const [messages, setMessages] = useState([]), [error, setError] = useState('');
  const [title, setTitle] = useState(''), [tool, setTool] = useState('codex'), [model, setModel] = useState('');
  const [repositories, setRepositories] = useState(''), [text, setText] = useState(''), [sending, setSending] = useState(false);
  const base = '/api/' + area + '/sessions';
  async function api(path, payload) {
    const response = await fetch(path, payload === undefined ? {} : {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Factory-UI': '1'}, body: JSON.stringify(payload)});
    const data = await response.json(); if (!response.ok) throw Error(data.error || 'Request failed'); return data;
  }
  useEffect(() => {
    let live = true;
    async function poll() { try { const list = await api(base); const rows = selected ? await api(base + '/' + selected + '/messages') : []; if (live) {setSessions(list); setMessages(rows);} } catch {if (live) setError('Sessions unavailable');} }
    poll(); const timer = setInterval(poll, 2000); return () => {live = false; clearInterval(timer);};
  }, [base, selected]);
  async function create(e) {e.preventDefault(); setSending(true); try {const item = await api(base, {title, tool, model, repositories: repositories.split(',').map(r => r.trim()).filter(Boolean)}); setSelected(String(item.id)); setError('');} catch (e) {setError(e.message);} finally {setSending(false);} }
  async function send(e) {e.preventDefault(); setSending(true); try {setMessages(await api(base + '/' + selected + '/messages', {text})); setText(''); setError('');} catch (e) {setError(e.message);} finally {setSending(false);} }
  return <><h1>{area === 'homelab' ? 'Home Lab' : 'Factory'} sessions</h1><p>Each message runs one turn. Replies appear here. Planning changes stay in this session.</p>{error && <p role="alert">{error}</p>}<form onSubmit={create}><label>Title<input value={title} onChange={e => setTitle(e.target.value)} required maxLength={200}/></label><label>Tool<select value={tool} onChange={e => setTool(e.target.value)}><option>codex</option><option>claude</option></select></label><label>Model<input value={model} onChange={e => setModel(e.target.value)} required/></label><label>Repositories (owner/name, separated by commas)<input value={repositories} onChange={e => setRepositories(e.target.value)}/></label><button disabled={sending}>Create session</button></form><label>Session<select value={selected} onChange={e => {setSelected(e.target.value); setMessages([]);}}><option value="">Select a session</option>{sessions.map(s => <option key={s.id} value={s.id}>{s.title} · {s.state}</option>)}</select></label>{selected && <><section aria-live="polite">{messages.map(m => <article key={m.id}><strong>{m.role} · {m.status}</strong><p className="text">{m.text}</p></article>)}</section><form onSubmit={send}><label>Message<textarea value={text} onChange={e => setText(e.target.value)} required maxLength={32000}/></label><button disabled={sending || sessions.find(s => String(s.id) === selected)?.state === 'failed'}>Send</button></form></>}</>;
}
export function App() { return <div className="shell"><header><Link className="brand" to="/home-lab">Factory home</Link><nav aria-label="Areas"><NavLink to="/home-lab">Home Lab</NavLink><NavLink to="/factory">Factory</NavLink></nav></header><main><nav aria-label="Sessions"><Link to="/home-lab/sessions">Home Lab sessions</Link> · <Link to="/factory/sessions">Factory sessions</Link></nav><Routes><Route path="/home-lab/sessions" element={<Sessions key="homelab" area="homelab"/>}/><Route path="/factory/sessions" element={<Sessions key="factory" area="factory"/>}/><Route path="/" element={<Empty title="Home Lab"/>}/><Route path="/home-lab/*" element={<Empty title="Home Lab"/>}/><Route path="/factory" element={<Slices/>}/><Route path="/factory/slices" element={<Slices/>}/><Route path="/factory/slices/:project/:slice" element={<Detail/>}/><Route path="*" element={<Empty title="Not found"/>}/></Routes></main></div>; }
if (document.getElementById('root')) createRoot(document.getElementById('root')).render(<BrowserRouter><App/></BrowserRouter>);
