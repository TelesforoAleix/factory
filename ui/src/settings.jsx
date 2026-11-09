import {projectsChanged} from './project-page';
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
  return <><h1>Settings</h1><section><h2>Appearance</h2><div className="segmented" role="group" aria-label="Appearance">{['device', 'light', 'dark'].map(value => <button key={value} type="button" aria-pressed={theme === value} onClick={() => choose(value)}>{value[0].toUpperCase() + value.slice(1)}</button>)}</div></section><section><h2>Projects</h2>{error && <p role="alert">{error}</p>}<div className="settings-projects">{projects.filter(p => p.key !== 'NEW').map(p => <div className="settings-project" key={p.key}><code>{p.key}</code><a href={"/projects/" + p.key}>{p.name}</a><label><input type="checkbox" role="switch" aria-label={'Active ' + p.name} checked={p.active !== false} disabled={!!busy} onChange={e => activate(p.key, e.target.checked)}/> Active</label></div>)}</div>{adding ? <form onSubmit={add}><label>Key<input required pattern="[A-Z]{3}" minLength={3} maxLength={3} value={key} onChange={e => setKey(e.target.value)}/></label><small>Three capitals. The key is permanent.</small><label>Name<input required maxLength={60} value={name} onChange={e => setName(e.target.value)}/></label><div className="actions"><button disabled={!!busy}>Create project</button><button type="button" onClick={() => setAdding(false)}>Cancel</button></div></form> : <button onClick={() => setAdding(true)}>Add project</button>}</section></>;
}
