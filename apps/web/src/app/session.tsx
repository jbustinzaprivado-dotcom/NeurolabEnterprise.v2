import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react';
import type { ReactNode } from 'react';
import type { Actor } from '@/types/domain';
import type { DirectoryUser } from '@/types/project';
import { hasAccessToken, setAccessToken } from '@/lib/api/client';
import { sessionApi } from '@/lib/api/resources';
import type { ApiUser, ClientConfig } from '@/lib/api/resources';
import { Icon } from '@/components/ui/Icon';

/* Sesión de M10: quién es el usuario, el directorio de personas y los límites vigentes.
   Sin token, la API de desarrollo responde como el usuario demo; `switchUser` inicia
   sesión como otro usuario demo para comprobar cómo cambian los permisos por rol. */

interface Session {
  actor: Actor;
  users: DirectoryUser[];
  config: ClientConfig;
  /** true cuando hay token propio (no el usuario por defecto del modo desarrollo). */
  signedIn: boolean;
  switchUser: (userId: string) => Promise<void>;
  signOut: () => void;
}

const SessionContext = createContext<Session | null>(null);

function toActor(user: ApiUser): Actor {
  return { id: user.id, displayName: user.displayName, email: user.email, role: user.role, initials: user.initials };
}

export function SessionProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<{ actor: Actor; users: DirectoryUser[]; config: ClientConfig } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let cancelled = false;
    setError(null);
    Promise.all([sessionApi.me(), sessionApi.directory(), sessionApi.config()])
      .then(([me, users, config]) => {
        if (!cancelled) setState({ actor: toActor(me), users, config });
      })
      .catch((caught: unknown) => {
        if (!cancelled) setError(caught instanceof Error ? caught.message : 'No fue posible abrir la sesión.');
      });
    return () => {
      cancelled = true;
    };
  }, [attempt]);

  /* Cambiar de identidad recarga la aplicación: ningún dato del usuario anterior sobrevive. */
  const switchUser = useCallback(async (userId: string) => {
    const session = await sessionApi.devLogin(userId);
    setAccessToken(session.accessToken);
    window.location.reload();
  }, []);

  const signOut = useCallback(() => {
    setAccessToken(null);
    window.location.reload();
  }, []);

  const value = useMemo<Session | null>(
    () => (state ? { ...state, signedIn: hasAccessToken(), switchUser, signOut } : null),
    [state, switchUser, signOut],
  );

  if (error) {
    return (
      <div className="session-gate" role="alert">
        <Icon name="alertTriangle" size={22} />
        <h1>No hay conexión con la API de NeuroLab</h1>
        <p>{error}</p>
        <p className="session-gate__hint">
          Inicia el backend con <code>run.bat</code> o <code>venv\Scripts\python.exe services\api\app\main.py</code>.
        </p>
        <button type="button" className="btn btn--primary" onClick={() => setAttempt((n) => n + 1)}>
          <Icon name="refresh" size={16} />
          Reintentar
        </button>
      </div>
    );
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
