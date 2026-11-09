// @vitest-environment jsdom
import {afterEach, expect, test, vi} from 'vitest';
import {visiblePolling} from './polling';
afterEach(() => {vi.useRealTimers(); vi.restoreAllMocks();});

test('hidden tabs stop polling and showing the tab refreshes immediately', async () => {
  vi.useFakeTimers();
  let hidden = false;
  vi.spyOn(document, 'hidden', 'get').mockImplementation(() => hidden);
  const poll = vi.fn(async () => {}), stop = visiblePolling(poll, 5000);
  await vi.advanceTimersByTimeAsync(5000);
  expect(poll).toHaveBeenCalledTimes(2);
  hidden = true; document.dispatchEvent(new Event('visibilitychange'));
  await vi.advanceTimersByTimeAsync(60000);
  expect(poll).toHaveBeenCalledTimes(2);
  hidden = false; document.dispatchEvent(new Event('visibilitychange'));
  expect(poll).toHaveBeenCalledTimes(3);
  stop();
  await vi.advanceTimersByTimeAsync(60000);
  document.dispatchEvent(new Event('visibilitychange'));
  expect(poll).toHaveBeenCalledTimes(3);
});

test('hidden mount does no work and slow polls never overlap', async () => {
  vi.useFakeTimers();
  let hidden = true, finish;
  vi.spyOn(document, 'hidden', 'get').mockImplementation(() => hidden);
  const poll = vi.fn(() => new Promise(resolve => {finish = resolve;}));
  const stop = visiblePolling(poll, 5000);
  expect(poll).not.toHaveBeenCalled();
  hidden = false; document.dispatchEvent(new Event('visibilitychange'));
  await vi.advanceTimersByTimeAsync(20000);
  hidden = true; document.dispatchEvent(new Event('visibilitychange'));
  hidden = false; document.dispatchEvent(new Event('visibilitychange'));
  expect(poll).toHaveBeenCalledTimes(1);
  finish(); await vi.advanceTimersByTimeAsync(5000);
  expect(poll).toHaveBeenCalledTimes(2);
  stop(); finish();
  await vi.advanceTimersByTimeAsync(20000);
  expect(poll).toHaveBeenCalledTimes(2);
});
