import React from 'react';

export const isActive = p => p?.key === 'NEW' || p?.active !== false;
export function ProjectFilter({projects, value, onChange}) {
  const choices = projects.filter(isActive);
  const selected = choices.some(p => p.key === value) ? value : '';
  return <div className="project-choices" role="group" aria-label="Project">{[{key:'',name:'All'}, ...choices].map(p => <button key={p.key} type="button" aria-pressed={selected === p.key} onClick={() => onChange(p.key)}>{p.name || p.key}</button>)}</div>;
}
