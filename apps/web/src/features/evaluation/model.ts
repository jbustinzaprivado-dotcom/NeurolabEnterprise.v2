import type { IconName } from '@/components/ui/Icon';
import type {
  ClassMetrics,
  EpochMetrics,
  EvaluationClass,
  EvaluationMetric,
  EvaluationRun,
  EvaluationSummary,
  ObservationKind,
  RunTone,
} from '@/types/evaluation';
import { formatLoss, formatNumber, formatRate } from '@/lib/format';

/** Etiquetas de la matriz en su orden; si la ejecución no las trae, se numeran. */
export function classesOf(run: EvaluationRun): EvaluationClass[] {
  return (
    run.classes ??
    run.confusion.map((_, index) => ({ id: String(index), label: `Clase ${index + 1}`, short: `C${index + 1}` }))
  );
}

/** Deriva métricas por clase y macro desde la matriz de confusión (filas = real). */
export function metricsFromConfusion(confusion: number[][]): {
  perClass: ClassMetrics[];
  summary: EvaluationSummary;
} {
  const size = confusion.length;
  const supports = confusion.map((row) => row.reduce((sum, value) => sum + value, 0));
  const predicted = Array.from({ length: size }, (_, column) =>
    confusion.reduce((sum, row) => sum + (row[column] ?? 0), 0),
  );
  const total = supports.reduce((sum, value) => sum + value, 0);
  let correct = 0;

  const perClass: ClassMetrics[] = confusion.map((row, index) => {
    const classId = String(index);
    const truePositive = row[index] ?? 0;
    correct += truePositive;
    const falseNegative = supports[index] - truePositive;
    const falsePositive = predicted[index] - truePositive;
    const precision = truePositive + falsePositive > 0 ? truePositive / (truePositive + falsePositive) : 0;
    const recall = truePositive + falseNegative > 0 ? truePositive / (truePositive + falseNegative) : 0;
    const f1 = precision + recall > 0 ? (2 * precision * recall) / (precision + recall) : 0;
    return {
      classId,
      support: supports[index],
      predicted: predicted[index],
      truePositive,
      falsePositive,
      falseNegative,
      precision,
      recall,
      f1,
    };
  });

  const average = (pick: (item: ClassMetrics) => number) =>
    perClass.length > 0 ? perClass.reduce((sum, item) => sum + pick(item), 0) / perClass.length : 0;

  const weakest = perClass.reduce<ClassMetrics | null>(
    (worst, item) => (worst === null || item.f1 < worst.f1 ? item : worst),
    null,
  );

  return {
    perClass,
    summary: {
      total,
      accuracy: total > 0 ? correct / total : 0,
      balancedAccuracy: average((item) => item.recall),
      precision: average((item) => item.precision),
      recall: average((item) => item.recall),
      f1: average((item) => item.f1),
      weakestClassId: weakest?.classId ?? '0',
    },
  };
}

export interface ConfusionPair {
  actual: number;
  predicted: number;
  count: number;
}

/** Error más frecuente fuera de la diagonal, útil como lectura rápida del informe. */
export function largestConfusionPair(confusion: number[][]): ConfusionPair | null {
  let best: ConfusionPair | null = null;
  for (let actual = 0; actual < confusion.length; actual += 1) {
    for (let predicted = 0; predicted < confusion[actual].length; predicted += 1) {
      const count = confusion[actual][predicted];
      if (actual !== predicted && count > 0 && (!best || count > best.count)) {
        best = { actual, predicted, count };
      }
    }
  }
  return best;
}

export function metricValue(point: EpochMetrics, metric: EvaluationMetric, split: 'train' | 'validation'): number {
  if (metric === 'loss') return split === 'train' ? point.loss : point.valLoss;
  if (metric === 'accuracy') return split === 'train' ? point.accuracy : point.valAccuracy;
  return split === 'train' ? point.f1 : point.valF1;
}

export function formatMetricValue(metric: EvaluationMetric, value: number): string {
  return metric === 'loss' ? formatLoss(value) : formatRate(value);
}

export function formatMetricAxis(metric: EvaluationMetric, value: number): string {
  return metric === 'loss' ? formatLoss(value) : formatRate(value, 0);
}

export const metricMeta: Record<EvaluationMetric, { label: string; axis: string }> = {
  loss: { label: 'Pérdida', axis: 'pérdida' },
  accuracy: { label: 'Exactitud', axis: 'exactitud' },
  f1: { label: 'F1 macro', axis: 'F1 macro' },
};

export const runToneColor: Record<RunTone, string> = {
  indigo: 'var(--c-indigo-500)',
  sky: 'var(--c-sky-500)',
  emerald: 'var(--c-emerald-500)',
  amber: 'var(--c-amber-500)',
};

export function signed(value: number, decimals = 1): string {
  const prefix = value > 0 ? '+' : value < 0 ? '−' : '±';
  return `${prefix}${formatNumber(Math.abs(value), decimals)}`;
}

export const observationKindMeta: Record<
  ObservationKind,
  { label: string; icon: IconName; hint: string }
> = {
  LIMITATION: {
    label: 'Limitación',
    icon: 'alertTriangle',
    hint: 'Condición que acota la validez de la evaluación.',
  },
  OBSERVATION: {
    label: 'Observación',
    icon: 'info',
    hint: 'Lectura del comportamiento del modelo durante la evaluación.',
  },
  RISK: {
    label: 'Riesgo',
    icon: 'alertCircle',
    hint: 'Hallazgo que requiere seguimiento antes de publicar el modelo.',
  },
};

export const OBSERVATION_FILTERS: Array<{ id: ObservationKind | 'ALL'; label: string }> = [
  { id: 'ALL', label: 'Todos' },
  { id: 'LIMITATION', label: 'Limitaciones' },
  { id: 'OBSERVATION', label: 'Observaciones' },
  { id: 'RISK', label: 'Riesgos' },
];
