// @vitest-environment jsdom
import React from 'react';
import {render, screen, cleanup, act} from '@testing-library/react';
import {afterEach, test, expect, vi} from 'vitest';
import {SliceList} from './pipeline';
const dnd = vi.hoisted(() => ({end:null, sensors:[]}));
vi.mock('@dnd-kit/core', async importOriginal => ({...await importOriginal(), DndContext:({children,onDragEnd}) => {dnd.end=onDragEnd; return <div>{children}</div>;}, useSensors:(...sensors) => {dnd.sensors=sensors; return sensors;}}));
afterEach(() => {cleanup(); vi.unstubAllGlobals();});
const slices = [{id:'test/0', title:'First', state:'ready', movable:true}, {id:'test/1', title:'Second', state:'planned', movable:true}, {id:'test/2',title:'Running',state:'issued',movable:false}];
test('only movable rows have handles and touch uses the board hold constraint', () => {
  render(<SliceList slices={slices} refresh={vi.fn()}/>);
  expect(screen.getAllByRole('button').map(b => b.getAttribute('aria-label'))).toEqual(['Drag slice test/0','Drag slice test/1']);
  expect(dnd.sensors[1].options.activationConstraint).toEqual({delay:300,tolerance:8});
});
test('posts placement, reloads saved order, and shows refusal on the dragged row', async () => {
  const refresh=vi.fn(), fetchMock=vi.fn().mockResolvedValueOnce({ok:true,json:async()=>({order:['test/1','test/0','test/2']})}).mockResolvedValueOnce({ok:false,json:async()=>({error:'A slice must stay after its dependencies'})});
  vi.stubGlobal('fetch', fetchMock);
  render(<SliceList slices={slices} refresh={refresh}/>);
  await act(async () => dnd.end({active:{id:'test/1'},over:{id:'test/0'}}));
  expect(fetchMock.mock.calls[0][0]).toBe('/api/slices/test%2F1/place');
  expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toEqual({before:'test/0'});
  expect(fetchMock.mock.calls[0][1].headers['X-Factory-UI']).toBe('1');
  expect(refresh).toHaveBeenCalledTimes(1);
  await act(async () => dnd.end({active:{id:'test/0'},over:{id:'test/1'}}));
  expect(screen.getByRole('status').closest('li').textContent).toContain('First');
  expect(screen.getByRole('status').textContent).toContain('dependencies');
  expect(refresh).toHaveBeenCalledTimes(1);
  expect(Array.from(document.querySelectorAll('li')).map(li => li.textContent.includes('First') ? 'First' : li.textContent.includes('Second') ? 'Second' : 'Running')).toEqual(['First','Second','Running']);
});
