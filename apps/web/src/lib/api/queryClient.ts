import { QueryClient } from '@tanstack/react-query';
import { ApiError } from '@/lib/api/client';

/* Caché de consultas (§5: "TanStack Query para consultas/cache"). Cada recurso de la API
   tiene una clave; tras una mutación se invalidan las claves afectadas y todas las
   pantallas que muestran ese dato se actualizan a la vez. */

export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 10_000,
      refetchOnWindowFocus: true,
      /* Un 4xx (permiso, validación) no mejora reintentando; un fallo de red sí. */
      retry: (failures, error) => !(error instanceof ApiError && error.status >= 400 && error.status < 500) && failures < 2,
    },
    mutations: { retry: false },
  },
});

export const queryKeys = {
  authConfig: ['auth-config'] as const,
  session: ['session'] as const,
  dashboard: ['dashboard'] as const,
  catalog: ['catalog'] as const,
  projects: ['projects'] as const,
  trainingJobs: ['training-jobs'] as const,
  evaluations: ['evaluations'] as const,
  observations: ['observations'] as const,
  models: ['models'] as const,
  reportExports: ['report-exports'] as const,
  admin: ['admin'] as const,
};

/** Lo que cambia cuando se lanza, cancela o cierra un entrenamiento. */
export function invalidateTraining(): Promise<void> {
  return Promise.all([
    queryClient.invalidateQueries({ queryKey: queryKeys.trainingJobs }),
    queryClient.invalidateQueries({ queryKey: queryKeys.dashboard }),
    queryClient.invalidateQueries({ queryKey: queryKeys.evaluations }),
    queryClient.invalidateQueries({ queryKey: queryKeys.models }),
  ]).then(() => undefined);
}

/** Lo que cambia al tocar proyectos, datasets o arquitecturas. */
export function invalidateCatalog(): Promise<void> {
  return Promise.all([
    queryClient.invalidateQueries({ queryKey: queryKeys.catalog }),
    queryClient.invalidateQueries({ queryKey: queryKeys.projects }),
    queryClient.invalidateQueries({ queryKey: queryKeys.dashboard }),
  ]).then(() => undefined);
}
