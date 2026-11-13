// @vitest-environment jsdom
import React from 'react';
import {render, screen, fireEvent, cleanup, act} from '@testing-library/react';
import {afterEach, test, expect, vi} from 'vitest';
import {HomeLabSettings} from './home-lab-settings';

const routes = {routes:[{purpose:'chat', live:{provider:'gateway',model:'model/one'}, health:'configured', routes:[{provider:'gateway',model:'model/one',enabled:true},{provider:'backup',model:'model/two',enabled:false}]},{purpose:'vision-*',live:null,health:'down',routes:[]}]};
const providers = {providers:[{name:'gateway',kind:'hosted',state:'configured',purposes:['chat','vision-*']}]};
afterEach(() => {cleanup(); vi.useRealTimers(); vi.unstubAllGlobals();});
test('renders routes, expandable table, providers and null live route', async () => {
  vi.stubGlobal('fetch', vi.fn(async url => ({ok:true,json:async () => url.endsWith('routes') ? routes : providers})));
  render(<HomeLabSettings/>);
  expect(await screen.findByText('vision-*')).toBeTruthy();
  expect(screen.getByText('No live route')).toBeTruthy();
  expect(screen.getByText('hosted · configured')).toBeTruthy();
  expect(screen.getByText('chat, vision-*')).toBeTruthy();
  const details = screen.getByText('chat', {selector:'strong'}).closest('details');
  expect(details.open).toBe(false);
  fireEvent.click(details.querySelector('summary'));
  expect(details.open).toBe(true);
  expect(screen.getByText('backup · model/two · disabled')).toBeTruthy();
  expect(screen.getByRole('link', {name:'Settings page'}).getAttribute('href')).toBe('/settings#roles');
});
test('polls every 30 seconds, retains data on failure and recovers', async () => {
  vi.useFakeTimers();
  let fail = false;
  const fetcher = vi.fn(async url => ({ok:!fail,json:async () => url.endsWith('routes') ? routes : providers}));
  vi.stubGlobal('fetch', fetcher);
  await act(async () => {render(<HomeLabSettings/>);});
  expect(fetcher).toHaveBeenCalledTimes(2);
  fail = true;
  await act(async () => {await vi.advanceTimersByTimeAsync(29999);});
  expect(fetcher).toHaveBeenCalledTimes(2);
  await act(async () => {await vi.advanceTimersByTimeAsync(1);});
  expect(fetcher).toHaveBeenCalledTimes(4);
  expect(screen.getByRole('status').textContent).toContain('Home Lab unavailable');
  expect(screen.getByText('No live route')).toBeTruthy();
  expect(screen.getByText('hosted · configured')).toBeTruthy();
  fail = false;
  await act(async () => {await vi.advanceTimersByTimeAsync(30000);});
  expect(screen.queryByRole('status')).toBeNull();
});
