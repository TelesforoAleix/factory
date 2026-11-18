import {EvalRuns, EvalSets, EvalSet, EvalNew, EvalRun} from './evals';
import {ProjectPage} from './project-page';
import {ProjectNavigation} from './project-navigation';
import {visiblePolling} from './polling';
import {Chats} from './chats';
import {Home} from './home';
import {Ideas} from './ideas';
import React, {useEffect, useState} from 'react';
import {createRoot} from 'react-dom/client';
import {BrowserRouter, Link, NavLink, Route, Routes, useParams, useSearchParams} from 'react-router-dom';
import './style.css';
import {Settings} from './settings';
import {HomeLabSettings} from './home-lab-settings';
import {Pipeline, FeaturePage} from './pipeline';
import {Library, OldLibraryRedirect} from './library';
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
  async function changeLevel(level) {try {const response = await fetch('/api/slices/' + id.split('/').map(encodeURIComponent).join('/') + '/level', {method:'POST', headers:{'Content-Type':'application/json','X-Factory-UI':'1'}, body:JSON.stringify({level})}); const data = await response.json(); if (!response.ok) throw Error(data.error); setItem(current => ({...current,...data})); setMessage('');} catch(e) {setMessage(e.message || 'Request failed');}}
  if (!item) return <p>{result.error ? 'Unable to load slice.' : 'Loading…'}</p>;
  return <><Link to="/factory/slices">← All slices</Link><h1>{item.title}</h1><p className="muted">{item.id} · {item.state}{item.paused ? ' · paused' : ''}</p><section><h2>Actions</h2><div className="actions"><button onClick={() => act('start')}>Start</button><button onClick={() => act('pause')}>Pause</button><button onClick={() => act('resume')}>Resume</button></div>{item.attention && ['question','escalation','node-step'].includes(item.attention.kind) && <form onSubmit={e => {e.preventDefault(); act('answer', {value: answer});}}><label>Answer<textarea value={answer} onChange={e => setAnswer(e.target.value)} required /></label><button>Send answer</button></form>}{item.attention?.kind === 'merge' && <><form onSubmit={e => {e.preventDefault(); act('review', {value: verdict});}}><label>Review<textarea value={verdict} onChange={e => setVerdict(e.target.value)} required /></label><button>Record review</button></form><p>Pull request: {item.pr ? '#' + item.pr : 'not recorded'}</p>{item.pr && (confirm ? <div><p>Confirm approval of PR #{item.pr}?</p><button onClick={() => act('approve', {pr: item.pr, confirmed: true})}>Confirm approval</button> <button onClick={() => setConfirm(false)}>Cancel</button></div> : <button onClick={() => setConfirm(true)}>Approve PR #{item.pr}</button>)}</>}{message && <p role="status" className="text">{message}</p>}</section><section><h2>Details</h2><dl><dt>Repository</dt><dd>{item.repo}</dd><dt>Feature</dt><dd>{item.feature}</dd><dt>Level</dt><dd>{['planned','ready'].includes(item.state) ? <select aria-label="Slice level" value={item.level || ''} onChange={e => changeLevel(e.target.value)}>{!item.level && <option value="">Set by hand</option>}{['light','standard','strong'].map(level => <option key={level} value={level}>{level[0].toUpperCase() + level.slice(1)}</option>)}</select> : (item.level ? item.level[0].toUpperCase() + item.level.slice(1) : 'Set by hand')}</dd><dt>Executors</dt><dd>{item.runs?.length ? <ul>{item.runs.map((run, i) => <li key={i}>{[run.role, run.tool, run.model, run.effort, run.started_at].filter(Boolean).join(' · ')}</li>)}</ul> : 'None'}</dd><dt>Dependencies</dt><dd>{item.depends_on.join(', ') || 'None'}</dd><dt>Scheduled</dt><dd>{item.slot || 'Not scheduled'}</dd><dt>Pull request</dt><dd>{item.pr ? '#' + item.pr : 'None'}</dd><dt>Cost</dt><dd>not recorded</dd></dl></section><section><h2>Attention</h2>{item.attention ? <><strong>{item.attention.kind}</strong><p className="text">{item.attention.body}</p>{item.attention.answer && <p className="text">{item.attention.answer}</p>}{item.attention.review && <p className="text">Review: {item.attention.review.verdict}</p>}</> : <p className="muted">No attention needed.</p>}</section><section><h2>Final message</h2>{item.final ? <><strong>{item.final.kind}</strong><p className="text">{item.final.body}</p><small>{item.final.at}</small></> : <p className="muted">not recorded</p>}</section><section><h2>Log</h2>{item.log.length ? <ul className="log">{item.log.map((entry, i) => <li key={i}><small>{entry.at} · {entry.actor}</small><div className="text">{entry.event}</div></li>)}</ul> : <p className="muted">No log entries.</p>}</section></>;
}
function Sessions({area}) {
  const [searchParams] = useSearchParams();
  const [sessions, setSessions] = useState([]), [selected, setSelected] = useState(searchParams.get('session') || '');
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
    const stop = visiblePolling(poll, 5000); return () => {live = false; stop();};
  }, [base, selected]);
  async function create(e) {e.preventDefault(); setSending(true); try {const item = await api(base, {title, tool, model, repositories: repositories.split(',').map(r => r.trim()).filter(Boolean)}); setSelected(String(item.id)); setError('');} catch (e) {setError(e.message);} finally {setSending(false);} }
  async function send(e) {e.preventDefault(); setSending(true); try {setMessages(await api(base + '/' + selected + '/messages', {text})); setText(''); setError('');} catch (e) {setError(e.message);} finally {setSending(false);} }
  return <><h1>{area === 'homelab' ? 'Home Lab' : 'Factory'} sessions</h1><p>Each message runs one turn. Replies appear here. {area === 'homelab' ? 'Committed planning Markdown is delivered to main after each turn.' : 'Planning is read-only.'}</p>{error && <p role="alert">{error}</p>}<form onSubmit={create}><label>Title<input value={title} onChange={e => setTitle(e.target.value)} required maxLength={200}/></label><label>Tool<select value={tool} onChange={e => setTool(e.target.value)}><option>codex</option><option>claude</option></select></label><label>Model<input value={model} onChange={e => setModel(e.target.value)} required/></label><label>Repositories (owner/name, separated by commas)<input value={repositories} onChange={e => setRepositories(e.target.value)}/></label><button disabled={sending}>Create session</button></form><label>Session<select value={selected} onChange={e => {setSelected(e.target.value); setMessages([]);}}><option value="">Select a session</option>{sessions.map(s => <option key={s.id} value={s.id}>{s.title} · {s.state}</option>)}</select></label>{selected && <><section aria-live="polite">{messages.map(m => <article key={m.id} className={"message " + m.role + (m.role === 'assistant' && m.text.includes('?') ? ' planner-question' : '')}><strong>{m.role === 'assistant' ? 'Planner' : 'You'} · {m.status}</strong>{m.role === 'assistant' && m.text.includes('?') && <small className="question-label">Planner question</small>}<p className="text">{m.text.startsWith('Planning pushed commit ') ? <>Planning pushed commit <code>{m.text.slice(23)}</code></> : m.text}</p></article>)}</section><form onSubmit={send}><label>Message<textarea value={text} onChange={e => setText(e.target.value)} required maxLength={32000}/></label><button disabled={sending}>Send</button></form></>}</>;
}
export function App() { return <div className="shell"><header><Link className="brand" to="/">Workshop</Link><nav aria-label="Areas"><NavLink to="/" end>Home</NavLink><NavLink to="/pipeline">Pipeline</NavLink><NavLink to="/chats">Chats</NavLink><NavLink to="/ideas">Ideas</NavLink><NavLink to="/library">Library</NavLink><NavLink to="/evals">Evals</NavLink><NavLink to="/settings">Settings</NavLink></nav><ProjectNavigation/></header><main><Routes><Route path="/evals" element={<EvalRuns/>}/><Route path="/evals/sets" element={<EvalSets/>}/><Route path="/evals/sets/:id" element={<EvalSet/>}/><Route path="/evals/new" element={<EvalNew/>}/><Route path="/evals/runs/:id" element={<EvalRun/>}/><Route path="/projects/:key" element={<ProjectPage/>}/><Route path="/settings" element={<Settings/>}/><Route path="/settings/home-lab" element={<HomeLabSettings/>}/><Route path="/chats" element={<Chats/>}/><Route path="/chats/:id" element={<Chats/>}/><Route path="/pipeline" element={<Pipeline/>}/><Route path="/pipeline/:id" element={<FeaturePage/>}/><Route path="/factory/sessions" element={<Sessions key="factory" area="factory"/>}/><Route path="/" element={<Home/>}/><Route path="/ideas" element={<Ideas/>}/><Route path="/library" element={<Library/>}/><Route path="/library/documents/*" element={<Library/>}/><Route path="/library/skills/:name" element={<Library skill/>}/><Route path="/library/prompts/:name" element={<Library prompt/>}/><Route path="/home-lab" element={<OldLibraryRedirect/>}/><Route path="/home-lab/*" element={<OldLibraryRedirect/>}/><Route path="/factory" element={<Slices/>}/><Route path="/factory/slices" element={<Slices/>}/><Route path="/factory/slices/:project/:slice" element={<Detail/>}/><Route path="*" element={<Empty title="Not found"/>}/></Routes></main></div>; }
if (document.getElementById('root')) createRoot(document.getElementById('root')).render(<BrowserRouter><App/></BrowserRouter>);
