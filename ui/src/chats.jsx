import React, {useEffect, useRef, useState} from 'react';
import {Link, useParams} from 'react-router-dom';
import {Markdown} from './documents';
import {ProjectFilter, isActive} from './projects';

async function request(url, method, body) {
  const response = await fetch(url, method ? {method, headers:{'Content-Type':'application/json', 'X-Factory-UI':'1'}, ...(body ? {body:JSON.stringify(body)} : {})} : undefined);
  const data = await response.json();
  if (!response.ok) throw Error(data.error || 'Chats unavailable');
  return data;
}
const labels = {orchestrator:'Orchestrator', project:'Project', feature:'Feature', legacy:'Legacy'};
const date = value => value ? new Intl.DateTimeFormat('en-GB', {timeZone:'Europe/Copenhagen', dateStyle:'medium', timeStyle:'short'}).format(new Date(value)) : '';
export function FeatureChatLink({feature}) {
  const [chat, setChat] = useState(null);
  useEffect(() => {let live = true; setChat(null); request('/api/chats').then(rows => {if (live) setChat(rows.find(c => c.feature === feature));}).catch(() => {}); return () => {live = false;};}, [feature]);
  return chat ? <p><Link to={'/chats/' + chat.id}>Open feature chat →</Link></p> : null;
}
function Usage({usage}) {
  if (!usage) return null;
  const names = {input_tokens:'Input', cached_tokens:'Cached', cache_write_tokens:'Cache write', output_tokens:'Output', reasoning_tokens:'Reasoning'};
  const parts = Object.entries(usage.tokens || {}).filter(([,v]) => v != null).map(([k,v]) => `${names[k] || k}: ${v.toLocaleString()} tokens`);
  if (usage.seconds != null) parts.push(`${Math.round(usage.seconds)} seconds`);
  return parts.length ? <details className="chat-usage" title={parts.join(' · ')}><summary>Turn usage</summary><small>{parts.join(' · ')}</small></details> : null;
}
function Transcript({messages, usage}) {
  return <div className="chat-transcript" aria-live="polite">{messages.map(m => {
    const role = `${m.role === 'owner' ? 'You' : m.role === 'assistant' ? 'Assistant' : 'System'}${m.automatic ? ' · Automatic' : ''}`;
    const meta = <span className="message-meta"><time>{date(m.time)}</time>{m.status && <> · {m.status}</>}</span>;
    const content = m.role === 'assistant' && !m.automatic ? <Markdown>{m.text}</Markdown> : <p className="text">{m.text}</p>;
    return m.automatic || m.role === 'system' ? <details key={m.id} className="chat-collapsed"><summary><span>{role}</span> <span className="message-meta">{date(m.time)}{m.status && ' · ' + m.status}</span> · {m.text.split('\n')[0]}</summary>{content}</details> : <article className={'message ' + m.role} key={m.id}><div className="message-heading"><strong>{role}</strong>{meta}</div>{content}{m.role === 'assistant' && <Usage usage={usage[m.id]}/>}</article>;
  })}</div>;
}
export function Chats() {
  const {id} = useParams();
  const [projects,setProjects] = useState([]);
  const [chats,setChats] = useState([]), [chat,setChat] = useState(null), [messages,setMessages] = useState([]), [usage,setUsage] = useState({}), [project,setProject] = useState(''), [error,setError] = useState(''), [text,setText] = useState(''), [sending,setSending] = useState(false), [model,setModel] = useState(''), [tool,setTool] = useState(''), [settingsOpen,setSettingsOpen] = useState(false);
  useEffect(() => {if (projects.some(p => p.key === project && !isActive(p))) setProject('');}, [projects, project]);
  const settingsRef = useRef(null);
  useEffect(() => {if (!settingsOpen) return; const key = e => {if (e.key === 'Escape') setSettingsOpen(false);}; const outside = e => {if (!settingsRef.current?.contains(e.target)) setSettingsOpen(false);}; document.addEventListener('keydown', key); document.addEventListener('pointerdown', outside); return () => {document.removeEventListener('keydown', key); document.removeEventListener('pointerdown', outside);};}, [settingsOpen]);
  useEffect(() => {let live = true; async function poll() {try {const [rows, projects] = await Promise.all([request('/api/chats'), request('/api/projects')]); if (live) {setChats(rows); setProjects(projects);}} catch (e) {if (live) setError(e.message);}} poll(); const timer = setInterval(poll, 5000); return () => {live = false; clearInterval(timer);};}, []);
  useEffect(() => {let live = true; setSettingsOpen(false); setChat(null); setMessages([]); setUsage({}); setText(''); setError(''); if (!id) return () => {live = false;};
    async function open() {try {const result = await request(`/api/chats/${id}/open`, 'POST'); if (!live) return; setChat(result.chat); setModel(result.chat.model); setTool(result.chat.tool); setMessages(result.messages); setChats(rows => rows.map(c => String(c.id) === id ? result.chat : c));} catch(e) {if (live) setError(e.message);}}
    open(); return () => {live = false;};
  }, [id]);
  useEffect(() => {if (!chat || String(chat.id) !== id) return; let live = true; async function poll() {try {const [current, rows, figures] = await Promise.all([request(`/api/chats/${id}`), request(`/api/${chat.area}/sessions/${id}/messages`), request(`/api/chats/${id}/usage`)]); if (live) {setChat(current); setMessages(rows); setUsage(figures);}} catch(e) {if (live) setError(e.message);}} poll(); const timer = setInterval(poll, 5000); return () => {live = false; clearInterval(timer);};}, [id, chat?.area]);
  async function send(e) {e.preventDefault(); setSending(true); try {const rows = await request(`/api/${chat.area}/sessions/${id}/messages`, 'POST', {text}); setMessages(rows); setText(''); setError('');} catch(e) {setError(e.message);} finally {setSending(false);}}
  async function configure(fields) {try {const result = await request(`/api/chats/${id}`, 'PATCH', fields); setChat(result); setModel(result.model); setTool(result.tool); setSettingsOpen(false); setError('');} catch(e) {setError(e.message);}}
  async function unread() {try {const result = await request(`/api/chats/${id}/unread`, 'POST'); setChats(rows => rows.map(c => c.id === result.id ? result : c)); setChat(result); setError('');} catch(e) {setError(e.message);}}
  async function archive() {try {const result = await request(`/api/chats/${id}/${chat.archived ? 'unarchive' : 'archive'}`, 'POST'); setChat(result); setChats(rows => rows.map(c => c.id === result.id ? result : c)); setError('');} catch(e) {setError(e.message);}}
  const visible = chats.filter(c => !project || c.project === project), active = visible.filter(c => !c.archived && (c.waiting || !c.project || isActive(projects.find(p => p.key === c.project))));
  const groups = [['Waiting for you', active.filter(c => c.waiting)], ['Development Orchestrator', active.filter(c => !c.waiting && c.kind === 'orchestrator')], ['Project orchestrators', active.filter(c => !c.waiting && c.kind === 'project')], ['Features', active.filter(c => !c.waiting && c.kind === 'feature')], ['Legacy', active.filter(c => !c.waiting && c.kind === 'legacy')]];
  const rows = items => items.map(c => <Link className={'chat-row' + (String(c.id) === id ? ' selected' : '')} key={c.id} to={'/chats/' + c.id}><span>{c.kind === 'project' ? (c.project_name || c.project || c.title) : c.title}</span><span className="chat-kind">{labels[c.kind] || c.kind}</span>{c.waiting && !c.archived && <span className="chat-waiting">Waiting for you</span>}{c.state === 'running' && <span className="running-dot" aria-label="Turn running"/>}</Link>);
  return <div className={'chats' + (id ? ' chat-open' : '')}><aside className="chat-list"><h1>Chats</h1><ProjectFilter projects={projects} value={project} onChange={setProject}/>{groups.map(([title,items]) => items.length > 0 && <div key={title}><h2>{title} <small>{items.length}</small></h2>{rows(items)}</div>)}<details className="chat-archive"><summary>Archived chats ({visible.filter(c => c.archived).length})</summary>{rows(visible.filter(c => c.archived))}</details></aside><div className="chat-main"><Link className="chat-back" to="/chats">← Chats</Link>{error && <p role="alert">{error}</p>}{chat ? <><div className="chat-header"><div><div className="chat-title-line"><h1>{chat.kind === 'project' ? (chat.project_name || chat.project || chat.title) : chat.title}</h1><small className="chat-model">{chat.tool} · {chat.model}</small><div className="chat-settings" ref={settingsRef}><button type="button" disabled={chat.state === 'running'} aria-expanded={settingsOpen} onClick={() => {setTool(chat.tool); setModel(chat.model); setSettingsOpen(!settingsOpen);}}>Change model</button>{settingsOpen && <form className="chat-settings-panel" onSubmit={e => {e.preventDefault(); configure({tool, model});}}><label>Tool<select aria-label="Chat tool" value={tool} disabled={chat.state === 'running'} onChange={e => setTool(e.target.value)}><option>codex</option><option>claude</option></select></label><label>Model<input aria-label="Chat model" value={model} onChange={e => setModel(e.target.value)} required disabled={chat.state === 'running'}/></label><button disabled={chat.state === 'running'}>Save</button></form>}</div></div><p>{chat.feature ? <>Feature {chat.feature} · <Link to={'/pipeline?feature=' + encodeURIComponent(chat.feature)}>Pipeline card</Link></> : chat.kind === 'project' ? <>Project orchestrator · {chat.project_name || chat.project}</> : chat.project ? <>Project {chat.project_name || chat.project}</> : labels[chat.kind]}</p></div><div className="actions">{chat.kind !== 'orchestrator' && <button onClick={archive}>{chat.archived ? 'Unarchive' : 'Archive'}</button>}<button onClick={unread}>Mark unread</button></div></div><Transcript messages={messages} usage={usage}/><form className="chat-compose" onSubmit={send}><label>Message<textarea value={text} onChange={e => setText(e.target.value)} required maxLength={32000}/></label><button disabled={sending || chat.state === 'failed'}>Send</button>{chat.state === 'running' && <small>Queued</small>}</form></> : !id ? <p>Select a chat to see its transcript.</p> : !error && <p>Loading…</p>}</div></div>;
}
