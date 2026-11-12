// @vitest-environment jsdom
import React from 'react';
import {render, screen, fireEvent, waitFor, cleanup} from '@testing-library/react';
import {MemoryRouter} from 'react-router-dom';
import {afterEach, test, expect, vi} from 'vitest';
import {Home, Attention} from './home';
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

test.each([false, true])('feature blocks start open on desktop and folded on phone (%s)', async phone => {
  vi.stubGlobal('matchMedia', () => ({matches:phone, addEventListener:vi.fn(), removeEventListener:vi.fn()}));
  const data = {projects:[],features:[{id:'N',title:'Queued',stage:'next'}],attention:[{kind:'failure',id:'bad',text:'Problem'}],chats:[],running:[{kind:'chat',id:7,title:'Planning',project:'P'}],building:[{id:'F1',title:'Feature',done:0,total:1,slices:[{id:'S1',title:'Working',state:'issued'}]}],unlinked:[{id:'S2',title:'Unlinked',state:'ready',no_feature:'Maintenance'}]};
  vi.stubGlobal('fetch', async url => ({ok:true,json:async () => url === '/api/home' ? data : []}));
  const {container} = render(<MemoryRouter><Home/></MemoryRouter>);
  await screen.findByText('Problem');
  const feature = screen.getByRole('button',{name:/F1/});
  const unlinked = screen.getByRole('button',{name:/Not in a feature/});
  expect(feature.getAttribute('aria-expanded')).toBe(String(!phone));
  expect(unlinked.getAttribute('aria-expanded')).toBe(String(!phone));
  const text = container.textContent;
  expect(text.indexOf('Problem')).toBeLessThan(text.indexOf('Running now'));
  expect(text.indexOf('Running now')).toBeLessThan(text.indexOf('F1'));
  expect(text.indexOf('F1')).toBeLessThan(text.indexOf('Next:'));
  expect(text.indexOf('Next:')).toBeLessThan(text.indexOf('Not in a feature'));
  if (phone) { fireEvent.click(feature); fireEvent.click(unlinked); }
  expect(screen.getByText('Maintenance')).toBeTruthy();
  expect(screen.getByRole('link',{name:/Feature/}).getAttribute('href')).toBe('/pipeline/F1');
});

test('empty activity sections are hidden', async () => {
  const data = {projects:[],features:[],attention:[],running:[],building:[],unlinked:[],chats:[]};
  vi.stubGlobal('fetch', async url => ({ok:true,json:async () => url === '/api/home' ? data : []}));
  render(<MemoryRouter><Home/></MemoryRouter>);
  await screen.findByText('Home');
  await waitFor(() => expect(screen.queryByText('Loading…')).toBeNull());
  expect(screen.queryByText('Running now')).toBeNull();
  expect(screen.queryByText(/Next:/)).toBeNull();
  expect(screen.queryByText('Not in a feature')).toBeNull();
});

test('failed install offers same-slice retry beside Review', async () => {
  const data = {projects:[], features:[], running:[], chats:[], attention:[
    {kind:'failure',id:'factory/IF1b',retry_install:true,installing:false,since:'2026-11-08T00:00:00Z',text:'stderr: migration missing'}]};
  const fetcher = vi.fn().mockImplementation((url, options) => {
    if (options?.method === 'POST') data.attention[0].installing = true;
    return Promise.resolve({ok:true, json:async () => structuredClone(data)});
  });
  vi.stubGlobal('fetch', fetcher);
  render(<MemoryRouter><Home/></MemoryRouter>);
  expect(await screen.findByText('stderr: migration missing')).toBeTruthy();
  expect(screen.getByRole('link', {name:'Review'}).getAttribute('href')).toBe('/factory/slices/factory/IF1b');
  fireEvent.click(screen.getByRole('button', {name:'Retry install'}));
  await waitFor(() => expect(fetcher).toHaveBeenCalledWith('/api/slices/factory/IF1b/install', expect.objectContaining({method:'POST'})));
  await waitFor(() => expect(screen.getByRole('button', {name:'Install requested'}).disabled).toBe(true));
});

test('Home links new arrivals and ready explorations', async () => {
  const data = {projects:[],features:[],running:[],chats:[],attention:[]};
  vi.stubGlobal('fetch', async url => ({ok:true,json:async () => url === '/api/inbox' ? [{id:1,route:'New'},{id:2,route:'Idea'}] : url === '/api/ideas' ? [{id:8,title:'Insight',state:'exploring',exploration_note:'Ready'}] : data}));
  render(<MemoryRouter><Home/></MemoryRouter>);
  expect((await screen.findByRole('link',{name:'1 inbox items need routing'})).getAttribute('href')).toBe('/ideas?tab=inbox');
  expect(screen.getByRole('link',{name:'Insight · Exploration ready'}).getAttribute('href')).toBe('/ideas?tab=ideas&idea=8');
});


test('chat proposal labels the install card and leaves the owner Install action available', () => {
  const act = vi.fn();
  const item = {kind:'install',id:'factory/IW1',installable:true,installing:false,label:'proposed by chat',text:'Install the merged commit'};
  render(<MemoryRouter><Attention item={item} act={act}/></MemoryRouter>);
  expect(screen.getByText('Install · proposed by chat')).toBeTruthy();
  const install = screen.getByRole('button', {name:'Install'});
  expect(install.disabled).toBe(false);
  expect(act).not.toHaveBeenCalled();
  fireEvent.click(install);
  expect(act).toHaveBeenCalledExactlyOnceWith('/api/slices/factory/IW1/install', {});
});

test('shows the orchestrator count only when nonzero', async () => {
  const data = {projects:[], features:[], running:[], chats:[], attention:[], orchestrator_count:3};
  global.fetch = vi.fn(async url => ({ok:true, json:async () => url === '/api/home' ? data : []}));
  render(<MemoryRouter><Home /></MemoryRouter>);
  expect(await screen.findByText('With the orchestrator: 3')).toBeTruthy();
});
