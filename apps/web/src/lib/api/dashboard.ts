import type { DashboardSnapshot, JobCurves } from '@/types/domain';
import { api } from '@/lib/api/client';

/**
 * Estado agregado del M01. El detalle de cada trabajo llega además por el canal
 * `GET /api/v1/training-jobs/{id}/events` (§9) cuando una pantalla lo sigue en vivo.
 */
export function fetchDashboard(signal?: AbortSignal): Promise<DashboardSnapshot> {
  return api.get<DashboardSnapshot>('/dashboard', { signal });
}

/** Historial época a época del trabajo: pérdida (entrenamiento/validación) y métrica. */
export function fetchJobCurves(jobId: string, signal?: AbortSignal): Promise<JobCurves> {
  return api.get<JobCurves>(`/training-jobs/${jobId}/metrics`, { signal });
}

/** La cancelación es una solicitud: el worker confirma el estado final (RN-05). */
export function requestCancellation(jobId: string, reason?: string): Promise<{ jobId: string; status: string }> {
  return api.post(`/training-jobs/${jobId}/cancel`, reason ? { reason } : undefined);
}

/** Origen de los datos que muestran las pantallas: la API de la plataforma. */
export const dataSource: 'demo' | 'api' = 'api';
