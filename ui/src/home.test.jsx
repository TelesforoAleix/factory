// @vitest-environment jsdom
import React from 'react';
import {render, screen, fireEvent, waitFor} from '@testing-library/react';
import {MemoryRouter} from 'react-router-dom';
import {test, expect, vi} from 'vitest';
import {Home} from './home';

test('Home filters sections and sends a quick answer under the guard', async () => {
  const data = {projects:[{key:'FAC',name:'Factory'},{key:'OTH',name:'Other'}], features:[{id:'FAC-F1',title:'Next feature',project:'FAC',stage:'next'}], running:[], chats:[], attention:[{kind:'question',id:'demo/one',project:'FAC',since:'2026-01-01T00:00:00Z',text:'Choose?'}]};
  const fetcher = vi.fn().mockImplementation((url, options) => Promise.resolve({ok:true, json:async () => data, text:async () => 'ok'}));
  vi.stubGlobal('fetch', fetcher);
  render(<MemoryRouter><Home/></MemoryRouter>);
  expect(await screen.findByText('Choose?')).toBeTruthy();
  fireEvent.change(screen.getByLabelText('Answer'), {target:{value:'Proceed'}});
  fireEvent.click(screen.getByText('Send answer'));
  await waitFor(() => expect(fetcher).toHaveBeenCalledWith('/api/actions/answer/demo/one', expect.objectContaining({method:'POST', headers:expect.objectContaining({'X-Factory-UI':'1'}), body:JSON.stringify({value:'Proceed'})})));
  fireEvent.change(screen.getByLabelText('Project'), {target:{value:'OTH'}});
  expect(screen.queryByText('Choose?')).toBeNull();
  expect(screen.queryByText('Next feature')).toBeNull();
});

test('Testing review links to chat and requested install remains an owner action', async () => {
  const data = {projects:[], features:[], running:[], chats:[], attention:[
    {kind:'testing-review',id:'FAC-F1',chat:12,since:'2026-01-01T00:00:00Z',text:'Please test'},
    {kind:'install',id:'factory/TR1',installable:true,installing:true,since:'2026-01-01T00:00:00Z',text:'Install the change'}]};
  const fetcher = vi.fn().mockResolvedValue({ok:true,json:async () => data});
  vi.stubGlobal('fetch', fetcher);
  render(<MemoryRouter><Home/></MemoryRouter>);
  expect(await screen.findByText('Testing review')).toBeTruthy();
  expect(screen.getByRole('link', {name:'Open chat'}).getAttribute('href')).toBe('/chats/12');
  expect(screen.getByText(/FAC-F1 · .* waiting/)).toBeTruthy();
  fireEvent.click(screen.getByRole('button', {name:'Install requested'}));
  await waitFor(() => expect(fetcher).toHaveBeenCalledWith('/api/slices/factory/TR1/install', expect.objectContaining({method:'POST'})));
});
