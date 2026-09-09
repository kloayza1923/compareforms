import { useEffect, useState, type FormEvent } from 'react';
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
  const [refresh, setRefresh] = useState(0);
  useEffect(() => {
    let alive = true; let timer: ReturnType<typeof setTimeout>;
    const load = async () => {
      try {
        const value = await api<Run>(`/runs/${runId}`);
        if (!alive) return; setRun(value); setError('');
        setSelectedCase(previous => previous || value.cases[0]?.id || '');
        if (['queued', 'running'].includes(value.status)) timer = setTimeout(load, 3000);
      } catch (cause) { if (alive) { setError(errorMessage(cause)); timer = setTimeout(load, 10000); } }
    };
    void load(); return () => { alive = false; clearTimeout(timer); };
  }, [runId, refresh]);
  const current = run?.cases.find(item => item.id === selectedCase);
  const cases = run?.cases.filter(item => item.patient_name.toLocaleLowerCase('es').includes(patientSearch.toLocaleLowerCase('es'))) || [];
  const active = run && ['queued', 'running'].includes(run.status);
  return <><PageHeading title="Revisión de resultados" action={<div className="d-flex gap-2 flex-wrap"><a href="#/history" className="btn btn-outline-secondary">Historial</a>{run?.report_available && <a href={reportUrl(run.id)} className="btn btn-primary"><Icon name="download" /> Descargar Excel</a>}</div>}>Primero identifica al paciente; después revisa el tipo de cambio y su ubicación en ambos PDF.</PageHeading>
    {run?.report_available && <Notice>{excelSnapshotNotice}</Notice>}
    {error && <Notice tone="danger">No se pudo actualizar el progreso: {error}. Los trabajos ya iniciados continúan en el servidor.</Notice>}
    {!run ? <Busy /> : <>
      <section className="run-overview"><div><span className="eyebrow">EJECUCIÓN {run.id.slice(0, 8)}</span><div className="run-state"><StateBadge status={run.status} /><span>{run.completed} de {run.total} expedientes procesados</span></div></div><div className="run-progress"><div className="progress" role="progressbar" aria-label="Expedientes procesados" aria-valuenow={percentage(run.completed, run.total)} aria-valuemin={0} aria-valuemax={100}><div className={`progress-bar ${active ? 'progress-bar-striped progress-bar-animated' : ''}`} style={{ width: `${percentage(run.completed, run.total)}%` }} /></div><small>{active ? 'Puedes cerrar el navegador. El análisis continuará.' : 'Consulta el estado de cada expediente; un resultado parcial no permite concluir ausencia de diferencias.'}</small></div></section>
      {run.total === 0 && <Notice tone="danger">Sin comparación: esta ejecución no tiene expedientes. No puede interpretarse como «sin diferencias».</Notice>}
      {run.error && <Notice tone="danger">{run.error}</Notice>}
      {run.status === 'partial' && <Notice tone="warning">Resultado parcial / no concluyente. Revisa los expedientes pendientes, errores y limitaciones antes de usar el informe.</Notice>}
      <div className="review-layout"><aside className="patient-selector surface-card"><h2>Pacientes <span>{run.cases.length}</span></h2><label className="visually-hidden" htmlFor="patient-search">Buscar paciente</label><input className="form-control mb-3" id="patient-search" type="search" placeholder="Buscar paciente…" value={patientSearch} onChange={event => setPatientSearch(event.target.value)} />{cases.map(item => <button key={item.id} className={`patient-button ${item.id === selectedCase ? 'selected' : ''}`} aria-pressed={item.id === selectedCase} onClick={() => setSelectedCase(item.id)}><strong>{item.patient_name || 'Paciente sin identificar'}</strong><StateBadge status={caseStatus(item)} /><small>{item.comparison ? `${allFindings(item).length} observaciones` : 'Comparación pendiente'}</small></button>)}{!cases.length && <p className="text-secondary small">No hay pacientes para mostrar.</p>}</aside>
        <div className="review-content">{current ? <CaseReview key={current.id} runId={run.id} caseItem={current} refresh={() => setRefresh(value => value + 1)} /> : <Empty title="Selecciona un paciente">La identificación y la evidencia se mostrarán aquí.</Empty>}</div></div>
    </>}</>;
}

function CaseReview({ runId, caseItem, refresh }: { runId: string; caseItem: Case; refresh: () => void }) {
  const comparison = caseItem.comparison;
  const countsDetermined = pageCountsDetermined(comparison, caseItem.status);
  const [filter, setFilter] = useState('all');
  const [findingId, setFindingId] = useState('');
  const [showManual, setShowManual] = useState(false);
  const findings = allFindings(caseItem);
  const visible = findings.filter(finding => filter === 'all' || finding.change_type === filter);
  const selected = findings.find(finding => finding.id === findingId);
  return <><section className="surface-card patient-detail"><p className="eyebrow">PACIENTE / EXPEDIENTE</p><h2 className="patient-name">{caseItem.patient_name || 'Identidad pendiente de verificación'}</h2><div className="patient-detail-actions"><StateBadge status={caseStatus(caseItem)} /><a href={documentUrl(caseItem.original_id)} target="_blank" rel="noopener noreferrer">Abrir PDF de origen ↗</a><a href={documentUrl(caseItem.modified_id)} target="_blank" rel="noopener noreferrer">Abrir PDF modificado ↗</a></div>
    {comparison ? <><div className="page-metrics"><div><span>Origen</span><strong>{comparison.pages_original}<small> páginas</small></strong></div><div><span>Modificado</span><strong>{comparison.pages_modified}<small> páginas</small></strong></div><div><span>Incorporadas</span><strong className={countsDetermined ? undefined : 'fs-6'}>{countsDetermined ? `+${comparison.pages_added}` : 'Sin determinar'}</strong></div><div><span>Retiradas</span><strong className={countsDetermined ? undefined : 'fs-6'}>{countsDetermined ? `−${comparison.pages_removed}` : 'Sin determinar'}</strong></div><div><span>Reubicadas</span><strong className={countsDetermined ? undefined : 'fs-6'}>{countsDetermined ? comparison.pages_relocated : 'Sin determinar'}</strong></div></div>{!countsDetermined && <Notice tone="warning"><strong>Correspondencia automática pendiente de confirmar.</strong> Los conteos de páginas incorporadas, retiradas y reubicadas no están determinados de forma concluyente. Los números de origen y modificado indican únicamente sus páginas físicas; revisa el mapa y las limitaciones.</Notice>}{comparison.limitations.length > 0 && <Notice tone="warning"><strong>Limitaciones de la revisión</strong><ul className="mb-0 mt-2">{comparison.limitations.map((text, index) => <li key={index}>{text}</li>)}</ul></Notice>}
      <div className="section-toolbar mt-4"><div><h3 className="small-heading mb-1">Observaciones documentales</h3><span className="text-secondary small">{visible.length} de {findings.length} · Páginas físicas del visor PDF</span></div><div className="d-flex gap-2 flex-wrap"><label><span className="visually-hidden">Filtrar por tipo de cambio</span><select className="form-select form-select-sm" aria-label="Filtrar por tipo de cambio" value={filter} onChange={event => setFilter(event.target.value)}><option value="all">Todos los tipos de cambio</option>{Object.entries(changeLabels).map(([type, label]) => <option key={type} value={type}>{label}</option>)}</select></label><button className="btn btn-sm btn-outline-primary" onClick={() => setShowManual(value => !value)}><Icon name="plus" size={15} /> Añadir observación</button></div></div>
      {!visible.length ? <Empty title={findings.length ? 'No hay observaciones de este tipo' : comparison.status === 'no_differences_detected' ? 'Sin diferencias detectadas' : 'No hay hallazgos concluyentes'}>{comparison.status === 'inconclusive' ? 'No se puede concluir igualdad. Revisa las limitaciones y la documentación.' : 'Puedes registrar una diferencia omitida por el sistema con sus páginas y evidencia.'}</Empty> : <div className="table-responsive"><table className="table audit-table findings-table"><thead><tr><th>Paciente</th><th>Tipo</th><th>Observación</th><th>Antes · origen</th><th>Después · modificado</th><th>Página origen</th><th>Página modificado</th><th>Revisión</th></tr></thead><tbody>{visible.map(finding => <tr key={finding.id} className={selected?.id === finding.id ? 'selected-row' : ''}><td className="patient-cell">{caseItem.patient_name}</td><td><ChangeBadge type={finding.change_type} /></td><td><strong className="finding-category">{finding.category}</strong><div className="evidence-text">{finding.description}</div></td><td className="evidence-text before-cell">{finding.before || 'No corresponde'}</td><td className="evidence-text after-cell">{finding.after || 'No corresponde'}</td><td><PageLink documentId={caseItem.original_id} page={finding.page_original} /></td><td><PageLink documentId={caseItem.modified_id} page={finding.page_modified} /></td><td><button className="btn btn-sm btn-outline-primary" onClick={() => setFindingId(finding.id)}>Ver evidencia</button>{finding.review_required && <small className="d-block mt-2 text-warning-emphasis">Requiere revisión</small>}</td></tr>)}</tbody></table></div>}
      <details className="page-map mt-3"><summary>Guía de correspondencia de páginas</summary><p className="form-text mt-2">La correspondencia es automática. Una página retirada confirmada no tiene página equivalente en el modificado; una incorporada confirmada no tiene página de origen. Las candidatas marcadas por revisar no confirman incorporación ni retiro.</p><div className="table-responsive"><table className="table audit-table"><thead><tr><th>Paciente</th><th>Página origen</th><th>Página modificado</th><th>Correspondencia</th></tr></thead><tbody>{comparison.page_map.map((match, index) => <tr key={index}><td>{caseItem.patient_name}</td><td><PageLink documentId={caseItem.original_id} page={match.page_original} /></td><td><PageLink documentId={caseItem.modified_id} page={match.page_modified} /></td><td>{match.review_required ? 'Correspondencia pendiente de confirmar' : changeLabels[match.status as ChangeType] || ({ matched: 'Asociada automáticamente', identical: 'Idéntica', unchanged: 'Sin cambios detectados', ambiguous: 'Asociación por revisar' }[match.status] || match.status)}</td></tr>)}</tbody></table></div></details>
      <p className="method-note">Motor {comparison.engine_version}. El mínimo error busca reducir omisiones, falsas alertas y asociaciones incorrectas; no minimizar la cantidad de diferencias.</p>
    </> : <Notice>Este expediente todavía no tiene una comparación disponible. Su estado no implica que los documentos sean iguales.</Notice>}
  </section>{(caseItem.reviews?.length || 0) > 0 && <section className="surface-card mt-4"><h2>Historial de revisión del auditor</h2><p className="form-text">Paciente: {caseItem.patient_name}. Las decisiones se conservan; no sustituyen ni borran el resultado original.</p>{caseItem.reviews!.map((review, index) => <article className="persisted-review" key={review.id}><div><span className="state-badge badge-neutral">{reviewLabels[review.decision]}</span><small>Registro {index + 1}</small><button className="btn btn-sm btn-outline-primary" onClick={() => setFindingId(review.finding_id)}>Ver evidencia asociada</button></div><p className="evidence-text">{review.comment || 'Sin comentario registrado.'}</p></article>)}</section>}{showManual && <ManualFinding runId={runId} caseItem={caseItem} onSaved={() => { setShowManual(false); refresh(); }} />}{selected && <EvidenceReview key={selected.id} runId={runId} caseItem={caseItem} finding={selected} onClose={() => setFindingId('')} onSaved={refresh} />}</>;
}

export function PageLink({ documentId, page }: { documentId: string; page?: number | null }) {
  return page && page > 0 ? <a className="page-link-inline" href={documentUrl(documentId, page)} target="_blank" rel="noopener noreferrer">{pageLabel(page)} ↗</a> : <span className="not-applicable">No corresponde</span>;
}

function EvidenceReview({ runId, caseItem, finding, onClose, onSaved }: { runId: string; caseItem: Case; finding: Finding; onClose: () => void; onSaved: () => void }) {
  const [error, setError] = useState('');
  const [message, setMessage] = useState('');
  const [busy, setBusy] = useState(false);
  const [proposal, setProposal] = useState(false);
  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault(); const fields = new FormData(event.currentTarget); setBusy(true); setError(''); setMessage('');
    try {
      if (proposal) await post('/improvements', { run_id: runId, case_id: caseItem.id, finding_id: finding.id, description: fields.get('description'), expected_benefit: fields.get('expected_benefit') });
      else await post(`/runs/${runId}/cases/${caseItem.id}/reviews`, { finding_id: finding.id, decision: fields.get('decision'), comment: fields.get('comment') });
      setMessage(proposal ? 'Propuesta registrada para análisis técnico. No se aplicó ningún cambio a Roboti.' : 'Revisión guardada en el historial. El resultado automático original se conserva.');
      onSaved();
    } catch (cause) { setError(errorMessage(cause)); } finally { setBusy(false); }
  };
  return <section className="surface-card evidence-panel mt-4"><div className="section-toolbar"><div><p className="eyebrow">EVIDENCIA SELECCIONADA</p><h2>{caseItem.patient_name}</h2></div><button className="btn btn-sm btn-outline-secondary" onClick={onClose}>Cerrar evidencia</button></div><ChangeBadge type={finding.change_type} /><p className="mt-3 evidence-text">{finding.description}</p>
    <div className="row g-3"><div className="col-lg-6"><PdfEvidence label="Origen · antes" documentId={caseItem.original_id} page={finding.page_original} content={finding.before} /></div><div className="col-lg-6"><PdfEvidence label="Modificado · después" documentId={caseItem.modified_id} page={finding.page_modified} content={finding.after} /></div></div>
    <p className="form-text mt-3">Los números corresponden a la página física del PDF. El visor del navegador puede no destacar la región; usa «Abrir página» para ampliar. La diferencia visual no acredita autenticidad de una firma.</p>
    <div className="review-form"><div className="d-flex gap-2 mb-3"><button className={`btn btn-sm ${!proposal ? 'btn-primary' : 'btn-outline-secondary'}`} onClick={() => setProposal(false)}>Revisar observación</button><button className={`btn btn-sm ${proposal ? 'btn-primary' : 'btn-outline-secondary'}`} onClick={() => setProposal(true)}>Proponer mejora</button></div>{error && <Notice tone="danger">{error}</Notice>}{message && <Notice tone="success">{message}</Notice>}
      <form onSubmit={submit}>{proposal ? <><label className="form-label" htmlFor={`proposal-${finding.id}`}>Problema documental y cambio propuesto</label><textarea className="form-control" id={`proposal-${finding.id}`} name="description" rows={3} required maxLength={4000} defaultValue={finding.description} /><label className="form-label mt-3" htmlFor={`benefit-${finding.id}`}>¿Qué mejoraría y cómo se comprobaría?</label><textarea className="form-control" id={`benefit-${finding.id}`} name="expected_benefit" rows={3} maxLength={4000} required /><p className="form-text">La propuesta no confirma la causa. Un expediente de origen DALIA no demuestra un defecto de Roboti.</p></> : <><label className="form-label" htmlFor={`decision-${finding.id}`}>Decisión del auditor</label><select className="form-select" id={`decision-${finding.id}`} name="decision" defaultValue="needs_review"><option value="needs_review">Solicitar revisión / evidencia insuficiente</option><option value="confirmed">Confirmar observación</option><option value="false_positive">Falso positivo</option></select><label className="form-label mt-3" htmlFor={`comment-${finding.id}`}>Fundamento de la revisión</label><textarea className="form-control" id={`comment-${finding.id}`} name="comment" rows={3} required maxLength={4000} placeholder="Explica lo verificado en los documentos y las páginas consultadas." /></>}
      <button className="btn btn-primary mt-3" disabled={busy}>{busy ? 'Guardando…' : proposal ? 'Registrar propuesta sin aplicar cambios' : 'Guardar revisión'}</button></form>
    </div></section>;
}

function PdfEvidence({ label, documentId, page, content }: { label: string; documentId: string; page: number | null; content: string }) {
  return <div className="pdf-evidence"><header><strong>{label}</strong>{page ? <a href={documentUrl(documentId, page)} target="_blank" rel="noopener noreferrer">Abrir página {page} ↗</a> : <span>No corresponde</span>}</header><div className="pdf-excerpt evidence-text">{content || 'Sin contenido correspondiente en esta versión.'}</div>{page ? <iframe key={`${documentId}-${page}`} title={`${label}, página ${page}`} src={documentUrl(documentId, page)} loading="lazy" /> : <div className="no-page">No hay una página equivalente en esta versión del documento.</div>}</div>;
}

function ManualFinding({ runId, caseItem, onSaved }: { runId: string; caseItem: Case; onSaved: () => void }) {
  const [error, setError] = useState(''); const [busy, setBusy] = useState(false);
  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault(); const fields = new FormData(event.currentTarget);
    const original = fields.get('page_original'); const modified = fields.get('page_modified');
    if (!original && !modified) { setError('Indica al menos una página como evidencia de la observación.'); return; }
    if (['modified', 'relocated'].includes(String(fields.get('change_type'))) && (!original || !modified)) { setError('Un cambio o una reubicación necesita la página correspondiente en ambas versiones.'); return; }
    if (!String(fields.get('before') || '').trim() && !String(fields.get('after') || '').trim()) { setError('Registra el contenido antes o después para respaldar la observación.'); return; }
    setBusy(true); setError('');
    try { await post(`/runs/${runId}/cases/${caseItem.id}/findings`, { description: fields.get('description'), before: fields.get('before'), after: fields.get('after'), page_original: original ? Number(original) : null, page_modified: modified ? Number(modified) : null, change_type: fields.get('change_type') }); onSaved(); }
    catch (cause) { setError(errorMessage(cause)); } finally { setBusy(false); }
  };
  return <section className="surface-card mt-4"><h2>Añadir diferencia no detectada</h2><p className="text-secondary">Paciente: <strong>{caseItem.patient_name}</strong>. Se registrará como hallazgo manual del auditor, no del motor automático.</p>{error && <Notice tone="danger">{error}</Notice>}<form onSubmit={submit}><label className="form-label" htmlFor="manual-type">Tipo de cambio</label><select className="form-select mb-3" id="manual-type" name="change_type" defaultValue="modified">{Object.entries(changeLabels).map(([key, label]) => <option value={key} key={key}>{label}</option>)}</select><label className="form-label" htmlFor="manual-description">Descripción documental</label><textarea className="form-control mb-3" id="manual-description" name="description" required maxLength={4000} rows={3} /><div className="row g-3"><div className="col-md-6"><label className="form-label" htmlFor="manual-before">Antes · origen</label><textarea className="form-control" id="manual-before" name="before" rows={3} maxLength={8000} /><label className="form-label mt-3" htmlFor="manual-original-page">Página de origen</label><input className="form-control" id="manual-original-page" name="page_original" type="number" min={1} max={caseItem.comparison?.pages_original} step={1} /></div><div className="col-md-6"><label className="form-label" htmlFor="manual-after">Después · modificado</label><textarea className="form-control" id="manual-after" name="after" rows={3} maxLength={8000} /><label className="form-label mt-3" htmlFor="manual-modified-page">Página del modificado</label><input className="form-control" id="manual-modified-page" name="page_modified" type="number" min={1} max={caseItem.comparison?.pages_modified} step={1} /></div></div><p className="form-text">Deja vacía la página que no corresponde. No escribas «0» para una página inexistente.</p><button className="btn btn-primary" disabled={busy}>{busy ? 'Guardando…' : 'Registrar observación manual'}</button></form></section>;
}
