// @vitest-environment jsdom
import React from 'react';
import {render, screen, fireEvent, cleanup, waitFor} from '@testing-library/react';
import {MemoryRouter} from 'react-router-dom';
import {afterEach, test, expect, vi} from 'vitest';
import {App} from './main';
import {Markdown} from './documents';
afterEach(() => {cleanup(); vi.unstubAllGlobals();});
test('Markdown disables raw HTML and renders phone-scrollable GFM tables', () => {
  const {container} = render(<Markdown>{'# Safe\n\n<script>alert(1)</script>\n\n<img src=x onerror="alert(1)">\n\n| Task | State |\n| --- | --- |\n| Demo | Ready |\n\n[unsafe](javascript:alert(1))'}</Markdown>);
  expect(screen.getByRole('heading', {name: 'Safe'})).toBeTruthy();
  expect(container.querySelector('script')).toBeNull();
  expect(container.querySelector('img')).toBeNull();
  expect(container.querySelector('[onerror]')).toBeNull();
  expect(container.querySelector('a')?.getAttribute('href')).not.toContain('javascript:');
  expect(container.querySelector('.table-scroll table')).toBeTruthy();
  expect(screen.getByRole('cell', {name: 'Ready'})).toBeTruthy();
});
test('lists documents by folder and searches', async () => {
  const fetchMock = vi.fn(async () => ({ok: true, json: async () => [{path: 'design/plan.md', folder: 'design', title: 'Plan', status: 'draft', date: '2026-11-01'}]}));
  vi.stubGlobal('fetch', fetchMock);
  render(<MemoryRouter initialEntries={['/home-lab']}><App/></MemoryRouter>);
  expect(await screen.findByText('Plan')).toBeTruthy();
  expect(screen.getByRole('heading', {name: 'design'})).toBeTruthy();
  expect(screen.getByText('draft · 2026-11-01')).toBeTruthy();
  fireEvent.change(screen.getByLabelText('Search documents'), {target: {value: 'router'}});
  await waitFor(() => expect(fetchMock).toHaveBeenCalledWith('/api/homelab/documents?q=router', {}));
});
test('backlog renders a table and saves and sends owner notes with the guard', async () => {
  const fetchMock = vi.fn(async (url, options) => ({ok: true, json: async () => {
    if (url.includes('/documents/')) return {path: 'backlog.md', title: 'Backlog', status: 'draft', date: '2026-11-01', markdown: '| Task | State |\n| --- | --- |\n| Demo | Ready |'};
    if (url === '/api/homelab/sessions') return [{id: 7, title: 'Review', state: 'idle'}];
    if (url.includes('/notes/')) return options?.method === 'POST' ? [{id: 1, text: 'Review this', time: '2026-11-01'}] : [];
    return [];
  }}));
  vi.stubGlobal('fetch', fetchMock);
  render(<MemoryRouter initialEntries={['/home-lab/backlog']}><App/></MemoryRouter>);
  expect(await screen.findByRole('table')).toBeTruthy();
  fireEvent.change(screen.getByLabelText('Leave a note'), {target: {value: 'Review this'}});
  fireEvent.click(screen.getByRole('button', {name: 'Save note'}));
  expect(await screen.findByText('Review this')).toBeTruthy();
  fireEvent.change(screen.getByLabelText('Home Lab session'), {target: {value: '7'}});
  fireEvent.click(screen.getByRole('button', {name: 'Send note into session'}));
  await waitFor(() => expect(fetchMock.mock.calls.some(([url, options]) => url === '/api/homelab/send-note/1/backlog.md' && options.headers['X-Factory-UI'] === '1' && JSON.parse(options.body).session === 7)).toBe(true));
});
test('grill starts with document and named repositories and selects the resulting session', async () => {
  const fetchMock = vi.fn(async (url) => ({ok: true, json: async () => {
    if (url === '/api/homelab/documents') return [{path: 'plan.md'}];
    if (url === '/api/homelab/grills') return {id: 9};
    if (url.endsWith('/messages')) return [{id: 1, role: 'assistant', status: 'done', text: 'Which machine?'}];
    return [{id: 9, title: 'Grill: Plan', state: 'idle'}];
  }}));
  vi.stubGlobal('fetch', fetchMock);
  render(<MemoryRouter initialEntries={['/home-lab/grills']}><App/></MemoryRouter>);
  await screen.findByRole('option', {name: 'plan.md'});
  fireEvent.change(screen.getByLabelText('Document'), {target: {value: 'plan.md'}});
  fireEvent.change(screen.getByLabelText('Model'), {target: {value: 'synthetic'}});
  fireEvent.change(screen.getByLabelText('Repositories (owner/name, separated by commas)'), {target: {value: 'owner/repo'}});
  fireEvent.click(screen.getByRole('button', {name: 'Start grill'}));
  expect(await screen.findByText('Which machine?')).toBeTruthy();
  expect(screen.getByText('Planner question').closest('article').className).toContain('planner-question');
  const call = fetchMock.mock.calls.find(([url]) => url === '/api/homelab/grills');
  expect(call[1].headers['X-Factory-UI']).toBe('1');
  expect(JSON.parse(call[1].body)).toEqual({document: 'plan.md', tool: 'codex', model: 'synthetic', repositories: ['owner/repo']});
});
