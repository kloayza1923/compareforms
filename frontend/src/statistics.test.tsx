import { render, screen, fireEvent, cleanup } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { summarizeCases, incidenceCount, coveragePercentages, incidencePercentages } from './statistics';
import { RunStatistics } from './RunStatistics';
import type { Case, ChangeType } from './types';
afterEach(cleanup);
const item = (id: string, types: ChangeType[]): Case => ({ id, patient_name: id, status:'completed', original_id:'o', modified_id:'m', comparison:{status:'with_differences',pages_original:1,pages_modified:1,pages_added:0,pages_removed:0,pages_relocated:0,page_map:[],limitations:[],engine_version:'test',content_coverage:{method:'aligned-token-coverage-v1',total_units:100,unmeasured_page_pairs:0,units:{unchanged:50,modified:30,added:10,removed:5,relocated:3,review:2}},findings:types.map((type,index)=>({id:String(index),change_type:type,category:'test',description:'test',before:'a',after:'b',page_original:1,page_modified:1,confidence:1,review_required:true,page_relocated:true}))} });
describe('review statistics',()=>{
 it('rounds the five categories to exactly the affected share',()=>{
 const shares=coveragePercentages({unchanged:3,modified:1,added:1,removed:1,relocated:1,review:1});
 expect(Math.round(Object.values(shares).reduce((a,b)=>a+b,0)*10)).toBe(1000);
 expect(shares.unchanged).toBe(37.5);
 });
 it('counts each finding once and keeps pending cases out of the analyzed denominator',()=>{
  const cases=[item('one',['added','removed','modified','relocated','review']),item('two',[]),{...item('pending',[]),comparison:null}];
  const stats=summarizeCases(cases);
  expect(stats).toMatchObject({counts:{added:1,removed:1,modified:1,relocated:1,review:1},total:5,available:2,affected:1});
  expect(incidenceCount(cases[0],'relocated')).toBe(1);
 });
 it('supports zero findings and no available results',()=>{
  expect(summarizeCases([]).total).toBe(0);
  render(<RunStatistics cases={[]} totalCases={3} active selected="all" onSelect={()=>{}} />);
  expect(screen.getByRole('img').getAttribute('aria-label')).toBe('Porcentaje comparativo no disponible');
  expect(screen.queryByText(/NaN/)).toBeNull();
 });
  it('calculates incidence percentages summing to 100% with largest remainder', () => {
    const shares = incidencePercentages({ added: 18, removed: 24, modified: 41, relocated: 23, review: 85 });
    const sum = Math.round(Object.values(shares).reduce((a, b) => a + b, 0) * 10) / 10;
    expect(sum).toBe(100);
    expect(shares.added).toBe(9.4);
    expect(shares.removed).toBe(12.6);
    expect(shares.modified).toBe(21.5);
    expect(shares.relocated).toBe(12);
    expect(shares.review).toBe(44.5);
  });
  it('renders incidence percentages for patient when content coverage is not available', () => {
    const patientCase: Case = {
      id: 'patient-1',
      patient_name: 'ALMEIDA LEON COLOMBIA AMADA',
      status: 'completed',
      original_id: 'o',
      modified_id: 'm',
      comparison: {
        status: 'with_differences',
        pages_original: 10,
        pages_modified: 10,
        pages_added: 0,
        pages_removed: 0,
        pages_relocated: 0,
        page_map: [],
        limitations: [],
        engine_version: 'test',
        findings: [
          ...Array.from({ length: 18 }, (_, i) => ({ id: `add-${i}`, change_type: 'added' as ChangeType, category: 'test', description: 'test', before: 'a', after: 'b', page_original: 1, page_modified: 1, confidence: 1, review_required: false, page_relocated: false })),
          ...Array.from({ length: 24 }, (_, i) => ({ id: `rem-${i}`, change_type: 'removed' as ChangeType, category: 'test', description: 'test', before: 'a', after: 'b', page_original: 1, page_modified: 1, confidence: 1, review_required: false, page_relocated: false })),
          ...Array.from({ length: 41 }, (_, i) => ({ id: `mod-${i}`, change_type: 'modified' as ChangeType, category: 'test', description: 'test', before: 'a', after: 'b', page_original: 1, page_modified: 1, confidence: 1, review_required: false, page_relocated: false })),
          ...Array.from({ length: 23 }, (_, i) => ({ id: `rel-${i}`, change_type: 'relocated' as ChangeType, category: 'test', description: 'test', before: 'a', after: 'b', page_original: 1, page_modified: 1, confidence: 1, review_required: false, page_relocated: false })),
          ...Array.from({ length: 85 }, (_, i) => ({ id: `rev-${i}`, change_type: 'review' as ChangeType, category: 'test', description: 'test', before: 'a', after: 'b', page_original: 1, page_modified: 1, confidence: 1, review_required: false, page_relocated: false })),
        ],
      },
    };
    render(<RunStatistics scope="patient" cases={[patientCase]} totalCases={1} active={false} selected="all" onSelect={() => {}} />);
    expect(screen.getByRole('img').getAttribute('aria-label')).toContain('Distribución de 191 incidencias');
    expect(screen.getByText('100%')).toBeDefined();
    expect(screen.getByText(/44,5%/)).toBeDefined();
    expect(screen.getByText(/21,5%/)).toBeDefined();
    expect(screen.getByText(/12,6%/)).toBeDefined();
    expect(screen.getByText(/9,4%/)).toBeDefined();
    expect(screen.queryByText(/Esta ejecución no tiene una medición comparativa/)).toBeNull();
  });
 it('exposes percentages, counts and category selection',()=>{
  const onSelect=vi.fn();render(<RunStatistics cases={[item('one',['modified','modified','added']),item('two',[])]} totalCases={2} active={false} selected="all" onSelect={onSelect} />);
  expect(screen.getAllByText('50%').length).toBeGreaterThan(0);
  expect(screen.getByRole('img').getAttribute('aria-label')).toContain('50% sin cambios');
  fireEvent.click(screen.getByRole('button',{name:/Modificado/}));expect(onSelect).toHaveBeenCalledWith('modified');
 });
});
