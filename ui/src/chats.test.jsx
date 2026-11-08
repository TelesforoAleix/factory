// @vitest-environment jsdom
import React from 'react';
import {render, screen, fireEvent, cleanup, waitFor} from '@testing-library/react';
import {MemoryRouter} from 'react-router-dom';
import {afterEach, test, expect, vi} from 'vitest';
import {App} from './main';
afterEach(() => {cleanup(); vi.unstubAllGlobals();});
test('opens a chat, queues a message, and marks it unread', async () => {
  const chat = {id:7, title:'Example chat', kind:'feature', feature:'F-1', project:'alpha', area:'factory', tool:'codex', model:'test', state:'running', waiting:false};
  const messages = [{id:1, role:'system', automatic:true, status:'done', text:'Instructions\nMore'}, {id:2, role:'assistant', automatic:false, status:'done', text:'Hello', time:'2026-01-01T12:00:00+00:00'}];
  const fetchMock = vi.fn(async (url, options) => ({ok:true, json:async () => {
    if (url === '/api/chats') return [chat, {...chat, id:8, title:'Archived', archived:true}];
    if (url.endsWith('/open')) return {chat, messages};
    if (url.endsWith('/usage')) return {'2':{tokens:{input_tokens:100}, seconds:3}};
    if (url.endsWith('/messages')) return messages;
    if (url.endsWith('/unread')) return {...chat, waiting:true};
    return chat;
  }}));
  vi.stubGlobal('fetch', fetchMock);
  render(<MemoryRouter initialEntries={['/chats/7']}><App/></MemoryRouter>);
  expect(await screen.findByText('Hello')).toBeTruthy();
  expect(screen.getAllByText(/Instructions/)[0].closest('details').open).toBe(false);
  expect(await screen.findByText('Turn usage')).toBeTruthy();
  expect(screen.getByText('Queued')).toBeTruthy();
  expect(screen.getByLabelText('Chat tool').disabled).toBe(true);
  fireEvent.change(screen.getByLabelText('Message'), {target:{value:'Next'}});
  fireEvent.click(screen.getByRole('button', {name:'Send'}));
  fireEvent.click(screen.getByRole('button', {name:'Mark unread'}));
  await waitFor(() => expect(fetchMock.mock.calls.some(([url, opts]) => url === '/api/factory/sessions/7/messages' && opts?.method === 'POST' && JSON.parse(opts.body).text === 'Next')).toBe(true));
  expect(fetchMock.mock.calls.some(([url]) => url === '/api/chats/7/unread')).toBe(true);
  expect(screen.getByText('Archived chats (1)').closest('details').open).toBe(false);
});

test('assistant Markdown is rendered while owner text stays literal', async () => {
  const chat = {id:7, title:'Example', kind:'project', area:'factory', tool:'codex', model:'test', state:'idle'};
  const messages = [{id:1, role:'assistant', text:'**Bold reply**\n\n<script>bad()</script>'}, {id:2, role:'owner', text:'**Literal owner**'}];
  vi.stubGlobal('fetch', async url => ({ok:true, json:async () => url === '/api/chats' ? [chat] : url.endsWith('/open') ? {chat, messages} : url.endsWith('/messages') ? messages : url.endsWith('/usage') ? {} : chat}));
  const {container} = render(<MemoryRouter initialEntries={['/chats/7']}><App/></MemoryRouter>);
  expect((await screen.findByText('Bold reply')).tagName).toBe('STRONG');
  expect(screen.getByText('**Literal owner**').closest('.owner').querySelector('strong').textContent).toBe('You');
  expect(container.querySelector('script')).toBeNull();
});
