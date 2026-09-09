import { describe, expect, it } from 'vitest';
import { canStartRun, dateLabel, pageCountsDetermined, pageLabel, percentage, requiresPartialScope } from './presentation';
import { documentUrl } from './api';
import type { Comparison, Inventory } from './types';

const base: Inventory = { documents: [], pairs: [], unpaired: [], rejections: [], can_run: true };
describe('Controles de mínimo error', () => {
  it('nunca habilita una ejecución de cero parejas, aunque can_run sea incorrecto', () => {
    expect(canStartRun(base, true)).toBe(false);
    expect(canStartRun(null, true)).toBe(false);
  });
  it('una sugerencia no equivale a confirmación del auditor', () => {
    expect(canStartRun({ ...base, pairs: [{ id: 'p', original_id: 'o', modified_id: 'm', patient_name: 'PACIENTE SINTÉTICO', confirmed: false }] }, true)).toBe(false);
  });
  it('los documentos no pareados requieren aceptación explícita de alcance parcial', () => {
    const inventory: Inventory = { ...base, pairs: [{ id: 'p', original_id: 'o', modified_id: 'm', patient_name: 'PACIENTE SINTÉTICO', confirmed: true }], unpaired: [{ id: 'u', side: 'original', original_name: 'no-pareado.pdf', patient_name: 'OTRO PACIENTE SINTÉTICO' }] };
    expect(canStartRun(inventory, false)).toBe(false);
    expect(canStartRun(inventory, true)).toBe(true);
  });
  it('no sustituye una página inexistente por página 1', () => {
    expect(pageLabel(null)).toBe('No corresponde');
    expect(pageLabel(0)).toBe('No corresponde');
    expect(documentUrl('doc', null)).not.toContain('#page=');
    expect(documentUrl('doc', 33)).toBe('/api/v1/documents/doc/content#page=33');
  });
  it('rechazos bloqueantes necesitan alcance parcial, anexos informativos no', () => {
    const inventory: Inventory = { ...base, pairs: [{ id: 'p', original_id: 'o', modified_id: 'm', patient_name: 'PACIENTE SINTÉTICO', confirmed: true }], rejections: [{ name: 'corrupto.pdf', reason: 'PDF inválido', blocking: true }] };
    expect(requiresPartialScope(inventory)).toBe(true);
    expect(canStartRun(inventory, false)).toBe(false);
    expect(canStartRun(inventory, true)).toBe(true);
    expect(requiresPartialScope({ ...inventory, rejections: [{ name: 'anexo.csv', reason: 'Anexo informativo', blocking: false }] })).toBe(false);
  });
  it('convierte los timestamps Unix en segundos del backend, no milisegundos', () => {
    expect(dateLabel(1788220800)).toContain('2026');
    expect(dateLabel('2026-09-01T00:00:00Z')).toContain('2026');
    expect(dateLabel('no-fecha')).toBe('Fecha no disponible');
  });
  it('progreso cero no produce NaN ni 100%', () => {
    expect(percentage(0, 0)).toBe(0);
    expect(percentage(1, 4)).toBe(25);
    expect(percentage(5, 4)).toBe(100);
  });
  it('no convierte una correspondencia ambigua en conteos concluyentes', () => {
    const comparison: Comparison = { status: 'with_differences', pages_original: 2, pages_modified: 3, pages_added: 1, pages_removed: 0, pages_relocated: 0, findings: [], page_map: [], limitations: [], engine_version: 'test' };
    expect(pageCountsDetermined(comparison, 'completed')).toBe(true);
    expect(pageCountsDetermined({ ...comparison, status: 'inconclusive' }, 'completed')).toBe(false);
    expect(pageCountsDetermined(comparison, 'inconclusive')).toBe(false);
    expect(pageCountsDetermined({ ...comparison, page_counts_reconciled: false })).toBe(false);
    expect(pageCountsDetermined({ ...comparison, page_map: [{ page_original: null, page_modified: 3, status: 'added', similarity: .4, review_required: true }] })).toBe(false);
  });
});
