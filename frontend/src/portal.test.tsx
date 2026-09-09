import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { NewComparison, BatchPage } from './BatchPage';
import { RunPage } from './RunPage';
import { api, post } from './api';
import type { Batch, Run } from './types';

vi.mock('./api', async importOriginal => ({ ...await importOriginal<typeof import('./api')>(), api: vi.fn(), post: vi.fn() }));
const apiMock = vi.mocked(api);
const batch: Batch = { id: 'b', name: 'Revisión de prueba', period: '2026_06', source_mode: 'manual', source_system: 'dalia', status: 'draft', created_at: '2026-06-01T12:00:00Z' };
const run: Run = {
  id: 'r', batch_id: 'b', status: 'completed', completed: 1, total: 1, error: null, report_available: true,
  cases: [{ id: 'c', patient_name: 'PACIENTE SINTÉTICO PARA TEST', original_id: 'original', modified_id: 'modified', status: 'completed', comparison: {
    status: 'with_differences', engine_version: 'test', pages_original: 2, pages_modified: 2, pages_added: 1, pages_removed: 1, pages_relocated: 0, limitations: [], page_map: [],
    findings: [
      { id: 'f1', change_type: 'added', category: 'Documento', description: 'Documento de soporte incorporado', before: '', after: 'Texto incorporado sintético', page_original: null, page_modified: 2, confidence: 1, review_required: false },
      { id: 'f2', change_type: 'removed', category: 'Documento', description: 'Documento de soporte retirado', before: 'Texto retirado sintético', after: '', page_original: 1, page_modified: null, confidence: 1, review_required: false },
    ],
  } }],
};
beforeEach(() => vi.clearAllMocks());
describe('Flujo del auditor', () => {
  it('exige seleccionar la alternativa manual y no simula Roboti', () => {
    render(<NewComparison capabilities={null} />);
    const create = screen.getByRole('button', { name: /Crear revisión y cargar ZIP/ });
    expect(create).toBeDisabled();
    fireEvent.click(screen.getByRole('checkbox', { name: /Usar carga manual/ }));
    expect(create).toBeEnabled();
    expect(screen.getByLabelText('Procedencia del original')).toHaveValue('dalia');
  });
  it('cero expedientes muestra Sin comparación y botón bloqueado', async () => {
    apiMock.mockImplementation(async path => path === '/batches' ? [batch] : { documents: [], pairs: [], unpaired: [], rejections: [], can_run: true });
    render(<BatchPage batchId="b" />);
    await screen.findByText('Revisión de prueba');
    expect(screen.getByRole('button', { name: /Comparar expedientes/ })).toBeDisabled();
    expect(screen.getByText(/Sin comparación: necesitas al menos una pareja confirmada/)).toBeInTheDocument();
    expect(post).not.toHaveBeenCalled();
  });
  it('el paciente es la primera columna y el filtro separa incorporaciones de retiradas', async () => {
    apiMock.mockResolvedValue(run);
    render(<RunPage runId="r" />);
    await screen.findByText('Documento de soporte incorporado');
    const table = screen.getAllByRole('table')[0];
    const headers = within(table).getAllByRole('columnheader');
    expect(headers[0]).toHaveTextContent('Paciente');
    expect(headers[5]).toHaveTextContent('Página origen');
    expect(headers[6]).toHaveTextContent('Página modificado');
    expect(screen.getByRole('link', { name: /Descargar Excel/ })).toHaveAttribute('href', '/api/v1/runs/r/report');
    fireEvent.change(screen.getByLabelText('Filtrar por tipo de cambio'), { target: { value: 'removed' } });
    expect(screen.getByText('Documento de soporte incorporado')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name:'Buscar' }));
    expect(screen.getByText('Documento de soporte retirado')).toBeInTheDocument();
    expect(screen.queryByText('Documento de soporte incorporado')).not.toBeInTheDocument();
    const row = screen.getByText('Documento de soporte retirado').closest('tr')!;
    expect(within(row).getByRole('link', { name: 'Pág. 1 ↗' })).toHaveAttribute('href', '/api/v1/documents/original/content#page=1');
    expect(within(row).getAllByText('No corresponde').length).toBeGreaterThan(0);
  });
  it('una ejecución vacía nunca aparece como evidencia de igualdad', async () => {
    apiMock.mockResolvedValue({ ...run, total: 0, completed: 0, cases: [], report_available: false });
    render(<RunPage runId="r" />);
    await waitFor(() => expect(screen.getByText(/Sin comparación: esta ejecución no tiene expedientes/)).toBeInTheDocument());
    expect(screen.queryByText('Sin diferencias detectadas')).not.toBeInTheDocument();
    expect(screen.queryByRole('link', { name: /Descargar Excel/ })).not.toBeInTheDocument();
  });
  it('muestra las omisiones manuales y las revisiones persistidas después de recargar', async () => {
    apiMock.mockResolvedValue({ ...run, cases: [{ ...run.cases[0],
      manual_findings: [{ id: 'manual1', change_type: 'added', description: 'Dato omitido por el detector', before: '', after: 'Dato comprobado por auditor', page_original: 1, page_modified: 1 }],
      reviews: [{ id: 'review1', finding_id: 'f1', decision: 'confirmed', comment: 'Verificado con el expediente de prueba.' }],
    }] });
    render(<RunPage runId="r" />);
    await screen.findByText('Dato omitido por el detector');
    expect(screen.getByText('Observación manual del auditor')).toBeInTheDocument();
    expect(screen.getByText('Historial de revisión del auditor')).toBeInTheDocument();
    expect(screen.getByText('Verificado con el expediente de prueba.')).toBeInTheDocument();
  });
  it('permite aceptar alcance parcial cuando el único problema es un PDF rechazado', async () => {
    apiMock.mockImplementation(async path => path === '/batches' ? [batch] : {
      documents: [], pairs: [{ id: 'p', original_id: 'o', modified_id: 'm', patient_name: 'PACIENTE SINTÉTICO', confirmed: true }], unpaired: [],
      rejections: [{ name: 'corrupto.pdf', reason: 'PDF inválido', blocking: true }], can_run: true,
    });
    render(<BatchPage batchId="b" />);
    const checkbox = await screen.findByRole('checkbox', { name: /Acepto comparar solo las parejas confirmadas/ });
    expect(screen.getByRole('button', { name: /Comparar expedientes/ })).toBeDisabled();
    fireEvent.click(checkbox);
    expect(screen.getByRole('button', { name: /Comparar expedientes/ })).toBeEnabled();
  });
  it('un resultado no concluyente no presenta conteos añadidos o retirados como confirmados', async () => {
    apiMock.mockResolvedValue({ ...run, status: 'partial', cases: [{ ...run.cases[0], comparison: { ...run.cases[0].comparison!, status: 'inconclusive' } }] });
    render(<RunPage runId="r" />);
    await screen.findByText('Documento de soporte incorporado');
    expect(screen.queryByText('Correspondencia automática pendiente de confirmar.')).not.toBeInTheDocument();
    fireEvent.click(screen.getByText('Detalles y correspondencia de páginas'));
    expect(screen.getAllByText('Sin determinar')).toHaveLength(3);
    expect(screen.queryByText('+1')).not.toBeInTheDocument();
    expect(screen.queryByText('−1')).not.toBeInTheDocument();
    expect(screen.getByText(/El Excel descargable es una instantánea del resultado del motor/)).toHaveTextContent('no se incorporan a ese archivo');
  });
  it('una fila del mapa pendiente de revisión invalida los conteos aunque el estado general diga completado', async () => {
    apiMock.mockResolvedValue({ ...run, cases: [{ ...run.cases[0], comparison: { ...run.cases[0].comparison!, page_map: [{ page_original: null, page_modified: 2, status: 'added', similarity: .4, review_required: true }] } }] });
    render(<RunPage runId="r" />);
    await screen.findByText('Documento de soporte incorporado');
    expect(screen.queryByText('Correspondencia automática pendiente de confirmar.')).not.toBeInTheDocument();
    fireEvent.click(screen.getByText('Detalles y correspondencia de páginas'));
    expect(screen.getAllByText('Sin determinar')).toHaveLength(3);
    expect(screen.getByText('Correspondencia pendiente de confirmar')).toBeInTheDocument();
  });
});
