// @vitest-environment jsdom
import React from 'react';
import {render, screen, fireEvent, cleanup} from '@testing-library/react';
import {afterEach, expect, test, vi} from 'vitest';
import {Settings} from './settings';
import {readFileSync} from 'node:fs';

vi.stubGlobal('fetch', vi.fn(async () => ({ok:true, json:async () => []})));

afterEach(() => { cleanup(); vi.restoreAllMocks(); localStorage.clear(); delete document.documentElement.dataset.theme; });

test('appearance persists and applies each choice', () => {
  render(<Settings/>);
  for (const value of ['Dark', 'Light', 'Device']) {
    fireEvent.click(screen.getByRole('button', {name: value}));
    expect(document.documentElement.dataset.theme).toBe(value.toLowerCase());
    expect(localStorage.getItem('theme')).toBe(value.toLowerCase());
    expect(screen.getByRole('button', {name: value}).getAttribute('aria-pressed')).toBe('true');
  }
});

test('storage failures fall back to device', () => {
  vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => { throw Error(); });
  vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw Error(); });
  render(<Settings/>);
  fireEvent.click(screen.getByRole('button', {name: 'Dark'}));
  expect(document.documentElement.dataset.theme).toBe('device');
  expect(screen.getByRole('button', {name: 'Device'}).getAttribute('aria-pressed')).toBe('true');
});

test('bootstrap applies persisted choice and handles unavailable storage', () => {
  const html = readFileSync('index.html', 'utf8');
  const script = html.match(/<script>(.*?)<\/script>/)[1];
  localStorage.setItem('theme', 'dark');
  new Function(script)();
  expect(document.documentElement.dataset.theme).toBe('dark');
  vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => { throw Error(); });
  new Function(script)();
  expect(document.documentElement.dataset.theme).toBe('device');
});
