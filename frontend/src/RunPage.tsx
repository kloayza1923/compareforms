import { RunStatistics } from './RunStatistics';
import { incidenceCount } from './statistics';
import { useEffect, useRef, useState, type FormEvent } from 'react';
import { api, documentUrl, errorMessage, post, reportUrl } from './api';
import { Busy, ChangeBadge, Empty, Icon, Notice, PageHeading, StateBadge } from './components';
import { changeLabels, dateLabel, excelSnapshotNotice, pageCountsDetermined, pageLabel, percentage } from './presentation';
import type { Batch, Case, ChangeType, Finding, Review, Run } from './types';

const reviewLabels: Record<Review['decision'], string> = { confirmed: 'Confirmado por auditor', false_positive: 'Falso positivo', needs_review: 'Revisión solicitada' };
const caseStatus = (value: Case) => value.comparison?.status === 'no_differences_detected' && value.manual_findings?.length ? 'manual_observations' : value.comparison?.status || value.status;
function allFindings(caseItem: Case): Finding[] {
  return [...(caseItem.comparison?.findings || []).map(finding => ({ ...finding, source: 'automatic' as const })),
    ...(caseItem.manual_findings || []).map(finding => ({ ...finding, category: 'Observación manual del auditor', source: 'manual' as const, confidence: null, review_required: true }))];
}

export function HistoryPage() {
  const [batches, setBatches] = useState<Batch[]>([]);
  const [runs, setRuns] = useState<Run[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [search, setSearch] = useState('');
  useEffect(() => {
    let alive = true;
    Promise.all([api<Batch[]>('/batches'), api<Run[]>('/runs')]).then(([batchList, runList]) => { if (alive) { setBatches(batchList); setRuns(runList); } }).catch(cause => { if (alive) setError(errorMessage(cause)); }).finally(() => { if (alive) setLoading(false); });
    return () => { alive = false; };
  }, []);
  const visible = batches.filter(batch => `${batch.name} ${batch.period}`.toLocaleLowerCase('es').includes(search.toLocaleLowerCase('es')));
  return <><PageHeading title="Historial de revisiones" action={<a href="#/new" className="btn btn-primary"><Icon name="plus" /> Nueva comparación</a>}>Retoma una revisión o descarga el informe de una ejecución específica.</PageHeading>{error && <Notice tone="danger">{error}</Notice>}
    {runs.some(run => run.report_available) && <Notice>{excelSnapshotNotice}</Notice>}
    <section className="surface-card"><div className="section-toolbar"><h2>Revisiones documentales</h2><label className="search-field"><span className="visually-hidden">Buscar revisión o período</span><input className="form-control" type="search" placeholder="Buscar revisión o período…" value={search} onChange={event => setSearch(event.target.value)} /></label></div>
      {loading ? <Busy /> : !visible.length ? <Empty title={batches.length ? 'No hay coincidencias' : 'Aún no hay revisiones'}>Las revisiones y sus resultados aparecerán aquí, incluso después de cerrar el navegador.</Empty> : <div className="history-list">{visible.map(batch => {
        const batchRuns = runs.filter(run => run.batch_id === batch.id);
        return <article key={batch.id} className="history-item"><div className="history-title"><span className="history-icon"><Icon /></span><div><a href={`#/batches/${batch.id}`}>{batch.name}</a><p>{batch.period.replace('_', ' / ')} · {batch.source_system === 'dalia' ? 'Origen DALIA' : batch.source_system === 'roboti' ? 'Origen Roboti' : 'Origen manual'} · {dateLabel(batch.created_at)}</p></div><StateBadge status={batch.status} /></div>{!batchRuns.length ? <div className="history-empty">Sin ejecuciones. <a href={`#/batches/${batch.id}`}>Continuar preparación</a></div> : <div className="table-responsive"><table className="table audit-table mb-0"><thead><tr><th>Ejecución</th><th>Estado</th><th>Expedientes procesados</th><th>Resultados</th></tr></thead><tbody>{batchRuns.map(run => <tr key={run.id}><td><a className="code-reference" href={`#/runs/${run.id}`}>{run.id.slice(0, 8)}</a>{run.created_at && <small className="d-block text-secondary">{dateLabel(run.created_at)}</small>}</td><td><StateBadge status={run.status} /></td><td>{run.completed} / {run.total}</td><td><a className="btn btn-sm btn-outline-primary me-2" href={`#/runs/${run.id}`}>Ver revisión</a>{run.report_available && <a className="btn btn-sm btn-download" href={reportUrl(run.id)}><Icon name="download" size={15} /> Excel</a>}</td></tr>)}</tbody></table></div>}</article>;
      })}</div>}
    </section></>;
}

export function RunPage({ runId, initialCaseId }: { runId: string; initialCaseId?: string }) {
  const [run, setRun] = useState<Run | null>(null);
  const [error, setError] = useState('');
  const [selectedCase, setSelectedCase] = useState(initialCaseId || '');
  const [patientSearch, setPatientSearch] = useState('');
  const [statisticType, setStatisticType] = useState<ChangeType | 'all'>('all');
  const [refresh, setRefresh] = useState(0);
  useEffect(() => {
    let alive = true; let timer: ReturnType<typeof setTimeout>;
    const load = async () => {
      try {
        const value = await api<Run>(`/runs/${runId}`);
        if (!alive) return; setRun(value); setError('');
        setSelectedCase(previous => previous || [...value.cases].sort((a, b) => incidenceCount(b) - incidenceCount(a))[0]?.id || '');
        if (['queued', 'running'].includes(value.status)) timer = setTimeout(load, 3000);
      } catch (cause) { if (alive) { setError(errorMessage(cause)); timer = setTimeout(load, 10000); } }
    };
    void load(); return () => { alive = false; clearTimeout(timer); };
  }, [runId, refresh]);
  const current = run?.cases.find(item => item.id === selectedCase);
  const cases = (run?.cases.filter(item => item.patient_name.toLocaleLowerCase('es').includes(patientSearch.toLocaleLowerCase('es')) && (statisticType === 'all' || incidenceCount(item, statisticType) > 0)) || []).sort((a, b) => incidenceCount(b, statisticType) - incidenceCount(a, statisticType));
  const selectStatistic = (type: ChangeType | 'all') => {
    setStatisticType(type); setPatientSearch('');
    const ranked = [...(run?.cases || [])].filter(item => type === 'all' || incidenceCount(item, type) > 0).sort((a, b) => incidenceCount(b, type) - incidenceCount(a, type));
    setSelectedCase(ranked[0]?.id || '');
  };
  const active = run && ['queued', 'running'].includes(run.status);
  return <><PageHeading title="Revisión de resultados" action={<div className="d-flex gap-2 flex-wrap"><a href="#/history" className="btn btn-outline-secondary">Historial</a>{run && !active && <a href={`#/batches/${run.batch_id}`} className="btn btn-outline-primary">Volver a comparar</a>}{run?.report_available && <a href={reportUrl(run.id)} className="btn btn-primary"><Icon name="download" /> Descargar Excel</a>}</div>}>Consulta el resumen general y prioriza los pacientes con más incidencias antes de revisar la evidencia.</PageHeading>
    {run?.report_available && <Notice>{excelSnapshotNotice}</Notice>}
    {error && <Notice tone="danger">No se pudo actualizar el progreso: {error}. Los trabajos ya iniciados continúan en el servidor.</Notice>}
    {!run ? <Busy /> : <>
      <section className="run-overview"><div><span className="eyebrow">EJECUCIÓN {run.id.slice(0, 8)}</span><div className="run-state"><StateBadge status={run.status} /><span>{run.completed} de {run.total} expedientes procesados</span></div></div><div className="run-progress"><div className="progress" role="progressbar" aria-label="Expedientes procesados" aria-valuenow={percentage(run.completed, run.total)} aria-valuemin={0} aria-valuemax={100}><div className={`progress-bar ${active ? 'progress-bar-striped progress-bar-animated' : ''}`} style={{ width: `${percentage(run.completed, run.total)}%` }} /></div><small>{active ? 'Puedes cerrar el navegador. El análisis continuará.' : 'Consulta el estado de cada expediente; un resultado parcial no permite concluir ausencia de diferencias.'}</small></div></section>
      {run.total === 0 && <Notice tone="danger">Sin comparación: esta ejecución no tiene expedientes. No puede interpretarse como «sin diferencias».</Notice>}
      {run.error && <Notice tone="danger">{run.error}</Notice>}
      {run.status === 'partial' && <Notice tone="warning">Resultado parcial / no concluyente. Revisa los expedientes pendientes, errores y limitaciones antes de usar el informe.</Notice>}
      <RunStatistics cases={run.cases} totalCases={run.total} active={!!active} selected={statisticType} onSelect={selectStatistic} />
      <div className="review-layout"><aside className="patient-selector surface-card"><h2>Pacientes <span>{cases.length}</span></h2><p className="form-text">Mayor número de incidencias primero{statisticType !== 'all' ? ` · ${changeLabels[statisticType]}` : ''}.</p><label className="visually-hidden" htmlFor="patient-search">Buscar paciente</label><input className="form-control mb-3" id="patient-search" type="search" placeholder="Buscar paciente…" value={patientSearch} onChange={event => setPatientSearch(event.target.value)} />{cases.map(item => <button key={item.id} className={`patient-button ${item.id === selectedCase ? 'selected' : ''}`} aria-pressed={item.id === selectedCase} onClick={() => setSelectedCase(item.id)}><strong>{item.patient_name || 'Paciente sin identificar'}</strong><StateBadge status={caseStatus(item)} /><small>{item.comparison ? `${incidenceCount(item, statisticType)} incidencias${statisticType !== 'all' ? ` de ${allFindings(item).length}` : ''}` : 'Comparación pendiente'}</small></button>)}{!cases.length && <p className="text-secondary small">No hay pacientes para mostrar.</p>}</aside>
        <div className="review-content">{current ? <CaseReview key={`${current.id}-${statisticType}`} initialType={statisticType} runId={run.id} caseItem={current} refresh={() => setRefresh(value => value + 1)} /> : <Empty title="Selecciona un paciente">La identificación y la evidencia se mostrarán aquí.</Empty>}</div></div>
    </>}</>;
}

export function CaseReview({ runId, caseItem, refresh, initialType = 'all' }: { runId: string; caseItem: Case; refresh: () => void; initialType?: ChangeType | 'all' }) {
  const comparison = caseItem.comparison;
  const countsDetermined = pageCountsDetermined(comparison, caseItem.status);
  const [draft, setDraft] = useState({ type:initialType as string, from:'', to:'' });
  const [filters, setFilters] = useState(draft);
  const [filterError, setFilterError] = useState('');
  const [findingId, setFindingId] = useState('');
  const findings = allFindings(caseItem);
  const visible = findings.filter(finding => {
    const type = filters.type === 'all' || finding.change_type === filters.type;
    const pages = [finding.page_original, finding.page_modified].filter((page): page is number => page != null);
    return type && ((!filters.from && !filters.to) || pages.some(page => page >= Number(filters.from || 1) && page <= Number(filters.to || Infinity)));
  });
  const selected = findings.find(finding => finding.id === findingId);
  const search = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (draft.from && draft.to && Number(draft.from) > Number(draft.to)) { setFilterError('La página desde no puede ser mayor que la página hasta.'); return; }
    setFilterError(''); setFilters({ ...draft });
  };
  return <><section className="surface-card patient-detail"><p className="eyebrow">PACIENTE / EXPEDIENTE</p><h2 className="patient-name">{caseItem.patient_name || 'Identidad pendiente de verificación'}</h2><div className="patient-detail-actions"><StateBadge status={caseStatus(caseItem)} /><a href={documentUrl(caseItem.original_id)} target="_blank" rel="noopener noreferrer">Abrir PDF de origen ↗</a><a href={documentUrl(caseItem.modified_id)} target="_blank" rel="noopener noreferrer">Abrir PDF modificado ↗</a></div>
    {comparison ? <>
      <div className="section-toolbar mt-4"><div><h3 className="small-heading mb-1">Observaciones documentales</h3><span className="text-secondary small">{visible.length} de {findings.length} · Páginas físicas del visor PDF</span></div>
        <form className="finding-filters" onSubmit={search}>
          <label className="form-label">Tipo de cambio<select className="form-select form-select-sm" aria-label="Filtrar por tipo de cambio" value={draft.type} onChange={event => setDraft({ ...draft, type:event.target.value })}><option value="all">Todos los tipos de cambio</option>{Object.entries(changeLabels).map(([type, label]) => <option key={type} value={type}>{label}</option>)}</select></label>
          <label className="form-label">Pág. desde<input className="form-control form-control-sm" type="number" min={1} step={1} value={draft.from} onChange={event => setDraft({ ...draft, from:event.target.value })} /></label>
          <label className="form-label">Pág. hasta<input className="form-control form-control-sm" type="number" min={1} step={1} value={draft.to} onChange={event => setDraft({ ...draft, to:event.target.value })} /></label>
          <button className="btn btn-sm btn-primary" type="submit">Buscar</button>
        </form>
      </div><p className="form-text">El rango busca en las páginas de origen o del modificado.</p>
      {filterError && <Notice tone="danger">{filterError}</Notice>}
      {!visible.length ? <Empty title={findings.length ? 'No hay observaciones para estos filtros' : comparison.status === 'no_differences_detected' ? 'Sin diferencias detectadas' : 'No hay hallazgos concluyentes'}>{findings.length ? 'Ajusta el tipo o el rango de páginas y pulsa Buscar.' : 'Consulta los documentos y el detalle de la comparación.'}</Empty> : <div className="table-responsive"><table className="table audit-table findings-table"><thead><tr><th>Paciente</th><th>Tipo</th><th>Observación</th><th>Antes · origen</th><th>Después · modificado</th><th>Página origen</th><th>Página modificado</th><th>Revisión</th></tr></thead><tbody>{visible.map(finding => <tr key={finding.id} className={selected?.id === finding.id ? 'selected-row' : ''}><td className="patient-cell">{caseItem.patient_name}</td><td><ChangeBadge type={finding.change_type} />{finding.page_relocated && finding.change_type !== 'relocated' && <div className="mt-1"><ChangeBadge type="relocated" /></div>}</td><td><strong className="finding-category">{finding.category}</strong><div className="evidence-text">{finding.description}</div></td><td className="evidence-text before-cell">{finding.before || 'No corresponde'}</td><td className="evidence-text after-cell">{finding.after || 'No corresponde'}</td><td><PageLink documentId={caseItem.original_id} page={finding.page_original} /></td><td><PageLink documentId={caseItem.modified_id} page={finding.page_modified} /></td><td><button className="btn btn-sm btn-outline-primary" onClick={() => setFindingId(finding.id)}>Ver evidencia</button>{finding.review_required && <small className="d-block mt-2 text-warning-emphasis">Requiere revisión</small>}</td></tr>)}</tbody></table></div>}
      <details className="page-map mt-3"><summary>Detalles y correspondencia de páginas</summary>
        <div className="page-metrics"><div><span>Origen</span><strong>{comparison.pages_original}<small> páginas</small></strong></div><div><span>Modificado</span><strong>{comparison.pages_modified}<small> páginas</small></strong></div><div><span>Incorporadas</span><strong>{countsDetermined ? `+${comparison.pages_added}` : 'Sin determinar'}</strong></div><div><span>Retiradas</span><strong>{countsDetermined ? `−${comparison.pages_removed}` : 'Sin determinar'}</strong></div><div><span>Reubicadas</span><strong>{countsDetermined ? comparison.pages_relocated : 'Sin determinar'}</strong></div></div>
        <p className="form-text mt-2">Las correspondencias pendientes no confirman incorporación ni retiro de páginas.</p>
        {comparison.limitations.length > 0 && <div className="form-text"><strong>Limitaciones de la revisión</strong><ul>{comparison.limitations.map((text, index) => <li key={index}>{text}</li>)}</ul></div>}
        <div className="table-responsive"><table className="table audit-table"><thead><tr><th>Paciente</th><th>Página origen</th><th>Página modificado</th><th>Correspondencia</th></tr></thead><tbody>{comparison.page_map.map((match, index) => <tr key={index}><td>{caseItem.patient_name}</td><td><PageLink documentId={caseItem.original_id} page={match.page_original} /></td><td><PageLink documentId={caseItem.modified_id} page={match.page_modified} /></td><td>{match.review_required ? 'Correspondencia pendiente de confirmar' : changeLabels[match.status as ChangeType] || ({ matched:'Asociada automáticamente', identical:'Idéntica', unchanged:'Sin cambios detectados', ambiguous:'Asociación por revisar' }[match.status] || match.status)}</td></tr>)}</tbody></table></div>
        <p className="method-note">Motor {comparison.engine_version}.</p>
      </details>
    </> : <Notice>Este expediente todavía no tiene una comparación disponible.</Notice>}
  </section>{(caseItem.reviews?.length || 0) > 0 && <section className="surface-card mt-4"><h2>Historial de revisión del auditor</h2>{caseItem.reviews!.map((review, index) => <article className="persisted-review" key={review.id}><div><span className="state-badge badge-neutral">{reviewLabels[review.decision]}</span><small>Registro {index + 1}</small><button className="btn btn-sm btn-outline-primary" onClick={() => setFindingId(review.finding_id)}>Ver evidencia asociada</button></div><p className="evidence-text">{review.comment || 'Sin comentario registrado.'}</p></article>)}</section>}{selected && <EvidenceReview key={selected.id} runId={runId} caseItem={caseItem} finding={selected} onClose={() => setFindingId('')} onSaved={refresh} />}</>;
}

export function PageLink({ documentId, page }: { documentId: string; page?: number | null }) {
  return page && page > 0 ? <a className="page-link-inline" href={documentUrl(documentId, page)} target="_blank" rel="noopener noreferrer">{pageLabel(page)} ↗</a> : <span className="not-applicable">No corresponde</span>;
}

function EvidenceReview({ runId, caseItem, finding, onClose, onSaved }: { runId: string; caseItem: Case; finding: Finding; onClose: () => void; onSaved: () => void }) {
  const [error, setError] = useState('');
  const [message, setMessage] = useState('');
  const [busy, setBusy] = useState(false);
  const [proposal, setProposal] = useState(false);
  const dialog = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const node = dialog.current;
    if (node?.showModal) node.showModal(); else node?.setAttribute('open', '');
    return () => { if (node?.open && node.close) node.close(); };
  }, []);
  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault(); const fields = new FormData(event.currentTarget); setBusy(true); setError(''); setMessage('');
    try {
      if (proposal) await post('/improvements', { run_id: runId, case_id: caseItem.id, finding_id: finding.id, description: fields.get('description'), expected_benefit: fields.get('expected_benefit') });
      else await post(`/runs/${runId}/cases/${caseItem.id}/reviews`, { finding_id: finding.id, decision: fields.get('decision'), comment: fields.get('comment') });
      setMessage(proposal ? 'Propuesta registrada para análisis técnico. No se aplicó ningún cambio a Roboti.' : 'Revisión guardada en el historial. El resultado automático original se conserva.');
      onSaved();
    } catch (cause) { setError(errorMessage(cause)); } finally { setBusy(false); }
  };
  return <dialog ref={dialog} className="surface-card evidence-panel evidence-dialog" aria-label="Evidencia de la observación" onCancel={event => { event.preventDefault(); onClose(); }}><div className="section-toolbar"><div><p className="eyebrow">EVIDENCIA SELECCIONADA</p><h2>{caseItem.patient_name}</h2></div><button className="btn btn-sm btn-outline-secondary" onClick={onClose}>Cerrar evidencia</button></div><ChangeBadge type={finding.change_type} /><p className="mt-3 evidence-text">{finding.description}</p>
    <div className="row g-3"><div className="col-lg-6"><PdfEvidence label="Origen · antes" runId={runId} caseId={caseItem.id} findingId={finding.id} side="original" documentId={caseItem.original_id} page={finding.page_original} content={finding.before} /></div><div className="col-lg-6"><PdfEvidence label="Modificado · después" runId={runId} caseId={caseItem.id} findingId={finding.id} side="modified" documentId={caseItem.modified_id} page={finding.page_modified} content={finding.after} /></div></div>
    <p className="form-text mt-3">Los números corresponden a la página física del PDF. El amarillo señala el texto de esta observación localizado en cada página. Los PDF originales se conservan sin cambios.</p>
    <div className="review-form"><div className="d-flex gap-2 mb-3"><button className={`btn btn-sm ${!proposal ? 'btn-primary' : 'btn-outline-secondary'}`} onClick={() => setProposal(false)}>Revisar observación</button><button className={`btn btn-sm ${proposal ? 'btn-primary' : 'btn-outline-secondary'}`} onClick={() => setProposal(true)}>Proponer mejora</button></div>{error && <Notice tone="danger">{error}</Notice>}{message && <Notice tone="success">{message}</Notice>}
      <form onSubmit={submit}>{proposal ? <><label className="form-label" htmlFor={`proposal-${finding.id}`}>Problema documental y cambio propuesto</label><textarea className="form-control" id={`proposal-${finding.id}`} name="description" rows={3} required maxLength={4000} defaultValue={finding.description} /><label className="form-label mt-3" htmlFor={`benefit-${finding.id}`}>¿Qué mejoraría y cómo se comprobaría?</label><textarea className="form-control" id={`benefit-${finding.id}`} name="expected_benefit" rows={3} maxLength={4000} required /><p className="form-text">La propuesta no confirma la causa. Un expediente de origen DALIA no demuestra un defecto de Roboti.</p></> : <><label className="form-label" htmlFor={`decision-${finding.id}`}>Decisión del auditor</label><select className="form-select" id={`decision-${finding.id}`} name="decision" defaultValue="needs_review"><option value="needs_review">Solicitar revisión / evidencia insuficiente</option><option value="confirmed">Confirmar observación</option><option value="false_positive">Falso positivo</option></select><label className="form-label mt-3" htmlFor={`comment-${finding.id}`}>Fundamento de la revisión</label><textarea className="form-control" id={`comment-${finding.id}`} name="comment" rows={3} required maxLength={4000} placeholder="Explica lo verificado en los documentos y las páginas consultadas." /></>}
      <button className="btn btn-primary mt-3" disabled={busy}>{busy ? 'Guardando…' : proposal ? 'Registrar propuesta sin aplicar cambios' : 'Guardar revisión'}</button></form>
    </div></dialog>;
}

interface EvidenceImage { image: string; highlighted: boolean; page: number; method: string | null; regions?: number[][] }
function PdfEvidence({ label, runId, caseId, findingId, side, documentId, page, content }: { label: string; runId: string; caseId: string; findingId: string; side:'original' | 'modified'; documentId: string; page:number | null; content:string }) {
  const [evidence, setEvidence] = useState<EvidenceImage | null>(null);
  const viewport = useRef<HTMLDivElement>(null);
  const [error, setError] = useState('');
  useEffect(() => {
    if (!page) return;
    let alive = true;
    api<EvidenceImage>(`/runs/${encodeURIComponent(runId)}/cases/${encodeURIComponent(caseId)}/findings/${encodeURIComponent(findingId)}/evidence?side=${side}`)
      .then(value => { if (alive) setEvidence(value); }).catch(cause => { if (alive) setError(errorMessage(cause)); });
    return () => { alive = false; };
  }, [runId, caseId, findingId, side, page]);
  return <div className="pdf-evidence"><header><strong>{label}</strong>{page ? <a href={documentUrl(documentId, page)} target="_blank" rel="noopener noreferrer">Abrir página {page} ↗</a> : <span>No corresponde</span>}</header>
    <div className="pdf-excerpt evidence-text">{content ? <mark>{content}</mark> : 'Sin contenido correspondiente en esta versión.'}</div>
    {!page ? <div className="no-page">No hay una página equivalente en esta versión del documento.</div> : error ? <Notice tone="danger">{error}</Notice> : !evidence ? <Busy text="Preparando página resaltada…" /> : <>
      {!evidence.highlighted && <p className="form-text px-3">No se localizó una región única para este texto. Consulta la página completa.</p>}
      <div className="evidence-image-scroll" ref={viewport}><img className="evidence-page-image" onLoad={event => {
        const region = evidence.regions?.[0]; const box = viewport.current; const image = event.currentTarget;
        if (region && box && image.naturalWidth) {
          const scale = image.clientWidth / image.naturalWidth;
          box.scrollTop = Math.max(0, region[1] * scale - 70);
          box.scrollLeft = Math.max(0, region[0] * scale - box.clientWidth / 3);
        }
      }} src={evidence.image} alt={`${label}, página ${page}${evidence.highlighted ? ', cambio resaltado en amarillo' : ''}`} /></div>
    </>}
  </div>;
}
