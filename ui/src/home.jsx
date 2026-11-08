import {ProjectFilter, isActive} from './projects';
import React, {useEffect, useState} from 'react';
import {Link} from 'react-router-dom';
import {DndContext, MouseSensor, TouchSensor, useSensor, useSensors, closestCorners} from '@dnd-kit/core';
import {SortableContext, useSortable, verticalListSortingStrategy} from '@dnd-kit/sortable';
import {CSS} from '@dnd-kit/utilities';

const stages = ['shortlist','grilling','ready','next','building','testing','done','parked'];
const title = s => s[0].toUpperCase() + s.slice(1);
const slicePath = id => '/factory/slices/' + id.split('/').map(encodeURIComponent).join('/');
function elapsed(at) { if (!at) return 'Time unknown'; const mins = Math.max(0, Math.floor((Date.now() - new Date(at)) / 60000)); return mins < 60 ? `${mins}m` : mins < 1440 ? `${Math.floor(mins / 60)}h ${mins % 60}m` : `${Math.floor(mins / 1440)}d ${Math.floor(mins % 1440 / 60)}h`; }
function NextItem({item}) {
  const {attributes, listeners, setNodeRef, transform, transition} = useSortable({id:item.id});
  return <div className="home-row next-row" ref={setNodeRef} style={{transform:CSS.Transform.toString(transform), transition}}><button className="drag-handle" {...attributes} {...listeners} aria-label={'Drag ' + item.id}>⠿</button><Link to={'/pipeline/' + encodeURIComponent(item.id)}><strong>{item.title}</strong><small>{item.id}</small></Link></div>;
}
function Attention({item, act}) {
  const [answer, setAnswer] = useState(''), [confirm, setConfirm] = useState(false);
  const labels = {'testing-review':'Testing review', failure:'Failure', approval:'Approval', install:'Install', decision:'Decision', question:'Question or escalation', stuck:'Stuck', limit:'Limit full'};
  return <article className={'home-attention home-' + item.kind}><div className="home-card-heading"><strong>{labels[item.kind]}</strong><small>{item.id} · {elapsed(item.since)} waiting</small></div>{item.title && <h3>{item.title}</h3>}<p className="text">{item.text}</p>{item.verdict && <p className="text"><strong>Review:</strong> {item.verdict}</p>}
    <div className="actions">{item.kind === 'approval' && <>{confirm ? <><button onClick={() => act('/api/actions/approve/' + item.id, {pr:item.pr, confirmed:true})}>Confirm PR #{item.pr}</button><button onClick={() => setConfirm(false)}>Cancel</button></> : <button disabled={!item.pr} onClick={() => setConfirm(true)}>Accept</button>}<Link to={item.chat ? '/chats/' + item.chat : slicePath(item.id)}>Review</Link></>}
    {item.kind === 'install' && item.installable && <button onClick={() => act('/api/slices/' + item.id + '/install', {})}>{item.installing ? 'Install requested' : 'Install'}</button>}
    {['decision','testing-review'].includes(item.kind) && <Link to={'/chats/' + item.chat}>Open chat</Link>}{['stuck','failure'].includes(item.kind) && <Link to={slicePath(item.id)}>Open slice</Link>}{item.kind === 'limit' && <Link to="/pipeline">Open Pipeline</Link>}</div>
    {item.kind === 'question' && <form onSubmit={e => {e.preventDefault(); act('/api/actions/answer/' + item.id, {value:answer});}}><label>Answer<textarea required value={answer} onChange={e => setAnswer(e.target.value)}/></label><button>Send answer</button></form>}
  </article>;
}
export function Home() {
  const [data,setData] = useState(null), [error,setError] = useState(''), [project,setProject] = useState('');
  const sensors = useSensors(useSensor(MouseSensor, {activationConstraint:{distance:8}}), useSensor(TouchSensor, {activationConstraint:{delay:300,tolerance:8}}));
  useEffect(() => {if (data?.projects.some(p => p.key === project && !isActive(p))) setProject('');}, [data, project]);
  async function refresh() {const r = await fetch('/api/home'); if (!r.ok) throw Error('Home unavailable'); setData(await r.json());}
  useEffect(() => {refresh().catch(e => setError(e.message)); const timer = setInterval(() => refresh().catch(() => setError('Home unavailable')), 30000); return () => clearInterval(timer);}, []);
  async function act(url, payload) {try {setError(''); const r = await fetch(url, {method:'POST',headers:{'Content-Type':'application/json','X-Factory-UI':'1'},body:JSON.stringify(payload)}); if (!r.ok) {const text = await r.text(); try {throw Error(JSON.parse(text).error || 'Request failed');} catch(e) {if (e instanceof SyntaxError) throw Error(text || 'Request failed'); throw e;}} await refresh();} catch(e) {setError(e.message);}}
  function dragEnd({active,over}) {if (!over || active.id === over.id) return; const all = data.features.filter(f => f.stage === 'next'); const old = all.findIndex(f => f.id === active.id), target = all.findIndex(f => f.id === over.id); act('/api/pipeline/' + encodeURIComponent(active.id) + '/place', old < target ? {after:over.id} : {before:over.id});}
  if (!data) return <><h1>Home</h1><p>{error || 'Loading…'}</p></>;
  const visible = x => !project || x.project === project; const cards = data.attention.filter(x => visible(x) || x.kind === 'limit'); const next = data.features.filter(f => f.stage === 'next' && visible(f));
  return <div className="home"><div className="page-heading"><h1>Home</h1><ProjectFilter projects={data.projects} value={project} onChange={setProject}/></div>{error && <p role="alert">{error}</p>}
    {!!cards.length && <section><h2>Needs your attention</h2><div className="home-board">{cards.map((a,i) => <Attention key={a.kind + a.id + a.since + i} item={a} act={act}/>)}</div></section>}
    <div className="quick-chats" aria-label="Quick chats">{(data.quick_chats || []).map(c => <Link key={c.id} to={'/chats/' + c.id}>{c.title}</Link>)}</div>
    <section><h2>Chats waiting for you</h2>{data.chats.filter(visible).length ? <div className="list">{data.chats.filter(visible).map(c => <Link className="home-row" key={c.id} to={'/chats/' + c.id}><strong>{c.project && c.title === c.project ? (data.projects.find(p => p.key === c.project)?.name || c.project) : c.title}</strong><small>{c.feature || data.projects.find(p => p.key === c.project)?.name || c.project || 'Chat'}</small></Link>)}</div> : <p className="muted">No chats waiting.</p>}</section>
    <section><h2>Running now</h2>{data.running.filter(visible).length ? <div className="list">{data.running.filter(visible).map(s => <Link className="home-row" key={s.id} to={slicePath(s.id)}><span className="running-dot"/><strong>{s.title}</strong><small>{s.id}</small><time>{elapsed(s.since)} running</time></Link>)}</div> : <p className="muted">Nothing running.</p>}</section>
    <section><h2>Next</h2><DndContext sensors={sensors} collisionDetection={closestCorners} onDragEnd={dragEnd}><SortableContext items={next.map(f => f.id)} strategy={verticalListSortingStrategy}><div className="list">{next.map(f => <NextItem key={f.id} item={f}/>)}</div></SortableContext></DndContext>{!next.length && <p className="muted">Nothing queued.</p>}</section>
    <section><h2>Pipeline</h2><div className="home-strip">{stages.map(stage => <Link key={stage} to="/pipeline"><span>{title(stage)}</span><strong>{data.features.filter(f => f.stage === stage && visible(f) && (!['shortlist','parked'].includes(stage) || isActive(data.projects.find(p => p.key === f.project)))).length}</strong></Link>)}</div></section>
  </div>;
}
