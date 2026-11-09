// @vitest-environment jsdom
import React from 'react';
import {render, screen, fireEvent, cleanup, waitFor} from '@testing-library/react';
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
  fireEvent.click(screen.getAllByRole('button', {name:'Move to Grilling'})[0]);
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
  expect(screen.getByRole('button', {name:'No project yet'})).toBeTruthy();
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
