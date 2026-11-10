import React from 'react';

export function ModelSelects({models, value, onChange, prefix = '', cells = false, disabled = false}) {
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
  const selects = [<label key="tool">Tool<select disabled={disabled} aria-label={prefix + (prefix ? 'tool' : 'Tool')} value={value.tool} onChange={e => toolChanged(e.target.value)}><option value="">Select tool</option>{['codex','claude'].filter(t => models.some(m => m.tool === t)).map(t => <option key={t} value={t}>{t}</option>)}</select></label>, <label key="model">Model<select disabled={disabled} aria-label={prefix + (prefix ? 'model' : 'Model')} value={selected?.model || ''} onChange={e => modelChanged(e.target.value)}><option value="">Select model</option>{choices.map(m => <option key={m.model} value={m.model}>{m.label}</option>)}</select></label>, <label key="effort">Effort<select disabled={disabled} aria-label={prefix + (prefix ? 'effort' : 'Effort')} value={selected?.efforts.includes(value.effort) ? value.effort : ''} onChange={e => onChange({...value, effort:e.target.value})}><option value="">Select effort</option>{selected?.efforts.map(e => <option key={e} value={e}>{e}</option>)}</select></label>];
  return cells ? selects.map((select, i) => <td key={i} data-label={['Tool','Model','Effort'][i]}>{select}</td>) : <div className="model-selects">{selects}</div>;
}
