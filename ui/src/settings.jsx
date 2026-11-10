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
const headers = {'Content-Type':'application/json','X-Factory-UI':'1'};
async function api(url, body) {const r = await fetch(url, body ? {method:'POST', headers, body:JSON.stringify(body)} : undefined); const data = await r.json(); if (!r.ok) throw Error(data.error || 'Settings unavailable'); return data;}
const roleOrder = Object.keys(roleNames);
const roleFields = ['tool','model','effort'];
function ModelSettings() {
  const [status,setStatus] = useState({models:[],updates:[]}), [roles,setRoles] = useState([]), [savedRoles,setSavedRoles] = useState([]), [limits,setLimits] = useState([]), [savedLimits,setSavedLimits] = useState([]), [error,setError] = useState(''), [busy,setBusy] = useState('');
  useEffect(() => {let live = true; Promise.all([api('/api/settings/models'),api('/api/settings/roles'),api('/api/settings/limits')]).then(([m,r,l]) => {if (live) {setStatus(m?.models && m?.updates ? m : {models:[],updates:[]}); setRoles(Array.isArray(r) ? r : []); setSavedRoles(Array.isArray(r) ? r : []); setLimits(Array.isArray(l) ? l : []); setSavedLimits(Array.isArray(l) ? l : []);}}).catch(e => {if (live) setError(e.message);}); return () => {live = false;};}, []);
  useEffect(() => {if (!status.updates.some(u => ['queued','running'].includes(u.status))) return; const timer = setTimeout(() => api('/api/settings/models').then(setStatus).catch(e => setError(e.message)), 1000); return () => clearTimeout(timer);}, [status]);
  const orderedRoles = [...roles].sort((a,b) => roleOrder.indexOf(a.role) - roleOrder.indexOf(b.role));
  const changedRoles = orderedRoles.filter(row => {const saved = savedRoles.find(r => r.role === row.role); return saved && roleFields.some(k => row[k] !== saved[k]);});
  const changedLimits = limits.filter(row => {const saved = savedLimits.find(r => r.name === row.name); return saved && String(row.value) !== String(saved.value);});
  const updating = busy === 'models' || status.updates.some(u => ['queued','running'].includes(u.status));
  const refreshed = status.models.map(m => Date.parse(m.refreshed_at)).filter(Number.isFinite);
  async function update() {
    setBusy('models'); setError('');
    try {for (const tool of ['codex','claude']) {await api('/api/settings/models/update',{tool}); setStatus(s => ({...s, updates:[...s.updates.filter(u => u.tool !== tool), {tool,status:'queued'}]}));}} catch(e) {setError(e.message);} finally {setBusy('');}
  }
  async function saveRoles(e) {
    e.preventDefault(); setBusy('roles'); setError('');
    try {let result; for (const row of changedRoles) {result = await api('/api/settings/roles',{role:row.role,tool:row.tool,model:row.model,effort:row.effort}); setSavedRoles(result);} setRoles(result);}
    catch(e) {setError(e.message);} finally {setBusy('');}
  }
  async function saveLimits(e) {
    e.preventDefault(); setBusy('limits'); setError('');
    try {let result; for (const row of changedLimits) {result = await api('/api/settings/limits',{name:row.name,value:Number(row.value)}); setSavedLimits(result);} setLimits(result);}
    catch(e) {setError(e.message);} finally {setBusy('');}
  }
  return <>{error && <p role="alert">{error}</p>}<section><h2>Models</h2><button type="button" disabled={!!busy || updating} onClick={update}>Update available models</button><p>Refreshed: {refreshed.length ? new Date(Math.max(...refreshed)).toLocaleString() : 'never'}</p>{status.updates.filter(u => ['queued','running','failed'].includes(u.status)).map((u,i) => <p role="status" key={u.id ?? u.tool + i}>{u.tool}: {u.status}{u.reason ? ': ' + u.reason : ''}</p>)}</section><section><h2>Roles</h2><form onSubmit={saveRoles}><table className="settings-roles"><thead><tr><th>Role</th><th>Tool</th><th>Model</th><th>Effort</th></tr></thead><tbody>{orderedRoles.map(row => <tr key={row.role}><th scope="row">{roleNames[row.role] || row.role}{row.in_list === false && <p>Current choice is not in the stored model list.</p>}</th><ModelSelects cells disabled={!!busy} prefix={(roleNames[row.role] || row.role) + ' '} models={status.models} value={row} onChange={v => setRoles(rows => rows.map(r => r.role === row.role ? {...r,...v} : r))}/></tr>)}</tbody></table><button disabled={!!busy || !changedRoles.length || changedRoles.some(r => !r.model || !r.effort)}>Save</button></form></section><section><h2>Limits</h2><form onSubmit={saveLimits}><div className="settings-limits">{limits.map(row => {const name = row.name.replaceAll('_',' '); const displayName = name[0].toUpperCase() + name.slice(1); return <div className="settings-choice" key={row.name}><label>{displayName}<input type="number" disabled={!!busy} min="1" max={row.name === 'repository_runs' ? 1 : row.name === 'executors' ? 4 : undefined} required value={row.value} onChange={e => setLimits(rows => rows.map(r => r.name === row.name ? {...r,value:e.target.value} : r))}/></label><small>{row.description}</small></div>;})}</div><button disabled={!!busy || !changedLimits.length}>Save</button></form></section></>;
}
