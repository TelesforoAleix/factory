import {usePhone} from './phone';
import {ProjectFilter} from './projects';
import React, {useEffect, useMemo, useRef, useState} from 'react';
import {Link, Navigate, useNavigate, useParams, useSearchParams} from 'react-router-dom';
import {createTextAnnotator} from '@recogito/text-annotator';
import '@recogito/text-annotator/text-annotator.css';
import {api, encoded, Markdown} from './documents';

// Exact text is mandatory. Context disambiguates repeated passages; never guess.
export function quoteOffset(text, selector) {
  if (!selector?.exact) return -1;
  const hits = []; let pos = text.indexOf(selector.exact);
  while (pos !== -1) {hits.push(pos); pos = text.indexOf(selector.exact, pos + 1);}
  const contextual = hits.filter(i => (!selector.prefix || text.slice(0, i).endsWith(selector.prefix)) && (!selector.suffix || text.slice(i + selector.exact.length).startsWith(selector.suffix)));
  return contextual.length === 1 ? contextual[0] : hits.length === 1 ? hits[0] : -1;
}
function PassageViewer({doc, comments, onSelect, onAnchors}) {
  const root = useRef(null), annotator = useRef(null);
  useEffect(() => {
    const element = root.current;
    const anno = createTextAnnotator(element, {userSelectAction: 'SELECT', style: (_annotation, state) => ({fill: '#888888', fillOpacity: 0.16, underlineStyle: 'solid', underlineColor: state?.selected ? 'var(--signal-mark)' : 'var(--secondary)', underlineThickness: 1})});
    annotator.current = anno;
    anno.on('createAnnotation', annotation => {
      const selected = annotation.target.selector[0];
      if (!selected?.quote) return;
      const text = element.textContent;
      onSelect({type:'TextQuoteSelector', exact:selected.quote, prefix:text.slice(Math.max(0, selected.start - 64), selected.start), suffix:text.slice(selected.end, selected.end + 64)});
    });
    anno.on('selectionChanged', annotations => {
      const id = annotations[0]?.id;
      if (id?.startsWith('comment-')) document.getElementById(id)?.scrollIntoView({block:'nearest', behavior:'smooth'});
    });
    return () => {annotator.current = null; anno.destroy();};
  }, [doc.path, doc.markdown]);
  useEffect(() => {
    const text = root.current.textContent, anchors = {};
    const annotations = comments.flatMap(c => {
      const start = quoteOffset(text, c.selector); anchors[c.id] = start >= 0;
      return start < 0 ? [] : [{id:'comment-' + c.id, bodies:[], target:{annotation:'comment-' + c.id, selector:[{quote:c.selector.exact, start, end:start + c.selector.exact.length}]}}];
    });
    annotator.current?.setAnnotations(annotations);
    onAnchors(anchors);
  }, [doc, comments]);
  return <div ref={root} className="passage-viewer" aria-label="Document text"><Markdown>{doc.markdown}</Markdown></div>;
}
function Breakable({text}) { return text.split(/([/-])/).map((part, i) => <React.Fragment key={i}>{part}{(part === '/' || part === '-') && <wbr/>}</React.Fragment>); }
function FolderList({documents, link, path}) {
  const root = {files:[], folders:{}};
  for (const doc of documents) {
    const parts = doc.path.split('/'); parts.pop(); let node = root;
    for (const part of parts) node = (node.folders[part] ||= {files:[], folders:{}});
    node.files.push(doc);
  }
  function render(node, prefix='') {return <ul>{node.files.map(d => <li key={d.path}><Link className={d.path === path ? 'selected' : undefined} aria-current={d.path === path ? 'page' : undefined} to={link('/library/documents/' + encoded(d.path))}>{d.title}<small><Breakable text={d.path}/></small></Link></li>)}{Object.entries(node.folders).sort(([a],[b]) => a.localeCompare(b)).map(([name, child]) => <li key={name}><details><summary><Breakable text={name}/></summary>{render(child, prefix + name + '/')}</details></li>)}</ul>;}
  return render(root);
}
export function OldLibraryRedirect() {
  const params = useParams(), [search] = useSearchParams();
  const old = params['*'] || '';
  if (old === 'sessions') return <Navigate replace to={search.get('session')?.match(/^\d+$/) ? '/chats/' + search.get('session') : '/chats'}/>;
  return <Navigate replace to={old.startsWith('documents/') ? '/library/' + old : old === 'backlog' ? '/library/documents/backlog.md' : '/library'}/>;
}
function ResolveComment({comment, busy, resolve}) {
  const [open, setOpen] = useState(false), [note, setNote] = useState('');
  return open ? <form onSubmit={e => {e.preventDefault(); resolve(note);}}><label>Resolution note<input required maxLength={1000} value={note} onChange={e => setNote(e.target.value)}/></label><button disabled={busy}>Save resolution</button><button type="button" onClick={() => setOpen(false)}>Cancel</button></form> : <button disabled={busy} onClick={() => setOpen(true)}>Resolve comment {comment.id}</button>;
}
export function Library({skill=false}) {
  const phone = usePhone();
  const params = useParams(), path = skill ? params.name : params['*'];
  const [search, setSearch] = useSearchParams(), project = search.get('project') || '', query = search.get('q') || '';
  const [tree,setTree] = useState({documents:[], projects:[]}), [skills,setSkills] = useState([]), [chats,setChats] = useState([]);
  const [doc,setDoc] = useState(null), [comments,setComments] = useState([]), [receiver,setReceiver] = useState(''), [selection,setSelection] = useState(null), [anchors,setAnchors] = useState({});
  const [text,setText] = useState(''), [error,setError] = useState(''), [busy,setBusy] = useState(false), [notice,setNotice] = useState('');
  const navigate = useNavigate(), generation = useRef(0);
  const link = url => url + (search.size ? '?' + search.toString() : '');
  useEffect(() => {let live = true;
    const timer = setTimeout(() => api('/api/library?' + new URLSearchParams({project,q:query})).then(data => {if (live) setTree(data);}).catch(e => {if (live) setError(e.message);}), 150);
    return () => {live = false; clearTimeout(timer);};
  }, [project,query]);
  useEffect(() => {let live = true; Promise.all([api('/api/skills'),api('/api/chats?archived=false')]).then(([s,c]) => {if (live) {setSkills(s); setChats(c);}}).catch(e => {if (live) setError(e.message);}); return () => {live = false;};}, []);
  useEffect(() => {let live = true; generation.current++; setDoc(null); setComments([]); setSelection(null); setText(''); setError(''); setNotice(''); setReceiver(''); setBusy(false);
    if (path) Promise.all([api(skill ? '/api/skills/' + encoded(path) : '/api/library/documents/' + encoded(path)), skill ? [] : api('/api/library/comments/' + encoded(path))]).then(([d,c]) => {if (live) {setDoc(d); setComments(c); setReceiver(String(d.receiver?.id || ''));}}).catch(e => {if (live) setError(e.message);});
    return () => {live = false;};
  }, [path,skill]);
  function filter(key,value) {const next = new URLSearchParams(search); if (value) next.set(key,value); else next.delete(key); setSearch(next);}
  async function action(operation) {const current = generation.current; setBusy(true); setError(''); try {await operation(() => current === generation.current);} catch(e) {if (current === generation.current) setError(e.message);} finally {if (current === generation.current) setBusy(false);}}
  function save(e) {e.preventDefault(); action(async live => {const rows = await api('/api/library/comments/' + encoded(path), {text,selector:selection}); if (live()) {setComments(rows); setSelection(null); setText(''); setNotice('Draft saved');}});}
  function changeComment(id, method, payload={}) {action(async live => {const rows = await api('/api/library/comments/' + encoded(path) + '/' + id, payload, method); if (live()) setComments(rows);});}
  function send(grill=false) {action(async live => {const result = await api('/api/library/' + (grill ? 'grill/' : 'send/') + encoded(path), {chat:Number(receiver)}); if (live()) {if (grill) navigate('/chats/' + result.chat); else {setComments(result.comments); setNotice('Comments sent as one message');}}});}
  function toggle(enabled) {action(async live => {const updated = await api('/api/skills/' + encoded(path), {project,enabled}); if (live()) {setDoc(updated); setSkills(rows => rows.map(s => s.name === updated.name ? updated : s));}});}
  function toggleSkill(name, enabled) {action(async live => {const updated = await api('/api/skills/' + encoded(name), {project,enabled}); if (live()) {setSkills(rows => rows.map(s => s.name === updated.name ? updated : s)); if (skill && path === name) setDoc(updated);}});}
  const activeComments = useMemo(() => comments.filter(c => !c.resolved_at), [comments]), resolved = comments.filter(c => c.resolved_at);
  const drafts = comments.filter(c => !c.sent_at), visibleSkills = skills.filter(s => (s.name + ' ' + s.description).toLowerCase().includes(query.toLowerCase()));
  return <div className={'library' + (path ? ' library-open' : '')}><div className="library-heading"><h1>Library</h1><ProjectFilter projects={tree.projects} value={project} onChange={value => filter('project', value)}/></div><div className="library-layout"><aside className="library-tree"><label>Search Library<input type="search" value={query} onChange={e => filter('q',e.target.value)}/></label><nav aria-label="Library tree"><details><summary>Skills &amp; guides</summary><ul>{visibleSkills.map(s => <li className="skill-row" key={s.name}><Link className={skill && path === s.name ? 'selected' : undefined} aria-current={skill && path === s.name ? 'page' : undefined} to={link('/library/skills/' + s.name)}>{s.name}<small title={s.version}>{s.version.slice(0,8)}</small></Link>{project && !phone && <label className="skill-row-switch"><input type="checkbox" aria-label={'Enable ' + s.name + ' for ' + (tree.projects.find(p => p.key === project)?.name || project)} checked={s.projects.includes(project)} disabled={busy} onChange={e => toggleSkill(s.name, e.target.checked)}/><span>{s.projects.includes(project) ? 'On' : 'Off'}</span></label>}</li>)}</ul></details><h2>Documents</h2>{tree.documents.length ? <FolderList documents={tree.documents} link={link} path={!skill ? path : null}/> : <p className="muted">No documents found.</p>}</nav></aside><div className="library-viewer"><Link className="library-back" to={link('/library')}>← Library</Link>{error && <p role="alert">{error}</p>}{notice && <p role="status">{notice}</p>}{!path ? <div className="library-placeholder"><h2>Your reference shelf</h2><p>Choose a document or guide from the tree.</p></div> : !doc ? <p>{error ? 'Unable to load this item.' : 'Loading…'}</p> : skill ? <section><h2>{doc.name}</h2><p>{doc.description}</p><p className="skill-version">Version <code>{doc.version}</code></p>{project && !phone ? <label className="skill-switch"><input type="checkbox" checked={doc.projects.includes(project)} disabled={busy} onChange={e => toggle(e.target.checked)}/> Enabled for {tree.projects.find(p => p.key === project)?.name || project}</label> : !phone && <p>Select a project to change its switch.</p>}<Markdown>{doc.markdown}</Markdown></section> : <><div className="library-document">{phone && <div className="phone-document-header"><h2>{doc.title}</h2><details><summary>Details</summary><p>{doc.path} · {doc.status} · {doc.date}</p></details></div>}<section>{phone ? <div className="passage-viewer"><Markdown>{doc.markdown}</Markdown></div> : <PassageViewer doc={doc} comments={activeComments} onSelect={setSelection} onAnchors={setAnchors}/>}</section><aside className="library-comments">{!phone && <div className="library-document-header"><h2>{doc.title}</h2><p className="muted">{doc.path} · {doc.status} · {doc.date}</p><div className="library-controls"><label className="receiver-chip">Send to<select aria-label="Receiving chat" value={receiver} onChange={e => setReceiver(e.target.value)}><option value="">Choose a chat</option>{chats.map(c => <option key={c.id} value={c.id}>{c.kind === 'project' ? (c.project_name || c.project || c.title) : c.title} · {c.kind}</option>)}</select></label><button disabled={busy || !receiver} onClick={() => send(true)}>Grill this document</button></div>{doc.receiver_error && <p role="status">{doc.receiver_error} · Choose another receiving chat.</p>}</div>}<h3>Comments</h3>{!phone && <button className="primary" disabled={busy || !drafts.length || !receiver} onClick={() => send()}>Send {drafts.length} comments</button>}<div className="library-comment-list">{!phone && selection && <form onSubmit={save}><h4>New passage comment</h4><blockquote>{selection.exact}</blockquote><label>Comment<textarea autoFocus required maxLength={16000} value={text} onChange={e => setText(e.target.value)}/></label><button disabled={busy}>Save draft</button><button type="button" onClick={() => setSelection(null)}>Cancel</button></form>}{!comments.length && <p className="muted">No comments yet.</p>}{activeComments.map(c => <article id={'comment-' + c.id} className="library-comment" key={c.id}><strong>{c.sent_at ? 'Sent' : 'Draft'}</strong>{c.selector ? <><blockquote>{c.selector.exact}</blockquote>{anchors[c.id] === false && <small>passage changed</small>}</> : <small>Whole-document note</small>}<p className="text">{c.text}</p>{c.sent_at ? <small>{c.chat ? <Link to={'/chats/' + c.chat}>{c.chat_title}</Link> : 'Imported note'} · <time dateTime={c.sent_at}>{new Date(c.sent_at).toLocaleString()}</time></small> : <small>Saved <time dateTime={c.time}>{new Date(c.time).toLocaleString()}</time></small>}{!phone && (c.sent_at ? <ResolveComment comment={c} busy={busy} resolve={note => changeComment(c.id, 'PATCH', {note})}/> : <button disabled={busy} onClick={() => changeComment(c.id, 'DELETE')}>Delete draft {c.id}</button>)}</article>)}{!!resolved.length && <details className="resolved-comments"><summary>Resolved ({resolved.length})</summary>{resolved.map(c => <article key={c.id}><p className="text">{c.resolution_note}</p><small>{c.chat ? <Link to={'/chats/' + c.chat}>{c.chat_title}</Link> : 'Imported note'} · <time dateTime={c.resolved_at}>{new Date(c.resolved_at).toLocaleString()}</time></small></article>)}</details>}</div></aside></div></>}</div></div></div>;
}
