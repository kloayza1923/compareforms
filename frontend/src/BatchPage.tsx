import { useEffect, useRef, useState, type FormEvent } from 'react';
import { api, errorMessage, post, requestKey } from './api';
import { Busy, Empty, Icon, Notice, PageHeading, StateBadge, StepTitle } from './components';
import { canStartRun, requiresPartialScope } from './presentation';
import type { Batch, Capabilities, Inventory } from './types';

export function NewComparison({ capabilities }: { capabilities: Capabilities | null }) {
  const [manual, setManual] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault(); if (!manual) return;
    const fields = new FormData(event.currentTarget); setBusy(true); setError('');
    try {
      const batch = await post<Batch>('/batches', { name: fields.get('name'), period: String(fields.get('period')).replace('-', '_'), source_mode: 'manual', source_system: fields.get('source_system') });
      window.location.hash = `/batches/${batch.id}`;
    } catch (cause) { setError(errorMessage(cause)); } finally { setBusy(false); }
  };
  return <><PageHeading title="Nueva comparación">Reúne las dos versiones del expediente y revisa cada cambio con evidencia.</PageHeading>
    <div className="workflow-strip"><span className="current"><b>1</b> Preparar revisión</span><span><b>2</b> Cargar y asociar</span><span><b>3</b> Comparar y revisar</span><span><b>4</b> Descargar Excel</span></div>
    <div className="row g-4"><div className="col-xl-8"><form className="surface-card" onSubmit={submit}><StepTitle number={1} title="Datos de la revisión">Cada revisión conserva sus documentos, resultados y decisiones.</StepTitle>{error && <Notice tone="danger">{error}</Notice>}
      <div className="row g-3"><div className="col-md-4"><label className="form-label" htmlFor="period">Período de atención</label><input className="form-control" id="period" type="month" name="period" required /></div><div className="col-md-8"><label className="form-label" htmlFor="name">Nombre de la revisión</label><input className="form-control" id="name" name="name" placeholder="Ej.: Revisión de expedientes IESS · junio" required maxLength={150} /></div></div>
      <hr /><StepTitle number={2} title="¿Cómo obtendrás el documento de origen?" />
      <div className={`source-option ${!manual ? 'selected' : ''}`}><div className="source-symbol"><Icon name="document" /></div><div><strong>Generar mediante Roboti</strong><p>Integración reservada para una siguiente entrega.</p><span className="state-badge badge-neutral">No disponible en esta versión</span></div></div>
      {!manual && <Notice tone="warning">{capabilities?.roboti.reason || 'La generación automática requiere una integración autorizada con Roboti. Para continuar, selecciona la carga manual.'}</Notice>}
      <div className="form-check manual-check"><input className="form-check-input" id="manual-source" type="checkbox" checked={manual} onChange={event => setManual(event.target.checked)} /><label className="form-check-label" htmlFor="manual-source"><strong>Usar carga manual del origen en lugar de Roboti</strong><small>Subiré un ZIP con los PDF generados por DALIA u otra fuente.</small></label></div>
      {manual && <div className="manual-source-fields"><label className="form-label" htmlFor="source-system">Procedencia del original</label><select className="form-select" id="source-system" name="source_system" defaultValue="dalia"><option value="dalia">DALIA</option><option value="manual_otro">Otra fuente · carga manual</option></select><p className="form-text">Los cambios de un origen DALIA no se atribuirán automáticamente a Roboti.</p></div>}
      <div className="card-actions"><span>Los documentos se cargarán en el siguiente paso.</span><button className="btn btn-primary" type="submit" disabled={busy || !manual}>{busy ? 'Creando revisión…' : 'Crear revisión y cargar ZIP'} <Icon name="arrow" /></button></div>
    </form></div><aside className="col-xl-4"><div className="guide-card"><p className="eyebrow">ANTES DE COMENZAR</p><h2>Dos versiones.<br />Una revisión trazable.</h2><div className="guide-item"><span>01</span><div><strong>Original</strong><p>El documento producido por el sistema, previo a la edición de auditoría.</p></div></div><div className="guide-item"><span>02</span><div><strong>Modificado</strong><p>La versión ajustada por auditoría, que se usará como referencia documental.</p></div></div><div className="guide-item"><span>03</span><div><strong>Confirma al paciente</strong><p>El sistema sugiere asociaciones. Tú verificas paciente y atención antes de comparar.</p></div></div><div className="guide-note"><Icon name="shield" /> El PDF modificado no se considera una verdad clínica infalible.</div></div></aside></div>
  </>;
}

export function BatchPage({ batchId }: { batchId: string }) {
  const [batch, setBatch] = useState<Batch | null>(null);
  const [inventory, setInventory] = useState<Inventory | null>(null);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [allowPartial, setAllowPartial] = useState(false);
  const keyRef = useRef<string | null>(null);
  const mutationRef = useRef(false);
  const refresh = async () => { setInventory(await api<Inventory>(`/batches/${batchId}/inventory`)); };
  useEffect(() => {
    let alive = true;
    Promise.all([api<Batch[]>('/batches'), api<Inventory>(`/batches/${batchId}/inventory`)]).then(([batches, value]) => {
      if (alive) { setBatch(batches.find(item => item.id === batchId) || null); setInventory(value); }
    }).catch(cause => { if (alive) setError(errorMessage(cause)); }).finally(() => { if (alive) setLoading(false); });
    return () => { alive = false; };
  }, [batchId]);
  const mutate = async (action: () => Promise<unknown>, success = '') => {
    if (mutationRef.current) return;
    mutationRef.current = true; setBusy(true); setError(''); setNotice('');
    try { await action(); await refresh(); keyRef.current = null; setNotice(success); }
    catch (cause) { setError(errorMessage(cause)); } finally { mutationRef.current = false; setBusy(false); }
  };
  const upload = (side: string, file: File) => mutate(async () => {
    const data = new FormData(); data.append('file', file);
    await api(`/batches/${batchId}/uploads?side=${side}`, { method: 'POST', body: data });
  }, `ZIP ${side === 'original' ? 'de origen' : 'modificado'} recibido. Revisa el inventario y las asociaciones.`);
  const start = async () => {
    if (mutationRef.current || !canStartRun(inventory, allowPartial)) return;
    mutationRef.current = true; setBusy(true); setError('');
    // Reuse after a transport failure; do not create duplicate jobs on retry.
    keyRef.current ||= requestKey();
    try {
      const run = await post<{ id: string; status: string }>(`/batches/${batchId}/runs`, { allow_partial: allowPartial }, { 'Idempotency-Key': keyRef.current });
      window.location.hash = `/runs/${run.id}`;
    } catch (cause) { setError(errorMessage(cause)); } finally { mutationRef.current = false; setBusy(false); }
  };
  if (loading) return <Busy />;
  const confirmed = inventory?.pairs.filter(pair => pair.confirmed).length || 0;
  const names = new Map(inventory?.documents.map(doc => [doc.id, doc.original_name]));
  const available = inventory?.documents.filter(doc => !inventory.pairs.some(pair => pair.confirmed && [pair.original_id, pair.modified_id].includes(doc.id))) || [];
  return <><PageHeading title={batch?.name || 'Preparar expedientes'} action={<a className="btn btn-outline-secondary" href="#/history">Ver historial</a>}><span className="period-tag">{batch?.period.replace('_', ' / ')}</span> Fuente del original: {batch?.source_system === 'dalia' ? 'DALIA' : batch?.source_system === 'roboti' ? 'Roboti' : 'Carga manual'}. Verifica ambas versiones antes de iniciar.</PageHeading>
    {error && <Notice tone="danger">{error}</Notice>}{notice && <Notice tone="success">{notice}</Notice>}
    <section className="surface-card"><StepTitle number={1} title="Carga de documentos">Selecciona un ZIP por versión. Cada archivo aceptado o rechazado queda en el inventario.</StepTitle><div className="row g-4"><div className="col-md-6"><ZipDrop side="original" title="PDF de origen" subtitle="Documentos sin los ajustes de auditoría" disabled={busy || batch?.source_mode !== 'manual'} onUpload={file => upload('original', file)} /></div><div className="col-md-6"><ZipDrop side="modified" title="PDF modificado" subtitle="Documentos ajustados por auditoría" disabled={busy} onUpload={file => upload('modified', file)} /></div></div>{busy && <Busy text="Procesando solicitud. No cierres esta pantalla durante la carga del ZIP…" />}</section>
    <section className="surface-card mt-4"><StepTitle number={2} title="Asociación de expedientes">Confirma que cada pareja corresponde al mismo paciente y a la misma atención.</StepTitle>
      <div className="inventory-stats"><span><strong>{inventory?.documents.length || 0}</strong> PDF recibidos</span><span><strong>{confirmed}</strong> parejas confirmadas</span><span><strong>{inventory?.unpaired.length || 0}</strong> sin asociar</span><span><strong>{inventory?.rejections.length || 0}</strong> archivos rechazados / anexos</span></div>
      {!inventory?.pairs.length ? <Empty title="Todavía no hay parejas confirmadas">Carga ambos ZIP y revisa las sugerencias. Ningún archivo se interpretará como «sin diferencias» sin haber sido comparado.</Empty> : <div className="table-responsive"><table className="table audit-table"><thead><tr><th>Paciente</th><th>PDF de origen</th><th>PDF modificado</th><th>Estado</th><th>Acción</th></tr></thead><tbody>{inventory.pairs.map(pair => <tr key={pair.id}><td className="patient-cell">{pair.patient_name || 'Identidad por confirmar'}</td><td>{names.get(pair.original_id)}</td><td>{names.get(pair.modified_id)}</td><td><span className={`state-badge ${pair.confirmed ? 'badge-success' : 'badge-warning'}`}>{pair.confirmed ? 'Confirmada por auditor' : 'Sugerencia · verificar'}</span></td><td>{!pair.confirmed && <button className="btn btn-sm btn-primary me-2" disabled={busy} onClick={() => mutate(() => post(`/batches/${batchId}/pairs`, { original_id: pair.original_id, modified_id: pair.modified_id, patient_name: pair.patient_name }), 'Asociación confirmada.')}>Confirmar</button>}<button className="btn btn-sm btn-outline-secondary" disabled={busy} onClick={() => mutate(() => api(`/batches/${batchId}/pairs/${pair.id}`, { method: 'DELETE' }), 'Asociación retirada. Los PDF se conservan.')}>Desasociar</button></td></tr>)}</tbody></table></div>}
      {available.length > 0 && <details className="association-panel" open={!inventory?.pairs.length}><summary>Asociar manualmente o resolver nombres diferentes</summary><form className="row g-3 mt-1" onSubmit={event => {
        event.preventDefault(); const fields = new FormData(event.currentTarget);
        void mutate(() => post(`/batches/${batchId}/pairs`, { original_id: fields.get('original_id'), modified_id: fields.get('modified_id'), patient_name: String(fields.get('patient_name')).trim() }), 'Asociación manual confirmada.');
      }}><div className="col-md-6"><label className="form-label" htmlFor="pair-original">Archivo de origen</label><select className="form-select" id="pair-original" name="original_id" required defaultValue=""><option value="" disabled>Seleccionar original</option>{available.filter(doc => doc.side === 'original').map(doc => <option key={doc.id} value={doc.id}>{doc.original_name}</option>)}</select></div><div className="col-md-6"><label className="form-label" htmlFor="pair-modified">Archivo modificado</label><select className="form-select" id="pair-modified" name="modified_id" required defaultValue=""><option value="" disabled>Seleccionar modificado</option>{available.filter(doc => doc.side === 'modified').map(doc => <option key={doc.id} value={doc.id}>{doc.original_name}</option>)}</select></div><div className="col-md-8"><label className="form-label" htmlFor="pair-patient">Nombre del paciente verificado</label><input className="form-control" id="pair-patient" name="patient_name" maxLength={200} required placeholder="Apellidos y nombres" /></div><div className="col-md-4 d-flex align-items-end"><button className="btn btn-outline-primary w-100" disabled={busy}>Confirmar esta pareja</button></div><p className="form-text">El nombre del archivo y su prefijo no demuestran identidad. Abre los documentos desde el inventario y comprueba la atención.</p></form></details>}
      {!!inventory?.documents.length && <details className="mt-3"><summary>Ver inventario completo de PDF</summary><div className="table-responsive mt-3"><table className="table audit-table"><thead><tr><th>Paciente sugerido</th><th>Versión</th><th>Archivo</th></tr></thead><tbody>{inventory.documents.map(doc => <tr key={doc.id}><td>{doc.patient_name || 'Por verificar'}</td><td>{doc.side === 'original' ? 'Origen' : 'Modificado'}</td><td><a href={`/api/v1/documents/${encodeURIComponent(doc.id)}/content`} target="_blank" rel="noopener noreferrer">{doc.original_name}</a></td></tr>)}</tbody></table></div></details>}
      {!!inventory?.rejections.length && <div className="mt-4"><h3 className="small-heading">Archivos no incorporados a la comparación</h3><ul className="rejection-list">{inventory.rejections.map((item, index) => <li key={`${item.name}-${index}`}><strong>{item.name}</strong><span>{item.reason}</span></li>)}</ul></div>}
    </section>
    <section className="start-panel mt-4"><div><h2>¿Listo para comparar?</h2><p>{confirmed ? `${confirmed} expediente(s) confirmado(s). El análisis continúa aunque cierres el navegador después de iniciar.` : 'Sin comparación: necesitas al menos una pareja confirmada.'}</p>{requiresPartialScope(inventory) && <div className="form-check"><input className="form-check-input" type="checkbox" id="partial" checked={allowPartial} onChange={event => { setAllowPartial(event.target.checked); keyRef.current = null; }} /><label className="form-check-label" htmlFor="partial">Acepto comparar solo las parejas confirmadas, excluyendo archivos faltantes o rechazados. El alcance parcial se registrará en el informe.</label></div>}</div><button className="btn btn-primary btn-lg" disabled={busy || !canStartRun(inventory, allowPartial)} onClick={start}>Comparar expedientes <Icon name="arrow" /></button></section>
  </>;
}

function ZipDrop({ side, title, subtitle, disabled, onUpload }: { side: string; title: string; subtitle: string; disabled: boolean; onUpload: (file: File) => Promise<void> }) {
  const [dragging, setDragging] = useState(false);
  const [filename, setFilename] = useState('');
  const [error, setError] = useState('');
  const input = useRef<HTMLInputElement>(null);
  const choose = (file?: File) => {
    if (!file || disabled) return;
    if (!/\.zip$/i.test(file.name)) { setError('Selecciona un archivo con extensión .zip.'); return; }
    setError(''); setFilename(file.name); void onUpload(file);
  };
  return <div className={`zip-drop ${dragging ? 'dragging' : ''} ${disabled ? 'disabled' : ''}`} onDragOver={event => { event.preventDefault(); if (!disabled) setDragging(true); }} onDragLeave={() => setDragging(false)} onDrop={event => { event.preventDefault(); setDragging(false); if (event.dataTransfer.files.length !== 1) { setError('Carga un ZIP por vez.'); return; } choose(event.dataTransfer.files[0]); }}>
    <span className={`upload-icon upload-${side}`}><Icon name="upload" size={26} /></span><h3>{title}</h3><p>{subtitle}</p><button type="button" className="btn btn-outline-primary" onClick={() => input.current?.click()} disabled={disabled}>Seleccionar ZIP</button><input type="file" accept=".zip,application/zip" ref={input} aria-label={`ZIP ${title}`} hidden disabled={disabled} onChange={event => { choose(event.target.files?.[0]); event.target.value = ''; }} /><small>{filename ? `Último seleccionado: ${filename}` : 'También puedes arrastrarlo aquí'}</small>{error && <p className="text-danger mt-2" role="alert">{error}</p>}
  </div>;
}
