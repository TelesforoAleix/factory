// @vitest-environment jsdom
import React from 'react';
import {render, screen, fireEvent, cleanup, waitFor} from '@testing-library/react';
import {MemoryRouter} from 'react-router-dom';
import {afterEach, test, expect, vi} from 'vitest';
import {App} from './main';
import {Markdown} from './documents';
afterEach(() => {cleanup(); vi.unstubAllGlobals();});
test('Markdown disables raw HTML and renders phone-scrollable GFM tables', () => {
  const {container} = render(<Markdown>{'# Safe\n\n<script>alert(1)</script>\n\n<img src=x onerror="alert(1)">\n\n| Task | State |\n| --- | --- |\n| Demo | Ready |\n\n[unsafe](javascript:alert(1))'}</Markdown>);
  expect(screen.getByRole('heading', {name: 'Safe'})).toBeTruthy();
  expect(container.querySelector('script')).toBeNull();
  expect(container.querySelector('img')).toBeNull();
  expect(container.querySelector('[onerror]')).toBeNull();
  expect(container.querySelector('a')?.getAttribute('href')).not.toContain('javascript:');
  expect(container.querySelector('.table-scroll table')).toBeTruthy();
  expect(screen.getByRole('cell', {name: 'Ready'})).toBeTruthy();
});
