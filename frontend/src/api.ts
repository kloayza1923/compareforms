const API = '/api/v1';
let csrfToken = '';
export const setCsrfToken = (token: string) => { csrfToken = token; };

export class ApiError extends Error {
  constructor(message: string, public status: number) { super(message); }
}

export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const method = (init.method || 'GET').toUpperCase();
  const headers = new Headers(init.headers);
  if (init.body && !(init.body instanceof FormData)) headers.set('Content-Type', 'application/json');
  if (!['GET', 'HEAD', 'OPTIONS'].includes(method) && csrfToken) headers.set('X-CSRF-Token', csrfToken);
  const response = await fetch(`${API}${path}`, { ...init, method, headers, credentials: 'same-origin', cache: 'no-store' });
  if (!response.ok) {
    let detail = `No se pudo completar la solicitud (${response.status}).`;
    try {
      const result = await response.json();
      if (typeof result.detail === 'string') detail = result.detail;
      else if (Array.isArray(result.detail)) detail = result.detail.map((e: { msg?: string }) => e.msg || 'Dato inválido').join('. ');
    } catch { /* A proxy may return HTML; never expose it as markup. */ }
    if (response.status === 401 && path !== '/auth/login' && path !== '/auth/me') window.dispatchEvent(new Event('session-expired'));
    throw new ApiError(detail, response.status);
  }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

export const post = <T>(path: string, body: unknown, headers?: HeadersInit) => api<T>(path, { method: 'POST', body: JSON.stringify(body), headers });
export const reportUrl = (id: string) => `${API}/runs/${encodeURIComponent(id)}/report`;
export const documentUrl = (id: string, page?: number | null) => `${API}/documents/${encodeURIComponent(id)}/content${page && page > 0 ? `#page=${page}` : ''}`;
export const errorMessage = (error: unknown) => error instanceof Error ? error.message : 'Ocurrió un error. Intenta nuevamente.';

// crypto.randomUUID is unavailable on some HTTP-only LAN development origins.
export function requestKey(): string {
  if (globalThis.crypto?.randomUUID) return globalThis.crypto.randomUUID();
  const bytes = globalThis.crypto.getRandomValues(new Uint8Array(16));
  return Array.from(bytes, x => x.toString(16).padStart(2, '0')).join('');
}
