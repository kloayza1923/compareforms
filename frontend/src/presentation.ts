import type { ChangeType, Comparison, Inventory } from './types';

export const changeLabels: Record<ChangeType, string> = {
  added: 'Incorporado', removed: 'Retirado', modified: 'Modificado', relocated: 'Reubicado', review: 'Por revisar',
};
export const statusLabels: Record<string, string> = {
  queued: 'En cola', running: 'Procesando', completed: 'Completado', partial: 'Parcial · no concluyente',
  failed: 'Error de ejecución', cancelled: 'Cancelado', draft: 'Borrador', ready: 'Listo',
  pending: 'Pendiente', with_differences: 'Con diferencias', no_differences_detected: 'Sin diferencias detectadas',
  inconclusive: 'No concluyente', processing: 'Procesando', needs_pairing: 'Requiere asociación',
  manual_observations: 'Con observaciones manuales',
};
export const stateLabel = (status: string) => statusLabels[status] || status;
export const pageLabel = (page: number | null | undefined) => page && page > 0 ? `Pág. ${page}` : 'No corresponde';
export const dateLabel = (value?: string | number) => {
  if (value === undefined || value === null || value === '') return '—';
  const date = new Date(typeof value === 'number' ? value * 1000 : value);
  return Number.isNaN(date.getTime()) ? 'Fecha no disponible' : new Intl.DateTimeFormat('es-EC', {
    dateStyle: 'medium', timeStyle: 'short', timeZone: 'America/Guayaquil',
  }).format(date);
};
export const requiresPartialScope = (inventory: Inventory | null) => !!inventory &&
  (inventory.unpaired.length > 0 || inventory.rejections.some(item => item.blocking !== false));
export const canStartRun = (inventory: Inventory | null, allowPartial: boolean) => !!inventory &&
  inventory.can_run && inventory.pairs.some(pair => pair.confirmed) && (!requiresPartialScope(inventory) || allowPartial);
export const percentage = (completed: number, total: number) => total > 0 ? Math.min(100, Math.max(0, Math.round(completed * 100 / total))) : 0;
export const pageCountsDetermined = (comparison: Comparison | null, caseStatus?: string) => !!comparison &&
  comparison.status !== 'inconclusive' && caseStatus !== 'inconclusive' && comparison.page_counts_reconciled !== false &&
  !comparison.page_map.some(mapping => mapping.review_required || ['review', 'ambiguous'].includes(mapping.status));
export const excelSnapshotNotice = 'El Excel descargable es una instantánea del resultado del motor en esta ejecución. Las revisiones y observaciones manuales registradas después se conservan en el portal y no se incorporan a ese archivo.';
