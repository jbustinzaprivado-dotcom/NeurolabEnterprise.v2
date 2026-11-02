import type { EpochPoint, TrainingJob } from '@/types/domain';
import { formatNumber, formatRate } from '@/lib/format';

/* Métrica de época según la tarea del trabajo. Clasificación: exactitud (más es mejor).
   Regresión: no hay exactitud; se usa el error absoluto medio de validación (menos es mejor),
   en las unidades del objetivo. Lo comparten el panel (M01), el detalle de M06 y M09. */

export type JobTask = TrainingJob['task'];

export function formatErrorAmount(value: number): string {
  return Math.abs(value) >= 100 ? formatNumber(value, 0) : formatNumber(value, 3);
}

export function epochMae(point: EpochPoint, split: 'train' | 'validation'): number {
  return point.metrics?.[split === 'train' ? 'mae' : 'val_mae'] ?? 0;
}

/** Valor con el que se ordenan las ejecuciones; null si el trabajo aún no tiene métrica. */
function score(job: TrainingJob): number | null {
  if (job.task === 'regression') return job.valMae ?? null;
  return job.valAccuracy;
}

/** true si `candidate` supera a `best`. Solo compara trabajos de la misma tarea. */
export function isBetterRun(candidate: TrainingJob, best: TrainingJob | null): boolean {
  const value = score(candidate);
  if (value === null) return false;
  if (best === null) return true;
  if (best.task !== candidate.task) return false;
  const reference = score(best);
  if (reference === null) return true;
  return candidate.task === 'regression' ? value < reference : value > reference;
}

/** Nombre corto de la métrica de comparación ("val_acc" o "MAE val"). */
export function scoreName(task: JobTask): string {
  return task === 'regression' ? 'MAE val' : 'val_acc';
}

/** Métrica de comparación formateada, p. ej. "91,3 %" o "87.569". */
export function formatScore(job: TrainingJob): string {
  // Sin épocas (p. ej. cancelado en cola) no hay métrica: un 0 % sería engañoso.
  if (job.epoch === 0) return '—';
  if (job.task === 'regression') return job.valMae !== null ? formatErrorAmount(job.valMae) : '—';
  return formatRate(job.valAccuracy, 1);
}
