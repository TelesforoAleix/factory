import React, {useEffect, useState} from 'react';
import {Link, useParams} from 'react-router-dom';
import {Attention} from './home';
import {visiblePolling} from './polling';

const label = s => s[0].toUpperCase() + s.slice(1);
export const projectsChanged = () => window.dispatchEvent(new Event('projects-changed'));
async function request(url, method, body) {
  const r = await fetch(url, method ? {method, headers:{'Content-Type':'application/json','X-Factory-UI':'1'}, body:JSON.stringify(body)} : undefined);
  const text = await r.text();
  let result; try {result = JSON.parse(text);} catch {result = text;}
  if (!r.ok) throw Error(result?.error || result || 'Request failed');
  return result;
}
function ProjectEdit({project, save, close}) {
  const [draft,setDraft] = useState(() => Object.fromEntries(['name','about','public_url','repository_url'].map(k => [k, project[k] || ''])));
  const [busy,setBusy] = useState(false), [error,setError] = useState('');
  async function submit(e) {e.preventDefault(); setBusy(true); setError(''); try {await save(draft); close();} catch(e) {setError(e.message);} finally {setBusy(false);}}
  const field = (key, name, options={}) => <label>{name}{options.multiline ? <textarea value={draft[key]} maxLength={options.maxLength} onChange={e => setDraft({...draft,[key]:e.target.value})}/> : <input value={draft[key]} type={options.url ? 'url' : 'text'} required={key === 'name'} maxLength={options.maxLength} onChange={e => setDraft({...draft,[key]:e.target.value})}/>}</label>;
  return <div className="project-dialog-backdrop"><div role="dialog" aria-modal="true" aria-labelledby="project-edit-title" className="project-dialog"><h2 id="project-edit-title">Edit project</h2><form className="project-edit" onSubmit={submit}>{field('name','Name',{maxLength:60})}{field('about','About',{multiline:true,maxLength:600})}{field('public_url','Public address',{url:true})}{field('repository_url','Repository link',{url:true})}{error && <p role="alert">{error}</p>}<div className="actions"><button disabled={busy}>Save</button><button type="button" disabled={busy} onClick={close}>Cancel</button></div></form></div></div>;
}
export function ProjectPage() {
  const {key} = useParams();
  return <Project key={key} projectKey={key}/>;
}
function Project({projectKey}) {
  const [ready,setReady] = useState(null);
  const [data,setData] = useState(null), [error,setError] = useState(''), [busy,setBusy] = useState(false), [editing,setEditing] = useState(false);
  const url = '/api/projects/' + encodeURIComponent(projectKey);
  async function refresh() {setData(await request(url));}
  useEffect(() => {let live = true; const stop = visiblePolling(async () => {try {const result = await request(url); if (live) {setData(result); setError('');}} catch(e) {if (live) setError(e.message);}}, 30000); return () => {live = false; stop();};}, [url]);
  useEffect(() => {if (!data) return; let live = true; Promise.all(data.features.map(f => request('/api/pipeline/' + encodeURIComponent(f.id)))).then(features => {if (live) setReady(features.flatMap(f => (f.slices || []).filter(s => s.eligibility?.status === 'ready')));}).catch(() => {if (live) setReady(false);}); return () => {live = false;};}, [data]);
  async function save(fields) {
    const project = await request(url, 'PATCH', fields);
    setData(d => ({...d,project})); projectsChanged();
  }
  async function activate(active) {
    setBusy(true); setError('');
    try {await request(url, 'PATCH', {active}); await refresh(); projectsChanged();} catch(e) {setError(e.message);} finally {setBusy(false);}
  }
  async function act(path, payload) {
    setError(''); try {await request(path, 'POST', payload); await refresh();} catch(e) {setError(e.message);}
  }
  if (!data) return <><h1>Project</h1><p role={error ? 'alert' : 'status'}>{error || 'Loading…'}</p></>;
  const p = data.project, pipeline = '/pipeline?project=' + p.key;
  const featureList = features => features.length ? <div className="list">{features.map(f => <div className="home-row project-feature" key={f.id}><Link to={'/pipeline/' + f.id}><strong>{f.title}</strong><small>{f.id} · {label(f.stage)}</small></Link>{f.extra && <small>{f.extra}</small>}{data.running.filter(r => r.feature === f.id).map(r => <Link key={r.id} to={'/factory/slices/' + r.id}><span className="running-dot"/>{r.title} · Running</Link>)}</div>)}</div> : <p className="muted">Nothing here yet.</p>;
  return <div className="project-page"><div className="project-heading"><div className="project-field"><h1>{p.name} ({p.key})</h1><button onClick={() => setEditing(true)}>Edit</button><button disabled={busy} onClick={() => activate(!p.active)}>{p.active ? 'Deactivate' : 'Activate'}</button></div><div className="project-meta">{p.public_url && <a href={p.public_url} target="_blank" rel="noopener noreferrer">Public site ↗</a>}{p.repository_url && <a href={p.repository_url} target="_blank" rel="noopener noreferrer">Repository ↗</a>}</div></div>{editing && <ProjectEdit project={p} save={save} close={() => setEditing(false)}/ >}{error && <p role="alert">{error}</p>}
    <section><h2>About</h2><p className="text">{p.about || <span className="muted">Not set</span>}</p></section>
    {!!data.attention.length && <section><h2>Needs you</h2><div className="home-board">{data.attention.map((a,i) => <Attention key={a.kind + a.id + i} item={a} act={act}/>)}</div></section>}
    <section><h2>Now</h2>{featureList(data.features.filter(f => ['building','acceptance','testing'].includes(f.stage)))}<h3>Next</h3>{featureList(data.features.filter(f => f.stage === 'next'))}<div className="home-strip">{['shortlist','grilling','ready','next','building','acceptance','testing','parked'].map(stage => [stage, data.stages[stage] || 0]).map(([stage,count]) => <Link key={stage} to={pipeline}><span>{label(stage)}</span><strong>{count}</strong></Link>)}</div></section>
    <section><h2>Ready next</h2>{ready === null ? <p>Loading…</p> : ready === false ? <p>Ready items unavailable.</p> : ready.length ? <ul>{ready.map(s => <li key={s.id}><Link to={'/factory/slices/' + s.id.split('/').map(encodeURIComponent).join('/')}>{s.title} · {s.id}</Link></li>)}</ul> : <p className="muted">No items ready.</p>}</section>
    <section><h2>Chats</h2>{data.chats.length ? <div className="list">{data.chats.map(c => <Link className="home-row" key={c.id} to={'/chats/' + c.id}><strong>{c.kind === 'project' ? p.name + ' orchestrator' : c.title}</strong><small>{c.feature || 'Project orchestrator'}</small></Link>)}</div> : <p className="muted">No open chats.</p>}</section>
    <section><h2>Usage</h2><p className="muted">Calendar month in UTC. Costs come with Insights.</p><div className="project-usage">{[['month','This month'],['all_time','All time']].map(([period,title]) => <div key={period}><h3>{title}</h3><dl>{[['input_tokens','Input tokens'],['output_tokens','Output tokens'],['cached_tokens','Cached tokens'],['hours','Hours of runs']].map(([field,name]) => <React.Fragment key={field}><dt>{name}</dt><dd>{data.usage[period][field] == null ? 'Not recorded' : data.usage[period][field].toLocaleString(undefined,{maximumFractionDigits:field === 'hours' ? 2 : 0})}</dd></React.Fragment>)}</dl></div>)}</div></section>
    <section><h2>Documents</h2><Link to={'/library?project=' + p.key}>Open {p.name} in the Library →</Link></section>
  </div>;
}
