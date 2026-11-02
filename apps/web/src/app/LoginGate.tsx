import { useState } from 'react';
import type { FormEvent } from 'react';
import { sessionApi } from '@/lib/api/resources';
import { beginLogin } from '@/lib/auth/oidc';
import type { OidcConfig } from '@/lib/auth/oidc';
import { setAccessToken } from '@/lib/api/client';
import { Icon } from '@/components/ui/Icon';

/* Pantallas previas a la sesión: acceso con el proveedor de identidad (OIDC) o, sin
   proveedor configurado, con correo y contraseña propios de NeuroLab. */

export function OidcLoginGate({ config, error }: { config: OidcConfig; error?: string | null }) {
  const [busy, setBusy] = useState(false);
  return (
    <div className="session-gate session-gate--login">
      <Icon name="logo" size={34} />
      <h1>NeuroLab Enterprise</h1>
      <p>Accede con la cuenta de tu organización.</p>
      {error ? (
        <p className="session-gate__error" role="alert">
          {error}
        </p>
      ) : null}
      <button
        type="button"
        className="btn btn--primary"
        disabled={busy}
        onClick={() => {
          setBusy(true);
          void beginLogin(config).catch(() => setBusy(false));
        }}
      >
        <Icon name="lock" size={16} />
        {busy ? 'Redirigiendo…' : 'Iniciar sesión'}
      </button>
      <p className="session-gate__hint">
        La identidad la verifica el proveedor de la organización; NeuroLab no recibe tu contraseña.
      </p>
    </div>
  );
}

export function PasswordLoginGate() {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const session = await sessionApi.login(email, password);
      setAccessToken(session.accessToken);
      window.location.reload();
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : 'No fue posible iniciar sesión.');
      setBusy(false);
    }
  }

  return (
    <form className="session-gate session-gate--login" onSubmit={(event) => void submit(event)}>
      <Icon name="logo" size={34} />
      <h1>NeuroLab Enterprise</h1>
      <label className="session-gate__field">
        <span>Correo</span>
        <input className="adm-input" type="email" autoComplete="username" required value={email}
          onChange={(event) => setEmail(event.target.value)} />
      </label>
      <label className="session-gate__field">
        <span>Contraseña</span>
        <input className="adm-input" type="password" autoComplete="current-password" required value={password}
          onChange={(event) => setPassword(event.target.value)} />
      </label>
      {error ? (
        <p className="session-gate__error" role="alert">
          {error}
        </p>
      ) : null}
      <button type="submit" className="btn btn--primary" disabled={busy}>
        <Icon name="lock" size={16} />
        {busy ? 'Comprobando…' : 'Iniciar sesión'}
      </button>
    </form>
  );
}
