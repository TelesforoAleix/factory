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
  expect(screen.getByText('Skills & guides').closest('details').open).toBe(false);
  expect(screen.getByText('abcdef12')).toBeTruthy();
  fireEvent.click(screen.getByRole('button', {name:'Factory'}));
  fireEvent.change(screen.getByLabelText('Search Library'),{target:{value:'router'}});
  await waitFor(() => expect(fetchMock).toHaveBeenCalledWith('/api/library?project=FAC&q=router',{}));
});
test('skill rows expose the selected project switch', async () => {
  const fetchMock = fixture(); render(<MemoryRouter initialEntries={['/library?project=FAC']}><App/></MemoryRouter>);
  await screen.findByText('Skills & guides');
  fireEvent.click(screen.getByText('Skills & guides'));
  const toggle = await screen.findByRole('checkbox', {name:'Enable grilling for Factory'});
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
  await waitFor(() => expect(mock.setAnnotations.mock.calls.at(-1)[0][0].target.selector[0].start).toBe(2));
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
  fireEvent.click(await screen.findByRole('checkbox',{name:'Enabled for Factory'}));
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

test('root documents precede folders and empty comments cannot be sent', async () => {
  fixture(); const original = globalThis.fetch;
  vi.stubGlobal('fetch', (url, options) => url.startsWith('/api/library?') ? Promise.resolve({ok:true,json:async () => ({projects:[],documents:[doc,{path:'root.md',title:'Root plan'}]})}) : original(url,options));
  render(<MemoryRouter initialEntries={['/library/documents/factory/plan.md']}><App/></MemoryRouter>);
  await screen.findByText('A searchable document.');
  expect(screen.getByRole('button',{name:'Send 0 comments'}).disabled).toBe(true);
  await screen.findByText('Root plan');
  const tree = screen.getByRole('navigation',{name:'Library tree'});
  expect(tree.textContent.indexOf('Skills & guides')).toBeLessThan(tree.textContent.indexOf('Documents'));
  expect(tree.textContent.indexOf('Root plan')).toBeLessThan(tree.textContent.indexOf('factory'));
});

test('project row uses the shared active project order', async () => {
  vi.stubGlobal('fetch',vi.fn(async url => ({ok:true,json:async () => url.startsWith('/api/library?') ? {documents:[],projects:[{key:'LAB',name:'Lab',active:true},{key:'FAC',name:'Factory',active:false},{key:'NEW',name:'No project yet',active:true}]} : []})));
  render(<MemoryRouter initialEntries={['/library']}><App/></MemoryRouter>);
  await screen.findByRole('button',{name:'Lab'});
  expect([...screen.getByRole('group',{name:'Project'}).querySelectorAll('button')].map(b => b.textContent)).toEqual(['All','Lab']);
});

test('drafts delete and sent comments resolve into a collapsed history', async () => {
  let comments = [{id:1,text:'Draft to delete',selector,time:'2026-11-01'}, {id:2,text:'Sent to resolve',selector,time:'2026-11-01',sent_at:'2026-11-02',chat:7,chat_title:'Factory project'}];
  const fetcher = vi.fn(async (url, options) => {
    if (url.endsWith('/1') && options?.method === 'DELETE') comments = comments.filter(c => c.id !== 1);
    if (url.endsWith('/2') && options?.method === 'PATCH') comments = comments.map(c => ({...c,resolved_at:'2026-11-03',resolution_note:JSON.parse(options.body).note}));
    return {ok:true,json:async () => url.startsWith('/api/library?') ? {documents:[doc],projects:[]} : url === '/api/skills' ? [] : url.startsWith('/api/chats') ? [chat] : url.includes('/documents/') ? doc : comments};
  });
  vi.stubGlobal('fetch',fetcher);
  render(<MemoryRouter initialEntries={['/library/documents/factory/plan.md']}><App/></MemoryRouter>);
  await screen.findByText('Draft to delete');
  expect(screen.queryByRole('button',{name:'Delete draft 2'})).toBeNull();
  fireEvent.click(screen.getByRole('button',{name:'Delete draft 1'}));
  await waitFor(() => expect(screen.queryByText('Draft to delete')).toBeNull());
  fireEvent.click(screen.getByRole('button',{name:'Resolve comment 2'}));
  fireEvent.change(screen.getByLabelText('Resolution note'),{target:{value:'Fixed in the design'}});
  fireEvent.click(screen.getByRole('button',{name:'Save resolution'}));
  const summary = await screen.findByText('Resolved (1)');
  expect(summary.closest('details').open).toBe(false);
  expect(screen.queryByText('Sent to resolve')).toBeNull();
  expect(screen.getByText('Fixed in the design')).toBeTruthy();
  expect(screen.getByRole('link',{name:'Factory project'}).getAttribute('href')).toBe('/chats/7');
  await waitFor(() => expect(mock.setAnnotations.mock.calls.at(-1)[0]).toEqual([]));
  expect(fetcher.mock.calls.filter(([,o]) => ['PATCH','DELETE'].includes(o?.method)).every(([,o]) => o.headers['X-Factory-UI'] === '1')).toBe(true);
});

test('all document folders start collapsed, including unassigned folders', async () => {
  fixture(); const original = globalThis.fetch;
  vi.stubGlobal('fetch', (url, options) => url.startsWith('/api/library?') ? Promise.resolve({ok:true,json:async () => ({projects:[],documents:[doc,{path:'unassigned/nested/note.md',title:'Note'},{path:'root.md',title:'Root'}]})}) : original(url,options));
  render(<MemoryRouter initialEntries={['/library']}><App/></MemoryRouter>);
  await screen.findByText('Root');
  const tree = screen.getByRole('navigation',{name:'Library tree'});
  expect([...tree.querySelectorAll('details')].every(d => !d.open)).toBe(true);
  expect(tree.textContent.indexOf('Root')).toBeLessThan(tree.textContent.indexOf('factory'));
});

test('phone document shows details and comments without write controls', async () => {
  vi.stubGlobal('matchMedia', () => ({matches:true, addEventListener:vi.fn(), removeEventListener:vi.fn()}));
  const fetcher = fixture([{id:1,text:'Read only',selector,time:'2026-11-01',sent_at:'2026-11-02'}]);
  render(<MemoryRouter initialEntries={['/library/documents/factory/plan.md']}><App/></MemoryRouter>);
  expect(await screen.findByText('Read only')).toBeTruthy();
  expect(screen.getByText('Details').closest('details').open).toBe(false);
  expect(screen.queryByRole('button',{name:/Send|Resolve|Delete|Grill/})).toBeNull();
  expect(screen.queryByLabelText('Receiving chat')).toBeNull();
  expect(fetcher.mock.calls.every(([,options]) => !options?.method)).toBe(true);
});
