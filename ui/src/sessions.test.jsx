// @vitest-environment jsdom
import React from 'react';
import {render, screen, fireEvent, cleanup, waitFor} from '@testing-library/react';
import {MemoryRouter} from 'react-router-dom';
import {afterEach, test, expect, vi} from 'vitest';
import {App} from './main';
afterEach(() => {cleanup(); vi.unstubAllGlobals();});
test.each([['factory', '/factory/sessions']])('sends one guarded message in %s and displays replies as text', async (area, path) => {
  const rows = [{id: 1, role: 'assistant', status: 'done', text: '<script>reply</script>'}];
  const fetchMock = vi.fn(async (url, options) => ({ok: true, json: async () => {
    if (url.endsWith('/messages')) return rows;
    if (options?.method === 'POST') return {id: 7};
    return [{id: 7, title: 'Example', state: 'idle'}];
  }}));
  vi.stubGlobal('fetch', fetchMock);
  render(<MemoryRouter initialEntries={[path]}><App/></MemoryRouter>);
  fireEvent.change(screen.getByLabelText('Title'), {target: {value: 'Example'}});
  fireEvent.change(screen.getByLabelText('Model'), {target: {value: 'synthetic'}});
  fireEvent.click(screen.getByRole('button', {name: 'Create session'}));
  expect(await screen.findByText('<script>reply</script>')).toBeTruthy();
  expect(document.querySelector('script')).toBeNull();
  fireEvent.change(screen.getByLabelText('Message'), {target: {value: 'next turn'}});
  await waitFor(() => expect(screen.getByRole('button', {name: 'Send'}).disabled).toBe(false));
  fireEvent.click(screen.getByRole('button', {name: 'Send'}));
  await waitFor(() => expect(fetchMock.mock.calls.some(([url, options]) =>
    url === `/api/${area}/sessions/7/messages` && options?.method === 'POST' &&
    options.headers['X-Factory-UI'] === '1' && JSON.parse(options.body).text === 'next turn')).toBe(true));
});

test('shows the full pushed planning commit in the session', async () => {
  const commit = 'abcdef0123456789abcdef0123456789abcdef01';
  vi.stubGlobal('fetch', vi.fn(async url => ({ok: true, json: async () =>
    url.endsWith('/messages') ? [{id: 2, role: 'assistant', status: 'done', text: 'Planning pushed commit ' + commit}]
      : [{id: 7, title: 'Example', state: 'idle'}]})));
  render(<MemoryRouter initialEntries={['/factory/sessions?session=7']}><App/></MemoryRouter>);
  expect((await screen.findByText(commit)).tagName).toBe('CODE');
});
