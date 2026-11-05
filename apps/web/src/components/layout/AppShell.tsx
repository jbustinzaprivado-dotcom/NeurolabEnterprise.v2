import { useEffect, useState } from 'react';
import { Outlet, useLocation } from 'react-router-dom';
import { useLayoutMode } from '@/hooks/useLayoutMode';
import { PlatformDataProvider, usePlatformData } from '@/app/providers';
import { QueryClientProvider } from '@tanstack/react-query';
import { SessionProvider, useSession } from '@/app/session';
import { queryClient } from '@/lib/api/queryClient';
import { Sidebar } from '@/components/layout/Sidebar';
import { Topbar } from '@/components/layout/Topbar';

/* Preferencia de cada persona en su navegador: menú fijo (empuja el contenido) o desplegable. */
const PIN_KEY = 'neurolab.nav.pinned';

function readPinned(): boolean {
  try {
    return window.localStorage.getItem(PIN_KEY) === '1';
  } catch {
    return false;
  }
}

function ShellFrame() {
  const mode = useLayoutMode();
  const [navOpen, setNavOpen] = useState(false);
  const [pinned, setPinned] = useState(readPinned);
  const togglePinned = () => {
    setPinned((value) => {
      try {
        window.localStorage.setItem(PIN_KEY, value ? '0' : '1');
      } catch {
        /* Sin almacenamiento (ventana privada): la preferencia dura solo esta visita. */
      }
      return !value;
    });
  };
  const location = useLocation();
  const { snapshot } = usePlatformData();
  const { actor } = useSession();

  /* El cajón móvil se cierra al navegar y con Escape. */
  useEffect(() => {
    setNavOpen(false);
  }, [location.pathname]);

  useEffect(() => {
    if (mode !== 'drawer') setNavOpen(false);
  }, [mode]);

  useEffect(() => {
    if (!navOpen) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setNavOpen(false);
    };
    document.addEventListener('keydown', onKeyDown);
    document.body.style.overflow = 'hidden';
    return () => {
      document.removeEventListener('keydown', onKeyDown);
      document.body.style.overflow = '';
    };
  }, [navOpen]);

  const liveBadges = {
    M06: (snapshot?.activeJobs.length ?? 0) + (snapshot?.queuedJobs.length ?? 0),
  };

  return (
    <div className="shell" data-mode={mode} data-nav-open={navOpen} data-nav-pinned={pinned}>
      <a className="u-skip-link" href="#main-content">
        Saltar al contenido principal
      </a>

      <Sidebar
        mode={mode}
        open={navOpen}
        onClose={() => setNavOpen(false)}
        pinned={pinned}
        onTogglePinned={togglePinned}
        actor={actor}
        liveBadges={liveBadges}
      />

      <button
        type="button"
        className="scrim"
        aria-label="Cerrar navegación"
        tabIndex={navOpen ? 0 : -1}
        onClick={() => setNavOpen(false)}
      />

      <div className="workspace">
        <Topbar mode={mode} onOpenNav={() => setNavOpen(true)} />
        <main id="main-content" className="canvas" tabIndex={-1}>
          <div className="canvas__inner">
            <Outlet />
          </div>
        </main>
      </div>
    </div>
  );
}

/** Caché de consultas, luego la sesión (identidad y límites) y los datos de plataforma
    que consumen la barra lateral, el encabezado y cada módulo. */
export function AppShell() {
  return (
    <QueryClientProvider client={queryClient}>
      <SessionProvider>
        <PlatformDataProvider>
          <ShellFrame />
        </PlatformDataProvider>
      </SessionProvider>
    </QueryClientProvider>
  );
}
