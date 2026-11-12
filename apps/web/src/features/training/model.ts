import type {
  Actor,
  EpochPoint,
  JobStatus,
  NetworkFamily,
  TrainingJob,
  UserRole,
} from '@/types/domain';

/* Modelo de M06 · Entrenamientos (§6 Documento Maestro).
   - Configuración de épocas, batch size y optimizador.
   - Cola y prioridad por permisos.
   - Inicio, cancelación y reintento.
   - Progreso en tiempo real.

   La API es la fuente de verdad: valida, encola y el worker ejecuta con TensorFlow/Keras.
   Aquí solo viven las reglas que la interfaz aplica antes de enviar (la API las repite)
   y la lectura del registro de cada trabajo. Ningún cálculo de red neuronal ocurre en el
   navegador (RN-03). */

export type RunOrigin = 'plataforma' | 'local';
export type QueuePriority = 'CRITICA' | 'ALTA' | 'NORMAL' | 'BAJA';
export type LogLevel = 'info' | 'warn' | 'error' | 'success';

export interface RunLog {
  at: number;
  level: LogLevel;
  /** Emisor de la línea: api, scheduler, worker, watchdog o registry. */
  source: string;
  text: string;
}

export interface RunRecord {
  jobId: string;
  origin: RunOrigin;
  version: string;
  priority: QueuePriority;
  learningRate: number;
  seed: number;
  /** Clasificación: peso de clases con que se entrenó. */
  classWeight?: 'none' | 'balanced';
  /** Binaria: umbral de la clase positiva; null si no aplica. */
  threshold?: number | null;
  owner: string;
  /** Identificador del trabajo del que nace esta ejecución, si es un reintento. */
  retryOf?: string;
  /** Motivo de cierre que registró el worker o la API (cancelación, fallo). */
  motivo?: string;
  logs: RunLog[];
  metrics: EpochPoint[];
}

export type RunStore = Record<string, RunRecord>;

export interface ProjectOption {
  id: string;
  name: string;
  /** Solo arquitecturas guardadas en M04, con su versión. */
  architectures: {
    id: string;
    name: string;
    family: NetworkFamily;
    version: number;
    trainable: boolean;
    outputUnits: number | null;
    /** RNN: [pasos, variables]; CNN: [alto, ancho, canales]. Null en redes densas. */
    inputShape: number[] | null;
  }[];
  /** Versión vigente de cada dataset de M05 con su esquema verificado. */
  datasets: { id: string; name: string; version: number; columns: { name: string; kind: string; unique: number }[] }[];
  canLaunch: boolean;
}

export interface LaunchValues {
  projectId: string;
  /** Id de la versión de arquitectura. */
  architecture: string;
  /** Id de la versión de dataset. */
  dataset: string;
  targetColumn: string;
  epochs: string;
  batch: string;
  optimizer: string;
  learningRate: string;
  seed: string;
  priority: QueuePriority;
  /** Clasificación: «balanced» da más peso a la clase menos frecuente. */
  classWeight: 'none' | 'balanced';
  /** Clasificación binaria: probabilidad desde la que se predice la clase positiva (0,05–0,95). */
  threshold: string;
}

export const EMPTY_LAUNCH: LaunchValues = {
  projectId: '',
  architecture: '',
  dataset: '',
  targetColumn: '',
  epochs: '40',
  batch: '16',
  optimizer: 'adam',
  learningRate: '0,01',
  seed: '42',
  priority: 'NORMAL',
  classWeight: 'none',
  threshold: '0.5',
};

export const PRIORITY_LABEL: Record<QueuePriority, string> = {
  CRITICA: 'Crítica',
  ALTA: 'Alta',
  NORMAL: 'Normal',
  BAJA: 'Baja',
};

/** Menor rango se despacha antes. */
export const PRIORITY_RANK: Record<QueuePriority, number> = {
  CRITICA: 0,
  ALTA: 1,
  NORMAL: 2,
  BAJA: 3,
};

export const OPTIMIZERS: { id: string; label: string; hint: string }[] = [
  { id: 'adam', label: 'Adam', hint: 'Converge rápido y tolera tasas moderadas; opción por defecto.' },
  { id: 'adamw', label: 'AdamW', hint: 'Adam con decaimiento de peso desacoplado, estable en redes profundas.' },
  { id: 'rmsprop', label: 'RMSprop', hint: 'Buena inercia en secuencias recurrentes largas.' },
  { id: 'sgd', label: 'SGD', hint: 'Sensible a la tasa: exige ajuste fino y buenas semillas.' },
];

/** Límites por defecto; los vigentes llegan de `GET /config` (M10). */
export const LIMITS = {
  epochs: { min: 1, max: 500 },
  batch: { min: 1, max: 1024 },
  learningRate: { min: 0.000_001, max: 1 },
  /** Horas de cómputo por trabajo antes de que el worker lo corte. */
  maxGpuHours: 24,
};

/** Segundos por época con lote 64 cuando aún no hay historial. Medidos con los datasets demo
    en un worker de CPU; el historial real del proyecto reemplaza estos valores en cuanto existe. */
const FAMILY_EPOCH_SECONDS: Record<NetworkFamily, number> = {
  FEEDFORWARD: 0.25,
  RNN: 1.0,
  CNN: 0.8,
  GAN: 1.5,
};

/** Un lote más chico da más pasos por época: el tiempo crece de forma sublineal. */
const batchFactor = (fromBatch: number, toBatch: number) => Math.pow(Math.max(1, fromBatch) / Math.max(1, toBatch), 0.45);

/* --------------------------------------------------------------------- permisos */

export type TrainingPermission = 'lanzar' | 'priorizar' | 'adelantar' | 'cancelar' | 'reintentar';

const PERMISSIONS: Record<TrainingPermission, { roles: UserRole[]; note: string }> = {
  lanzar: {
    roles: ['admin', 'owner', 'engineer'],
    note: 'Requiere proyecto, arquitectura y dataset validados (§10).',
  },
  priorizar: {
    roles: ['admin', 'owner'],
    note: 'Reasignar prioridad a un trabajo ajeno corresponde a la responsabilidad del proyecto.',
  },
  adelantar: {
    roles: ['admin'],
    note: 'Forzar el inicio de un trabajo ajeno salta el orden de la cola; sólo administración.',
  },
  cancelar: {
    roles: ['admin', 'owner', 'engineer'],
    note: 'Es una solicitud: el worker confirma el estado final y registra el motivo (RN-05).',
  },
  reintentar: {
    roles: ['admin', 'owner', 'engineer'],
    note: 'El reintento crea un trabajo nuevo y conserva la trazabilidad del original.',
  },
};

const PERMISSION_LABEL: Record<TrainingPermission, string> = {
  lanzar: 'Encolar ejecución',
  priorizar: 'Cambiar prioridad',
  adelantar: 'Iniciar sin esperar turno',
  cancelar: 'Solicitar cancelación',
  reintentar: 'Reintentar',
};

export const PERMISSION_ROWS = (Object.keys(PERMISSIONS) as TrainingPermission[]).map((id) => ({
  id,
  label: PERMISSION_LABEL[id],
  roles: PERMISSIONS[id].roles,
  note: PERMISSIONS[id].note,
}));

/** Forma corta del nombre, la que usan los registros de auditoría: "Ana Quispe Ramos" → "A. Quispe". */
export function shortName(displayName: string): string {
  const parts = displayName.trim().split(/\s+/);
  return parts.length < 2 ? displayName : `${parts[0].slice(0, 1)}. ${parts[1]}`;
}

/** Un dueño siempre opera sobre sus propios trabajos; los ajenos siguen la matriz. */
const SELF_ALLOWED: TrainingPermission[] = ['cancelar', 'reintentar', 'adelantar'];

export function can(
  actor: Actor,
  permission: TrainingPermission,
  options: { mine?: boolean } = {},
): boolean {
  if (options.mine && SELF_ALLOWED.includes(permission)) return true;
  return PERMISSIONS[permission].roles.includes(actor.role);
}

export function maxPriorityFor(actor: Actor): QueuePriority {
  if (actor.role === 'admin' || actor.role === 'owner') return 'CRITICA';
  if (actor.role === 'engineer') return 'ALTA';
  return 'NORMAL';
}

/** Versión del artefacto: el sufijo `vN` de la arquitectura es la que registra M08. */
export function versionFor(architectureName: string): string {
  const match = /v(\d+(?:\.\d+)?)/i.exec(architectureName);
  return match ? `v${match[1]}` : 'v1';
}

/* ------------------------------------------------------------------ validación */

export interface LaunchIssues {
  errors: Partial<Record<keyof LaunchValues, string>>;
  warnings: Partial<Record<keyof LaunchValues, string>>;
}

export function toNumber(raw: string): number {
  return Number(raw.replace(',', '.'));
}

function isPowerOfTwo(value: number): boolean {
  return value > 0 && (value & (value - 1)) === 0;
}

export function validateLaunch(
  values: LaunchValues,
  actor: Actor,
  limits: { epochs: number; batch: number } = { epochs: LIMITS.epochs.max, batch: LIMITS.batch.max },
): LaunchIssues {
  const errors: LaunchIssues['errors'] = {};
  const warnings: LaunchIssues['warnings'] = {};

  if (!values.projectId) errors.projectId = 'Seleccione el proyecto dueño de la ejecución (§10).';
  if (!values.architecture) errors.architecture = 'Sin arquitectura validada no hay grafo que compilar: créela en M04.';
  if (!values.dataset) errors.dataset = 'Indique el dataset de entrenamiento y validación; se registra en M05.';
  else if (!values.targetColumn) errors.targetColumn = 'Elija la columna objetivo que el modelo debe predecir.';

  const epochs = toNumber(values.epochs);
  if (!values.epochs.trim()) errors.epochs = 'Las épocas son obligatorias.';
  else if (!Number.isFinite(epochs) || !Number.isInteger(epochs)) errors.epochs = 'Use un número entero de épocas.';
  else if (epochs < LIMITS.epochs.min) errors.epochs = `Mínimo ${LIMITS.epochs.min} época.`;
  else if (epochs > limits.epochs) errors.epochs = `El límite por trabajo es ${limits.epochs} épocas.`;

  const batch = toNumber(values.batch);
  if (!values.batch.trim()) errors.batch = 'El tamaño de lote es obligatorio.';
  else if (!Number.isFinite(batch) || !Number.isInteger(batch)) errors.batch = 'Use un número entero de muestras por lote.';
  else if (batch < LIMITS.batch.min || batch > limits.batch) {
    errors.batch = `El lote debe estar entre ${LIMITS.batch.min} y ${limits.batch}.`;
  } else if (!isPowerOfTwo(batch)) {
    warnings.batch = 'Los lotes de tamaño binario aprovechan mejor la memoria.';
  }

  const rate = toNumber(values.learningRate);
  if (!values.learningRate.trim()) errors.learningRate = 'La tasa de aprendizaje es obligatoria.';
  else if (!Number.isFinite(rate) || rate <= 0) errors.learningRate = 'Use un valor positivo.';
  else if (rate > LIMITS.learningRate.max) errors.learningRate = `Máximo ${LIMITS.learningRate.max}.`;
  else if (values.optimizer === 'sgd' && rate > 0.05) {
    warnings.learningRate = 'SGD con una tasa tan alta suele hacer explotar los gradientes.';
  }

  const seed = toNumber(values.seed);
  if (!values.seed.trim()) errors.seed = 'La semilla es obligatoria para reproducir la ejecución.';
  else if (!Number.isInteger(seed) || seed < 0) errors.seed = 'Use un entero mayor o igual que 0.';

  if (PRIORITY_RANK[values.priority] < PRIORITY_RANK[maxPriorityFor(actor)]) {
    errors.priority = `Su rol permite como máximo prioridad ${PRIORITY_LABEL[maxPriorityFor(actor)]}.`;
  }

  return { errors, warnings };
}

/* ------------------------------------------------------------------- estimación */

export interface Estimate {
  epochSeconds: number;
  totalSeconds: number;
  gpuHours: number;
  overLimit: boolean;
  /** De dónde sale la cifra, para mostrarlo junto a ella. */
  basis: string;
}

/** Qué se va a entrenar, para buscar ejecuciones comparables en el historial. */
export interface EstimateTarget {
  family: NetworkFamily;
  architectureName?: string;
  projectId?: string;
}

function median(values: number[]): number {
  const sorted = [...values].sort((a, b) => a - b);
  const mid = Math.floor(sorted.length / 2);
  return sorted.length % 2 ? sorted[mid] : (sorted[mid - 1] + sorted[mid]) / 2;
}

/** Segundos por época medidos en un trabajo terminado, llevados al lote que se va a usar. */
function measuredPace(job: TrainingJob, batch: number): number | null {
  if (job.epoch <= 0 || job.durationSeconds <= 0 || !['COMPLETED', 'CANCELLED'].includes(job.status)) return null;
  return (job.durationSeconds / job.epoch) * batchFactor(job.batch, batch);
}

/**
 * Ritmo esperado antes de lanzar. Usa, en este orden: entrenamientos anteriores de la misma
 * arquitectura en el proyecto, de la misma familia, o un valor de referencia. La duración real
 * la publica el worker época a época.
 */
export function estimate(target: EstimateTarget, batch: number, epochs: number, history: TrainingJob[] = []): Estimate {
  const sameArchitecture = history.filter(
    (job) => job.projectId === target.projectId && job.architectureName === target.architectureName,
  );
  const sameFamily = history.filter((job) => job.family === target.family);
  const paces = (jobs: TrainingJob[]) => jobs.map((job) => measuredPace(job, batch)).filter((v): v is number => v !== null);

  let raw: number;
  let basis: string;
  const own = paces(sameArchitecture);
  const family = paces(sameFamily);
  if (own.length) {
    raw = median(own);
    basis = `según ${own.length} entrenamiento${own.length === 1 ? '' : 's'} anterior${own.length === 1 ? '' : 'es'} de esta arquitectura`;
  } else if (family.length) {
    raw = median(family);
    basis = `según ${family.length} entrenamiento${family.length === 1 ? '' : 's'} de la misma familia`;
  } else {
    raw = FAMILY_EPOCH_SECONDS[target.family] * batchFactor(64, batch);
    basis = 'valor de referencia: aún no hay entrenamientos comparables';
  }
  const epochSeconds = Math.max(0.1, Math.round(raw * 10) / 10);
  const totalSeconds = epochSeconds * Math.max(1, epochs);
  const gpuHours = totalSeconds / 3600;
  return { epochSeconds, totalSeconds, gpuHours, overLimit: gpuHours > LIMITS.maxGpuHours, basis };
}

/* ---------------------------------------------------------------- acciones (RN-02) */

export type OutcomeTone = 'success' | 'info' | 'danger';

/** Resultado de una acción de la consola: se muestra en la banda de avisos. */
export interface LaunchOutcome {
  ok: boolean;
  tone: OutcomeTone;
  message: string;
  /** Identificador del trabajo nuevo, cuando la acción creó uno. */
  jobId?: string;
}

/* ------------------------------------------------------------------- lecturas UI */

/** Campos de trazabilidad que la API añade a `TrainingJob`. */
interface TracedJob extends TrainingJob {
  architectureVersion?: number;
  priority?: QueuePriority;
  learningRate?: number;
  seed?: number;
  retryOfId?: string | null;
  statusReason?: string | null;
  classWeight?: 'none' | 'balanced';
  threshold?: number | null;
}

/** Registro de un trabajo de la API: parámetros y motivo de cierre persistidos. */
export function apiRecord(job: TrainingJob): RunRecord {
  const traced = job as TracedJob;
  return {
    jobId: job.id,
    origin: 'plataforma',
    version: traced.architectureVersion ? `v${traced.architectureVersion}` : versionFor(job.architectureName),
    priority: traced.priority ?? 'NORMAL',
    learningRate: traced.learningRate ?? 0,
    seed: traced.seed ?? 0,
    classWeight: traced.classWeight,
    threshold: traced.threshold ?? null,
    owner: job.owner,
    retryOf: traced.retryOfId ?? undefined,
    motivo: traced.statusReason ?? undefined,
    logs: [],
    metrics: [],
  };
}

/** Punto de acceso único: registro ya construido o reconstruido desde el trabajo. El
   resultado se memoriza por objeto para que la misma fila conserve identidad estable. */
const recordCache = new WeakMap<TrainingJob, RunRecord>();

export function recordFor(job: TrainingJob, records: RunStore): RunRecord {
  const own = records[job.id];
  if (own) return own;
  const cached = recordCache.get(job);
  if (cached) return cached;
  const built = apiRecord(job);
  recordCache.set(job, built);
  return built;
}

/** Estados que aún no han cerrado (RN-02). */
export function isActive(status: JobStatus): boolean {
  return status === 'QUEUED' || status === 'PREPARING' || status === 'RUNNING';
}

/** Sólo estos ocupan un worker; en cola no consume capacidad. */
export function isOccupying(status: JobStatus): boolean {
  return status === 'PREPARING' || status === 'RUNNING';
}
