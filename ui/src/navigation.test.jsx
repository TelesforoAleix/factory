// @vitest-environment jsdom
import React from 'react';
import {render, screen, fireEvent} from '@testing-library/react';
import {MemoryRouter} from 'react-router-dom';
import {test, expect, vi} from 'vitest';
import {App} from './main';
test('navigation switches between persistent areas', async () => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ok: true, json: async () => []}));
  render(<MemoryRouter initialEntries={['/home-lab']}><App/></MemoryRouter>);
  expect(screen.getByRole('heading', {name: 'Home Lab'})).toBeTruthy();
  fireEvent.click(screen.getByRole('link', {name: 'Factory', exact: true}));
  expect(await screen.findByText('No slices yet.')).toBeTruthy();
  fireEvent.click(screen.getByRole('link', {name: 'Home Lab'}));
  expect(screen.getByRole('heading', {name: 'Home Lab'})).toBeTruthy();
});

test('slice detail displays a recorded final as text and handles its absence', async () => {
  const item = {id: 'demo/one', title: 'Example', state: 'ready', paused: false,
    repo: 'demo/repo', feature: 'Example', executor: {tool: 'codex', model: 'test'},
    depends_on: [], slot: null, pr: null, attention: null, log: [], final: null};
  const fetchMock = vi.fn().mockResolvedValue({ok: true, json: async () => item});
  vi.stubGlobal('fetch', fetchMock);
  const page = render(<MemoryRouter initialEntries={['/factory/slices/demo/one']}><App/></MemoryRouter>);
  expect(await screen.findByText('not recorded', {selector: 'p'})).toBeTruthy();
  page.unmount();
  item.final = {kind: 'handover', body: '<script>hello</script>\nfinished', at: '2026-01-01T00:00:00Z'};
  render(<MemoryRouter initialEntries={['/factory/slices/demo/one']}><App/></MemoryRouter>);
  expect(await screen.findByText('<script>hello</script> finished', {normalizer: text => text.replace(/\s+/g, ' ').trim()})).toBeTruthy();
  expect(document.querySelector('script')).toBeNull();
});
