import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react';
import type { ReactNode } from 'react';
import { useQuery } from '@tanstack/react-query';
import type { Actor } from '@/types/domain';
import type { DirectoryUser } from '@/types/project';
import { ApiError, hasAccessToken, setAccessToken } from '@/lib/api/client';
import { queryKeys } from '@/lib/api/queryClient';
import { sessionApi } from '@/lib/api/resources';
import type { ApiUser, AuthConfig, ClientConfig } from '@/lib/api/resources';
import { CALLBACK_PATH, completeLogin, logout, restoreSession } from '@/lib/auth/oidc';
import type { OidcConfig } from '@/lib/auth/oidc';
import { Icon } from '@/components/ui/Icon';
import { OidcLoginGate, PasswordLoginGate } from '@/app/LoginGate';

/* Sesión de M10: quién es el usuario, el directorio de personas y los límites vigentes.
   - Proveedor de identidad (oidc): sin token se pide iniciar sesión en el proveedor; al
     volver a /auth/callback se canjea el código y la API registra el acceso.
   - Local: correo y contraseña propios; en desarrollo, sin token se actúa como el usuario
     demo y `switchUser` cambia a otro usuario demo para probar los permisos por rol. */

interface Session {
  actor: Actor;
  users: DirectoryUser[];
  config: ClientConfig;
  provider: AuthConfig['provider'];
  /** true cuando hay token propio (no el usuario por defecto del modo desarrollo). */
  signedIn: boolean;
  switchUser: (userId: string) => Promise<void>;
  signOut: () => void;
}

type Phase = 'checking' | 'ready' | 'signedOut';

const SessionContext = createContext<Session | null>(null);

function toActor(user: ApiUser): Actor {
  return { id: user.id, displayName: user.displayName, email: user.email, role: user.role, initials: user.initials };
}

function message(error: unknown, fallback: string): string {
  return error instanceof Error ? error.message : fallback;
}

export function SessionProvider({ children }: { children: ReactNode }) {
  const auth = useQuery({ queryKey: queryKeys.authConfig, queryFn: sessionApi.authConfig, staleTime: Infinity, retry: 1 });
  const authConfig = auth.data ?? null;
  const oidc = authConfig?.provider === 'oidc' ? (authConfig as OidcConfig & { devLogin: boolean }) : null;
  const [phase, setPhase] = useState<Phase>('checking');
  const [loginError, setLoginError] = useState<string | null>(null);

  useEffect(() => {
    if (!authConfig) return;
    let active = true;
    const settle = (next: Phase) => {
      if (active) setPhase(next);
    };
    if (!oidc) {
      settle(hasAccessToken() || authConfig.devLogin ? 'ready' : 'signedOut');
    } else if (window.location.pathname === CALLBACK_PATH) {
      completeLogin(oidc)
        .then(async (returnTo) => {
          await sessionApi.startSession();
          window.location.replace(returnTo);
        })
        .catch((error: unknown) => {
          if (!active) return;
          setLoginError(message(error, 'No fue posible completar el inicio de sesión.'));
          window.history.replaceState(null, '', '/');
          setPhase('signedOut');
        });
    } else {
      void restoreSession(oidc).then((restored) => settle(restored ? 'ready' : 'signedOut'));
    }
    return () => {
      active = false;
    };
  }, [authConfig, oidc]);

  const query = useQuery({
    queryKey: queryKeys.session,
    queryFn: async () => {
      const [me, users, config] = await Promise.all([sessionApi.me(), sessionApi.directory(), sessionApi.config()]);
      return { actor: toActor(me), users: users as DirectoryUser[], config };
    },
    enabled: phase === 'ready',
    staleTime: 60_000,
    retry: (count, error) => !(error instanceof ApiError && (error.status === 401 || error.status === 403)) && count < 2,
  });

  /* Token rechazado (expiró la sesión o la cuenta no está en NeuroLab): de vuelta al acceso. */
  useEffect(() => {
    if (!(query.error instanceof ApiError) || ![401, 403].includes(query.error.status)) return;
    if (query.error.status === 403) setLoginError(query.error.message);
    if (oidc || !authConfig?.devLogin) {
      setAccessToken(null);
      setPhase('signedOut');
    }
  }, [query.error, oidc, authConfig]);

  /* Cambiar de identidad recarga la aplicación: ningún dato del usuario anterior sobrevive. */
  const switchUser = useCallback(async (userId: string) => {
    const session = await sessionApi.devLogin(userId);
    setAccessToken(session.accessToken);
    window.location.reload();
  }, []);

  const signOut = useCallback(() => {
    if (oidc) {
      logout(oidc);
      return;
    }
    setAccessToken(null);
    window.location.reload();
  }, [oidc]);

  const state = query.data ?? null;
  const value = useMemo<Session | null>(
    () =>
      state && authConfig
        ? { ...state, provider: authConfig.provider, signedIn: hasAccessToken(), switchUser, signOut }
        : null,
    [state, authConfig, switchUser, signOut],
  );

  const failure = auth.isError ? auth.error : query.isError && phase === 'ready' ? query.error : null;
  const authFailure = failure instanceof ApiError && [401, 403].includes(failure.status);
  if (failure && !authFailure) {
    const idpDown = failure instanceof ApiError && failure.status === 503;
    return (
      <div className="session-gate" role="alert">
        <Icon name="alertTriangle" size={22} />
        <h1>{idpDown ? 'El proveedor de identidad no responde' : 'No hay conexión con la API de NeuroLab'}</h1>
        <p>{message(failure, 'No fue posible abrir la sesión.')}</p>
        <p className="session-gate__hint">
          Inicia el backend con <code>run.bat</code>
          {oidc || idpDown ? (
            <>
              {' '}
              y Keycloak con <code>infra\keycloak\iniciar.ps1</code>
            </>
          ) : null}
          .
        </p>
        <button
          type="button"
          className="btn btn--primary"
          onClick={() => void (auth.isError ? auth.refetch() : query.refetch())}
        >
          <Icon name="refresh" size={16} />
          Reintentar
        </button>
      </div>
    );
  }

  if (phase === 'signedOut' && authConfig) {
    return oidc ? <OidcLoginGate config={oidc} error={loginError} /> : <PasswordLoginGate />;
  }

  if (!value) {
    return (
      <div className="session-gate" aria-busy="true">
        <p>Abriendo sesión…</p>
      </div>
    );
  }

  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>;
}

export function useSession(): Session {
  const context = useContext(SessionContext);
  if (!context) throw new Error('useSession debe usarse dentro de SessionProvider');
  return context;
}
