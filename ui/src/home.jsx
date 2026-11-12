import {visiblePolling} from './polling';
import {usePhone} from './phone';
import {ProjectFilter, isActive} from './projects';
import React, {useEffect, useState} from 'react';
import {Link} from 'react-router-dom';
const slicePath = id => '/factory/slices/' + id.split('/').map(encodeURIComponent).join('/');
function elapsed(at) { if (!at) return 'Time unknown'; const mins = Math.max(0, Math.floor((Date.now() - new Date(at)) / 60000)); return mins < 60 ? `${mins}m` : mins < 1440 ? `${Math.floor(mins / 60)}h ${mins % 60}m` : `${Math.floor(mins / 1440)}d ${Math.floor(mins % 1440 / 60)}h`; }
function SliceRows({slices}) {
  return <div className="list">{slices.map(s => <div className="home-slice" key={s.id}><Link to={slicePath(s.id)}><strong>{s.title}</strong> <small>{s.id}</small></Link><span>{s.state}{s.state === 'issued' && ' · In progress'}</span>{s.no_feature && <p>{s.no_feature}</p>}</div>)}</div>;
}
function FeatureBlock({feature, phone}) {
  const [open, setOpen] = useState(!phone);
  const current = feature.slices.filter(s => s.state === 'issued');
  return <section className="home-feature"><button className="home-fold" aria-expanded={open} onClick={() => setOpen(!open)}><strong>{feature.id}</strong><span>{feature.done} of {feature.total} done</span>{current.length > 0 && <span>In progress: {current.map(s => s.title).join(', ')}</span>}</button>{open && <><h3><Link to={'/pipeline/' + encodeURIComponent(feature.id)}>{feature.title}</Link></h3><SliceRows slices={feature.slices}/></>}</section>;
}
function UnlinkedBlock({slices, phone}) {
  const [open, setOpen] = useState(!phone);
  return <section className="home-feature"><button className="home-fold" aria-expanded={open} onClick={() => setOpen(!open)}><strong>Not in a feature</strong><span>{slices.length} open</span></button>{open && <SliceRows slices={slices}/>}</section>;
}
export function Attention({item, act}) {
  const [answer, setAnswer] = useState(''), [confirm, setConfirm] = useState(false);
  const labels = {'testing-review':'Testing review', failure:'Failure', approval:'Approval', install:'Install', decision:'Decision', question:'Question or escalation', stuck:'Stuck', limit:'Limit full'};
  return <article className={'home-attention home-' + item.kind}><div className="home-card-heading"><strong>{labels[item.kind]}{item.label && <> · {item.label}</>}</strong><small>{item.id} · {elapsed(item.since)} waiting</small></div>{item.title && <h3>{item.title}</h3>}<p className="text">{item.text}</p>{item.verdict && <p className="text"><strong>Review:</strong> {item.verdict}</p>}
    <div className="actions">{item.kind === 'approval' && <>{confirm ? <><button onClick={() => act('/api/actions/approve/' + item.id, {pr:item.pr, confirmed:true})}>Confirm PR #{item.pr}</button><button onClick={() => setConfirm(false)}>Cancel</button></> : <button disabled={!item.pr} onClick={() => setConfirm(true)}>Accept</button>}<Link to={item.chat ? '/chats/' + item.chat : slicePath(item.id)}>Review</Link></>}
    {item.kind === 'install' && item.installable && <button onClick={() => act('/api/slices/' + item.id + '/install', {})}>{item.installing ? 'Install requested' : 'Install'}</button>}
    {item.kind === 'failure' && item.retry_install && <button disabled={item.installing} onClick={() => act('/api/slices/' + item.id + '/install', {})}>{item.installing ? 'Install requested' : 'Retry install'}</button>}
    {item.reactivate && <button onClick={() => act('/api/chats/' + item.chat + '/reactivate', {})}>Reactivate</button>}
    {['decision','testing-review'].includes(item.kind) && <Link to={'/chats/' + item.chat}>Open chat</Link>}{['stuck','failure'].includes(item.kind) && <Link to={slicePath(item.id)}>{item.kind === 'failure' ? 'Review' : 'Open slice'}</Link>}{item.kind === 'limit' && <Link to="/pipeline">Open Pipeline</Link>}</div>
    {item.kind === 'question' && <form onSubmit={e => {e.preventDefault(); act('/api/actions/answer/' + item.id, {value:answer});}}><label>Answer<textarea required value={answer} onChange={e => setAnswer(e.target.value)}/></label><button>Send answer</button></form>}
  </article>;
}
export function Home() {
  const [inboxIdeas,setInboxIdeas] = useState({inbox:[],ideas:[]});
  useEffect(() => {let live = true; const stop = visiblePolling(async () => {try {const [inbox,ideas] = await Promise.all(['/api/inbox','/api/ideas'].map(async u => {const r = await fetch(u); if (!r.ok) throw Error(); return r.json();})); if (live && Array.isArray(inbox) && Array.isArray(ideas)) setInboxIdeas({inbox,ideas});} catch {}}, 30000); return () => {live = false; stop();};}, []);
  const [data,setData] = useState(null), [error,setError] = useState(''), [project,setProject] = useState('');
  const phone = usePhone();
  useEffect(() => {if (data?.projects.some(p => p.key === project && !isActive(p))) setProject('');}, [data, project]);
  async function refresh() {const r = await fetch('/api/home'); if (!r.ok) throw Error('Home unavailable'); setData(await r.json());}
  useEffect(() => {let live = true; const stop = visiblePolling(async () => {try {const r = await fetch('/api/home'); if (!r.ok) throw Error('Home unavailable'); const data = await r.json(); if (live) setData(data);} catch(e) {if (live) setError(e.message);}}, 30000); return () => {live = false; stop();};}, []);
  async function act(url, payload) {try {setError(''); const r = await fetch(url, {method:'POST',headers:{'Content-Type':'application/json','X-Factory-UI':'1'},body:JSON.stringify(payload)}); if (!r.ok) {const text = await r.text(); try {throw Error(JSON.parse(text).error || 'Request failed');} catch(e) {if (e instanceof SyntaxError) throw Error(text || 'Request failed'); throw e;}} await refresh();} catch(e) {setError(e.message);}}
  if (!data) return <><h1>Home</h1><p>{error || 'Loading…'}</p></>;
  const visible = x => !project || x.project === project; const cards = data.attention.filter(x => visible(x) || x.kind === 'limit'); const next = data.features.filter(f => f.stage === 'next' && visible(f));
  return <div className="home"><div className="page-heading"><h1>Home</h1><ProjectFilter projects={data.projects} value={project} onChange={setProject}/></div>{error && <p role="alert">{error}</p>}
    {(inboxIdeas.inbox.some(i => i.route === 'New') || inboxIdeas.ideas.some(i => i.state === 'exploring' && i.exploration_note)) && <section><h2>Needs you</h2>{inboxIdeas.inbox.filter(i => i.route === 'New').length > 0 && <p><Link to="/ideas?tab=inbox">{inboxIdeas.inbox.filter(i => i.route === 'New').length} inbox items need routing</Link></p>}{inboxIdeas.ideas.filter(i => i.state === 'exploring' && i.exploration_note && (!project || i.tags?.includes(project))).map(i => <p key={i.id}><Link to={'/ideas?tab=ideas&idea=' + i.id}>{i.title} · Exploration ready</Link></p>)}</section>}
    {!!data.orchestrator_count && <p>With the orchestrator: {data.orchestrator_count}</p>}
    {!!cards.length && <section><h2>Needs your attention</h2><div className="home-board">{cards.map((a,i) => <Attention key={a.kind + a.id + a.since + i} item={a} act={act}/>)}</div></section>}
    {!!(data.running_now || []).filter(visible).length && <section><h2>Running now</h2><div className="list">{(data.running_now || []).filter(visible).map((r,i) => <Link className="home-row" key={r.kind + r.id + i} to={r.kind === 'chat' ? '/chats/' + r.id : slicePath(r.id)}><span className="running-dot"/><strong>{r.kind === 'chat' ? 'Workshop chat' : r.kind === 'install' ? 'Install or rollback' : 'Slice'}: {r.title}</strong><small>{r.project || 'No project'} · {r.id}</small><time>{elapsed(r.since)} running</time></Link>)}</div></section>}
    {(data.building || []).filter(visible).map(f => <FeatureBlock key={f.id} feature={f} phone={phone}/>)}
    {!!next.length && <p className="home-next">Next: {next.map((f,i) => <React.Fragment key={f.id}>{i > 0 && ', '}<Link to={'/pipeline/' + encodeURIComponent(f.id)}>{f.title}</Link></React.Fragment>)}</p>}
    {!!(data.unlinked || []).filter(visible).length && <UnlinkedBlock slices={data.unlinked.filter(visible)} phone={phone}/>}

  </div>;
}
