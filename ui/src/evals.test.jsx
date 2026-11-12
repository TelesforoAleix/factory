// @vitest-environment jsdom
import React from 'react';
import {describe, it, expect, vi, afterEach} from 'vitest';
import {render, screen, cleanup, within} from '@testing-library/react';
import {MemoryRouter} from 'react-router-dom';
import {RunTable, EvalRuns, EvalSets, EvalNew} from './evals';
afterEach(() => {cleanup(); vi.unstubAllGlobals();});
describe('eval pages', () => {
 it('renders empty metrics and separate judge shares', () => {
  const run = {configurations:[{id:'c'}],attempts:[{case:'x',configuration_id:'c',state:'done',result:{tests:'pass'},metrics:{},verdicts:[{judge:'a',verdict:'mergeable'},{judge:'b',verdict:'not_mergeable'}]}]};
  render(<RunTable run={run} set={{id:'s',title:'Set',version:1,members:['x']}}/>);
  const cells = within(screen.getAllByRole('row')[1]).getAllByRole('cell');
  expect(cells.map(c => c.textContent)).toEqual(['1 / 1','100%','100%','0%','','','','','','']);
 });
 it('renders lists and no history estimate', async () => {
  vi.stubGlobal('fetch', vi.fn(url => Promise.resolve({ok:true,json:() => Promise.resolve(url.includes('settings') ? {models:[]} : [])})));
  const view = render(<MemoryRouter><EvalRuns/></MemoryRouter>); expect(await screen.findByText('No eval runs yet.')).toBeTruthy(); view.unmount();
  const sets = render(<MemoryRouter><EvalSets/></MemoryRouter>); expect(await screen.findByText('No sets yet.')).toBeTruthy(); sets.unmount();
  render(<MemoryRouter><EvalNew/></MemoryRouter>); expect(await screen.findByText(/no estimate/)).toBeTruthy();
 });
});

it('submits a scheduled run with a local offset and selected version', async () => {
 const {fireEvent, waitFor} = await import('@testing-library/react');
 const calls = [];
 vi.stubGlobal('fetch', vi.fn((url, options) => {calls.push([url,options]); const data = options ? {id:9} : url === '/api/evals/sets' ? [{id:'s',title:'Set',version:2,case_count:1}] : url === '/api/evals/sets/s' ? {id:'s',version:2,members:['x']} : url.includes('settings') ? {models:[]} : []; return Promise.resolve({ok:true,json:() => Promise.resolve(data)});}));
 render(<MemoryRouter><EvalNew/></MemoryRouter>);
 fireEvent.click(await screen.findByLabelText(/Set · version 2/));
 fireEvent.change(screen.getByLabelText('Title'),{target:{value:'Run'}});
 fireEvent.change(screen.getByLabelText('Model'),{target:{value:'m'}});
 fireEvent.change(screen.getByLabelText('Route'),{target:{value:'gateway'}});
 fireEvent.click(screen.getByLabelText('Schedule'));
 fireEvent.change(screen.getByLabelText('Local date and time'),{target:{value:'2026-12-01T12:30'}});
 fireEvent.click(screen.getByText('Create eval run'));
 await waitFor(() => expect(calls.some(([,o]) => o?.method === 'POST')).toBe(true));
 const [url,options] = calls.find(([,o]) => o?.method === 'POST'); const body = JSON.parse(options.body);
 expect(url).toBe('/api/evals/runs'); expect(options.headers['X-Factory-UI']).toBe('1');
 expect(body.sets).toEqual(['s:2']); expect(body.configurations).toEqual([{id:'pi-m',harness:'pi',model:'m',route:'gateway'}]);
 expect(body.scheduled_for).toMatch(/^2026-12-01T12:30:00[+-]\d\d:\d\d$/);
});

it('stops polling a completed run', async () => {
 const {EvalRun} = await import('./evals');
 const {Routes, Route} = await import('react-router-dom');
 const fetcher = vi.fn(() => Promise.resolve({ok:true,json:() => Promise.resolve({title:'Completed',state:'done',repeats:1,sets:[],attempts:[]})}));
 vi.stubGlobal('fetch', fetcher);
 render(<MemoryRouter initialEntries={['/evals/runs/1']}><Routes><Route path="/evals/runs/:id" element={<EvalRun/>}/></Routes></MemoryRouter>);
 expect(await screen.findByText('Completed')).toBeTruthy();
 document.dispatchEvent(new Event('visibilitychange'));
 await new Promise(resolve => setTimeout(resolve, 20));
 expect(fetcher).toHaveBeenCalledTimes(1);
});
