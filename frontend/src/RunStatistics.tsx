import { changeLabels } from './presentation';
import { coveragePercentages, statisticTypes, summarizeCases } from './statistics';
import type { Case, ChangeType } from './types';
const colors = { unchanged: '#dfe9ee', added: '#159e84', removed: '#dc625a', modified: '#dba321', relocated: '#5578cb', review: '#9862b5' };
const percent = (value: number) => new Intl.NumberFormat('es', { maximumFractionDigits: 1 }).format(value);
export function RunStatistics({ cases, totalCases, active, selected, onSelect }: { cases: Case[]; totalCases: number; active: boolean; selected: ChangeType | 'all'; onSelect: (type: ChangeType | 'all') => void }) {
  const stats = summarizeCases(cases);
  const shares = coveragePercentages(stats.units);
  const ready = stats.available > 0 && stats.measured === stats.available && Object.values(stats.units).some(value => value > 0);
  const affected = Math.round(statisticTypes.reduce((sum, type) => sum + shares[type], 0) * 10) / 10;
  let offset = 0;
  const slices = [...statisticTypes, 'unchanged' as const].map(type => {
    const start = offset; offset += shares[type];
    return `${colors[type]} ${start}% ${offset}%`;
  });
  return <section className="surface-card statistics-card" aria-label="Resumen estadístico de la revisión">
    <div className="section-toolbar"><div><p className="eyebrow">PANORAMA GENERAL</p><h2>Cambios respecto al documento original</h2></div><span className="text-secondary small">{active ? 'Resultados en curso' : 'Resultados disponibles'} · {stats.available} de {totalCases} expedientes con análisis</span></div>
    <div className="statistics-layout"><div className="statistics-chart" role="img" aria-label={ready ? `Texto comparado: ${percent(affected)}% con cambios o por revisar; ${percent(shares.unchanged)}% sin cambios` : 'Porcentaje comparativo no disponible'} style={{ background: ready ? `conic-gradient(${slices.join(',')})` : colors.unchanged }}><div><strong>{ready ? `${percent(affected)}%` : '—'}</strong><span>del texto comparado</span></div></div>
    <div className="statistics-detail"><p className="statistics-kpi"><strong>{ready ? `${percent(affected)}%` : '—'}</strong> del texto con cambios o por revisar</p>
    <p className="form-text">{stats.total} incidencias registradas. El porcentaje estima el volumen de texto afectado; no representa un porcentaje de errores.</p>
    {!ready && <p className="form-text">Esta ejecución no tiene una medición comparativa completa. Usa «Volver a comparar» para calcularla. No se deduce un porcentaje del número de incidencias.</p>}
    {ready && <div className="statistics-category mb-2"><span className="statistics-dot" style={{ background: colors.unchanged }} /><span>Sin cambios de texto ni reubicación detectados</span><strong>{percent(shares.unchanged)}%</strong><small>texto conservado</small></div>}
    <div className="statistics-legend">{statisticTypes.map(type => <button key={type} className={`statistics-category ${selected === type ? 'is-selected' : ''}`} aria-pressed={selected === type} disabled={!stats.counts[type]} onClick={() => onSelect(type)}><span className="statistics-dot" style={{ background: colors[type] }} /><span>{changeLabels[type]}</span><strong>{ready ? `${percent(shares[type])}%` : '—'}</strong><small>{stats.counts[type]} incidencias</small></button>)}</div>
    <button className="btn btn-sm btn-outline-primary mt-3" aria-pressed={selected === 'all'} onClick={() => onSelect('all')}>Ver todas las incidencias</button>
    <p className="form-text mt-2">Los cinco tipos suman {ready ? `${percent(affected)}%` : 'el porcentaje afectado'}. Base: palabras y números del original más el texto adicional, comparados entre páginas correspondientes. El texto que cambia se cuenta una sola vez; el texto conservado de una página movida se cuenta como reubicado. «Por revisar» mide texto cuya correspondencia es incierta.</p>
    {(stats.unmeasuredPages > 0 || stats.graphicFindings > 0) && <p className="form-text">Alcance: solo texto medible. {stats.unmeasuredPages} correspondencias sin texto medible y {stats.graphicFindings} incidencias gráficas quedan fuera del porcentaje; requieren revisión visual.</p>}
    </div></div>
  </section>;
}
