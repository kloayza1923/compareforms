import { afterEach, describe, expect, it, vi } from 'vitest';
import { api, ApiError, post, setCsrfToken } from './api';

afterEach(() => { setCsrfToken(''); vi.unstubAllGlobals(); });
describe('Sesión y errores API', () => {
  it('envía cookie mismo origen y CSRF solo por cabecera en mutaciones', async () => {
    const fetcher = vi.fn().mockResolvedValue(new Response(JSON.stringify({ id: 'new' }), { status: 201 }));
    vi.stubGlobal('fetch', fetcher); setCsrfToken('synthetic-csrf-token');
    await post('/batches', { name: 'SINTÉTICO' });
    const [url, init] = fetcher.mock.calls[0];
    expect(url).toBe('/api/v1/batches');
    expect(init.credentials).toBe('same-origin');
    expect(init.headers.get('X-CSRF-Token')).toBe('synthetic-csrf-token');
    expect(url).not.toContain('synthetic-csrf-token');
  });
  it('conserva el límite multipart generado por el navegador', async () => {
    const fetcher = vi.fn().mockResolvedValue(new Response(JSON.stringify({}), { status: 200 }));
    vi.stubGlobal('fetch', fetcher);
    await api('/batches/b/uploads?side=original', { method: 'POST', body: new FormData() });
    expect(fetcher.mock.calls[0][1].headers.has('Content-Type')).toBe(false);
  });
  it('un error no se transforma en resultados vacíos', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({ detail: 'No existen parejas confirmadas.' }), { status: 422 })));
    await expect(post('/batches/b/runs', { allow_partial: false })).rejects.toMatchObject({ status: 422, message: 'No existen parejas confirmadas.' } satisfies Partial<ApiError>);
  });
});
