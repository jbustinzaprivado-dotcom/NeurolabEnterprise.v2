import { setAccessToken, setUnauthorizedHandler } from '@/lib/api/client';

/* Inicio de sesión con el proveedor de identidad (§11): Authorization Code + PKCE.
   La interfaz es un cliente público: no guarda secretos. El verificador PKCE y el `state`
   viven solo en esta pestaña hasta volver del proveedor; los tokens, en sessionStorage,
   y el de acceso (5 min) se renueva con el de refresco antes de expirar. */

export interface OidcConfig {
  provider: 'oidc';
  issuer: string;
  clientId: string;
  authorizationEndpoint: string;
  tokenEndpoint: string;
  endSessionEndpoint: string | null;
}

interface StoredTokens {
  accessToken: string;
  refreshToken: string | null;
  idToken: string | null;
  expiresAt: number;
}

interface PendingLogin {
  state: string;
  verifier: string;
  returnTo: string;
}

const TOKENS_KEY = 'neurolab.oidc.tokens';
const PENDING_KEY = 'neurolab.oidc.pending';
export const CALLBACK_PATH = '/auth/callback';
const REFRESH_MARGIN_MS = 60_000;

let refreshTimer: ReturnType<typeof setTimeout> | null = null;
let refreshing: Promise<boolean> | null = null;

function readJson<T>(key: string): T | null {
  try {
    const raw = sessionStorage.getItem(key);
    return raw ? (JSON.parse(raw) as T) : null;
  } catch {
    return null;
  }
}

function writeJson(key: string, value: unknown) {
  try {
    if (value === null) sessionStorage.removeItem(key);
    else sessionStorage.setItem(key, JSON.stringify(value));
  } catch {
    /* Sin almacenamiento: la sesión vive solo en memoria y se pierde al recargar. */
  }
}

function base64Url(bytes: Uint8Array): string {
  let text = '';
  bytes.forEach((byte) => {
    text += String.fromCharCode(byte);
  });
  return btoa(text).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
}

function randomString(): string {
  return base64Url(crypto.getRandomValues(new Uint8Array(32)));
}

async function challengeFor(verifier: string): Promise<string> {
  const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(verifier));
  return base64Url(new Uint8Array(digest));
}

function redirectUri(): string {
  return `${window.location.origin}${CALLBACK_PATH}`;
}

/** Lleva al formulario del proveedor; al volver, `completeLogin` recoge el código. */
export async function beginLogin(config: OidcConfig): Promise<void> {
  const verifier = randomString();
  const state = randomString();
  const here = `${window.location.pathname}${window.location.search}`;
  writeJson(PENDING_KEY, { state, verifier, returnTo: here.startsWith(CALLBACK_PATH) ? '/' : here });
  const params = new URLSearchParams({
    client_id: config.clientId,
    response_type: 'code',
    scope: 'openid profile email',
    redirect_uri: redirectUri(),
    state,
    code_challenge: await challengeFor(verifier),
    code_challenge_method: 'S256',
  });
  window.location.assign(`${config.authorizationEndpoint}?${params.toString()}`);
}

async function tokenRequest(config: OidcConfig, body: Record<string, string>): Promise<StoredTokens> {
  const response = await fetch(config.tokenEndpoint, {
    method: 'POST',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body: new URLSearchParams({ client_id: config.clientId, ...body }),
  });
  const payload = (await response.json().catch(() => ({}))) as Record<string, unknown>;
  if (!response.ok || typeof payload.access_token !== 'string') {
    const reason = typeof payload.error_description === 'string' ? payload.error_description : `error ${response.status}`;
    throw new Error(`El proveedor de identidad rechazó la solicitud (${reason}).`);
  }
  const previous = readJson<StoredTokens>(TOKENS_KEY);
  return {
    accessToken: payload.access_token,
    refreshToken: typeof payload.refresh_token === 'string' ? payload.refresh_token : previous?.refreshToken ?? null,
    idToken: typeof payload.id_token === 'string' ? payload.id_token : previous?.idToken ?? null,
    expiresAt: Date.now() + Number(payload.expires_in ?? 300) * 1000,
  };
}

function store(config: OidcConfig, tokens: StoredTokens | null) {
  writeJson(TOKENS_KEY, tokens);
  setAccessToken(tokens?.accessToken ?? null, false);
  if (refreshTimer) clearTimeout(refreshTimer);
  refreshTimer = null;
  if (tokens?.refreshToken) {
    const wait = Math.max(5_000, tokens.expiresAt - Date.now() - REFRESH_MARGIN_MS);
    refreshTimer = setTimeout(() => void refresh(config), wait);
  }
}

/** Renueva el token de acceso; false si la sesión del proveedor ya terminó. */
export function refresh(config: OidcConfig): Promise<boolean> {
  const current = readJson<StoredTokens>(TOKENS_KEY);
  if (!current?.refreshToken) return Promise.resolve(false);
  refreshing ??= tokenRequest(config, { grant_type: 'refresh_token', refresh_token: current.refreshToken })
    .then((tokens) => {
      store(config, tokens);
      return true;
    })
    .catch(() => {
      store(config, null);
      return false;
    })
    .finally(() => {
      refreshing = null;
    });
  return refreshing;
}

/** Al volver del proveedor: valida `state`, canjea el código y devuelve adónde regresar. */
export async function completeLogin(config: OidcConfig): Promise<string> {
  const params = new URLSearchParams(window.location.search);
  const pending = readJson<PendingLogin>(PENDING_KEY);
  writeJson(PENDING_KEY, null);
  const error = params.get('error');
  if (error) throw new Error(params.get('error_description') ?? `El proveedor de identidad devolvió «${error}».`);
  const code = params.get('code');
  if (!code || !pending || params.get('state') !== pending.state) {
    throw new Error('La respuesta del proveedor no corresponde a un inicio de sesión de esta pestaña. Vuelve a intentarlo.');
  }
  const tokens = await tokenRequest(config, {
    grant_type: 'authorization_code',
    code,
    redirect_uri: redirectUri(),
    code_verifier: pending.verifier,
  });
  store(config, tokens);
  return pending.returnTo || '/';
}

/** Recupera la sesión de la pestaña tras recargar; false si no hay o ya no se puede renovar. */
export async function restoreSession(config: OidcConfig): Promise<boolean> {
  setUnauthorizedHandler(() => refresh(config));
  const tokens = readJson<StoredTokens>(TOKENS_KEY);
  if (!tokens) {
    setAccessToken(null);
    return false;
  }
  if (tokens.expiresAt - Date.now() > REFRESH_MARGIN_MS) {
    store(config, tokens);
    return true;
  }
  return refresh(config);
}

/** Cierra la sesión aquí y en el proveedor (si no, volvería a entrar sin pedir contraseña). */
export function logout(config: OidcConfig) {
  const tokens = readJson<StoredTokens>(TOKENS_KEY);
  store(config, null);
  if (!config.endSessionEndpoint) {
    window.location.assign('/');
    return;
  }
  const params = new URLSearchParams({
    client_id: config.clientId,
    post_logout_redirect_uri: `${window.location.origin}/`,
  });
  if (tokens?.idToken) params.set('id_token_hint', tokens.idToken);
  window.location.assign(`${config.endSessionEndpoint}?${params.toString()}`);
}
