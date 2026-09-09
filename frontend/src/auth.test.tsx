import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import App, { Login } from './App';
import { UsersPage } from './ManagementPages';
import { api, ApiError, post } from './api';
import type { Auth, AuthConfig } from './types';

vi.mock('./api', async importOriginal => ({ ...await importOriginal<typeof import('./api')>(), api: vi.fn(), post: vi.fn() }));
const apiMock = vi.mocked(api);
const postMock = vi.mocked(post);
const aitrol: AuthConfig = { provider: 'aitrol', password_management: 'aitrol' };
const authorized: Auth = { user: { id: 'synthetic-user', username: 'auditor@example.test', role: 'admin', organization_id: 'org2', auth_provider: 'aitrol', company_id: 'company2', company_name: 'Empresa sintética dos' }, csrf_token: 'test-csrf-not-a-real-token' };
const companyChoice = { requires_company: true as const, companies: [{ id: 'company1', name: 'Empresa sintética uno' }, { id: 'company2', name: 'Empresa sintética dos' }] };

beforeEach(() => { vi.clearAllMocks(); window.location.hash = ''; });
function enterAitrolCredentials() {
  fireEvent.change(screen.getByLabelText('Correo de Aitrol / Roboti'), { target: { value: 'auditor@example.test' } });
  fireEvent.change(screen.getByLabelText('Contraseña'), { target: { value: 'synthetic-password-for-test' } });
}

describe('Identidad Aitrol / Roboti', () => {
  it('requiere seleccionar empresa antes de iniciar sesión y reenvía las credenciales desde el formulario', async () => {
    const onLogin = vi.fn();
    const storageWrite = vi.spyOn(Storage.prototype, 'setItem');
    postMock.mockResolvedValueOnce(companyChoice).mockResolvedValueOnce(authorized);
    render(<Login config={aitrol} message="" onLogin={onLogin} />);
    expect(screen.getByLabelText('Correo de Aitrol / Roboti')).toHaveAttribute('maxlength', '254');
    enterAitrolCredentials();
    fireEvent.click(screen.getByRole('button', { name: /Ingresar al portal/ }));
    const companySelect = await screen.findByLabelText('Empresa');
    expect(onLogin).not.toHaveBeenCalled();
    expect(screen.getByText(/la sesión aún no está iniciada/)).toBeInTheDocument();
    expect(screen.getByLabelText('Contraseña')).toHaveValue('synthetic-password-for-test');
    expect(postMock).toHaveBeenNthCalledWith(1, '/auth/login', { username: 'auditor@example.test', password: 'synthetic-password-for-test' });
    fireEvent.change(companySelect, { target: { value: 'company2' } });
    fireEvent.click(screen.getByRole('button', { name: /Ingresar a la empresa/ }));
    await waitFor(() => expect(onLogin).toHaveBeenCalledWith(authorized));
    expect(postMock).toHaveBeenNthCalledWith(2, '/auth/login', { username: 'auditor@example.test', password: 'synthetic-password-for-test', company_id: 'company2' });
    expect(screen.getByLabelText('Contraseña')).toHaveValue('');
    expect(storageWrite).not.toHaveBeenCalled();
  });

  it('cambiar el correo elimina las empresas verificadas para la identidad anterior', async () => {
    postMock.mockResolvedValue(companyChoice);
    render(<Login config={aitrol} message="" onLogin={vi.fn()} />);
    enterAitrolCredentials();
    fireEvent.click(screen.getByRole('button', { name: /Ingresar al portal/ }));
    await screen.findByLabelText('Empresa');
    fireEvent.change(screen.getByLabelText('Correo de Aitrol / Roboti'), { target: { value: 'otra-cuenta@example.test' } });
    expect(screen.queryByLabelText('Empresa')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Ingresar al portal/ })).toBeEnabled();
  });

  it('una empresa única permite el Auth normal sin crear un selector ficticio', async () => {
    const onLogin = vi.fn(); postMock.mockResolvedValue(authorized);
    render(<Login config={aitrol} message="" onLogin={onLogin} />);
    enterAitrolCredentials();
    fireEvent.click(screen.getByRole('button', { name: /Ingresar al portal/ }));
    await waitFor(() => expect(onLogin).toHaveBeenCalledWith(authorized));
    expect(screen.queryByLabelText('Empresa')).not.toBeInTheDocument();
  });

  it('un rechazo de Aitrol no cambia silenciosamente al modo local', async () => {
    const onLogin = vi.fn(); postMock.mockRejectedValue(new ApiError('Credenciales no válidas.', 401));
    render(<Login config={aitrol} message="" onLogin={onLogin} />);
    enterAitrolCredentials();
    fireEvent.click(screen.getByRole('button', { name: /Ingresar al portal/ }));
    await screen.findByText('Credenciales no válidas.');
    expect(screen.getByLabelText('Correo de Aitrol / Roboti')).toBeInTheDocument();
    expect(onLogin).not.toHaveBeenCalled();
    expect(postMock).toHaveBeenCalledTimes(1);
  });

  it('mantiene el formulario de autenticación local cuando está configurado', async () => {
    const onLogin = vi.fn(); postMock.mockResolvedValue({ ...authorized, user: { ...authorized.user, auth_provider: 'local' } });
    render(<Login message="" onLogin={onLogin} />);
    expect(screen.getByLabelText('Usuario')).toHaveAttribute('maxlength', '120');
    fireEvent.change(screen.getByLabelText('Usuario'), { target: { value: 'auditor-local' } });
    fireEvent.change(screen.getByLabelText('Contraseña'), { target: { value: 'synthetic-local-password' } });
    fireEvent.click(screen.getByRole('button', { name: /Ingresar al portal/ }));
    await waitFor(() => expect(onLogin).toHaveBeenCalled());
    expect(postMock).toHaveBeenCalledWith('/auth/login', { username: 'auditor-local', password: 'synthetic-local-password' });
  });

  it('consulta auth/config público y muestra la empresa activa de la sesión', async () => {
    apiMock.mockImplementation(async path => {
      if (path === '/auth/config') return aitrol;
      if (path === '/auth/me') return authorized;
      return null;
    });
    render(<App />);
    await screen.findByTitle('Empresa seleccionada: Empresa sintética dos');
    expect(apiMock).toHaveBeenCalledWith('/auth/config');
    expect(screen.getByText('Empresa sintética dos')).toBeInTheDocument();
  });
});

describe('Usuarios administrados por Aitrol', () => {
  it('es solo consulta y no muestra creación ni contraseña inicial', async () => {
    apiMock.mockResolvedValue([authorized.user]);
    render(<UsersPage authConfig={aitrol} />);
    await screen.findByText('auditor@example.test');
    expect(screen.getByText('Consulta de usuarios sincronizados con Aitrol.')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Crear usuario' })).not.toBeInTheDocument();
    expect(screen.queryByLabelText('Contraseña inicial')).not.toBeInTheDocument();
    expect(postMock).not.toHaveBeenCalled();
  });

  it('conserva creación administrada para instalaciones locales', async () => {
    apiMock.mockResolvedValue([]);
    render(<UsersPage />);
    await waitFor(() => expect(screen.queryByText('Cargando información…')).not.toBeInTheDocument());
    expect(screen.getByRole('button', { name: 'Crear usuario' })).toBeInTheDocument();
    expect(screen.getByLabelText('Contraseña inicial')).toBeInTheDocument();
  });
});
