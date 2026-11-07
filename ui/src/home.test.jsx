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
  fireEvent.click(screen.getByRole('button',{name:'Other'}));
  expect(screen.queryByText('Choose?')).toBeNull();
  expect(screen.queryByText('Next feature')).toBeNull();
});
