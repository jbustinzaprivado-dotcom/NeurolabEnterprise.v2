import type { ModelStatus } from '@/lib/api/resources';
import type { ChipProps } from '@/components/ui/Chip';
import { formatNumber, formatRate } from '@/lib/format';

/* Estados y métricas de las versiones de modelo, compartidos por M08 y la ficha de proyecto (M02). */

export const STATUS_META: Record<ModelStatus, { label: string; tone: NonNullable<ChipProps['tone']>; hint: string }> = {
  DRAFT: { label: 'Borrador', tone: 'neutral', hint: 'Registrado por el worker; pendiente de revisión.' },
  REVIEWED: { label: 'Revisado', tone: 'preparing', hint: 'Métricas revisadas; pendiente de aprobación.' },
  APPROVED: { label: 'Aprobado', tone: 'completed', hint: 'Autorizado para su uso.' },
  RETIRED: { label: 'Retirado', tone: 'cancelled', hint: 'Fuera de uso; se conserva para trazabilidad.' },
};

/* Métricas de prueba según la tarea. Clasificación: accuracy y F1 macro. Regresión: R²
   (parte de la variación del objetivo que explica el modelo) y RMSE/MAE, que están en las
   unidades del objetivo y se leen mejor que la pérdida MSE (unidades al cuadrado). */
export function isRegression(metrics: Record<string, number>): boolean {
  return metrics.r2 !== undefined || metrics.rmse !== undefined;
}

export function formatError(value: number): string {
  return Math.abs(value) >= 100 ? formatNumber(value, 0) : formatNumber(value, 3);
}

export function formatR2(value: number): string {
  return formatNumber(value, 3);
}

/** Métrica principal de prueba para listados: accuracy en clasificación, R² en regresión. */
export function headlineMetric(metrics: Record<string, number>): { label: string; value: string } | null {
  if (isRegression(metrics)) return metrics.r2 !== undefined ? { label: 'R²', value: formatR2(metrics.r2) } : null;
  return metrics.accuracy !== undefined ? { label: 'accuracy', value: formatRate(metrics.accuracy) } : null;
}
