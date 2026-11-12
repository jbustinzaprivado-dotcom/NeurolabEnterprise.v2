/* Contratos del M07 · Evaluación y métricas. La partición de prueba queda
   reservada desde el M05 y sólo se consume aquí para la evaluación final (§6). */

import type { JobStatus, NetworkFamily } from '@/types/domain';

export type EvaluationMetric = 'loss' | 'accuracy' | 'f1' | 'mae';

export type EvaluationTask = 'classification' | 'regression';

export type EvaluationSplit = 'TEST' | 'VALIDATION';

export type ObservationKind = 'LIMITATION' | 'OBSERVATION' | 'RISK';

export type RunTone = 'indigo' | 'sky' | 'emerald' | 'amber';

/** Etiqueta supervisada del proyecto de clasificación evaluado. */
export interface EvaluationClass {
  id: string;
  label: string;
  /** Abreviatura para encabezados de la matriz de confusión. */
  short: string;
}

/** Métricas por época reportadas por el worker durante el M06. */
export interface EpochMetrics {
  epoch: number;
  loss: number;
  valLoss: number;
  accuracy: number;
  valAccuracy: number;
  f1: number;
  valF1: number;
  /** Error absoluto medio por época; solo en regresión (null en clasificación). */
  mae: number | null;
  valMae: number | null;
}

/** Métricas agregadas de una clase a partir de la matriz de confusión. */
export interface ClassMetrics {
  classId: string;
  support: number;
  predicted: number;
  truePositive: number;
  falsePositive: number;
  falseNegative: number;
  precision: number;
  recall: number;
  f1: number;
}

export interface EvaluationSummary {
  total: number;
  accuracy: number;
  balancedAccuracy: number;
  precision: number;
  recall: number;
  f1: number;
  weakestClassId: string;
}

/** Ejecución de entrenamiento con evaluación final sobre la partición de prueba. */
export interface EvaluationRun {
  id: string;
  jobId: string;
  task: EvaluationTask;
  /** Columna objetivo: da las unidades de RMSE y MAE en regresión. */
  target: string;
  /** Regresión: R², RMSE y MAE sobre la partición de prueba. */
  testMetrics: { r2?: number; rmse?: number; mae?: number };
  name: string;
  project: string;
  /** La API lo envía; sirve para comparar solo contra ejecuciones del mismo proyecto. */
  projectId: string;
  dataset: string;
  datasetVersion: string;
  family: NetworkFamily;
  architecture: string;
  optimizer: string;
  learningRate: number;
  batchSize: number;
  seed: number;
  epochs: number;
  bestEpoch: number;
  durationSeconds: number;
  finishedAt: string;
  status: JobStatus;
  split: EvaluationSplit;
  samples: number;
  testLoss: number;
  latencyP95Ms: number;
  /** Filas = clase real; columnas = clase predicha. Vacía en regresión. */
  confusion: number[][];
  /** Etiquetas en el orden de la matriz; las publica el worker al evaluar. */
  classes?: EvaluationClass[];
  history: EpochMetrics[];
  tone: RunTone;
  /** Clasificación: peso de clases con que se entrenó. */
  classWeight?: 'none' | 'balanced';
  /** Solo en clasificación binaria: umbral entrenado, clase positiva y [real, probabilidad] por fila. */
  binary?: BinaryEvaluation | null;
}

export interface BinaryEvaluation {
  threshold: number;
  positiveClass: string;
  scores: [number, number][];
}

export interface Observation {
  id: string;
  runId: string;
  kind: ObservationKind;
  title: string;
  body: string;
  author: string;
  createdAt: string;
  reviewed: boolean;
}

export interface ObservationDraft {
  runId: string;
  kind: ObservationKind;
  title: string;
  body: string;
}
