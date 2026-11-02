const BASE_URL = import.meta.env.VITE_API_BASE_URL ?? '/api/v1';
const DEFAULT_TIMEOUT_MS = 15_000;
const TOKEN_KEY = 'neurolab.session.token';

export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
    readonly detail?: string,
  ) {
    super(message);
    this.name = 'ApiError';
  }
}

/* Token de sesión. Sin token, la API de desarrollo actúa como el usuario demo
   (NEUROLAB_AUTH_DEV_BYPASS); con token, como quien inició sesión. */
let accessToken: string | null = readToken();

function readToken(): string | null {
  try {
    return localStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}

/** `persist: false` deja el token solo en memoria (el módulo OIDC guarda los suyos aparte). */
export function setAccessToken(token: string | null, persist = true) {
  accessToken = token;
  try {
    if (token && persist) localStorage.setItem(TOKEN_KEY, token);
    else localStorage.removeItem(TOKEN_KEY);
  } catch {
    /* Modo privado: la sesión vive solo en memoria. */
  }
}

/* Con proveedor de identidad, un 401 suele ser un token de acceso recién expirado: se
   renueva una vez y se repite la petición antes de dar la sesión por terminada. */
let onUnauthorized: (() => Promise<boolean>) | null = null;

export function setUnauthorizedHandler(handler: (() => Promise<boolean>) | null) {
  onUnauthorized = handler;
}

export function hasAccessToken(): boolean {
  return accessToken !== null;
}

function authHeaders(): Record<string, string> {
  return accessToken ? { Authorization: `Bearer ${accessToken}` } : {};
}

/** Mensaje legible a partir del cuerpo de error de FastAPI (`detail` texto, objeto o lista). */
function describeError(status: number, text: string): string {
  try {
    const parsed = JSON.parse(text) as { detail?: unknown };
    const detail = parsed.detail;
    if (typeof detail === 'string') return detail;
    if (detail && typeof detail === 'object' && !Array.isArray(detail)) {
      const record = detail as { message?: string; issues?: string[] };
      return [record.message, ...(record.issues ?? [])].filter(Boolean).join(' ');
    }
    if (Array.isArray(detail) && detail.length > 0) {
      const first = detail[0] as { loc?: unknown[]; msg?: string };
      const field = first.loc?.slice(1).join('.') ?? '';
      return `Dato inválido${field ? ` en ${field}` : ''}: ${first.msg ?? 'revise el formulario'}.`;
    }
  } catch {
    /* El cuerpo no era JSON. */
  }
  return status === 0 ? 'Sin conexión con la API.' : `La API respondió ${status}.`;
}

interface RequestOptions extends Omit<RequestInit, 'body'> {
  body?: unknown;
  timeoutMs?: number;
}

export async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  try {
    return await send<T>(path, options);
  } catch (error) {
    if (error instanceof ApiError && error.status === 401 && onUnauthorized && (await onUnauthorized())) {
      return send<T>(path, options);
    }
    throw error;
  }
}

async function send<T>(path: string, options: RequestOptions): Promise<T> {
  const { timeoutMs = DEFAULT_TIMEOUT_MS, body, ...init } = options;
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  const external = init.signal;
  external?.addEventListener('abort', () => controller.abort(), { once: true });
  const isForm = body instanceof FormData;

  try {
    const response = await fetch(`${BASE_URL}${path}`, {
      ...init,
      signal: controller.signal,
      headers: {
        Accept: 'application/json',
        ...(body === undefined || isForm ? {} : { 'Content-Type': 'application/json' }),
        ...authHeaders(),
        ...init.headers,
      },
      ...(body === undefined ? {} : { body: isForm ? body : JSON.stringify(body) }),
    });

    if (!response.ok) {
      const text = await response.text().catch(() => '');
      if (response.status === 401 && accessToken && !onUnauthorized) setAccessToken(null);
      throw new ApiError(response.status, describeError(response.status, text), text.slice(0, 400));
    }

    return response.status === 204 ? (undefined as T) : ((await response.json()) as T);
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') {
      if (external?.aborted) throw error;
      throw new ApiError(0, 'La solicitud excedió el tiempo de espera');
    }
    if (error instanceof TypeError) throw new ApiError(0, 'Sin conexión con la API. ¿Está corriendo el backend?');
    throw error;
  } finally {
    clearTimeout(timer);
  }
}

/** Descarga un archivo autenticado y lo guarda con el nombre que propone el servidor. */
export async function download(path: string, fallbackName: string): Promise<void> {
  const response = await fetch(`${BASE_URL}${path}`, { headers: authHeaders() });
  if (!response.ok) {
    throw new ApiError(response.status, describeError(response.status, await response.text().catch(() => '')));
  }
  const disposition = response.headers.get('Content-Disposition') ?? '';
  const name = /filename="?([^"]+)"?/.exec(disposition)?.[1] ?? fallbackName;
  const url = URL.createObjectURL(await response.blob());
  const link = document.createElement('a');
  link.href = url;
  link.download = name;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

export interface StreamEvent {
  id: number | null;
  event: string;
  data: Record<string, unknown>;
}

/**
 * Canal SSE autenticado (§9). Se lee con `fetch` en lugar de `EventSource` para poder
 * enviar el token en la cabecera; al cortarse, reconecta con `Last-Event-ID` y el
 * servidor reenvía solo lo pendiente. Termina con el evento `end` o al abortar.
 */
export async function streamEvents(
  path: string,
  onEvent: (event: StreamEvent) => void,
  signal: AbortSignal,
): Promise<void> {
  let lastId: number | null = null;
  let attempts = 0;

  while (!signal.aborted) {
    try {
      const response = await fetch(`${BASE_URL}${path}`, {
        signal,
        headers: {
          Accept: 'text/event-stream',
          ...authHeaders(),
          ...(lastId !== null ? { 'Last-Event-ID': String(lastId) } : {}),
        },
      });
      if (!response.ok || !response.body) {
        throw new ApiError(response.status, describeError(response.status, await response.text().catch(() => '')));
      }
      attempts = 0;
      const reader = response.body.pipeThrough(new TextDecoderStream()).getReader();
      let buffer = '';
      for (;;) {
        const { value, done } = await reader.read();
        if (done) break;
        buffer += value.replace(/\r\n/g, '\n');
        let boundary = buffer.indexOf('\n\n');
        while (boundary !== -1) {
          const block = buffer.slice(0, boundary);
          buffer = buffer.slice(boundary + 2);
          boundary = buffer.indexOf('\n\n');
          let id: number | null = null;
          let event = 'message';
          const data: string[] = [];
          for (const line of block.split('\n')) {
            if (line.startsWith('id:')) id = Number(line.slice(3).trim());
            else if (line.startsWith('event:')) event = line.slice(6).trim();
            else if (line.startsWith('data:')) data.push(line.slice(5).trim());
          }
          if (data.length === 0) continue;
          if (id !== null) lastId = id;
          onEvent({ id, event, data: JSON.parse(data.join('\n')) as Record<string, unknown> });
          if (event === 'end') return;
        }
      }
    } catch (error) {
      if (signal.aborted) return;
      if (error instanceof ApiError && error.status >= 400 && error.status < 500) throw error;
    }
    attempts += 1;
    await new Promise((resolve) => setTimeout(resolve, Math.min(10_000, 1000 * 2 ** Math.min(attempts, 4))));
  }
}

export const api = {
  get: <T>(path: string, options?: RequestOptions) => request<T>(path, { ...options, method: 'GET' }),
  post: <T>(path: string, body?: unknown, options?: RequestOptions) =>
    request<T>(path, { ...options, method: 'POST', body }),
  put: <T>(path: string, body?: unknown, options?: RequestOptions) =>
    request<T>(path, { ...options, method: 'PUT', body }),
  patch: <T>(path: string, body?: unknown, options?: RequestOptions) =>
    request<T>(path, { ...options, method: 'PATCH', body }),
  delete: <T>(path: string, options?: RequestOptions) =>
    request<T>(path, { ...options, method: 'DELETE' }),
};
