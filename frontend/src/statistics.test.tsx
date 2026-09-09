import { render, screen, fireEvent, cleanup } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { summarizeCases, incidenceCount } from './statistics';
import { RunStatistics } from './RunStatistics';
import type { Case, ChangeType } from './types';
afterEach(cleanup);
const item = (id: string, types: ChangeType[]): Case => ({ id, patient_name: id, status:'completed', original_id:'o', modified_id:'m', comparison:{status:'with_differences',pages_original:1,pages_modified:1,pages_added:0,pages_removed:0,pages_relocated:0,page_map:[],limitations:[],engine_version:'test',findings:types.map((type,index)=>({id:String(index),change_type:type,category:'test',description:'test',before:'a',after:'b',page_original:1,page_modified:1,confidence:1,review_required:true,page_relocated:true}))} });
describe('review statistics',()=>{
 it('counts each finding once and keeps pending cases out of the analyzed denominator',()=>{
  const cases=[item('one',['added','removed','modified','relocated','review']),item('two',[]),{...item('pending',[]),comparison:null}];
  const stats=summarizeCases(cases);
  expect(stats).toEqual({counts:{added:1,removed:1,modified:1,relocated:1,review:1},total:5,available:2,affected:1});
  expect(incidenceCount(cases[0],'relocated')).toBe(1);
 });
 it('supports zero findings and no available results',()=>{
  expect(summarizeCases([]).total).toBe(0);
  render(<RunStatistics cases={[]} totalCases={3} active selected="all" onSelect={()=>{}} />);
  expect(screen.getByRole('img').getAttribute('aria-label')).toBe('Sin incidencias registradas');
  expect(screen.queryByText(/NaN/)).toBeNull();
 });
 it('exposes percentages, counts and category selection',()=>{
  const onSelect=vi.fn();render(<RunStatistics cases={[item('one',['modified','modified','added']),item('two',[])]} totalCases={2} active={false} selected="all" onSelect={onSelect} />);
  expect(screen.getByText('50%')).toBeTruthy();
  expect(screen.getByRole('img').getAttribute('aria-label')).toContain('66,7%');
  fireEvent.click(screen.getByRole('button',{name:/Modificado/}));expect(onSelect).toHaveBeenCalledWith('modified');
 });
});
