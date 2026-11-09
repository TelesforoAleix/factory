// @vitest-environment jsdom
import React from 'react';
import {render, screen, fireEvent, cleanup, waitFor, within} from '@testing-library/react';
import {MemoryRouter, Routes, Route} from 'react-router-dom';
import {afterEach, test, expect, vi} from 'vitest';
import {ProjectPage} from './project-page';
import {ProjectNavigation} from './project-navigation';
import {Settings} from './settings';
afterEach(() => {cleanup(); vi.unstubAllGlobals();});
const data = () => ({project:{key:'FAC',name:'Factory',active:true,about:'Build useful things.',public_url:'https://example.test',repository_url:'https://example.test/repo'}, attention:[{kind:'question',id:'demo/S1',text:'Proceed?',since:'2026-11-09T12:00:00Z'}], features:[{id:'FAC-F1',title:'Building it',stage:'building'},{id:'FAC-F2',title:'Test it',stage:'testing'},{id:'FAC-F3',title:'Queued',stage:'next'}], running:[{id:'demo/S1',feature:'FAC-F1',title:'Implement it'}], stages:{building:1,testing:1,next:1},chats:[{id:9,kind:'project'},{id:10,kind:'feature',feature:'FAC-F1',title:'Feature chat'}],usage:{month:{input_tokens:150,output_tokens:30,cached_tokens:50,hours:1.5},all_time:{input_tokens:300,output_tokens:60,cached_tokens:100,hours:3}}});
function response(value, ok=true) {return {ok,text:async () => JSON.stringify(value),json:async () => value};}
function page() {render(<MemoryRouter initialEntries={['/projects/FAC']}><Routes><Route path="/projects/:key" element={<ProjectPage/>}/></Routes></MemoryRouter>);}
test('project sections, usage, links, inline save and shared attention action', async () => {
  const d = data();
  const fetcher = vi.fn(async (url, options) => {
    if (options?.method === 'PATCH') return response({...d.project,...JSON.parse(options.body)});
    if (options?.method === 'POST') return response('Answered');
    return response(d);
  });
  vi.stubGlobal('fetch',fetcher); page();
  expect(await screen.findByRole('heading',{name:'Factory (FAC)'})).toBeTruthy();
  for (const name of ['About','Needs you','Now','Chats','Usage','Documents']) expect(screen.getByRole('heading',{name})).toBeTruthy();
  expect(screen.getByRole('link',{name:'Public site ↗'}).getAttribute('href')).toBe('https://example.test');
  expect(screen.getByRole('link',{name:'Open Factory in the Library →'}).getAttribute('href')).toBe('/library?project=FAC');
  expect(screen.getByText('Building').closest('a').getAttribute('href')).toBe('/pipeline?project=FAC');
  expect([...document.querySelectorAll('.project-page .home-strip span')].map(e => e.textContent)).toEqual(['Shortlist','Grilling','Ready','Next','Building','Testing','Parked']);
  expect(screen.queryByText('Done')).toBeNull();
  expect(screen.getByText('150')).toBeTruthy(); expect(screen.getByText('1.5')).toBeTruthy();
  expect(screen.getByText(/Costs come with Insights/)).toBeTruthy();
  expect(screen.getByText('Implement it · Running')).toBeTruthy();
  fireEvent.click(screen.getByRole('button',{name:'Edit'}));
  fireEvent.change(screen.getByLabelText('Name'),{target:{value:'Renamed'}});
  fireEvent.click(screen.getByRole('button',{name:'Save'}));
  expect(await screen.findByRole('heading',{name:'Renamed (FAC)'})).toBeTruthy();
  expect(fetcher).toHaveBeenCalledWith('/api/projects/FAC',expect.objectContaining({method:'PATCH',headers:expect.objectContaining({'X-Factory-UI':'1'}),body:JSON.stringify({name:'Renamed',about:'Build useful things.',public_url:'https://example.test',repository_url:'https://example.test/repo'})}));
  fireEvent.change(screen.getByLabelText('Answer'),{target:{value:'Yes'}});
  fireEvent.click(screen.getByRole('button',{name:'Send answer'}));
  await waitFor(() => expect(fetcher).toHaveBeenCalledWith('/api/actions/answer/demo/S1',expect.objectContaining({method:'POST',body:JSON.stringify({value:'Yes'})})));
});
test('empty attention is hidden, inactive page edits show errors and missing usage stays unknown', async () => {
  const d = data(); d.attention = []; d.project.active = false; d.usage.month.input_tokens = null;
  const fetcher = vi.fn(async () => response(d)); vi.stubGlobal('fetch',fetcher); page();
  await screen.findByRole('heading',{name:'Factory (FAC)'});
  expect(screen.queryByRole('heading',{name:'Needs you'})).toBeNull();
  expect(screen.getByRole('button',{name:'Activate'})).toBeTruthy();
  expect(screen.getByText('Not recorded')).toBeTruthy();
  fireEvent.click(screen.getByRole('button',{name:'Edit'}));
  fireEvent.change(screen.getByLabelText('About'),{target:{value:'New description'}});
  fetcher.mockResolvedValueOnce(response({error:'Save failed'},false));
  fireEvent.click(screen.getByRole('button',{name:'Save'}));
  expect(await screen.findByRole('alert')).toHaveProperty('textContent','Save failed');
  expect(screen.getByLabelText('About').value).toBe('New description');
});
test('desktop and phone project navigation list active real projects and underline the open page', async () => {
  vi.stubGlobal('fetch',vi.fn(async () => response([{key:'FAC',name:'Factory',active:true},{key:'LAB',name:'Lab',active:false},{key:'NEW',name:'No project yet',active:true}])));
  render(<MemoryRouter initialEntries={['/projects/FAC']}><ProjectNavigation/></MemoryRouter>);
  const nav = screen.getByRole('navigation',{name:'Projects'});
  const link = await within(nav).findByRole('link',{name:'Factory'});
  expect(link.classList.contains('active')).toBe(true);
  expect(link.getAttribute('aria-current')).toBe('page');
  expect(within(nav).queryByText('Lab')).toBeNull();
  expect(screen.queryByText('No project yet')).toBeNull();
  expect([...screen.getByRole('combobox',{name:'Projects'}).options].map(o => o.value)).toEqual(['','FAC']);
});
test('Settings links inactive projects and creates active projects with guarded POST', async () => {
  const fetcher = vi.fn(async (_url,options) => response(options ? {key:'SYN',name:'Synthetic',active:true} : [{key:'FAC',name:'Factory',active:false}]));
  vi.stubGlobal('fetch',fetcher); render(<Settings/>);
  expect((await screen.findByRole('link',{name:'Factory'})).getAttribute('href')).toBe('/projects/FAC');
  fireEvent.click(screen.getByRole('button',{name:'Add project'}));
  fireEvent.change(screen.getByLabelText('Key'),{target:{value:'SYN'}});
  fireEvent.change(screen.getByLabelText('Name'),{target:{value:'Synthetic'}});
  fireEvent.click(screen.getByRole('button',{name:'Create project'}));
  expect(await screen.findByRole('link',{name:'Synthetic'})).toBeTruthy();
  expect(screen.getByRole('switch',{name:'Active Synthetic'}).checked).toBe(true);
  expect(fetcher).toHaveBeenCalledWith('/api/projects',expect.objectContaining({method:'POST',headers:expect.objectContaining({'X-Factory-UI':'1'}),body:JSON.stringify({key:'SYN',name:'Synthetic'})}));
});
