// @vitest-environment jsdom
import React from 'react';
import {render, screen, fireEvent, cleanup, waitFor} from '@testing-library/react';
import {MemoryRouter} from 'react-router-dom';
import {afterEach, test, expect, vi} from 'vitest';
import {App} from './main';
afterEach(() => {cleanup(); vi.unstubAllGlobals();});
test('slice level can be set for a planned slice', async () => {
  const item = {id:'demo/one',title:'Example',state:'planned',repo:'repo',feature:'feature',executor:{tool:'codex',model:'old'},level:null,depends_on:[],log:[],attention:null};
  const fetcher = vi.fn(async (url, options) => ({ok:true,json:async () => url.endsWith('/level') ? {level:'strong',runs:[]} : url === '/api/projects' ? [] : item}));
  vi.stubGlobal('fetch',fetcher);
  render(<MemoryRouter initialEntries={['/factory/slices/demo/one']}><App/></MemoryRouter>);
  const select = await screen.findByLabelText('Slice level');
  expect(select.value).toBe('');
  fireEvent.change(select,{target:{value:'strong'}});
  await waitFor(() => expect(screen.getByLabelText('Slice level').value).toBe('strong'));
  expect(screen.queryByText('codex · old')).toBeNull();
  expect(fetcher).toHaveBeenCalledWith('/api/slices/demo/one/level',expect.objectContaining({body:JSON.stringify({level:'strong'})}));
});

test('slice page shows each platform run executor including Pi', async () => {
  const item = {id:'demo/one',title:'Example',state:'issued',repo:'repo',feature:'feature',
    executor:{tool:'codex',model:'obsolete-sol'},depends_on:[],log:[],attention:null,
    runs:[{role:'cut',executor:{harness:'claude',model:'opus'}},
          {role:'ticket',executor:{harness:'codex',model:'platform-model',effort:'high'}},
          {role:'ticket',executor:{configuration:'pi/fast'}},
          {role:'review',executor:{harness:'claude',model:'sonnet'}}]};
  vi.stubGlobal('fetch',vi.fn(async url => ({ok:true,json:async () => url === '/api/projects' ? [] : item})));
  render(<MemoryRouter initialEntries={['/factory/slices/demo/one']}><App/></MemoryRouter>);
  for (const text of ['cut · claude · opus','ticket · codex · platform-model · high',
                       'ticket · pi/fast','review · claude · sonnet']) {
    expect(await screen.findByText(text)).toBeTruthy();
  }
  expect(screen.queryByText(/obsolete-sol/)).toBeNull();
});

test('slice page shows none before any run', async () => {
  const item = {id:'demo/one',title:'Example',state:'planned',repo:'repo',feature:'feature',
    depends_on:[],log:[],attention:null,runs:[]};
  vi.stubGlobal('fetch',vi.fn(async url => ({ok:true,json:async () => url === '/api/projects' ? [] : item})));
  render(<MemoryRouter initialEntries={['/factory/slices/demo/one']}><App/></MemoryRouter>);
  const label = await screen.findByText('Executors');
  expect(label.nextElementSibling.textContent).toBe('None');
});
