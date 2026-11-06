// @vitest-environment jsdom
import React from 'react';
import {render, screen, fireEvent} from '@testing-library/react';
import {MemoryRouter} from 'react-router-dom';
import {test, expect, vi} from 'vitest';
import {App} from './main';
test('navigation switches between persistent areas', async () => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ok: true, json: async () => []}));
  render(<MemoryRouter initialEntries={['/home-lab']}><App/></MemoryRouter>);
  expect(screen.getByRole('heading', {name: 'Home Lab'})).toBeTruthy();
  fireEvent.click(screen.getByRole('link', {name: 'Factory', exact: true}));
  expect(await screen.findByText('No slices yet.')).toBeTruthy();
  fireEvent.click(screen.getByRole('link', {name: 'Home Lab'}));
  expect(screen.getByRole('heading', {name: 'Home Lab'})).toBeTruthy();
});
