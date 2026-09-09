import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { beforeEach, expect, it, vi } from 'vitest';
import { CaseReview } from './RunPage';
import { api } from './api';
import type { Case } from './types';
vi.mock('./api', async original => ({ ...await original<typeof import('./api')>(), api:vi.fn() }));
const item: Case = { id:'c', patient_name:'Paciente de prueba', original_id:'o', modified_id:'m', status:'completed', comparison:{
  status:'inconclusive',engine_version:'test',pages_original:30,pages_modified:50,pages_added:0,pages_removed:0,pages_relocated:1,page_map:[],limitations:['Limitación de prueba'],findings:[
    {id:'f1',change_type:'modified',category:'Diagnóstico',description:'Diagnóstico corregido',before:'K635 POLIPO DEL COLON',after:'K590 CONSTIPACION',page_original:2,page_modified:29,confidence:1,review_required:false,page_relocated:true},
    {id:'f2',change_type:'modified',category:'Importe',description:'Importe corregido',before:'$25,30',after:'$25,00',page_original:1,page_modified:1,confidence:1,review_required:false}
  ]} };
beforeEach(() => { vi.clearAllMocks(); vi.mocked(api).mockResolvedValue({image:'data:image/png;base64,aQ==',highlighted:true,page:2,method:'text'}); });
it('shows the table directly, applies page range only on Buscar and rejects an inverted range', () => {
  render(<CaseReview runId="r" caseItem={item} refresh={() => {}} />);
  expect(screen.queryByRole('button',{name:'Añadir observación'})).not.toBeInTheDocument();
  expect(screen.getByText('Limitación de prueba').closest('details')).not.toHaveAttribute('open');
  fireEvent.change(screen.getByLabelText('Pág. desde'),{target:{value:'29'}});
  fireEvent.change(screen.getByLabelText('Pág. hasta'),{target:{value:'29'}});
  expect(screen.getByText('Importe corregido')).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button',{name:'Buscar'}));
  expect(screen.queryByText('Importe corregido')).not.toBeInTheDocument();
  expect(screen.getByText('Diagnóstico corregido')).toBeInTheDocument();
  fireEvent.change(screen.getByLabelText('Pág. desde'),{target:{value:'30'}});
  fireEvent.click(screen.getByRole('button',{name:'Buscar'}));
  expect(screen.getByText(/desde no puede ser mayor/)).toBeInTheDocument();
});
it('opens both highlighted pages immediately and closes the evidence dialog', async () => {
  render(<CaseReview runId="r" caseItem={item} refresh={() => {}} />);
  fireEvent.click(screen.getAllByRole('button',{name:'Ver evidencia'})[0]);
  const dialog = await screen.findByRole('dialog',{name:'Evidencia de la observación'});
  await waitFor(() => expect(within(dialog).getAllByRole('img')).toHaveLength(2));
  expect(api).toHaveBeenCalledWith('/runs/r/cases/c/findings/f1/evidence?side=original');
  expect(api).toHaveBeenCalledWith('/runs/r/cases/c/findings/f1/evidence?side=modified');
  expect(within(dialog).getByText('K635 POLIPO DEL COLON').tagName).toBe('MARK');
  fireEvent.click(within(dialog).getByRole('button',{name:'Cerrar evidencia'}));
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
});
