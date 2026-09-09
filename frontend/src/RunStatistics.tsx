import { changeLabels } from './presentation';
import { statisticTypes, summarizeCases } from './statistics';
import type { Case, ChangeType } from './types';
const colors = { added: '#159e84', removed: '#dc625a', modified: '#dba321', relocated: '#5578cb', review: '#9862b5' };
const percent = (count: number, total: number) => total ? new Intl.NumberFormat('es', { maximumFractionDigits: 1 }).format(count * 100 / total) : '0';
export function RunStatistics({ cases, totalCases, active, selected, onSelect }: { cases: Case[]; totalCases: number; active: boolean; selected: ChangeType | 'all'; onSelect: (type: ChangeType | 'all') => void }) {
  const stats = summarizeCases(cases);
  let offset = 0;
  const slices = statisticTypes.map(type => {
    const start = offset; offset += stats.total ? stats.counts[type] / stats.total * 100 : 0;
    return `${colors[type]} ${start}% ${offset}%`;
  });
  return <section className="surface-card statistics-card" aria-label="Resumen estadístico de la revisión">
    <div className="section-toolbar"><div><p className="eyebrow">PANORAMA GENERAL</p><h2>Incidencias de la revisión</h2></div><span className="text-secondary small">{active ? 'Resultados en curso' : 'Resultados disponibles'} · {stats.available} de {totalCases} expedientes con análisis</span></div>
    <div className="statistics-layout"><div className="statistics-chart" role="img" aria-label={stats.total ? `Distribución de ${stats.total} incidencias: ${statisticTypes.map(type => `${changeLabels[type]} ${percent(stats.counts[type], stats.total)}%`).join(', ')}` : 'Sin incidencias registradas'} style={{ background: stats.total ? `conic-gradient(${slices.join(',')})` : '#e5eaf0' }}><div><strong>{stats.total}</strong><span>incidencias</span></div></div>
    <div className="statistics-detail"><p className="statistics-kpi"><strong>{stats.available ? `${percent(stats.affected, stats.available)}%` : '—'}</strong> de expedientes analizados con incidencias</p><p className="form-text">{stats.affected} de {stats.available} expedientes con análisis disponible. El pastel distribuye las {stats.total} incidencias por su tipo principal.</p>
    <div className="statistics-legend">{statisticTypes.map(type => <button key={type} className={`statistics-category ${selected === type ? 'is-selected' : ''}`} aria-pressed={selected === type} disabled={!stats.counts[type]} onClick={() => onSelect(type)}><span className="statistics-dot" style={{ background: colors[type] }} /><span>{changeLabels[type]}</span><strong>{percent(stats.counts[type], stats.total)}%</strong><small>{stats.counts[type]} incidencias</small></button>)}</div>
    <button className="btn btn-sm btn-outline-primary mt-3" aria-pressed={selected === 'all'} onClick={() => onSelect('all')}>Ver todas las incidencias</button>
    <p className="form-text mt-2">Selecciona un tipo para priorizar pacientes. Cada incidencia se cuenta una vez: un cambio modificado y reubicado se cuenta como modificado. «Por revisar» corresponde al tipo de incidencia, no al estado de validación del auditor.</p></div></div>
  </section>;
}
