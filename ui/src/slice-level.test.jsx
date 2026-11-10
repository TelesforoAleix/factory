// @vitest-environment jsdom
import React from 'react';
import {render, screen, fireEvent, cleanup, waitFor} from '@testing-library/react';
import {MemoryRouter} from 'react-router-dom';
import {afterEach, test, expect, vi} from 'vitest';
import {App} from './main';
afterEach(() => {cleanup(); vi.unstubAllGlobals();});
test('slice level can be set for a planned slice', async () => {
  const item = {id:'demo/one',title:'Example',state:'planned',repo:'repo',feature:'feature',executor:{tool:'codex',model:'old'},level:null,depends_on:[],log:[],attention:null};
  const fetcher = vi.fn(async (url, options) => ({ok:true,json:async () => url.endsWith('/level') ? {level:'strong',executor:{tool:'claude',model:'new',effort:'high'}} : url === '/api/projects' ? [] : item}));
  vi.stubGlobal('fetch',fetcher);
  render(<MemoryRouter initialEntries={['/factory/slices/demo/one']}><App/></MemoryRouter>);
  const select = await screen.findByLabelText('Slice level');
  expect(select.value).toBe('');
  fireEvent.change(select,{target:{value:'strong'}});
  await waitFor(() => expect(screen.getByText('claude · new · high')).toBeTruthy());
  expect(fetcher).toHaveBeenCalledWith('/api/slices/demo/one/level',expect.objectContaining({body:JSON.stringify({level:'strong'})}));
});
