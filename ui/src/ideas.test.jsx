// @vitest-environment jsdom
import React from 'react';
import {render, screen, fireEvent, cleanup, waitFor} from '@testing-library/react';
import {MemoryRouter} from 'react-router-dom';
import {afterEach, test, expect, vi} from 'vitest';
import {Ideas} from './ideas';
afterEach(() => {cleanup(); vi.unstubAllGlobals();});
const arrival = {id:1,text:'<script>Owner text</script>',route:'New',label:null,created_at:'2026-01-01T00:00:00Z',files:[],transcript:null};
const idea = {id:2,title:'Useful idea',note:'A note',state:'classified',tags:['FAC'],source_entry:1,created_at:'2026-01-01T00:00:00Z',history:[],features:[]};
function setup(path='/ideas') {
  const fetcher = vi.fn(async (url, opts) => ({ok:true,json:async () => {
    if (opts?.method === 'POST') return {};
    if (url === '/api/inbox') return [arrival];
    if (url === '/api/ideas') return [idea];
    if (url === '/api/projects') return [{key:'FAC',name:'Factory'}];
    if (url === '/api/chats') return [{id:5,title:'Development Orchestrator',kind:'orchestrator'}];
    if (url === '/api/pipeline') return {features:[]};
    if (url === '/api/inbox/1') return arrival;
    if (url === '/api/ideas/2') return idea;
    return [];
  }}));
  vi.stubGlobal('fetch', fetcher);
  const view = render(<MemoryRouter initialEntries={[path]}><Ideas/></MemoryRouter>);
  return {fetcher,...view};
}
test('inbox routes an arrival and shows literal detail', async () => {
  const {fetcher,container} = setup();
  fireEvent.click(await screen.findByRole('button',{name:/Owner text/}));
  expect(await screen.findByText('Original text')).toBeTruthy();
  expect(container.querySelector('script')).toBeNull();
  fireEvent.click(screen.getByRole('button',{name:'Send to chat…'}));
  fireEvent.change(screen.getByLabelText('Chat'),{target:{value:'5'}});
  fireEvent.click(screen.getByRole('button',{name:'Send'}));
  await waitFor(() => expect(fetcher.mock.calls.some(([url,o]) => url === '/api/inbox/1/route' && JSON.parse(o.body).chat === 5 && o.headers['X-Factory-UI'] === '1')).toBe(true));
});
test('ideas tab supports selection, tagging and detail', async () => {
  const {fetcher} = setup('/ideas?tab=ideas');
  fireEvent.click(await screen.findByRole('checkbox',{name:'Select Useful idea'}));
  fireEvent.click(screen.getByRole('button',{name:'Tag'}));
  fireEvent.change(screen.getByLabelText('Tags (comma separated)'),{target:{value:'FAC, intake'}});
  fireEvent.click(screen.getByRole('button',{name:'Tag selected'}));
  await waitFor(() => expect(fetcher.mock.calls.some(([url,o]) => url === '/api/ideas/tag' && JSON.parse(o.body).tags.includes('intake'))).toBe(true));
  fireEvent.click(screen.getByRole('button',{name:/Useful idea/}));
  expect(await screen.findByText('History')).toBeTruthy();
});
test('phone detail has a back control and hides the list with its workspace class', async () => {
  const {container} = setup('/ideas?tab=ideas&idea=2');
  expect(await screen.findByText('Original text')).toBeTruthy();
  expect(container.querySelector('.ideas-open .ideas-detail')).toBeTruthy();
  fireEvent.click(screen.getByRole('button',{name:'← Back'}));
  expect(container.querySelector('.ideas-open')).toBeNull();
});
