import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { Actor, TrainingJob } from '@/types/domain';
import { usePlatformData } from '@/app/providers';
import { useSession } from '@/app/session';
import { trainingApi } from '@/lib/api/resources';
import type { ApiTrainingJob } from '@/lib/api/resources';
import { useCatalog } from '@/lib/api/useCatalog';
import { formatNumber } from '@/lib/format';
import {
  can,
  estimate,
  isActive,
  isOccupying,
  recordFor,
  shortName,
  toNumber,
  validateLaunch,
} from '@/features/training/model';
import type {
  LaunchOutcome,
  LaunchValues,
  ProjectOption,
  QueuePriority,
  RunRecord,
  RunStore,
} from '@/features/training/model';

/* Estado compartido de M06 sobre la API. La lista de trabajos se consulta con más
   frecuencia mientras haya alguno activo; el detalle del trabajo seleccionado llega
   por SSE (`useJobStream`). Toda acción la valida y aplica el backend. */

const ACTIVE_POLL_MS = 2000;
const IDLE_POLL_MS = 8000;

function failure(caught: unknown): LaunchOutcome {
  return { ok: false, tone: 'danger', message: caught instanceof Error ? caught.message : 'La API rechazó la acción.' };
}

function firstError(issues: Partial<Record<keyof LaunchValues, string>>): string {
  const found = Object.values(issues).find((value) => Boolean(value));
  return found ?? 'Revise la configuración antes de encolar.';
}

/** La interfaz compara responsables por nombre corto ("A. Quispe"), como en la auditoría. */
function adapt(job: ApiTrainingJob): ApiTrainingJob {
  return { ...job, owner: shortName(job.owner) };
}

export interface TrainingModel {
  actor: Actor;
  jobs: TrainingJob[];
  /** Registros conocidos por trabajo; M09 los usa para trazas y semillas. */
  records: RunStore;
  projects: ProjectOption[];
  limits: { epochs: number; batch: number };
  freeWorkers: number;
  busyWorkers: number;
  status: 'loading' | 'ready' | 'error';
  error: string | null;
  lastUpdated: string | null;
  pendingCancellation: string | null;
  refresh: () => void;
  recordOf: (job: TrainingJob) => RunRecord;
  launch: (values: LaunchValues) => Promise<LaunchOutcome>;
  cancel: (job: TrainingJob, motivo: string) => Promise<LaunchOutcome>;
  retry: (job: TrainingJob) => Promise<LaunchOutcome>;
  changePriority: (job: TrainingJob, priority: QueuePriority) => Promise<LaunchOutcome>;
  start: (job: TrainingJob) => Promise<LaunchOutcome>;
}

export function useTrainingRuns(): TrainingModel {
  const { actor, config } = useSession();
  const { snapshot, refresh: refreshPlatform } = usePlatformData();
  const catalog = useCatalog();
  const [jobs, setJobs] = useState<ApiTrainingJob[]>([]);
  const [status, setStatus] = useState<TrainingModel['status']>('loading');
  const [error, setError] = useState<string | null>(null);
  const [lastUpdated, setLastUpdated] = useState<string | null>(null);
  const [pendingCancellation, setPendingCancellation] = useState<string | null>(null);
  const hasActive = useRef(false);

  const load = useCallback(async () => {
    try {
      const next = (await trainingApi.list()).map(adapt);
      setJobs(next);
      hasActive.current = next.some((job) => isActive(job.status));
      setError(null);
      setStatus('ready');
      setLastUpdated(new Date().toISOString());
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'No fue posible leer la cola.');
      setStatus((current) => (current === 'ready' ? 'ready' : 'error'));
    }
  }, []);

  /* Sondeo adaptativo: rápido con trabajos activos, lento en reposo, pausado en segundo plano. */
  useEffect(() => {
    let timer: number | undefined;
    let stopped = false;
    const tick = async () => {
      if (document.visibilityState === 'visible') await load();
      if (!stopped) timer = window.setTimeout(tick, hasActive.current ? ACTIVE_POLL_MS : IDLE_POLL_MS);
    };
    void tick();
    return () => {
      stopped = true;
      window.clearTimeout(timer);
    };
  }, [load]);

  const refresh = useCallback(() => {
    void load();
    void catalog.reload();
    refreshPlatform();
  }, [load, catalog, refreshPlatform]);

  const ordered = useMemo<TrainingJob[]>(
    () =>
      [...jobs].sort((a, b) => {
        const byActivity = Number(isActive(b.status)) - Number(isActive(a.status));
        if (byActivity !== 0) return byActivity;
        return Date.parse(b.queuedAt) - Date.parse(a.queuedAt);
      }),
    [jobs],
  );

  const records = useMemo<RunStore>(
    () => Object.fromEntries(ordered.map((job) => [job.id, recordFor(job, {})])),
    [ordered],
  );
  const recordOf = useCallback((job: TrainingJob) => records[job.id] ?? recordFor(job, {}), [records]);

  /* Catálogo del formulario: arquitecturas guardadas en M04 y versión vigente de cada dataset de M05. */
  const projects = useMemo<ProjectOption[]>(
    () =>
      catalog.projects.map((project) => ({
        id: project.id,
        name: project.name,
        canLaunch: project.permissions.includes('training.launch') && project.status !== 'ARCHIVED',
        architectures: catalog.architectures
          .filter((item) => item.projectId === project.id)
          .map((item) => {
            const last = item.config.layers[item.config.layers.length - 1];
            return {
              id: item.id,
              name: item.name,
              family: item.family,
              version: item.version,
              trainable: item.trainable,
              outputUnits: last?.type === 'Dense' ? last.units ?? null : null,
            };
          }),
        datasets: catalog.datasets
          .filter((item) => item.projectId === project.id && item.status === 'READY')
          .map((item) => ({ id: item.latestId, name: item.name, version: item.currentVersion, columns: item.columnSchema })),
      })),
    [catalog.projects, catalog.architectures, catalog.datasets],
  );

  const busyWorkers = jobs.filter((job) => isOccupying(job.status)).length;
  const online = snapshot?.health.workersOnline ?? 0;
  const limits = { epochs: config.maxEpochs, batch: config.maxBatchSize };

  const launch = useCallback(
    async (values: LaunchValues): Promise<LaunchOutcome> => {
      const issues = validateLaunch(values, actor, limits);
      if (Object.keys(issues.errors).length > 0) {
        return { ok: false, tone: 'danger', message: firstError(issues.errors) };
      }
      if (!can(actor, 'lanzar')) {
        return { ok: false, tone: 'danger', message: 'Su rol no permite encolar entrenamientos; solicite el acceso en M10.' };
      }
      try {
        const job = await trainingApi.launch(values.projectId, {
          architectureId: values.architecture,
          datasetId: values.dataset,
          targetColumn: values.targetColumn,
          epochs: Math.round(toNumber(values.epochs)),
          batchSize: Math.round(toNumber(values.batch)),
          optimizer: values.optimizer,
          learningRate: toNumber(values.learningRate),
          seed: Math.round(toNumber(values.seed)),
          priority: values.priority,
        });
        await load();
        refreshPlatform();
        const pace = estimate(job.family, job.batch, job.epochs);
        return {
          ok: true,
          tone: 'success',
          jobId: job.id,
          message: `${job.id} encolado · ${job.epochs} épocas · objetivo «${job.targetColumn}» · ~${formatNumber(pace.epochSeconds, 1)} s por época. ${
            online === 0 ? 'No hay workers en línea: el trabajo espera hasta que arranque uno.' : 'El worker lo tomará en cuanto quede libre.'
          }`,
        };
      } catch (caught) {
        return failure(caught);
      }
    },
    [actor, limits.epochs, limits.batch, load, refreshPlatform, online],
  );

  const cancel = useCallback(
    async (job: TrainingJob, motivo: string): Promise<LaunchOutcome> => {
      setPendingCancellation(job.id);
      try {
        const result = await trainingApi.cancel(job.id, motivo || 'Cancelado desde la consola.');
        await load();
        refreshPlatform();
        return result.status === 'CANCELLED'
          ? { ok: true, tone: 'info', message: `${job.id} estaba en cola y quedó cancelado.` }
          : { ok: true, tone: 'info', message: `Cancelación de ${job.id} solicitada; el worker la confirma al cerrar la época en curso (RN-05).` };
      } catch (caught) {
        return failure(caught);
      } finally {
        setPendingCancellation(null);
      }
    },
    [load, refreshPlatform],
  );

  const retry = useCallback(
    async (job: TrainingJob): Promise<LaunchOutcome> => {
      try {
        const created = await trainingApi.retry(job.id);
        await load();
        return {
          ok: true,
          tone: 'success',
          jobId: created.id,
          message: `${created.id} encolado como reintento ${created.attempt} de ${job.id}; el original conserva su registro.`,
        };
      } catch (caught) {
        return failure(caught);
      }
    },
    [load],
  );

  const changePriority = useCallback(
    async (job: TrainingJob, priority: QueuePriority): Promise<LaunchOutcome> => {
      try {
        await trainingApi.priority(job.id, priority);
        await load();
        return { ok: true, tone: 'info', message: `${job.id} pasa a prioridad ${priority}.` };
      } catch (caught) {
        return failure(caught);
      }
    },
    [load],
  );

  const start = useCallback(
    async (job: TrainingJob): Promise<LaunchOutcome> => {
      try {
        await trainingApi.start(job.id);
        await load();
        return { ok: true, tone: 'info', message: `${job.id} pasa al frente de la cola: el próximo worker libre lo toma.` };
      } catch (caught) {
        return failure(caught);
      }
    },
    [load],
  );

  return {
    actor,
    jobs: ordered,
    records,
    projects,
    limits,
    freeWorkers: Math.max(0, online - busyWorkers),
    busyWorkers,
    status,
    error: error ?? catalog.error,
    lastUpdated,
    pendingCancellation,
    refresh,
    recordOf,
    launch,
    cancel,
    retry,
    changePriority,
    start,
  };
}

export type { LaunchOutcome, QueuePriority, RunRecord, RunStore };
