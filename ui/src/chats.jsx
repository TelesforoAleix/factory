import {ModelSelects} from './model-selects';
import {usePhone} from './phone';
import {visiblePolling} from './polling';
import React, {useEffect, useLayoutEffect, useRef, useState} from 'react';
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
function eventSummary(text) {
  const first = text.split('\n')[0], slice = text.match(/^Slice: (.+)$/m)?.[1];
  return first.startsWith('Event: ') && !first.includes(' · ') && slice && slice !== '(feature event)' ? first + ' · ' + slice : first;
}
function Transcript({messages, usage, chatId}) {
  const ref = useRef(null), follow = useRef(true), previousChat = useRef(chatId);
  useLayoutEffect(() => {
    if (previousChat.current !== chatId) { follow.current = true; previousChat.current = chatId; }
    if (follow.current && ref.current) ref.current.scrollTop = ref.current.scrollHeight;
  }, [messages, chatId]);
  return <div ref={ref} onScroll={e => {const el = e.currentTarget; follow.current = el.scrollHeight - el.scrollTop - el.clientHeight <= 32;}} className="chat-transcript" aria-live="polite">{messages.map(m => {
    const role = `${m.role === 'owner' ? 'You' : m.role === 'assistant' ? 'Assistant' : 'System'}${m.automatic ? ' · Automatic' : ''}`;
    const meta = <span className="message-meta"><time>{date(m.time)}</time>{m.status && <> · {m.status}</>}</span>;
    const content = m.role === 'assistant' && !m.automatic ? <Markdown>{m.text}</Markdown> : <p className="text">{m.text}</p>;
    return m.automatic || m.role === 'system' ? <details key={m.id} className="chat-collapsed"><summary><span>{role}</span> <span className="message-meta">{date(m.time)}{m.status && ' · ' + m.status}</span> · {eventSummary(m.text)}</summary>{content}</details> : <article className={'message ' + m.role} key={m.id}><div className="message-heading"><strong>{role}</strong>{meta}</div>{content}{m.role === 'assistant' && <Usage usage={usage[m.id]}/>}</article>;
  })}</div>;
}
export function Chats() {
  const phone = usePhone();
  const {id} = useParams();
  useEffect(() => {
    const viewport = window.visualViewport, main = document.querySelector('main');
    if (!phone || !id || !viewport || !main) return;
    const resize = () => main.style.setProperty('--phone-chat-height', `${Math.max(0, viewport.height + viewport.offsetTop - main.getBoundingClientRect().top)}px`);
    resize(); viewport.addEventListener('resize', resize); viewport.addEventListener('scroll', resize);
    return () => {viewport.removeEventListener('resize', resize); viewport.removeEventListener('scroll', resize); main.style.removeProperty('--phone-chat-height');};
  }, [phone, id]);
  const [projects,setProjects] = useState([]);
  const [chats,setChats] = useState([]), [chat,setChat] = useState(null), [messages,setMessages] = useState([]), [usage,setUsage] = useState({}), [project,setProject] = useState(''), [error,setError] = useState(''), [text,setText] = useState(''), [sending,setSending] = useState(false), [model,setModel] = useState(''), [tool,setTool] = useState(''), [settingsOpen,setSettingsOpen] = useState(false), [effort,setEffort] = useState(''), [models,setModels] = useState([]);
  useEffect(() => {request('/api/settings/models').then(data => setModels(Array.isArray(data.models) ? data.models : [])).catch(() => {});}, []);
  useEffect(() => {if (projects.some(p => p.key === project && !isActive(p))) setProject('');}, [projects, project]);
  const settingsRef = useRef(null), menuRef = useRef(null);
  const [menuOpen, setMenuOpen] = useState(false);
  useEffect(() => {if (!menuOpen) return; const key = e => {if (e.key === 'Escape') {setMenuOpen(false); setSettingsOpen(false);}}; const outside = e => {if (!menuRef.current?.contains(e.target)) {setMenuOpen(false); setSettingsOpen(false);}}; document.addEventListener('keydown', key); document.addEventListener('pointerdown', outside); return () => {document.removeEventListener('keydown', key); document.removeEventListener('pointerdown', outside);};}, [menuOpen]);
  useEffect(() => {if (!settingsOpen || phone) return; const key = e => {if (e.key === 'Escape') setSettingsOpen(false);}; const outside = e => {if (!settingsRef.current?.contains(e.target)) setSettingsOpen(false);}; document.addEventListener('keydown', key); document.addEventListener('pointerdown', outside); return () => {document.removeEventListener('keydown', key); document.removeEventListener('pointerdown', outside);};}, [settingsOpen, phone]);
  useEffect(() => {let live = true; async function poll() {try {const [rows, projects] = await Promise.all([request('/api/chats'), request('/api/projects')]); if (live) {setChats(rows); setProjects(projects); setChat(current => current ? rows.find(c => c.id === current.id) || current : current);}} catch (e) {if (live) setError(e.message);}} const stop = visiblePolling(poll, 30000); return () => {live = false; stop();};}, []);
  useEffect(() => {let live = true; setSettingsOpen(false); setMenuOpen(false); setChat(null); setMessages([]); setUsage({}); setText(''); setError(''); if (!id) return () => {live = false;};
    async function open() {try {const result = await request(`/api/chats/${id}/open`, 'POST'); if (!live) return; setChat(result.chat); setModel(result.chat.model); setTool(result.chat.tool); setEffort(result.chat.effort); setMessages(result.messages); setChats(rows => rows.map(c => String(c.id) === id ? result.chat : c));} catch(e) {if (live) setError(e.message);}}
    open(); return () => {live = false;};
  }, [id]);
  useEffect(() => {if (!chat || String(chat.id) !== id) return; let live = true;
    async function poll() {try {const rows = await request(`/api/${chat.area}/sessions/${id}/messages`); if (live) setMessages(rows);} catch(e) {if (live) setError(e.message);}}
    const stop = visiblePolling(poll, 5000); return () => {live = false; stop();};
  }, [id, chat?.area]);
  const lastReply = messages.filter(m => m.role === 'assistant').at(-1)?.id;
  useEffect(() => {if (!id || !lastReply || document.hidden) return; let live = true;
    request(`/api/chats/${id}/usage`).then(data => {if (live) setUsage(data);}).catch(() => {});
    return () => {live = false;};
  }, [id, lastReply]);
  async function send(e) {e.preventDefault(); setSending(true); try {const rows = await request(`/api/${chat.area}/sessions/${id}/messages`, 'POST', {text}); setMessages(rows); setChat(c => ({...c, state:c.state === 'failed' ? 'idle' : c.state})); setText(''); setError('');} catch(e) {setError(e.message);} finally {setSending(false);}}
  async function configure(fields) {try {const result = await request(`/api/chats/${id}`, 'PATCH', fields); setChat(result); setModel(result.model); setTool(result.tool); setEffort(result.effort); setSettingsOpen(false); setError('');} catch(e) {setError(e.message);}}
  async function unread() {try {const result = await request(`/api/chats/${id}/unread`, 'POST'); setChats(rows => rows.map(c => c.id === result.id ? result : c)); setChat(result); setError('');} catch(e) {setError(e.message);}}
  async function archive() {try {const result = await request(`/api/chats/${id}/${chat.archived ? 'unarchive' : 'archive'}`, 'POST'); setChat(result); setChats(rows => rows.map(c => c.id === result.id ? result : c)); setError('');} catch(e) {setError(e.message);}}
  const visible = chats.filter(c => !project || c.project === project), active = visible.filter(c => !c.archived && (c.waiting || !c.project || isActive(projects.find(p => p.key === c.project))));
  const groups = [['Waiting for you', active.filter(c => c.waiting)], ['Development Orchestrator', active.filter(c => !c.waiting && c.kind === 'orchestrator')], ['Secretary', active.filter(c => !c.waiting && c.kind === 'secretary')], ['Project orchestrators', active.filter(c => !c.waiting && c.kind === 'project')], ['Features', active.filter(c => !c.waiting && c.kind === 'feature')], ['Legacy', active.filter(c => !c.waiting && c.kind === 'legacy')]];
  const rows = items => items.map(c => <Link className={'chat-row' + (String(c.id) === id ? ' selected' : '')} key={c.id} to={'/chats/' + c.id}><span>{c.kind === 'project' ? (c.project_name || c.project || c.title) : c.title}</span><span className="chat-kind">{labels[c.kind] || c.kind}</span>{c.waiting && !c.archived && <span className="chat-waiting">Waiting for you</span>}{c.state === 'running' && <span className="running-dot" aria-label="Turn running"/>}</Link>);
  return <div className={'chats' + (id ? ' chat-open' : '')}><aside className="chat-list"><h1>Chats</h1><ProjectFilter projects={projects} value={project} onChange={setProject}/>{groups.map(([title,items]) => items.length > 0 && <div key={title}><h2>{title} <small>{items.length}</small></h2>{rows(items)}</div>)}<details className="chat-archive"><summary>Archived chats ({visible.filter(c => c.archived).length})</summary>{rows(visible.filter(c => c.archived))}</details></aside><div className="chat-main"><Link className="chat-back" to="/chats">← Chats</Link>{error && <p role="alert">{error}</p>}{chat ? <><div className="chat-header"><div><div className="chat-title-line"><h1>{chat.kind === 'project' ? (chat.project_name || chat.project || chat.title) : chat.title}</h1><small className="chat-model">{chat.tool} · {chat.model}</small>{chat.in_list === false && <small>Current choice is not in the stored model list.</small>}{!phone && <div className="chat-settings desktop-chat-settings" ref={settingsRef}><button type="button" disabled={chat.state === 'running'} aria-expanded={settingsOpen} onClick={() => {setTool(chat.tool); setModel(chat.model); setEffort(chat.effort); setSettingsOpen(!settingsOpen);}}>Change model</button>{settingsOpen && <form className="chat-settings-panel" onSubmit={e => {e.preventDefault(); configure({tool, model, effort});}}><ModelSelects prefix="Chat " models={models} value={{tool,model,effort}} onChange={v => {setTool(v.tool); setModel(v.model); setEffort(v.effort);}}/><button disabled={!model || !effort}>Save</button><button type="button" onClick={() => configure({tool:null,model:null,effort:null})}>Use role default</button></form>}</div>}</div><p>{chat.feature ? <>Feature {chat.feature} · <Link to={'/pipeline?feature=' + encodeURIComponent(chat.feature)}>Pipeline card</Link></> : chat.kind === 'project' ? <>Project orchestrator · {chat.project_name || chat.project}</> : chat.project ? <>Project {chat.project_name || chat.project}</> : labels[chat.kind]}</p></div>{phone && <div className="phone-chat-menu" ref={menuRef}><button type="button" aria-label="Chat options" aria-expanded={menuOpen} onClick={() => {setMenuOpen(!menuOpen); setSettingsOpen(false);}}>⋯</button>{menuOpen && <div className="phone-chat-menu-panel"><button disabled={chat.state === 'running'} onClick={() => setSettingsOpen(!settingsOpen)}>Change model</button>{settingsOpen && <form onSubmit={e => {e.preventDefault(); configure({tool, model, effort});}}><ModelSelects prefix="Chat " models={models} value={{tool,model,effort}} onChange={v => {setTool(v.tool); setModel(v.model); setEffort(v.effort);}}/><button disabled={!model || !effort}>Save</button><button type="button" onClick={() => configure({tool:null,model:null,effort:null})}>Use role default</button></form>}<button onClick={() => {unread(); setMenuOpen(false);}}>Mark unread</button>{!['orchestrator','secretary'].includes(chat.kind) && <button onClick={() => {archive(); setMenuOpen(false);}}>{chat.archived ? 'Unarchive' : 'Archive'}</button>}</div>}</div>}{!phone && <div className="actions chat-header-actions"><button onClick={unread}>Mark unread</button>{!['orchestrator','secretary'].includes(chat.kind) && <button onClick={archive}>{chat.archived ? 'Unarchive' : 'Archive'}</button>}</div>}</div><Transcript messages={messages} usage={usage} chatId={id}/><form className="chat-compose" onSubmit={send}><label>Message<textarea value={text} onChange={e => setText(e.target.value)} required maxLength={32000}/></label><button disabled={sending}>Send</button>{chat.state === 'running' && <small>Queued</small>}</form></> : !id ? <p>Select a chat to see its transcript.</p> : !error && <p>Loading…</p>}</div></div>;
}
