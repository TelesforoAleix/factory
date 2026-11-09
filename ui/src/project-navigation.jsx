import React, {useEffect, useState} from 'react';
import {NavLink, useLocation, useNavigate} from 'react-router-dom';
import {visiblePolling} from './polling';

export function ProjectNavigation() {
  const [projects,setProjects] = useState([]), navigate = useNavigate(), location = useLocation();
  useEffect(() => {
    let live = true;
    async function refresh() {try {const r = await fetch('/api/projects'); if (r.ok) {const rows = await r.json(); if (live && Array.isArray(rows)) setProjects(rows.filter(p => p.active !== false && p.key !== 'NEW'));}} catch { /* Keep navigation available during temporary outages. */ }}
    const stop = visiblePolling(refresh, 30000);
    window.addEventListener('projects-changed', refresh);
    return () => {live = false; stop(); window.removeEventListener('projects-changed', refresh);};
  }, []);
  const selected = projects.find(p => location.pathname === '/projects/' + p.key)?.key || '';
  return <><nav className="project-nav" aria-label="Projects">{projects.map(p => <NavLink key={p.key} to={'/projects/' + p.key}>{p.name}</NavLink>)}</nav><label className="project-dropdown"><span>Projects</span><select aria-label="Projects" value={selected} onChange={e => {if (e.target.value) navigate('/projects/' + e.target.value);}}><option value="">Choose project</option>{projects.map(p => <option key={p.key} value={p.key}>{p.name}</option>)}</select></label></>;
}
