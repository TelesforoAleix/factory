import {projectsChanged} from './project-page';
import {ModelSelects} from './model-selects';
import React, {useEffect, useState} from 'react';

function readTheme() {
  try {
    const value = localStorage.getItem('theme');
    return value === 'light' || value === 'dark' ? value : 'device';
  } catch {
    return 'device';
  }
}

export function Settings() {
  const [adding,setAdding] = useState(false), [key,setKey] = useState(''), [name,setName] = useState('');
  const [theme, setTheme] = useState(readTheme);
  const [projects,setProjects] = useState([]), [busy,setBusy] = useState(''), [error,setError] = useState('');
  useEffect(() => {let live = true; fetch('/api/projects').then(async r => {if (!r.ok) throw Error('Projects unavailable'); return r.json();}).then(rows => {if (live) setProjects(rows);}).catch(e => {if (live) setError(e.message);}); return () => {live = false;};}, []);
  async function activate(key, active) {
    setBusy(key); setError('');
    try {
      const r = await fetch('/api/projects/' + key, {method:'PATCH', headers:{'Content-Type':'application/json','X-Factory-UI':'1'}, body:JSON.stringify({active})});
      const updated = await r.json(); if (!r.ok) throw Error(updated.error || 'Unable to save project');
      setProjects(rows => rows.map(p => p.key === key ? updated : p)); projectsChanged();
    } catch(e) {setError(e.message);} finally {setBusy('');}
  }
  async function add(e) {
    e.preventDefault(); setBusy('add'); setError('');
    try {
      const r = await fetch('/api/projects', {method:'POST', headers:{'Content-Type':'application/json','X-Factory-UI':'1'}, body:JSON.stringify({key,name})});
      const project = await r.json(); if (!r.ok) throw Error(project.error || 'Unable to add project');
      setProjects(rows => [...rows, project].sort((a,b) => a.key.localeCompare(b.key)));
      setAdding(false); setKey(''); setName(''); projectsChanged();
    } catch(e) {setError(e.message);} finally {setBusy('');}
  }
  function choose(value) {
    try {
      localStorage.setItem('theme', value);
    } catch {
      value = 'device';
    }
    document.documentElement.dataset.theme = value;
    setTheme(value);
  }
  return <><h1>Settings</h1><section><h2>Appearance</h2><div className="segmented" role="group" aria-label="Appearance">{['device', 'light', 'dark'].map(value => <button key={value} type="button" aria-pressed={theme === value} onClick={() => choose(value)}>{value[0].toUpperCase() + value.slice(1)}</button>)}</div></section><section><h2>Projects</h2>{error && <p role="alert">{error}</p>}<div className="settings-projects">{projects.filter(p => p.key !== 'NEW').map(p => <div className="settings-project" key={p.key}><code>{p.key}</code><a href={"/projects/" + p.key}>{p.name}</a><label><input type="checkbox" role="switch" aria-label={'Active ' + p.name} checked={p.active !== false} disabled={!!busy} onChange={e => activate(p.key, e.target.checked)}/> Active</label></div>)}</div>{adding ? <form onSubmit={add}><label>Key<input required pattern="[A-Z]{3}" minLength={3} maxLength={3} value={key} onChange={e => setKey(e.target.value)}/></label><small>Three capitals. The key is permanent.</small><label>Name<input required maxLength={60} value={name} onChange={e => setName(e.target.value)}/></label><div className="actions"><button disabled={!!busy}>Create project</button><button type="button" onClick={() => setAdding(false)}>Cancel</button></div></form> : <button onClick={() => setAdding(true)}>Add project</button>}</section><ModelSettings/></>;
}

const roleNames = {orchestrator:'Development Orchestrator', project:'Project orchestrator', feature:'Feature chat', secretary:'Secretary', light:'Light executor', standard:'Standard executor', strong:'Strong executor'};
const limitNames = {building_limit:'Building limit', waiting_limit:'Waiting limit', chat_auto_turns:'Chat automatic turns', executors:'Executors', repository_runs:'Runs per repository'};
const headers = {'Content-Type':'application/json','X-Factory-UI':'1'};
async function api(url, body) {const r = await fetch(url, body ? {method:'POST', headers, body:JSON.stringify(body)} : undefined); const data = await r.json(); if (!r.ok) throw Error(data.error || 'Settings unavailable'); return data;}
function ModelSettings() {
  const [status,setStatus] = useState({models:[],updates:[]}), [roles,setRoles] = useState([]), [limits,setLimits] = useState([]), [error,setError] = useState('');
  useEffect(() => {let live = true; Promise.all([api('/api/settings/models'),api('/api/settings/roles'),api('/api/settings/limits')]).then(([m,r,l]) => {if (live) {setStatus(m?.models && m?.updates ? m : {models:[],updates:[]}); setRoles(Array.isArray(r) ? r : []); setLimits(Array.isArray(l) ? l : []);}}).catch(e => {if (live) setError(e.message);}); return () => {live = false;};}, []);
  useEffect(() => {if (!status.updates.some(u => ['queued','running'].includes(u.status))) return; const timer = setTimeout(() => api('/api/settings/models').then(setStatus).catch(e => setError(e.message)), 1000); return () => clearTimeout(timer);}, [status]);
  async function update(tool) {try {await api('/api/settings/models/update',{tool}); setStatus(s => ({...s, updates:[...s.updates.filter(u => u.tool !== tool), {tool,status:'queued'}]}));} catch(e) {setError(e.message);}}
  async function saveRole(row) {try {const result = await api('/api/settings/roles',Object.fromEntries(['role','tool','model','effort'].map(k => [k,row[k]]))); setRoles(result); setError('');} catch(e) {setError(e.message);}}
  async function saveLimit(row) {try {setLimits(await api('/api/settings/limits',{name:row.name,value:Number(row.value)})); setError('');} catch(e) {setError(e.message);}}
  return <>{error && <p role="alert">{error}</p>}<section><h2>Models</h2>{['codex','claude'].map(tool => {const updateState = status.updates.find(u => u.tool === tool); return <div key={tool}><h3>{tool === 'codex' ? 'Codex' : 'Claude'}</h3><button disabled={['queued','running'].includes(updateState?.status)} onClick={() => update(tool)}>Update {tool === 'codex' ? 'Codex' : 'Claude'} models</button>{updateState && <p role="status">{updateState.status}{updateState.reason ? ': ' + updateState.reason : ''}</p>}<ul>{status.models.filter(m => m.tool === tool).map(m => <li key={m.model}>{m.label} · {m.efforts.join(', ')} · Refreshed {m.refreshed_at}</li>)}</ul></div>;})}</section><section><h2>Roles</h2>{roles.map(row => <form className="settings-choice" key={row.role} onSubmit={e => {e.preventDefault(); saveRole(row);}}><h3>{roleNames[row.role] || row.role}</h3>{row.in_list === false && <p>Current choice is not in the stored model list.</p>}<ModelSelects prefix={roleNames[row.role] + ' '} models={status.models} value={row} onChange={v => setRoles(rows => rows.map(r => r.role === row.role ? {...r,...v} : r))}/><button disabled={!row.model || !row.effort}>Save {roleNames[row.role] || row.role}</button></form>)}</section><section><h2>Limits</h2>{limits.map(row => <form className="settings-choice" key={row.name} onSubmit={e => {e.preventDefault(); saveLimit(row);}}><label>{limitNames[row.name] || row.name}<input type="number" min="1" max={row.name === 'repository_runs' ? 1 : row.name === 'executors' ? 4 : undefined} required value={row.value} onChange={e => setLimits(rows => rows.map(r => r.name === row.name ? {...r,value:e.target.value} : r))}/></label><p>{row.description}</p><button>Save {limitNames[row.name] || row.name}</button></form>)}</section></>;
}
