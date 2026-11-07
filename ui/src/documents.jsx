import React, {useEffect, useState} from 'react';
import {Link, useNavigate, useParams, useSearchParams} from 'react-router-dom';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';

export async function api(path, payload) {
  const response = await fetch(path, payload === undefined ? {} : {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Factory-UI': '1'}, body: JSON.stringify(payload)});
  const data = await response.json();
  if (!response.ok) throw Error(data.error || 'Request failed');
  return data;
}
const encoded = path => path.split('/').map(encodeURIComponent).join('/');
export function Markdown({children}) {
  return <div className="markdown"><ReactMarkdown skipHtml remarkPlugins={[remarkGfm]} components={{table: ({children}) => <div className="table-scroll" tabIndex={0}><table>{children}</table></div>}}>{children}</ReactMarkdown></div>;
}
export function Documents() {
  const [docs, setDocs] = useState(null), [query, setQuery] = useState(''), [error, setError] = useState('');
  useEffect(() => {
    let live = true;
    const timer = setTimeout(() => api('/api/homelab/documents?q=' + encodeURIComponent(query)).then(rows => {if (live) {setDocs(rows); setError('');}}).catch(e => {if (live) setError(e.message);}), 200);
    return () => {live = false; clearTimeout(timer);};
  }, [query]);
  const folders = Object.groupBy(docs || [], doc => doc.folder);
  return <><h1>Home Lab</h1><nav aria-label="Home Lab"><Link to="/home-lab/backlog">Backlog</Link><Link to="/home-lab/grills">Start a grill</Link></nav><label>Search documents<input type="search" value={query} onChange={e => setQuery(e.target.value)}/></label>{error && <p role="alert">{error}</p>}{!docs && !error && <p>Loading…</p>}{docs?.length === 0 && <p>No documents found.</p>}{Object.entries(folders).map(([folder, rows]) => <section key={folder}><h2>{folder === '.' ? 'Planning' : folder}</h2><div className="list">{rows.map(doc => <Link className="card" key={doc.path} to={'/home-lab/documents/' + encoded(doc.path)}><span><strong>{doc.title}</strong><small>{doc.path}</small></span><span>{doc.status} · {doc.date}</span></Link>)}</div></section>)}</>;
}
export function Document({backlog = false}) {
  const params = useParams(), path = backlog ? 'backlog.md' : params['*'];
  const [doc, setDoc] = useState(null), [notes, setNotes] = useState([]), [sessions, setSessions] = useState([]);
  const [text, setText] = useState(''), [session, setSession] = useState(''), [notice, setNotice] = useState(''), [busy, setBusy] = useState(false);
  const navigate = useNavigate();
  useEffect(() => {
    let live = true; setDoc(null); setNotice(''); setNotes([]);
    Promise.all([api('/api/homelab/documents/' + encoded(path)), api('/api/homelab/notes/' + encoded(path)), api('/api/homelab/sessions')]).then(([d, n, s]) => {if (live) {setDoc(d); setNotes(n); setSessions(s);}}).catch(e => {if (live) setNotice(e.message);});
    return () => {live = false;};
  }, [path]);
  async function save(e) {e.preventDefault(); setBusy(true); try {setNotes(await api('/api/homelab/notes/' + encoded(path), {text})); setText(''); setNotice('Note saved');} catch(e) {setNotice(e.message);} finally {setBusy(false);} }
  async function send(note) {setBusy(true); try {await api('/api/homelab/send-note/' + note.id + '/' + encoded(path), {session: Number(session)}); navigate('/home-lab/sessions?session=' + session);} catch(e) {setNotice(e.message);} finally {setBusy(false);} }
  return <><Link to="/home-lab">← Documents</Link>{notice && <p role="status">{notice}</p>}{!doc ? <p>{notice ? 'Unable to load document.' : 'Loading…'}</p> : <><h1>{backlog ? 'Backlog' : doc.title}</h1><p className="muted">{doc.path} · {doc.status} · {doc.date}</p><Link to={'/home-lab/grills?document=' + encodeURIComponent(path)}>Grill this document</Link><div className="document-layout"><section><Markdown>{doc.markdown}</Markdown></section><aside><section><h2>Owner notes</h2>{notes.length === 0 && <p>No notes yet.</p>}{notes.map(note => <article className="note" key={note.id}><small>{note.time}</small><p className="text">{note.text}</p><button disabled={!session || busy} onClick={() => send(note)}>Send note into session</button></article>)}<label>Home Lab session<select value={session} onChange={e => setSession(e.target.value)}><option value="">Choose a session</option>{sessions.filter(s => s.state !== 'failed').map(s => <option key={s.id} value={s.id}>{s.title}</option>)}</select></label><form onSubmit={save}><label>Leave a note<textarea value={text} onChange={e => setText(e.target.value)} required maxLength={16000}/></label><button disabled={busy}>Save note</button></form></section></aside></div></>}</>;
}
export function Grills() {
  const [searchParams] = useSearchParams();
  const [docs, setDocs] = useState([]), [document, setDocument] = useState(searchParams.get('document') || '');
  const [tool, setTool] = useState('codex'), [model, setModel] = useState(''), [repositories, setRepositories] = useState(''), [error, setError] = useState(''), [busy, setBusy] = useState(false);
  const navigate = useNavigate();
  useEffect(() => {api('/api/homelab/documents').then(setDocs).catch(e => setError(e.message));}, []);
  async function start(e) {e.preventDefault(); setBusy(true); try {const result = await api('/api/homelab/grills', {document, tool, model, repositories: repositories.split(',').map(r => r.trim()).filter(Boolean)}); navigate('/home-lab/sessions?session=' + result.id);} catch(e) {setError(e.message);} finally {setBusy(false);} }
  return <><h1>Start a Home Lab grill</h1><p>The planner asks one question at a time and waits for your answer.</p>{error && <p role="alert">{error}</p>}<form onSubmit={start}><label>Document<select value={document} onChange={e => setDocument(e.target.value)} required><option value="">Choose a document</option>{docs.map(d => <option key={d.path} value={d.path}>{d.path}</option>)}</select></label><label>Tool<select value={tool} onChange={e => setTool(e.target.value)}><option>codex</option><option>claude</option></select></label><label>Model<input value={model} onChange={e => setModel(e.target.value)} required/></label><label>Repositories (owner/name, separated by commas)<input value={repositories} onChange={e => setRepositories(e.target.value)} required/></label><button disabled={busy}>Start grill</button></form></>;
}
