import { useCallback, useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import type { Actor, TrainingJob } from '@/types/domain';
import { usePlatformData } from '@/app/providers';
import { useSession } from '@/app/session';
import { invalidateTraining, queryKeys } from '@/lib/api/queryClient';
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
  /** La persona con su rol en el proyecto (owner/engineer/reviewer/reader), que es el que aplica la API. */
  actorFor: (projectId: string) => Actor;
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
  const [pendingCancellation, setPendingCancellation] = useState<string | null>(null);

  /* Los permisos de M06 dependen del rol en cada proyecto, no del rol global (igual que la API);
     la administración conserva su rol en todos. */
  const actorFor = useCallback(
    (projectId: string): Actor => {
      if (actor.role === 'admin') return actor;
      const role = catalog.projects.find((project) => project.id === projectId)?.myRole;
      return { ...actor, role: (role as Actor['role']) ?? 'reader' };
    },
    [actor, catalog.projects],
  );

  /* Sondeo adaptativo: rápido con trabajos activos, lento en reposo, pausado en segundo plano. */
  const query = useQuery({
    queryKey: queryKeys.trainingJobs,
    queryFn: async () => (await trainingApi.list()).map(adapt),
    refetchInterval: (current) =>
      current.state.data?.some((job) => isActive(job.status)) ? ACTIVE_POLL_MS : IDLE_POLL_MS,
    refetchIntervalInBackground: false,
  });
  const jobs = useMemo(() => query.data ?? [], [query.data]);
  const status: TrainingModel['status'] = query.data ? 'ready' : query.isError ? 'error' : 'loading';
  const error = query.error instanceof Error ? query.error.message : null;
  const lastUpdated = query.dataUpdatedAt ? new Date(query.dataUpdatedAt).toISOString() : null;

  /** Tras cada acción se invalida la caché: cola, panel, evaluación y registro se refrescan juntos. */
  const load = useCallback(() => invalidateTraining(), []);

  const reloadCatalog = catalog.reload;
  const refresh = useCallback(() => {
    void load();
    void reloadCatalog();
    refreshPlatform();
  }, [load, reloadCatalog, refreshPlatform]);

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
      const issues = validateLaunch(values, actorFor(values.projectId), limits);
      if (Object.keys(issues.errors).length > 0) {
        return { ok: false, tone: 'danger', message: firstError(issues.errors) };
      }
      if (!can(actorFor(values.projectId), 'lanzar')) {
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
    [actor, actorFor, limits.epochs, limits.batch, load, refreshPlatform, online],
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
    actorFor,
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
