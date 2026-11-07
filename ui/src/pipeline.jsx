import React, {useEffect, useState} from 'react';
import {Link, useParams, useSearchParams} from 'react-router-dom';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import {DndContext, MouseSensor, TouchSensor, useSensor, useSensors, useDroppable, closestCorners} from '@dnd-kit/core';
import {SortableContext, useSortable, verticalListSortingStrategy} from '@dnd-kit/sortable';
import {CSS} from '@dnd-kit/utilities';

const stages = ['shortlist','grilling','ready','next','building','testing','done','parked'];
const name = s => s?.[0].toUpperCase() + s?.slice(1);
const date = value => value && new Intl.DateTimeFormat('en-GB', {timeZone: 'Europe/Copenhagen', dateStyle: 'medium'}).format(new Date(value));
const openAttention = a => a && (a.kind === 'owner-check' || a.kind === 'merge' && !a.approved || ['question','escalation','node-step'].includes(a.kind) && a.answer == null);
const attention = f => f.slices.filter(s => s.state !== 'accepted' && openAttention(s.attention));
function Markdown({text}) { return <div className="markdown"><ReactMarkdown remarkPlugins={[remarkGfm]}>{text}</ReactMarkdown></div>; }
function Header({item}) { return <><small>{item.id} · {name(item.stage)} · {item.project}</small><h2>{item.title}</h2></>; }
function Panel({item, act, close}) {
  const totals = item.numbers || {};
  const tokenFields = [['input_tokens', 'Input'], ['cached_tokens', 'Cached'], ['cache_write_tokens', 'Cache write'], ['output_tokens', 'Output'], ['reasoning_tokens', 'Reasoning']];
  return <aside className="pipeline-panel"><button className="panel-close" onClick={close} aria-label="Close preview">×</button><Header item={item}/>
    {attention(item).map(s => <p className="pipeline-attention text" key={s.id}><strong>{s.id}: </strong>{s.attention.body}</p>)}
    <div className="actions">{item.moves.map(stage => <button key={stage} onClick={() => act(item.id, stage)}>Move to {name(stage)}</button>)}</div>
    {item.sections[0] && <section><h3>{item.sections[0].name}</h3><Markdown text={item.sections[0].text}/></section>}
    <section><h3>Slices</h3>{item.slices.length ? item.slices.map(s => <p key={s.id}><strong>{s.id}</strong> · {s.title} · {s.state}</p>) : <p className="muted">No linked slices.</p>}</section>
    <section><h3>Numbers</h3>{tokenFields.filter(([key]) => totals[key] != null).map(([key, label]) => <p key={key}>{label} tokens: {totals[key].toLocaleString()}</p>)}{totals.seconds != null && <p>Seconds: {Math.round(totals.seconds).toLocaleString()}</p>}{item.stage_since && <p>In this stage: {Math.max(0, Math.floor((Date.now() - new Date(item.stage_since)) / 86400000))} days (since {date(item.stage_since)})</p>}</section>
    <Link to={'/pipeline/' + encodeURIComponent(item.id)}>Full feature page →</Link>
  </aside>;
}
function extra(item, index) {
  if (item.stage === 'ready') return `${item.slices.length} slices`;
  if (item.stage === 'next') return `Queue #${index + 1}`;
  if (item.stage === 'building') {
    if (attention(item).length) return 'Waiting for you';
    const running = item.slices.filter(s => ['issued','awaiting handover'].includes(s.state) && !s.paused);
    return item.slices.length ? `${item.slices.filter(s => s.state === 'accepted').length} of ${item.slices.length} slices done${running.length ? ' · ' + running.map(s => s.title).join(', ') : ''}` : null;
  }
  if (item.stage === 'done' && item.stage_since) return `Finished ${date(item.stage_since)}`;
  if (item.stage === 'parked' && item.parked_from) return `From ${name(item.parked_from)}`;
}
function Card({item, index, selected, select, act, close}) {
  const {attributes, listeners, setNodeRef, transform, transition, isDragging} = useSortable({id: item.id, data: {stage: item.stage}});
  const line = extra(item, index);
  return <div ref={setNodeRef} style={{transform: CSS.Transform.toString(transform), transition, opacity: isDragging ? .45 : 1}} className="pipeline-card-wrap">
    <div className={'pipeline-card' + (selected ? ' selected' : '')}><button className="drag-handle" {...attributes} {...listeners} aria-label={'Drag ' + item.id}>⠿</button><button className="pipeline-card-open" onClick={select} aria-expanded={selected}><span className="feature-chip">Feature</span><small>{item.id}</small><strong className="feature-title">{item.title}</strong><span className="project-tag">{item.project}</span>{line && <span className={line === 'Waiting for you' ? 'pipeline-attention' : 'feature-extra'}>{line}</span>}</button></div>
    {selected && <div className="mobile-panel"><Panel item={item} act={act} close={close}/></div>}
  </div>;
}
function Column({stage, items, selected, select, act, close, all}) {
  const {setNodeRef, isOver} = useDroppable({id: 'stage:' + stage});
  const [expanded, setExpanded] = useState(!['done', 'parked'].includes(stage));
  return <div ref={setNodeRef} className={'pipeline-column stage-' + stage + (isOver ? ' over' : '') + (expanded ? ' expanded' : '')}><h2><span className="stage-heading">{name(stage)} <small>{items.length}</small></span><button className="stage-toggle" aria-expanded={expanded} onClick={() => setExpanded(!expanded)}>{name(stage)} <small>{items.length}</small></button></h2><SortableContext items={items.map(i => i.id)} strategy={verticalListSortingStrategy}><div className="pipeline-cards">{items.map(item => <Card key={item.id} item={item} index={all.filter(f => f.stage === stage).findIndex(f => f.id === item.id)} selected={selected === item.id} select={() => select(item.id)} act={act} close={close}/>)}</div></SortableContext></div>;
}
export function Pipeline() {
  const [data, setData] = useState(null), [error, setError] = useState(''), [project, setProject] = useState('');
  const [params, setParams] = useSearchParams(); const selected = params.get('feature');
  const sensors = useSensors(useSensor(MouseSensor, {activationConstraint: {distance: 8}}), useSensor(TouchSensor, {activationConstraint: {delay: 300, tolerance: 8}}));
  async function refresh() { const r = await fetch('/api/pipeline'); if (!r.ok) throw Error('Pipeline unavailable'); setData(await r.json()); }
  useEffect(() => {refresh().catch(e => setError(e.message));}, []);
  async function post(id, operation, body) { const r = await fetch(`/api/pipeline/${encodeURIComponent(id)}/${operation}`, {method:'POST', headers:{'Content-Type':'application/json','X-Factory-UI':'1'}, body:JSON.stringify(body)}); const result = await r.json(); if (!r.ok) throw Error(result.error || 'Request failed'); }
  async function act(id, stage, placement) { try {setError(''); const item = data.features.find(f => f.id === id); if (stage !== item.stage) await post(id, 'move', {stage}); if (placement) await post(id, 'place', placement); } catch (e) {setError(e.message);} finally {try {await refresh();} catch {setError('Pipeline unavailable');}} }
  function dragEnd({active, over}) {if (!over || active.id === over.id) return; const item = data.features.find(f => f.id === active.id), target = data.features.find(f => f.id === over.id); const stage = target?.stage || String(over.id).replace('stage:', ''); if (!stages.includes(stage)) return; const visible = data.features.filter(f => f.stage === stage && (!project || f.project === project) && f.id !== item.id); let placement = {bottom:true}; if (target) { const old = data.features.filter(f => f.stage === stage).findIndex(f => f.id === item.id); const idx = data.features.filter(f => f.stage === stage).findIndex(f => f.id === target.id); placement = item.stage === stage && old < idx ? {after:target.id} : {before:target.id}; } else if (visible.length) placement = {after:visible[visible.length-1].id}; act(item.id, stage, placement); }
  const select = id => setParams(id ? {feature:id} : {});
  if (!data) return <><h1>Pipeline</h1><p>{error || 'Loading…'}</p></>;
  const visible = data.features.filter(f => !project || f.project === project); const current = data.features.find(f => f.id === selected);
  return <div className="pipeline"><h1>Pipeline</h1><div className="project-filter" aria-label="Project filter">{[{key:'',name:'All'}, ...data.projects].map(p => <button key={p.key} aria-pressed={project === p.key} onClick={() => setProject(p.key)}>{p.name}</button>)}</div>{error && <p role="status" className="pipeline-error">{error}</p>}
    <div className={'pipeline-layout' + (current ? ' has-panel' : '')}><DndContext sensors={sensors} collisionDetection={closestCorners} onDragEnd={dragEnd}><div className="pipeline-scroll"><div className="pipeline-grid">{stages.map(stage => <Column key={stage} stage={stage} items={visible.filter(f => f.stage === stage)} all={data.features} selected={selected} select={select} act={act} close={() => select(null)}/>)}</div></div></DndContext>{current && <div className="desktop-panel"><Panel item={current} act={act} close={() => select(null)}/></div>}</div>
  </div>;
}
export function FeaturePage() { const {id} = useParams(); const [item,setItem] = useState(null), [error,setError] = useState(''); useEffect(() => {fetch('/api/pipeline/' + encodeURIComponent(id)).then(r => {if (!r.ok) throw Error('Feature unavailable'); return r.json();}).then(setItem).catch(e => setError(e.message));}, [id]); return <><Link to={'/pipeline?feature=' + encodeURIComponent(id)}>← Pipeline</Link>{item ? <><Header item={item}/>{item.sections.map((s,i) => <details className="feature-section" key={s.name} open={i === 0 || undefined}><summary>{s.name}</summary><Markdown text={s.text}/></details>)}</> : <p>{error || 'Loading…'}</p>}</>; }
