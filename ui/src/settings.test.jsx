// @vitest-environment jsdom
import React from 'react';
import {render, screen, fireEvent, cleanup, waitFor} from '@testing-library/react';
import {afterEach, test, expect, vi} from 'vitest';
import {Settings} from './settings';
afterEach(() => {cleanup(); vi.unstubAllGlobals();});
test('project switches persist immediately, omit NEW and report a failed save', async () => {
  const project = {key:'FAC',name:'Factory',active:true};
  const fetcher = vi.fn(async (_url, options) => ({ok:true,json:async () => options ? {...project,active:false} : [project,{key:'NEW',name:'No project yet',active:true}]}));
  vi.stubGlobal('fetch',fetcher);
  render(<Settings/>);
  const toggle = await screen.findByRole('switch',{name:'Active Factory'});
  expect(toggle.checked).toBe(true);
  expect(screen.getByText('FAC').tagName).toBe('CODE');
  expect(screen.queryByText('No project yet')).toBeNull();
  fireEvent.click(toggle);
  await waitFor(() => expect(toggle.checked).toBe(false));
  expect(fetcher).toHaveBeenCalledWith('/api/projects/FAC',expect.objectContaining({method:'PATCH',headers:expect.objectContaining({'X-Factory-UI':'1'}),body:JSON.stringify({active:false})}));
  fetcher.mockResolvedValueOnce({ok:false,json:async () => ({error:'Save failed'})});
  fireEvent.click(toggle);
  expect(await screen.findByRole('alert')).toHaveProperty('textContent','Save failed');
  expect(toggle.checked).toBe(false);
});
