// @vitest-environment jsdom
import React from 'react';
import {render, screen, fireEvent, waitFor, cleanup} from '@testing-library/react';
import {MemoryRouter} from 'react-router-dom';
import {afterEach, test, expect, vi} from 'vitest';
import {Home} from './home';
afterEach(() => {cleanup(); vi.unstubAllGlobals();});

test('Home filters sections and sends a quick answer under the guard', async () => {
  const data = {projects:[{key:'FAC',name:'Factory'},{key:'OTH',name:'Other'}], features:[{id:'FAC-F1',title:'Next feature',project:'FAC',stage:'next'}], running:[], chats:[], attention:[{kind:'question',id:'demo/one',project:'FAC',since:'2026-01-01T00:00:00Z',text:'Choose?'}]};
  const fetcher = vi.fn().mockImplementation((url, options) => Promise.resolve({ok:true, json:async () => data, text:async () => 'ok'}));
  vi.stubGlobal('fetch', fetcher);
  render(<MemoryRouter><Home/></MemoryRouter>);
  expect(await screen.findByText('Choose?')).toBeTruthy();
  fireEvent.change(screen.getByLabelText('Answer'), {target:{value:'Proceed'}});
  fireEvent.click(screen.getByText('Send answer'));
  await waitFor(() => expect(fetcher).toHaveBeenCalledWith('/api/actions/answer/demo/one', expect.objectContaining({method:'POST', headers:expect.objectContaining({'X-Factory-UI':'1'}), body:JSON.stringify({value:'Proceed'})})));
  fireEvent.click(screen.getByRole('button', {name:'Other'}));
  expect(screen.queryByText('Choose?')).toBeNull();
  expect(screen.queryByText('Next feature')).toBeNull();
});

test('Testing review links to chat and requested install remains an owner action', async () => {
  const data = {projects:[], features:[], running:[], chats:[], attention:[
    {kind:'testing-review',id:'FAC-F1',chat:12,since:'2026-01-01T00:00:00Z',text:'Please test'},
    {kind:'install',id:'factory/TR1',installable:true,installing:true,since:'2026-01-01T00:00:00Z',text:'Install the change'}]};
  const fetcher = vi.fn().mockResolvedValue({ok:true,json:async () => data});
  vi.stubGlobal('fetch', fetcher);
  render(<MemoryRouter><Home/></MemoryRouter>);
  expect(await screen.findByText('Testing review')).toBeTruthy();
  expect(screen.getByRole('link', {name:'Open chat'}).getAttribute('href')).toBe('/chats/12');
  expect(screen.getByText(/FAC-F1 · .* waiting/)).toBeTruthy();
  fireEvent.click(screen.getByRole('button', {name:'Install requested'}));
  await waitFor(() => expect(fetcher).toHaveBeenCalledWith('/api/slices/factory/TR1/install', expect.objectContaining({method:'POST'})));
});

test('inactive attention, running and Next remain visible with quick chat links', async () => {
  const data = {projects:[{key:'FAC',name:'Factory',active:false},{key:'LAB',name:'Lab',active:true}], features:[{id:'FAC-F1',title:'Queued inactive',project:'FAC',stage:'next'}], running:[{id:'FAC/R1',title:'Running inactive',project:'FAC'}], chats:[{id:7,title:'Waiting inactive',project:'FAC'}], attention:[{kind:'failure',id:'FAC/R1',title:'Failure inactive',project:'FAC',text:'Needs help'}],quick_chats:[{id:1,title:'Development Orchestrator'},{id:9,title:'Lab'}]};
  vi.stubGlobal('fetch', vi.fn(async () => ({ok:true,json:async () => data})));
  render(<MemoryRouter><Home/></MemoryRouter>);
  expect(await screen.findByText('Failure inactive')).toBeTruthy();
  expect(screen.getByText('Running inactive')).toBeTruthy();
  expect(screen.getByText('Waiting inactive')).toBeTruthy();
  expect(screen.getByText('Queued inactive')).toBeTruthy();
  expect(screen.queryByRole('button',{name:'Factory'})).toBeNull();
  const quick = screen.getByLabelText('Quick chats');
  expect([...quick.querySelectorAll('a')].map(a => [a.textContent,a.getAttribute('href')])).toEqual([['Development Orchestrator','/chats/1'],['Lab','/chats/9']]);
});
