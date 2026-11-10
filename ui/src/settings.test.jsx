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

test('models refresh, roles filter and save, and limits save independently', async () => {
  const models = [{tool:'codex',model:'c',label:'Codex model',efforts:['low','high'],refreshed_at:'today'}, {tool:'claude',model:'a',label:'Claude model',efforts:['max'],refreshed_at:'today'}];
  const role = {role:'project',tool:'codex',model:'c',effort:'low',in_list:true};
  const limit = {name:'repository_runs',value:1,description:'One repository run.'};
  let queued = false, polls = 0;
  const fetcher = vi.fn(async (url, options) => {
    let data;
    if (url === '/api/projects') data = [];
    if (url === '/api/settings/models') data = {models,updates:queued ? [{tool:'codex',status:++polls > 1 ? 'completed' : 'running',reason:polls > 1 ? 'done' : null}] : []};
    if (url === '/api/settings/models/update') {queued = true; data = {status:'queued'};}
    if (url === '/api/settings/roles') data = options ? [{...role,...JSON.parse(options.body)}] : [role];
    if (url === '/api/settings/limits') data = [limit];
    return {ok:true,json:async () => data};
  });
  vi.stubGlobal('fetch',fetcher); render(<Settings/>);
  expect(await screen.findByText(/Codex model/)).toBeTruthy();
  fireEvent.click(screen.getByRole('button',{name:'Update Codex models'}));
  expect(await screen.findByText('queued')).toBeTruthy();
  expect(await screen.findByText('completed: done', {}, {timeout:4000})).toBeTruthy();
  fireEvent.change(screen.getByLabelText('Project orchestrator tool'),{target:{value:'claude'}});
  expect(screen.getByLabelText('Project orchestrator model').value).toBe('a');
  expect(screen.getByLabelText('Project orchestrator effort').value).toBe('max');
  fireEvent.click(screen.getByRole('button',{name:'Save Project orchestrator'}));
  await waitFor(() => expect(fetcher).toHaveBeenCalledWith('/api/settings/roles',expect.objectContaining({body:JSON.stringify({role:'project',tool:'claude',model:'a',effort:'max'})})));
  expect(screen.getByLabelText('Runs per repository').max).toBe('1');
  fireEvent.click(screen.getByRole('button',{name:'Save Runs per repository'}));
  await waitFor(() => expect(fetcher).toHaveBeenCalledWith('/api/settings/limits',expect.objectContaining({body:JSON.stringify({name:'repository_runs',value:1})})));
});
