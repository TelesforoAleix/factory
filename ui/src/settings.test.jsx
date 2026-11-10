// @vitest-environment jsdom
import React from 'react';
import {render, screen, fireEvent, cleanup, waitFor} from '@testing-library/react';
import {afterEach, test, expect, vi} from 'vitest';
import {Settings} from './settings';
afterEach(() => {cleanup(); vi.unstubAllGlobals();});
test('project switches persist immediately, omit NEW and report a failed save', async () => {
  const project = {key:'FAC',name:'Factory',active:true};
  const fetcher = vi.fn(async (url, options) => ({ok:true,json:async () => url === '/api/settings/models' ? {models:[],updates:[]} : url.startsWith('/api/settings/') ? [] : options ? {...project,active:false} : [project,{key:'NEW',name:'No project yet',active:true}]}));
  vi.stubGlobal('fetch',fetcher);
  render(<Settings/>);
  const toggle = await screen.findByRole('switch',{name:'Active Factory'});
  expect(toggle.checked).toBe(true);
  expect(screen.getByText('FAC').tagName).toBe('CODE');
  expect(screen.queryByText('No project yet')).toBeNull();
  fireEvent.click(toggle);
  await waitFor(() => expect(toggle.checked).toBe(false));
  expect(fetcher).toHaveBeenCalledWith('/api/projects/FAC',expect.objectContaining({method:'PATCH',headers:expect.objectContaining({'X-Factory-UI':'1'}),body:JSON.stringify({active:false})}));
  fetcher.mockResolvedValueOnce({ok:false,json:async () => ({error:'Save failed'})});
  fireEvent.click(toggle);
  expect(await screen.findByRole('alert')).toHaveProperty('textContent','Save failed');
  expect(toggle.checked).toBe(false);
});

test('combined settings save only changes and refresh both tools', async () => {
  const models = [{tool:'codex',model:'c',label:'Codex model',efforts:['low','high'],refreshed_at:'2025-01-01T00:00:00Z'}, {tool:'claude',model:'a',label:'Claude model',efforts:['max'],refreshed_at:'2025-02-01T12:00:00Z'}];
  let roles = [{role:'project',tool:'codex',model:'c',effort:'low',in_list:true}, {role:'feature',tool:'codex',model:'c',effort:'low',in_list:true}];
  let limits = [{name:'building_limit',value:2,description:'Building.'}, {name:'executors',value:2,description:'Executors.'}];
  const fetcher = vi.fn(async (url, options) => {
    let data;
    if (url === '/api/projects') data = [];
    if (url === '/api/settings/models') data = {models,updates:[]};
    if (url === '/api/settings/models/update') data = {status:'queued'};
    if (url === '/api/settings/roles') {if (options) roles = roles.map(r => r.role === JSON.parse(options.body).role ? {...r,...JSON.parse(options.body)} : r); data = roles;}
    if (url === '/api/settings/limits') {if (options) limits = limits.map(r => r.name === JSON.parse(options.body).name ? {...r,...JSON.parse(options.body)} : r); data = limits;}
    return {ok:true,json:async () => data};
  });
  vi.stubGlobal('fetch',fetcher); render(<Settings/>);
  expect(await screen.findByText('Refreshed: ' + new Date('2025-02-01T12:00:00Z').toLocaleString())).toBeTruthy();
  const saves = screen.getAllByRole('button',{name:'Save'});
  expect(saves.every(b => b.disabled)).toBe(true);
  fireEvent.click(screen.getByRole('button',{name:'Update available models'}));
  await waitFor(() => expect(fetcher.mock.calls.filter(([url]) => url === '/api/settings/models/update').map(([,opts]) => JSON.parse(opts.body).tool)).toEqual(['codex','claude']));
  expect(screen.getByRole('button',{name:'Update available models'}).disabled).toBe(true);
  fireEvent.change(screen.getByLabelText('Project orchestrator tool'),{target:{value:'claude'}});
  expect(screen.getByLabelText('Project orchestrator model').value).toBe('a');
  expect(screen.getByLabelText('Project orchestrator effort').value).toBe('max');
  fireEvent.click(saves[0]);
  await waitFor(() => expect(fetcher.mock.calls.filter(([url,opts]) => url === '/api/settings/roles' && opts)).toHaveLength(1));
  expect(fetcher).toHaveBeenCalledWith('/api/settings/roles',expect.objectContaining({headers:expect.objectContaining({'X-Factory-UI':'1'}),body:JSON.stringify({role:'project',tool:'claude',model:'a',effort:'max'})}));
  await waitFor(() => expect(saves[0].disabled).toBe(true));
  fireEvent.change(screen.getByLabelText('Building limit'),{target:{value:'3'}});
  fireEvent.click(saves[1]);
  await waitFor(() => expect(fetcher.mock.calls.filter(([url,opts]) => url === '/api/settings/limits' && opts)).toHaveLength(1));
  expect(fetcher).toHaveBeenCalledWith('/api/settings/limits',expect.objectContaining({body:JSON.stringify({name:'building_limit',value:3})}));
  await waitFor(() => expect(saves[1].disabled).toBe(true));
});

test('failed saves retain unsaved choices', async () => {
  const role = {role:'project',tool:'codex',model:'c',effort:'low',in_list:false};
  vi.stubGlobal('fetch',vi.fn(async (url, options) => ({ok:!options, json:async () => options ? {error:'Save failed'} : url === '/api/projects' ? [] : url === '/api/settings/models' ? {models:[{tool:'codex',model:'c',label:'C',efforts:['low','high'],refreshed_at:null}],updates:[]} : url === '/api/settings/roles' ? [role] : []})));
  render(<Settings/>);
  expect(await screen.findByText('Current choice is not in the stored model list.')).toBeTruthy();
  expect(screen.getByText('Refreshed: never')).toBeTruthy();
  fireEvent.change(screen.getByLabelText('Project orchestrator effort'),{target:{value:'high'}});
  fireEvent.click(screen.getAllByRole('button',{name:'Save'})[0]);
  expect(await screen.findByRole('alert')).toHaveProperty('textContent','Save failed');
  expect(screen.getByLabelText('Project orchestrator effort').value).toBe('high');
});

test('roles save in display order and retain changes after a partial failure', async () => {
  let roles = ['feature','project'].map(role => ({role,tool:'codex',model:'c',effort:'low',in_list:true}));
  const fetcher = vi.fn(async (url, options) => {
    if (url === '/api/settings/roles' && options) {
      const row = JSON.parse(options.body);
      if (row.role === 'feature') return {ok:false,json:async () => ({error:'Feature save failed'})};
      roles = roles.map(r => r.role === row.role ? {...r,...row} : r);
      return {ok:true,json:async () => roles};
    }
    return {ok:true,json:async () => url === '/api/projects' ? [] : url === '/api/settings/models' ? {models:[{tool:'codex',model:'c',label:'C',efforts:['low','high'],refreshed_at:null}],updates:[]} : url === '/api/settings/roles' ? roles : []};
  });
  vi.stubGlobal('fetch',fetcher); render(<Settings/>);
  await screen.findByLabelText('Project orchestrator effort');
  fireEvent.change(screen.getByLabelText('Feature chat effort'),{target:{value:'high'}});
  fireEvent.change(screen.getByLabelText('Project orchestrator effort'),{target:{value:'high'}});
  fireEvent.click(screen.getAllByRole('button',{name:'Save'})[0]);
  expect(await screen.findByRole('alert')).toHaveProperty('textContent','Feature save failed');
  expect(fetcher.mock.calls.filter(([url,opts]) => url === '/api/settings/roles' && opts).map(([,opts]) => JSON.parse(opts.body).role)).toEqual(['project','feature']);
  expect(screen.getByLabelText('Feature chat effort').value).toBe('high');
  expect(screen.getAllByRole('button',{name:'Save'})[0].disabled).toBe(false);
});
