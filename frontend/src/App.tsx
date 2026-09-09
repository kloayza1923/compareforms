import { useEffect, useState, type FormEvent } from 'react';
import { api, ApiError, errorMessage, post, setCsrfToken } from './api';
import type { Auth, AuthConfig, Capabilities, Company, LoginResult } from './types';
import { Busy, Icon, Notice, PageHeading } from './components';
import { BatchPage, NewComparison } from './BatchPage';
import { HistoryPage, RunPage } from './RunPage';
import { ImprovementsPage, ModelsPage, UsersPage } from './ManagementPages';

const getRoute = () => (window.location.hash.replace(/^#\/?/, '') || 'new').split('/');
export default function App() {
  const [auth, setAuth] = useState<Auth | null>(null);
  const [booting, setBooting] = useState(true);
  const [bootError, setBootError] = useState('');
  const [route, setRoute] = useState(getRoute);
  const [capabilities, setCapabilities] = useState<Capabilities | null>(null);
  const [authConfig, setAuthConfig] = useState<AuthConfig>({ provider: 'local', password_management: 'local' });
  useEffect(() => {
    let alive = true;
    const configuration = api<AuthConfig>('/auth/config').then(value => { if (alive) setAuthConfig(value); }).catch(error => {
      // Compatibility with earlier local-only installations; never change providers after a login failure.
      if (alive && !(error instanceof ApiError && error.status === 404)) setBootError(errorMessage(error));
    });
    const session = api<Auth>('/auth/me').then(value => { if (alive) { setCsrfToken(value.csrf_token); setAuth(value); } }).catch(error => {
      if (alive && !(error instanceof ApiError && error.status === 401)) setBootError(errorMessage(error));
    });
    Promise.all([configuration, session]).finally(() => { if (alive) setBooting(false); });
    const change = () => setRoute(getRoute());
    const expired = () => { setCsrfToken(''); setAuth(null); setBootError('Tu sesión venció. Ingresa nuevamente para continuar.'); };
    window.addEventListener('hashchange', change);
    window.addEventListener('session-expired', expired);
    return () => { alive = false; window.removeEventListener('hashchange', change); window.removeEventListener('session-expired', expired); };
  }, []);
  useEffect(() => {
    let alive = true;
    if (auth) api<Capabilities>('/capabilities').then(value => { if (alive) setCapabilities(value); }).catch(() => { if (alive) setCapabilities(null); });
    return () => { alive = false; };
  }, [auth]);
  if (booting) return <div className="boot-screen"><Busy text="Conectando con CompareForms…" /></div>;
  if (!auth) return <Login message={bootError} config={authConfig} onLogin={value => { setCsrfToken(value.csrf_token); setAuth(value); setBootError(''); }} />;
  const section = route[0];
  const menu = [
    { id: 'new', label: 'Nueva comparación', icon: 'plus' },
    { id: 'history', label: 'Historial', icon: 'history' },
    { id: 'improvements', label: 'Mejoras de Roboti', icon: 'shield' },
    ...(auth.user.role === 'admin' ? [{ id: 'users', label: 'Usuarios y permisos', icon: 'users' }] : []),
    ...(auth.user.role !== 'auditor' ? [{ id: 'models', label: 'Modelos · futuro', icon: 'model' }] : []),
  ];
  const logout = async () => { try { await post('/auth/logout', {}); setCsrfToken(''); setAuth(null); setCapabilities(null); } catch (error) { setBootError(errorMessage(error)); } };
  return <div className="portal-shell">
    <a className="skip-link" href="#main-content" onClick={event => { event.preventDefault(); document.getElementById('main-content')?.focus(); }}>Saltar al contenido</a>
    <aside className="sidebar">
      <a className="brand" href="#/new"><span className="brand-mark"><Icon name="document" size={25} /></span><span>Compare<span className="brand-light">Forms</span><small>CONTROL DOCUMENTAL</small></span></a>
      <div className="workspace-label">ESPACIO DE AUDITORÍA</div>
      <nav aria-label="Menú principal">{menu.map(item => <a href={`#/${item.id}`} key={item.id} aria-current={section === item.id || (item.id === 'history' && section === 'runs') || (item.id === 'new' && section === 'batches') ? 'page' : undefined}><Icon name={item.icon} /><span>{item.label}</span></a>)}</nav>
      <div className="sidebar-bottom"><div className="privacy-note"><Icon name="shield" /><div>Documentación privada<small>Acceso por organización</small></div></div><div className="user-row"><span className="avatar">{auth.user.username.slice(0, 2).toUpperCase()}</span><div className="user-description"><strong>{auth.user.username}</strong><small>{{ admin: 'Administrador', auditor: 'Auditor', supervisor: 'Supervisor' }[auth.user.role]}</small></div></div><button className="signout" onClick={logout}>Cerrar sesión</button></div>
    </aside>
    <div className="workspace"><div className="topbar"><span><span className="online-dot" /> Portal de auditoría médica{auth.user.company_name && <strong className="active-company" title={`Empresa seleccionada: ${auth.user.company_name}`}>{auth.user.company_name}</strong>}</span><span className="topbar-method">Motor A · mínimo error</span><button className="mobile-signout" onClick={logout}>Cerrar sesión</button></div>
      <main id="main-content" tabIndex={-1}>{bootError && <Notice tone="danger">{bootError}</Notice>}
        {section === 'new' && <NewComparison capabilities={capabilities} />}
        {section === 'batches' && route[1] && <BatchPage key={route[1]} batchId={route[1]} />}
        {section === 'history' && <HistoryPage />}
        {section === 'runs' && route[1] && <RunPage key={route[1]} runId={route[1]} initialCaseId={route[2]} />}
        {section === 'improvements' && <ImprovementsPage />}
        {section === 'users' && (auth.user.role === 'admin' ? <UsersPage authConfig={authConfig} authProvider={auth.user.auth_provider} /> : <Notice tone="warning">Esta sección requiere permiso de administrador.</Notice>)}
        {section === 'models' && (auth.user.role !== 'auditor' ? <ModelsPage capabilities={capabilities} /> : <Notice tone="warning">Esta sección está reservada a supervisión.</Notice>)}
        {!['new', 'batches', 'history', 'runs', 'improvements', 'users', 'models'].includes(section) && <PageHeading title="Página no encontrada">Regresa a Nueva comparación o al Historial.</PageHeading>}
      </main><footer className="workspace-footer">CompareForms · La comparación documental apoya la revisión; no constituye un dictamen clínico.</footer>
    </div>
  </div>;
}

export function Login({ onLogin, message, config = { provider: 'local', password_management: 'local' } }: { onLogin: (value: Auth) => void; message: string; config?: AuthConfig }) {
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [companies, setCompanies] = useState<Company[]>([]);
  const external = config.provider === 'aitrol';
  const resetCompanies = () => { setCompanies([]); setError(''); };
  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault(); if (busy) return;
    const form = event.currentTarget;
    // Read credentials directly from the form only for this request. Never retain the password in React state or storage.
    const fields = new FormData(form);
    const companyId = fields.get('company_id');
    if (companies.length && !companies.some(company => company.id === companyId)) { setError('Selecciona una empresa autorizada para continuar.'); return; }
    setBusy(true); setError('');
    try {
      const result = await post<LoginResult>('/auth/login', {
        username: fields.get('username'), password: fields.get('password'),
        ...(companies.length ? { company_id: companyId } : {}),
      });
      if ('requires_company' in result) {
        setCompanies(result.companies);
        if (!result.companies.length) setError('Esta cuenta no tiene empresas autorizadas disponibles. Consulta al administrador de Aitrol.');
      } else {
        form.reset(); setCompanies([]); onLogin(result);
      }
    }
    catch (cause) { setError(errorMessage(cause)); } finally { setBusy(false); }
  };
  return <div className="login-layout"><section className="login-story"><div className="brand"><span className="brand-mark"><Icon size={27} /></span>CompareForms</div><div><p className="eyebrow">TRAZABILIDAD PARA CADA EXPEDIENTE</p><h1>La evidencia,<br />en el lugar correcto.</h1><p>Compara documentos, localiza los cambios y transforma la revisión del auditor en mejoras verificables.</p><div className="login-points"><span><Icon name="check" /> Identidad del paciente primero</span><span><Icon name="check" /> Evidencia en ambos documentos</span><span><Icon name="check" /> Excel listo para revisión</span></div></div><small>Acceso institucional · Documentación médica privada</small></section>
      <section className="login-form-area"><form onSubmit={submit} className="login-card"><span className="login-lock"><Icon name="shield" size={26} /></span><h2>Bienvenido a CompareForms</h2><p>{external ? 'Usa el mismo correo y contraseña que en Roboti / Aitrol.' : 'Ingresa con tu usuario autorizado para continuar.'}</p>{(error || message) && <Notice tone="danger">{error || message}</Notice>}<label className="form-label" htmlFor="username">{external ? 'Correo de Aitrol / Roboti' : 'Usuario'}</label><input className="form-control form-control-lg" id="username" name="username" type={external ? 'email' : 'text'} autoComplete="username" required maxLength={external ? 254 : 120} readOnly={busy} onChange={resetCompanies} /><label className="form-label mt-4" htmlFor="password">Contraseña</label><input className="form-control form-control-lg" id="password" name="password" type="password" autoComplete="current-password" required readOnly={busy} onChange={resetCompanies} />{companies.length > 0 && <div className="company-selection mt-4"><Notice>Credenciales verificadas. Selecciona la empresa con la que trabajarás; la sesión aún no está iniciada.</Notice><label className="form-label" htmlFor="company-id">Empresa</label><select className="form-select form-select-lg" id="company-id" name="company_id" required defaultValue="" disabled={busy}><option value="" disabled>Seleccionar empresa autorizada</option>{companies.map(company => <option key={company.id} value={company.id}>{company.name}</option>)}</select></div>}<button className="btn btn-primary btn-lg w-100 mt-4" disabled={busy}>{busy ? 'Verificando acceso…' : companies.length ? 'Ingresar a la empresa' : 'Ingresar al portal'} <Icon name="arrow" /></button><p className="login-help">{external ? 'Los usuarios y las contraseñas se administran en Aitrol. Para recuperar tu acceso, contacta a su administrador.' : '¿Necesitas acceso? Solicita una cuenta al administrador de tu organización.'}</p></form></section></div>;
}
