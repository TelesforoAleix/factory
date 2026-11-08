// @vitest-environment jsdom
import React from 'react';
import {render, screen, fireEvent, cleanup, waitFor, act} from '@testing-library/react';
import {MemoryRouter} from 'react-router-dom';
import {afterEach, test, expect, vi} from 'vitest';
const mock = vi.hoisted(() => ({events:{}, setAnnotations:vi.fn()}));
vi.mock('@recogito/text-annotator', () => ({createTextAnnotator:() => ({on:(event,fn) => {mock.events[event]=fn;}, destroy:vi.fn(), setAnnotations:mock.setAnnotations})}));
import {App} from './main';
import {quoteOffset} from './library';
afterEach(() => {cleanup(); vi.unstubAllGlobals(); mock.setAnnotations.mockClear();});
const selector = {type:'TextQuoteSelector', exact:'searchable', prefix:'A ', suffix:' document.'};
const doc = {path:'factory/plan.md', title:'Plan', status:'draft', date:'2026-11-01', markdown:'A searchable document.', receiver:{id:7}};
const chat = {id:7,title:'Factory project',kind:'project',area:'factory',state:'idle'};
const skill = {name:'grilling',description:'Ask questions',version:'abcdef123456',projects:['FAC'],markdown:'Grill one question.'};
function fixture(comments=[]) {
  const fetchMock = vi.fn(async (url, options) => ({ok:true,json:async () => {
    if (url.startsWith('/api/library?')) return {documents:[doc],projects:[{key:'FAC',name:'Factory'}]};
    if (url === '/api/skills') return [skill];
    if (url === '/api/skills/grilling') return options?.method === 'POST' ? {...skill,projects:[]} : skill;
    if (url.startsWith('/api/chats')) return [chat];
    if (url.includes('/api/library/documents/')) return doc;
    if (url.includes('/api/library/comments/')) return options?.method === 'POST' ? [{id:1,text:'Why?',selector,time:'2026-11-01T12:00:00Z'}] : comments;
    if (url.includes('/api/library/send/')) return {chat:7,comments:comments.map(c => ({...c,sent_at:'2026-11-01T13:00:00Z',chat:7,chat_title:chat.title}))};
    if (url.includes('/api/library/grill/')) return {chat:7};
    return [];
  }}));
  vi.stubGlobal('fetch',fetchMock); return fetchMock;
}
test('tree filters search by project and links skills with versions', async () => {
  const fetchMock=fixture(); render(<MemoryRouter initialEntries={['/library']}><App/></MemoryRouter>);
  expect(await screen.findByText('Plan')).toBeTruthy();
  expect(screen.getByText('Skills & guides')).toBeTruthy();
  expect(screen.getByText('abcdef12')).toBeTruthy();
  fireEvent.change(screen.getByLabelText('Project'),{target:{value:'FAC'}});
  fireEvent.change(screen.getByLabelText('Search Library'),{target:{value:'router'}});
  await waitFor(() => expect(fetchMock).toHaveBeenCalledWith('/api/library?project=FAC&q=router',{}));
});
test('skill rows expose the selected project switch', async () => {
  const fetchMock = fixture(); render(<MemoryRouter initialEntries={['/library?project=FAC']}><App/></MemoryRouter>);
  const toggle = await screen.findByRole('checkbox', {name:'Enable grilling for FAC'});
  expect(toggle.checked).toBe(true);
  fireEvent.click(toggle);
  await waitFor(() => expect(fetchMock.mock.calls.some(([url,o]) => url === '/api/skills/grilling' && o?.method === 'POST' && JSON.parse(o.body).enabled === false)).toBe(true));
});
test('selection saves a W3C quote with context and guards the write', async () => {
  const fetchMock=fixture(); render(<MemoryRouter initialEntries={['/library/documents/factory/plan.md']}><App/></MemoryRouter>);
  await screen.findByText('A searchable document.');
  act(() => mock.events.createAnnotation({target:{selector:[{quote:'searchable',start:2,end:12}]}}));
  fireEvent.change(screen.getByLabelText('Comment'),{target:{value:'Why?'}});
  fireEvent.click(screen.getByRole('button',{name:'Save draft'}));
  expect(await screen.findByText('Draft saved')).toBeTruthy();
  const call=fetchMock.mock.calls.find(([url,o]) => url.includes('/comments/') && o?.method==='POST');
  expect(JSON.parse(call[1].body)).toEqual({text:'Why?',selector});
  expect(call[1].headers['X-Factory-UI']).toBe('1');
  expect(mock.setAnnotations.mock.calls.at(-1)[0][0].target.selector[0].start).toBe(2);
});
test('all drafts send once to chosen chat and sent history and changed quotes remain', async () => {
  const comments=[{id:1,text:'First?',selector,time:'2026-11-01'}, {id:2,text:'Second?',selector:{...selector,exact:'removed'},time:'2026-11-01'}];
  const fetchMock=fixture(comments); render(<MemoryRouter initialEntries={['/library/documents/factory/plan.md']}><App/></MemoryRouter>);
  expect(await screen.findByText('passage changed')).toBeTruthy();
  fireEvent.click(screen.getByRole('button',{name:'Send 2 comments'}));
  await screen.findByText('Comments sent as one message');
  expect(screen.getAllByText('Sent').length).toBe(2);
  expect(screen.getAllByRole('link',{name:'Factory project'}).length).toBe(2);
  const calls=fetchMock.mock.calls.filter(([url]) => url.includes('/send/'));
  expect(calls.length).toBe(1); expect(JSON.parse(calls[0][1].body)).toEqual({chat:7});
});
test('skill text and project switch use the existing backend', async () => {
  const fetchMock=fixture(); render(<MemoryRouter initialEntries={['/library/skills/grilling?project=FAC']}><App/></MemoryRouter>);
  expect(await screen.findByText('Grill one question.')).toBeTruthy();
  fireEvent.click(screen.getByRole('checkbox',{name:'Enabled for FAC'}));
  await waitFor(() => expect(fetchMock.mock.calls.some(([url,o]) => url==='/api/skills/grilling' && o?.method==='POST' && JSON.parse(o.body).enabled===false)).toBe(true));
});
test.each(['/home-lab','/home-lab/grills','/home-lab/backlog','/home-lab/documents/factory/plan.md'])('old address %s redirects into Library', async path => {
  fixture(); render(<MemoryRouter initialEntries={[path]}><App/></MemoryRouter>);
  expect(await screen.findByRole('heading',{name:'Library'})).toBeTruthy();
  expect(screen.queryByText('Start a Home Lab grill')).toBeNull();
});
test('quote anchoring keeps exact text, uses context and refuses ambiguous matches', () => {
  expect(quoteOffset('old old',{exact:'old',prefix:'old ',suffix:''})).toBe(4);
  expect(quoteOffset('old old',{exact:'old',prefix:'',suffix:''})).toBe(-1);
  expect(quoteOffset('changed',{exact:'old'})).toBe(-1);
  expect(quoteOffset('moved old here',{exact:'old',prefix:'previous'})).toBe(6);
});
test('long documents retain their text and scrollable table wrapper', async () => {
  const longText = 'long-document-content-'.repeat(30);
  const longDoc = {...doc, title:'A long document title '.repeat(4), markdown:`${longText}\n\n| First | Second |\n| --- | --- |\n| ${longText} | Value |\n\n\`\`\`\n${longText}\n\`\`\``};
  fixture();
  const originalFetch = globalThis.fetch;
  vi.stubGlobal('fetch', (url, options) => url.includes('/api/library/documents/') ? Promise.resolve({ok:true,json:async () => longDoc}) : originalFetch(url, options));
  render(<MemoryRouter initialEntries={['/library/documents/factory/plan.md']}><App/></MemoryRouter>);
  const viewer = await screen.findByLabelText('Document text');
  expect(viewer.querySelector('p').textContent).toBe(longText);
  expect(viewer.querySelector('.table-scroll[tabindex="0"] table')).toBeTruthy();
  expect(viewer.querySelector('pre code').textContent.trim()).toBe(longText);
});
