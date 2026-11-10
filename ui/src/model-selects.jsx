import React from 'react';

export function ModelSelects({models, value, onChange, prefix = ''}) {
  const choices = models.filter(m => m.tool === value.tool);
  const selected = choices.find(m => m.model === value.model || m.label === value.model);
  function toolChanged(tool) {
    const first = models.find(m => m.tool === tool);
    onChange({tool, model:first?.model || '', effort:first?.efforts[0] || ''});
  }
  function modelChanged(model) {
    const row = choices.find(m => m.model === model);
    onChange({...value, model, effort:row?.efforts[0] || ''});
  }
  return <div className="model-selects"><label>Tool<select aria-label={prefix + (prefix ? 'tool' : 'Tool')} value={value.tool} onChange={e => toolChanged(e.target.value)}><option value="">Select tool</option>{['codex','claude'].filter(t => models.some(m => m.tool === t)).map(t => <option key={t} value={t}>{t}</option>)}</select></label><label>Model<select aria-label={prefix + (prefix ? 'model' : 'Model')} value={selected?.model || ''} onChange={e => modelChanged(e.target.value)}><option value="">Select model</option>{choices.map(m => <option key={m.model} value={m.model}>{m.label}</option>)}</select></label><label>Effort<select aria-label={prefix + (prefix ? 'effort' : 'Effort')} value={selected?.efforts.includes(value.effort) ? value.effort : ''} onChange={e => onChange({...value, effort:e.target.value})}><option value="">Select effort</option>{selected?.efforts.map(e => <option key={e} value={e}>{e}</option>)}</select></label></div>;
}
