import { changeLabels } from './presentation';
import { coveragePercentages, incidencePercentages, statisticTypes, summarizeCases } from './statistics';
import type { Case, ChangeType } from './types';
const colors = { unchanged: '#dfe9ee', added: '#159e84', removed: '#dc625a', modified: '#dba321', relocated: '#5578cb', review: '#9862b5' };
const percent = (value: number) => new Intl.NumberFormat('es', { maximumFractionDigits: 1 }).format(value);
export function RunStatistics({ cases, totalCases, active, selected, onSelect, scope = 'executive' }: { scope?: 'patient' | 'executive'; cases: Case[]; totalCases: number; active: boolean; selected: ChangeType | 'all'; onSelect: (type: ChangeType | 'all') => void }) {
  const stats = summarizeCases(cases);
  const coverageReady = stats.available > 0 && stats.measured === stats.available && Object.values(stats.units).some(value => value > 0);
  const coverageShares = coveragePercentages(stats.units);
  const incidenceShares = incidencePercentages(stats.counts);
  const hasIncidences = stats.total > 0;
  const ready = coverageReady || hasIncidences;
  const displayShares = coverageReady ? coverageShares : incidenceShares;
  const affected = coverageReady ? Math.round(statisticTypes.reduce((sum, type) => sum + coverageShares[type], 0) * 10) / 10 : 100;
  let offset = 0;
  const slices = coverageReady
    ? [...statisticTypes, 'unchanged' as const].map(type => {
        const start = offset; offset += coverageShares[type];
        return `${colors[type]} ${start}% ${offset}%`;
      })
    : statisticTypes.map(type => {
        const start = offset; offset += incidenceShares[type];
        return `${colors[type]} ${start}% ${offset}%`;
      });
  const chartAriaLabel = coverageReady
    ? `Texto comparado: ${percent(affected)}% con cambios o por revisar; ${percent(coverageShares.unchanged)}% sin cambios`
    : hasIncidences
      ? `Distribución de ${stats.total} incidencias: ${statisticTypes.filter(type => stats.counts[type]).map(type => `${changeLabels[type]} ${percent(incidenceShares[type])}%`).join(', ')}`
      : 'Porcentaje comparativo no disponible';

  return <section className="surface-card statistics-card" aria-label={scope === 'patient' ? 'Estadística del paciente' : 'Resumen estadístico de la revisión'}>
    <div className="section-toolbar"><div><p className="eyebrow">{scope === 'patient' ? 'RESUMEN DEL PACIENTE' : 'PANORAMA GENERAL'}</p><h2>Cambios respecto al documento original</h2></div><span className="text-secondary small">{scope === 'patient' ? 'Solo este paciente' : `${active ? 'Resultados en curso' : 'Resultados disponibles'} · ${stats.available} de ${totalCases} expedientes con análisis`}</span></div>
    <div className="statistics-layout"><div className="statistics-chart" role="img" aria-label={chartAriaLabel} style={{ background: ready ? `conic-gradient(${slices.join(',')})` : colors.unchanged }}><div><strong>{ready ? (coverageReady ? `${percent(affected)}%` : '100%') : '—'}</strong><span>{coverageReady ? 'del texto comparado' : 'de incidencias'}</span></div></div>
    <div className="statistics-detail"><p className="statistics-kpi"><strong>{ready ? (coverageReady ? `${percent(affected)}%` : `${stats.total}`) : '—'}</strong> {coverageReady ? 'del texto con cambios o por revisar' : `incidencias registradas${hasIncidences ? ' (100%)' : ''}`}</p>
    <p className="form-text">{stats.total} incidencias registradas. {coverageReady ? 'El porcentaje estima el volumen de texto afectado; no representa un porcentaje de errores.' : 'El pastel distribuye las incidencias según su tipo de cambio.'}</p>
    {!ready && <p className="form-text">Sin incidencias registradas ni medición comparativa disponible para esta selección.</p>}
    {coverageReady && <div className="statistics-category mb-2"><span className="statistics-dot" style={{ background: colors.unchanged }} /><span>Sin cambios de texto ni reubicación detectados</span><strong>{percent(coverageShares.unchanged)}%</strong><small>texto conservado</small></div>}
    <div className="statistics-legend">{statisticTypes.map(type => <button key={type} className={`statistics-category ${selected === type ? 'is-selected' : ''}`} aria-pressed={selected === type} disabled={!stats.counts[type]} onClick={() => onSelect(type)}><span className="statistics-dot" style={{ background: colors[type] }} /><span>{changeLabels[type]}</span><strong>{ready ? `${percent(displayShares[type])}%` : '—'}</strong><small>{stats.counts[type]} incidencias</small></button>)}</div>
    <button className="btn btn-sm btn-outline-primary mt-3" aria-pressed={selected === 'all'} onClick={() => onSelect('all')}>Ver todas las incidencias</button>
    <p className="form-text mt-2">{coverageReady ? `Los cinco tipos suman ${percent(affected)}%. Base: palabras y números del original más el texto adicional, comparados entre páginas correspondientes. El texto que cambia se cuenta una sola vez; el texto conservado de una página movida se cuenta como reubicado. «Por revisar» mide texto cuya correspondencia es incierta.` : `Los cinco tipos suman 100%. Base: total de ${stats.total} incidencias registradas${scope === 'patient' ? ' de este paciente' : ''}.`}</p>
    {coverageReady && (stats.unmeasuredPages > 0 || stats.graphicFindings > 0) && <p className="form-text">Alcance: solo texto medible. {stats.unmeasuredPages} correspondencias sin texto medible y {stats.graphicFindings} incidencias gráficas quedan fuera del porcentaje; requieren revisión visual.</p>}
    </div></div>
  </section>;
}
