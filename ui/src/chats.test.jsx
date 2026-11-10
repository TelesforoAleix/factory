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
    if (url === '/api/projects') return [{key:'alpha',name:'Alpha',active:true}];
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
  expect(screen.getByRole('button', {name:'Change model'}).disabled).toBe(true);
  expect(screen.queryByLabelText('Chat tool')).toBeNull();
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
  vi.stubGlobal('fetch', async url => ({ok:true, json:async () => url === '/api/projects' ? [{key:'FAC',name:'Factory',active:true}] : url === '/api/chats' ? [chat] : url.endsWith('/open') ? {chat, messages} : url.endsWith('/messages') ? messages : url.endsWith('/usage') ? {} : chat}));
  const {container} = render(<MemoryRouter initialEntries={['/chats/7']}><App/></MemoryRouter>);
  expect((await screen.findByText('Bold reply')).tagName).toBe('STRONG');
  expect(screen.getByText('**Literal owner**').closest('.owner').querySelector('strong').textContent).toBe('You');
  expect(container.querySelector('script')).toBeNull();
});

test('project orchestrator shows its name and saves model settings', async () => {
  const chat = {id:7,title:'FAC',kind:'project',project:'FAC',project_name:'Factory',area:'factory',tool:'codex',model:'old',effort:'low',in_list:false,state:'idle'};
  const fetchMock = vi.fn(async (url, options) => ({ok:true,json:async () => url === '/api/settings/models' ? {models:[{tool:'codex',model:'old',label:'old',efforts:['low']},{tool:'claude',model:'new',label:'new',efforts:['high']}]} : url === '/api/projects' ? [{key:'FAC',name:'Factory',active:true}] : url === '/api/chats' ? [chat] : url.endsWith('/open') ? {chat,messages:[]} : url.endsWith('/messages') ? [] : url.endsWith('/usage') ? {} : options?.method === 'PATCH' ? {...chat,...JSON.parse(options.body)} : chat}));
  vi.stubGlobal('fetch', fetchMock);
  render(<MemoryRouter initialEntries={['/chats/7']}><App/></MemoryRouter>);
  expect(await screen.findByText('Project orchestrators')).toBeTruthy();
  expect(await screen.findByText('Project orchestrator · Factory')).toBeTruthy();
  expect(screen.getAllByText('Factory').length).toBeGreaterThan(1);
  expect(screen.getByText('Current choice is not in the stored model list.')).toBeTruthy();
  fireEvent.click(screen.getByRole('button',{name:'Change model'}));
  fireEvent.keyDown(document, {key:'Escape'});
  expect(screen.queryByLabelText('Chat tool')).toBeNull();
  fireEvent.click(screen.getByRole('button',{name:'Change model'}));
  fireEvent.pointerDown(document.body);
  expect(screen.queryByLabelText('Chat tool')).toBeNull();
  fireEvent.click(screen.getByRole('button',{name:'Change model'}));
  fireEvent.change(screen.getByLabelText('Chat tool'),{target:{value:'claude'}});
  fireEvent.change(screen.getByLabelText('Chat model'),{target:{value:'new'}});
  fireEvent.click(screen.getByRole('button',{name:'Save'}));
  await waitFor(() => expect(fetchMock.mock.calls.some(([url,o]) => url === '/api/chats/7' && o?.method === 'PATCH' && JSON.parse(o.body).model === 'new')).toBe(true));
  await waitFor(() => expect(screen.queryByLabelText('Chat model')).toBeNull());
  fireEvent.click(screen.getByRole('button',{name:'Change model'}));
  fireEvent.click(screen.getByRole('button',{name:'Use role default'}));
  await waitFor(() => expect(fetchMock.mock.calls.some(([url,o]) => url === '/api/chats/7' && o?.method === 'PATCH' && o.body === JSON.stringify({tool:null,model:null,effort:null}))).toBe(true));
});

test('inactive chats retain owner waits and archives', async () => {
  const base = {project:'FAC',kind:'project',state:'idle'};
  const chats = [{...base,id:1,title:'Hidden project'}, {...base,id:2,title:'Waiting project',kind:'feature',waiting:true}, {...base,id:3,title:'Old project',kind:'feature',archived:true}];
  vi.stubGlobal('fetch', vi.fn(async url => ({ok:true,json:async () => url === '/api/projects' ? [{key:'FAC',name:'Factory',active:false}, {key:'LAB',name:'Lab',active:true}] : chats})));
  render(<MemoryRouter initialEntries={['/chats']}><App/></MemoryRouter>);
  expect(await screen.findByText('Waiting project')).toBeTruthy();
  expect(screen.queryByText('Hidden project')).toBeNull();
  expect(screen.getByText('Old project')).toBeTruthy();
  expect(screen.queryByRole('button', {name:'Factory'})).toBeNull();
  expect(screen.getByRole('button', {name:'Lab'})).toBeTruthy();
});

test('archives and unarchives a running chat from its header', async () => {
  let chat = {id:7,title:'Archive example',kind:'feature',area:'factory',tool:'codex',model:'test',state:'running',waiting:true,archived:false};
  const fetcher = vi.fn(async (url, options) => {
    if (url.endsWith('/archive')) chat = {...chat,archived:true};
    if (url.endsWith('/unarchive')) chat = {...chat,archived:false};
    return {ok:true,json:async () => url === '/api/projects' ? [] : url === '/api/chats' ? [chat] : url.endsWith('/open') ? {chat,messages:[]} : url.endsWith('/messages') ? [] : url.endsWith('/usage') ? {} : chat};
  });
  vi.stubGlobal('fetch',fetcher);
  render(<MemoryRouter initialEntries={['/chats/7']}><App/></MemoryRouter>);
  const archive = await screen.findByRole('button',{name:'Archive'});
  expect(archive.disabled).toBe(false);
  fireEvent.click(archive);
  expect(await screen.findByRole('button',{name:'Unarchive'})).toBeTruthy();
  const group = screen.getByText('Archived chats (1)').closest('details');
  expect(group.querySelector('a').textContent).toContain('Archive example');
  expect(group.textContent).not.toContain('Waiting for you');
  expect(screen.queryByText('Waiting for you')).toBeNull();
  fireEvent.click(screen.getByRole('button',{name:'Unarchive'}));
  expect(await screen.findByRole('button',{name:'Archive'})).toBeTruthy();
  await waitFor(() => expect(screen.getByText('Archived chats (0)')).toBeTruthy());
  for (const action of ['archive','unarchive']) {
    expect(fetcher.mock.calls.some(([url,opts]) => url === '/api/chats/7/' + action && opts.method === 'POST' && opts.headers['X-Factory-UI'] === '1')).toBe(true);
  }
});

test('Development Orchestrator has no archive button', async () => {
  const chat = {id:1,title:'Development Orchestrator',kind:'orchestrator',area:'homelab',tool:'codex',model:'test',state:'idle'};
  vi.stubGlobal('fetch',async url => ({ok:true,json:async () => url === '/api/projects' ? [] : url === '/api/chats' ? [chat] : url.endsWith('/open') ? {chat,messages:[]} : url.endsWith('/messages') ? [] : url.endsWith('/usage') ? {} : chat}));
  render(<MemoryRouter initialEntries={['/chats/1']}><App/></MemoryRouter>);
  await screen.findByRole('button',{name:'Mark unread'});
  expect(screen.queryByRole('button',{name:'Archive'})).toBeNull();
  expect(screen.queryByRole('button',{name:'Unarchive'})).toBeNull();
});

test('failed chat allows a retry and labels slice events distinctly', async () => {
  const chat = {id:7,title:'Failed chat',kind:'feature',area:'factory',tool:'codex',model:'test',state:'failed'};
  let messages = [{id:1,role:'system',automatic:true,text:'Event: in review\nSlice: factory/SD1\nHandover'}];
  const fetcher = vi.fn(async (url, options) => {
    if (url.endsWith('/messages') && options?.method === 'POST') messages = [...messages,{id:2,role:'system',text:'New session started'},{id:3,role:'owner',text:'Retry'}];
    return {ok:true,json:async () => url === '/api/projects' ? [] : url === '/api/chats' ? [chat] : url.endsWith('/open') ? {chat,messages} : url.endsWith('/messages') ? messages : {}};
  });
  vi.stubGlobal('fetch',fetcher);
  render(<MemoryRouter initialEntries={['/chats/7']}><App/></MemoryRouter>);
  await screen.findAllByText(/Event: in review · factory\/SD1/);
  expect(screen.getByRole('button',{name:'Send'}).disabled).toBe(false);
  fireEvent.change(screen.getByLabelText('Message'),{target:{value:'Retry'}});
  fireEvent.click(screen.getByRole('button',{name:'Send'}));
  await screen.findAllByText(/New session started/);
  expect(fetcher.mock.calls.some(([url,o]) => url.endsWith('/messages') && o?.method === 'POST')).toBe(true);
  expect(fetcher.mock.calls.some(([url]) => url === '/api/chats/7')).toBe(false);
});

test('opens the transcript at its latest message', async () => {
  const chat = {id:7,title:'Example',kind:'feature',area:'factory',tool:'codex',model:'test',state:'idle'};
  const messages = [{id:1,role:'owner',text:'Latest'}];
  vi.stubGlobal('fetch', async url => ({ok:true,json:async () => url === '/api/projects' ? [] : url === '/api/chats' ? [chat] : url.endsWith('/open') ? {chat,messages} : url.endsWith('/messages') ? messages : {}}));
  const height = vi.spyOn(HTMLElement.prototype, 'scrollHeight', 'get').mockReturnValue(1000);
  try {
    render(<MemoryRouter initialEntries={['/chats/7']}><App/></MemoryRouter>);
    await screen.findByText('Latest');
    expect(document.querySelector('.chat-transcript').scrollTop).toBe(1000);
  } finally { height.mockRestore(); }
});

test('phone chat options menu contains the header actions', async () => {
  vi.stubGlobal('matchMedia', () => ({matches:true, addEventListener:vi.fn(), removeEventListener:vi.fn()}));
  const chat = {id:7,title:'Phone chat',kind:'feature',area:'factory',tool:'codex',model:'test',state:'idle'};
  vi.stubGlobal('fetch', async url => ({ok:true,json:async () => url === '/api/projects' ? [] : url === '/api/chats' ? [chat] : url.endsWith('/open') ? {chat,messages:[]} : url.endsWith('/messages') ? [] : chat}));
  render(<MemoryRouter initialEntries={['/chats/7']}><App/></MemoryRouter>);
  const menu = await screen.findByRole('button',{name:'Chat options'});
  expect(screen.queryByRole('button',{name:'Mark unread'})).toBeNull();
  fireEvent.click(menu);
  for (const name of ['Change model','Mark unread','Archive']) expect(screen.getByRole('button',{name})).toBeTruthy();
  fireEvent.click(screen.getByRole('button',{name:'Change model'}));
  expect(screen.getByLabelText('Chat model')).toBeTruthy();
  fireEvent.keyDown(document,{key:'Escape'});
  expect(screen.queryByRole('button',{name:'Mark unread'})).toBeNull();
});

test('Secretary remains listed after it is read', async () => {
  const chats = [{id:1,title:'Development Orchestrator',kind:'orchestrator'}, {id:2,title:'Secretary',kind:'secretary',waiting:false}];
  vi.stubGlobal('fetch', async url => ({ok:true,json:async () => url === '/api/projects' ? [] : chats}));
  render(<MemoryRouter initialEntries={['/chats']}><App/></MemoryRouter>);
  expect((await screen.findByText('Secretary', {selector:'h2'})).nextSibling.textContent).toContain('Secretary');
});
