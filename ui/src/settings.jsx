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
  const [theme, setTheme] = useState(readTheme);
  const [projects,setProjects] = useState([]), [busy,setBusy] = useState(''), [error,setError] = useState('');
  useEffect(() => {let live = true; fetch('/api/projects').then(async r => {if (!r.ok) throw Error('Projects unavailable'); return r.json();}).then(rows => {if (live) setProjects(rows);}).catch(e => {if (live) setError(e.message);}); return () => {live = false;};}, []);
  async function activate(key, active) {
    setBusy(key); setError('');
    try {
      const r = await fetch('/api/projects/' + key, {method:'PATCH', headers:{'Content-Type':'application/json','X-Factory-UI':'1'}, body:JSON.stringify({active})});
      const updated = await r.json(); if (!r.ok) throw Error(updated.error || 'Unable to save project');
      setProjects(rows => rows.map(p => p.key === key ? updated : p));
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
  return <><h1>Settings</h1><section><h2>Appearance</h2><div className="segmented" role="group" aria-label="Appearance">{['device', 'light', 'dark'].map(value => <button key={value} type="button" aria-pressed={theme === value} onClick={() => choose(value)}>{value[0].toUpperCase() + value.slice(1)}</button>)}</div></section><section><h2>Projects</h2>{error && <p role="alert">{error}</p>}<div className="settings-projects">{projects.filter(p => p.key !== 'NEW').map(p => <div className="settings-project" key={p.key}><code>{p.key}</code><span>{p.name}</span><label><input type="checkbox" role="switch" aria-label={'Active ' + p.name} checked={p.active !== false} disabled={!!busy} onChange={e => activate(p.key, e.target.checked)}/> Active</label></div>)}</div></section></>;
}
