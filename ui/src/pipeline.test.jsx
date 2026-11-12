// @vitest-environment jsdom
import React from 'react';
import {render, screen, fireEvent, cleanup, waitFor, within} from '@testing-library/react';
import {MemoryRouter} from 'react-router-dom';
import {afterEach, test, expect, vi} from 'vitest';
import {App} from './main';
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });
const feature = {id:'FAC-F1', title:'Synthetic feature', project:'FAC', stage:'shortlist', aliases:[], sections:[{name:'Overview',text:'**Summary**'}], slices:[], moves:['grilling'], numbers:{}, stage_since:null};
test('filters, previews and displays a move refusal', async () => {
  const fetchMock = vi.fn(async (url, options) => options?.method === 'POST' ? {ok:false,json:async()=>({error:'No agreed design yet'})} : {ok:true,json:async()=> url === '/api/pipeline/FAC-F1' ? feature : url === '/api/chats' ? [] : ({projects:[{key:'FAC',name:'Factory'}, {key:'LAB',name:'Lab'}],features:[feature]})});
  vi.stubGlobal('fetch', fetchMock);
  render(<MemoryRouter initialEntries={['/pipeline']}><App/></MemoryRouter>);
  fireEvent.click(await screen.findByRole('button', {name:'Lab'}));
  expect(screen.queryByText('Synthetic feature')).toBeNull();
  fireEvent.click(screen.getByRole('button', {name:'Factory'}));
  fireEvent.click(screen.getByRole('button', {name:/Synthetic feature/}));
  expect((await screen.findAllByText('Summary')).length).toBeGreaterThan(0);
  fireEvent.click(screen.getAllByRole('button', {name:'Grilling'})[0]);
  expect(await screen.findByText('No agreed design yet')).toBeTruthy();
  await waitFor(() => expect(fetchMock.mock.calls.some(([url, options]) => url === '/api/pipeline/FAC-F1/move' && options?.headers['X-Factory-UI'] === '1')).toBe(true));
});

test('shows a project selector and collapsible stage counts', async () => {
  const projects = Array.from({length: 11}, (_, i) => ({key:`P${i}`, name:`Project ${i}`}));
  const features = [feature, {...feature, id:'FAC-F2', title:'Finished feature', stage:'done'}, {...feature, id:'FAC-F3', title:'Parked feature', stage:'parked'}];
  vi.stubGlobal('fetch', vi.fn(async () => ({ok:true, json:async()=>({projects, features})})));
  render(<MemoryRouter initialEntries={['/pipeline']}><App/></MemoryRouter>);
  const filter = await screen.findByRole('group', {name:'Project'});
  expect(Array.from(filter.querySelectorAll('button')).map(button => button.textContent)).toEqual(['All', ...projects.map(p => p.name)]);
  expect(document.querySelector('.feature-chip')).toBeNull();
  expect(document.querySelector('.stage-done')).toBeNull();
  expect(screen.queryByText('Finished feature')).toBeNull();
  const parked = document.querySelector('.stage-parked .stage-toggle');
  expect(parked.getAttribute('aria-expanded')).toBe('false');
});

test('inactive projects hide only Shortlist and Parked and mark in-flight cards', async () => {
  const projects = [{key:'FAC',name:'Factory',active:false}, {key:'LAB',name:'Lab',active:true}, {key:'NEW',name:'No project yet',active:true}];
  const features = ['shortlist','parked','grilling','ready','next','building','testing'].map((stage,i) => ({...feature,id:`FAC-F${i + 1}`,title:`Inactive ${stage}`,stage}));
  vi.stubGlobal('fetch', vi.fn(async () => ({ok:true,json:async()=>({projects,features})})));
  render(<MemoryRouter initialEntries={['/pipeline']}><App/></MemoryRouter>);
  await screen.findByText('Inactive grilling');
  expect(screen.queryByText('Inactive shortlist')).toBeNull();
  expect(screen.queryByText('Inactive parked')).toBeNull();
  expect(screen.getAllByText('Inactive').length).toBe(5);
  expect(screen.queryByRole('button', {name:'Factory'})).toBeNull();
  expect(screen.getByRole('button', {name:'Lab'})).toBeTruthy();
  expect(screen.queryByRole('button', {name:'No project yet'})).toBeNull();
});

test('slim cards fetch one detail only when opened', async () => {
  const card = {id:feature.id, title:feature.title, project:'FAC', stage:'building', position:0, extra:'Waiting for you', waiting:true, slice_count:1, open_attention:1};
  const fetcher = vi.fn(async url => ({ok:true,json:async () => url === '/api/pipeline' ? {projects:[],features:[card]} : url === '/api/chats' ? [] : feature}));
  vi.stubGlobal('fetch', fetcher);
  render(<MemoryRouter initialEntries={['/pipeline']}><App/></MemoryRouter>);
  await screen.findByText('Waiting for you');
  expect(fetcher.mock.calls.some(([url]) => url === '/api/pipeline/FAC-F1')).toBe(false);
  fireEvent.click(screen.getByRole('button', {name:/Synthetic feature/}));
  await screen.findAllByText('Summary');
  expect(fetcher.mock.calls.filter(([url]) => url === '/api/pipeline/FAC-F1')).toHaveLength(1);
});

test('full feature page reads only its detail', async () => {
  const fetcher = vi.fn(async url => ({ok:true,json:async () => url === '/api/chats' ? [] : feature}));
  vi.stubGlobal('fetch', fetcher);
  render(<MemoryRouter initialEntries={['/pipeline/FAC-F1']}><App/></MemoryRouter>);
  await screen.findByText('Summary');
  expect(fetcher.mock.calls.some(([url]) => url === '/api/pipeline')).toBe(false);
});

test('groups stages into four columns and toggles compact preview', async () => {
  vi.stubGlobal('fetch', vi.fn(async url => ({ok:true,json:async () => url === '/api/pipeline' ? {projects:[],features:[feature]} : url === '/api/chats' ? [] : feature})));
  render(<MemoryRouter initialEntries={['/pipeline']}><App/></MemoryRouter>);
  await screen.findByText('Synthetic feature');
  const groups = [...document.querySelectorAll('.pipeline-group')];
  expect(groups.map(g => [...g.querySelectorAll('.pipeline-column')].map(c => c.className.match(/stage-\w+/)[0]))).toEqual([['stage-shortlist'],['stage-grilling'],['stage-ready','stage-next'],['stage-building','stage-testing'],['stage-parked']]);
  const card = screen.getByRole('button', {name:/Synthetic feature/});
  fireEvent.click(card);
  expect(document.querySelector('.pipeline-layout.has-panel')).toBeTruthy();
  expect(card.getAttribute('aria-expanded')).toBe('true');
  fireEvent.click(card);
  expect(document.querySelector('.pipeline-layout.has-panel')).toBeNull();
  fireEvent.click(card);
  fireEvent.keyDown(document, {key:'Escape'});
  expect(document.querySelector('.pipeline-layout.has-panel')).toBeNull();
});

test('phone stages start collapsed except the active three and a card closes on a second tap', async () => {
  vi.stubGlobal('matchMedia', () => ({matches:true, addEventListener:vi.fn(), removeEventListener:vi.fn()}));
  const card = {...feature, stage:'ready'};
  vi.stubGlobal('fetch', vi.fn(async url => ({ok:true,json:async () => url === '/api/pipeline' ? {projects:[],features:[card]} : url === '/api/chats' ? [] : card})));
  render(<MemoryRouter initialEntries={['/pipeline']}><App/></MemoryRouter>);
  await screen.findByText('Synthetic feature');
  expect([...document.querySelectorAll('.stage-toggle')].map(b => [b.textContent.trim().replace(/\s+\d+$/, ''), b.getAttribute('aria-expanded')])).toEqual([['Shortlist','false'],['Grilling','false'],['Ready','true'],['Next','true'],['Building','true'],['Testing','false'],['Parked','false']]);
  const button = screen.getByRole('button',{name:/Synthetic feature/});
  fireEvent.click(button);
  await waitFor(() => expect(document.querySelector('.mobile-panel')).toBeTruthy());
  fireEvent.click(button);
  expect(document.querySelector('.mobile-panel')).toBeNull();
});

test('swaps an open panel in place and loads slice details on demand', async () => {
  const second = {...feature, id:'FAC-F2', title:'Second feature', slices:[{id:'repo/S1', title:'Slice', state:'ready', movable:false, final:{body:'First line'}}]};
  let resolveSecond;
  const pending = new Promise(resolve => {resolveSecond = resolve;});
  const fetcher = vi.fn(async url => {
    if (url === '/api/pipeline') return {ok:true,json:async () => ({projects:[],features:[feature,second]})};
    if (url === '/api/pipeline/FAC-F2') return pending;
    return {ok:true,json:async () => url === '/api/chats' ? [] : url.startsWith('/api/slices/') ? {final:{body:'Full final'},log:[{at:'now',actor:'tester',event:'history'}]} : feature};
  });
  vi.stubGlobal('fetch', fetcher);
  render(<MemoryRouter initialEntries={['/pipeline']}><App/></MemoryRouter>);
  fireEvent.click(await screen.findByRole('button', {name:/Synthetic feature/}));
  await screen.findAllByText('Summary');
  const panel = document.querySelector('.desktop-panel');
  fireEvent.click(screen.getByRole('button', {name:/Second feature/}));
  expect(document.querySelector('.desktop-panel')).toBe(panel);
  expect(panel.querySelector('[aria-busy="true"]')).toBeTruthy();
  resolveSecond({ok:true,json:async () => second});
  await waitFor(() => expect(panel.textContent).toContain('First line'));
  expect(fetcher.mock.calls.some(([url]) => url.startsWith('/api/slices/'))).toBe(false);
  fireEvent.click(panel.querySelector('.slice-row button'));
  expect(panel.querySelector('.slice-panel')).toBeTruthy();
});

test('project page context filters Pipeline and survives preview open and close', async () => {
  const other = {...feature,id:'LAB-F1',project:'LAB',title:'Other project feature'};
  vi.stubGlobal('fetch', vi.fn(async url => ({ok:true,json:async () => url === '/api/pipeline' ? {projects:[{key:'FAC',name:'Factory',active:false},{key:'LAB',name:'Lab'}],features:[feature,other]} : url === '/api/chats' ? [] : feature})));
  render(<MemoryRouter initialEntries={['/pipeline?project=FAC']}><App/></MemoryRouter>);
  const card = await screen.findByRole('button',{name:/Synthetic feature/});
  expect(screen.queryByText('Other project feature')).toBeNull();
  fireEvent.click(card);
  await screen.findAllByText('Summary');
  expect(screen.queryByText('Other project feature')).toBeNull();
  fireEvent.keyDown(document,{key:'Escape'});
  expect(screen.queryByText('Other project feature')).toBeNull();
  expect(screen.getByRole('button',{name:'Factory'}).getAttribute('aria-pressed')).toBe('true');
});

test('slice chips and relationship panel use board explanations', async () => {
  const statuses = ['ready','blocked','waiting for a decision','waiting for a test or approval','resource busy','failed'];
  const slices = statuses.map((status,i) => ({id:`demo/S${i}`,title:`Item ${i}`,state:'ready',movable:false,eligibility:{status,...(i === 1 ? {ids:['demo/blocker']} : {})},depends_on:i === 1 ? ['demo/prerequisite'] : [],dependants:i === 1 ? ['demo/dependant'] : []}));
  const detail = {...feature,slices};
  vi.stubGlobal('fetch',vi.fn(async url => ({ok:true,json:async()=>url === '/api/pipeline' ? {projects:[],features:[feature]} : url === '/api/chats' ? [] : detail})));
  render(<MemoryRouter initialEntries={['/pipeline/FAC-F1']}><App/></MemoryRouter>);
  for (const status of statuses) expect(await screen.findByText(status)).toBeTruthy();
  fireEvent.click(screen.getByRole('button',{name:/Item 1/}));
  const panel = screen.getByLabelText('Slice demo/S1');
  for (const [heading,id] of [['Blockers','demo/blocker'],['Prerequisites','demo/prerequisite'],['Dependants','demo/dependant']]) {
    expect(panel.textContent).toContain(heading);
    expect(within(panel).getByRole('link',{name:id}).getAttribute('href')).toBe('/factory/slices/' + id);
  }
});
