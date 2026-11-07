// @vitest-environment jsdom
import React from 'react';
import {render, screen, fireEvent, cleanup, waitFor} from '@testing-library/react';
import {MemoryRouter} from 'react-router-dom';
import {afterEach, test, expect, vi} from 'vitest';
import {App} from './main';
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });
const feature = {id:'FAC-F1', title:'Synthetic feature', project:'FAC', stage:'shortlist', aliases:[], sections:[{name:'Overview',text:'**Summary**'}], slices:[], moves:['grilling'], numbers:{}, stage_since:null};
test('filters, previews and displays a move refusal', async () => {
  const fetchMock = vi.fn(async (url, options) => options?.method === 'POST' ? {ok:false,json:async()=>({error:'No agreed design yet'})} : {ok:true,json:async()=>({projects:[{key:'FAC',name:'Factory'}, {key:'LAB',name:'Lab'}],features:[feature]})});
  vi.stubGlobal('fetch', fetchMock);
  render(<MemoryRouter initialEntries={['/pipeline']}><App/></MemoryRouter>);
  fireEvent.click(await screen.findByRole('button', {name:'Lab'}));
  expect(screen.queryByText('Synthetic feature')).toBeNull();
  fireEvent.click(screen.getByRole('button', {name:'Factory'}));
  fireEvent.click(screen.getByRole('button', {name:/Synthetic feature/}));
  expect(screen.getAllByText('Summary').length).toBeGreaterThan(0);
  fireEvent.click(screen.getAllByRole('button', {name:'Move to Grilling'})[0]);
  expect(await screen.findByText('No agreed design yet')).toBeTruthy();
  await waitFor(() => expect(fetchMock.mock.calls.some(([url, options]) => url === '/api/pipeline/FAC-F1/move' && options?.headers['X-Factory-UI'] === '1')).toBe(true));
});

test('shows all project buttons and collapsible stage counts', async () => {
  const projects = Array.from({length: 11}, (_, i) => ({key:`P${i}`, name:`Project ${i}`}));
  const features = [feature, {...feature, id:'FAC-F2', title:'Finished feature', stage:'done'}, {...feature, id:'FAC-F3', title:'Parked feature', stage:'parked'}];
  vi.stubGlobal('fetch', vi.fn(async () => ({ok:true, json:async()=>({projects, features})})));
  render(<MemoryRouter initialEntries={['/pipeline']}><App/></MemoryRouter>);
  const filter = await screen.findByLabelText('Project filter');
  expect(Array.from(filter.querySelectorAll('button')).map(button => button.textContent)).toEqual(['All', ...projects.map(p => p.name)]);
  expect(filter.querySelector('select')).toBeNull();
  const done = document.querySelector('.stage-done .stage-toggle');
  const parked = document.querySelector('.stage-parked .stage-toggle');
  expect(done.textContent).toContain('1');
  expect(done.getAttribute('aria-expanded')).toBe('false');
  expect(parked.getAttribute('aria-expanded')).toBe('false');
  fireEvent.click(done);
  expect(done.getAttribute('aria-expanded')).toBe('true');
  expect(document.querySelector('.stage-done').classList.contains('expanded')).toBe(true);
});
