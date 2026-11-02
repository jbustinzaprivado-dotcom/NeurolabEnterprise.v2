import { createContext, useCallback, useContext, useMemo } from 'react';
import type { ReactNode } from 'react';
import { useMutation, useQuery } from '@tanstack/react-query';
import type { DashboardSnapshot } from '@/types/domain';
import { fetchDashboard, requestCancellation } from '@/lib/api/dashboard';
import { invalidateTraining, queryKeys } from '@/lib/api/queryClient';

/** Intervalo de sincronización del M01; el detalle de cada trabajo llega por SSE (§9). */
const POLL_MS = 5000;

type LoadStatus = 'loading' | 'ready' | 'error';

interface PlatformData {
  snapshot: DashboardSnapshot | null;
  status: LoadStatus;
  error: string | null;
  lastUpdated: string | null;
  pendingCancellation: string | null;
  refresh: () => void;
  cancelJob: (jobId: string) => void;
}

const PlatformDataContext = createContext<PlatformData | null>(null);

export function PlatformDataProvider({ children }: { children: ReactNode }) {
  /* El sondeo se pausa en segundo plano y se repite al volver a la pestaña (§16): un
     fallo puntual conserva el último snapshot en pantalla. */
  const query = useQuery({
    queryKey: queryKeys.dashboard,
    queryFn: ({ signal }) => fetchDashboard(signal),
    refetchInterval: POLL_MS,
    refetchIntervalInBackground: false,
  });

  const cancel = useMutation({
    mutationFn: (jobId: string) => requestCancellation(jobId),
    onSettled: () => invalidateTraining(),
  });

  const refetch = query.refetch;
  const refresh = useCallback(() => {
    void refetch();
  }, [refetch]);

  const mutate = cancel.mutate;
  const cancelJob = useCallback((jobId: string) => mutate(jobId), [mutate]);

  const snapshot = query.data ?? null;
  const value = useMemo<PlatformData>(
    () => ({
      snapshot,
      status: snapshot ? 'ready' : query.isError ? 'error' : 'loading',
      error: query.error instanceof Error ? query.error.message : cancel.isError ? 'La solicitud de cancelación no pudo registrarse' : null,
      lastUpdated: snapshot?.generatedAt ?? null,
      pendingCancellation: cancel.isPending ? (cancel.variables ?? null) : null,
      refresh,
      cancelJob,
    }),
    [snapshot, query.isError, query.error, cancel.isError, cancel.isPending, cancel.variables, refresh, cancelJob],
  );

  return <PlatformDataContext.Provider value={value}>{children}</PlatformDataContext.Provider>;
}

export function usePlatformData(): PlatformData {
  const context = useContext(PlatformDataContext);
  if (!context) {
    throw new Error('usePlatformData debe usarse dentro de PlatformDataProvider');
  }
  return context;
}
