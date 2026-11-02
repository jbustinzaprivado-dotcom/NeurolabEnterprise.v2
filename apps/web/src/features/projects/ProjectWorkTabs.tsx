import { useMemo, useState } from 'react';
import type { ReactNode } from 'react';
import { Link } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import type { ProjectRecord } from '@/types/project';
import type { TrainingJob } from '@/types/domain';
import { invalidateTraining, queryKeys } from '@/lib/api/queryClient';
import { modelsApi, trainingApi } from '@/lib/api/resources';
import type { ApiModelVersion, ApiTrainingJob } from '@/lib/api/resources';
import { useCatalog } from '@/lib/api/useCatalog';
import { familyMeta } from '@/lib/nav';
import { formatDateTime, formatDuration, formatNumber, formatRelativeTime } from '@/lib/format';
import { Chip, StatusChip } from '@/components/ui/Chip';
import { Icon } from '@/components/ui/Icon';
import { formatBytes, formatRows } from '@/features/datasets/model';
import { shortName } from '@/features/training/model';
import { STATUS_META, headlineMetric } from '@/features/model-registry/model';

/* Pestañas de trabajo de la ficha de proyecto (§7): Arquitectura, Dataset, Entrenamientos,
   Modelos e Historial. Muestran lo que el proyecto ya tiene con los mismos datos y cachés
   que M04–M08; para crear o cambiar algo se va al módulo correspondiente, donde la API
   vuelve a comprobar permisos. */

interface TabProps {
  project: ProjectRecord;
  permissions: string[];
}

const ACTIVE = new Set(['QUEUED', 'PREPARING', 'RUNNING']);

function Empty({ icon, title, text, action }: { icon: Parameters<typeof Icon>[0]['name']; title: string; text: string; action?: ReactNode }) {
  return (
    <div className="empty pj-work-empty">
      <Icon name={icon} />
      <h3>{title}</h3>
      <p>{text}</p>
      {action}
    </div>
  );
}

function ModuleLink({ to, label }: { to: string; label: string }) {
  return (
    <Link to={to} className="pj-link">
      {label}
      <Icon name="arrowRight" size={13} />
    </Link>
  );
}

function Loading() {
  return <p className="pj-muted" aria-busy="true">Cargando…</p>;
}

/** Trabajos del proyecto; comparte la caché de M06 para no repetir la consulta. */
function useProjectJobs(projectId: string) {
  // Misma clave y misma forma de datos que useTrainingRuns (M06).
  const query = useQuery({
    queryKey: queryKeys.trainingJobs,
    queryFn: async () => (await trainingApi.list()).map((job) => ({ ...job, owner: shortName(job.owner) })),
  });
  const jobs = useMemo(
    () => (query.data ?? []).filter((job) => job.projectId === projectId),
    [query.data, projectId],
  );
  return { jobs, loading: !query.data && !query.isError, error: query.error instanceof Error ? query.error.message : null };
}

function useProjectModels(projectId: string) {
  const query = useQuery({
    queryKey: [...queryKeys.models, projectId],
    queryFn: () => modelsApi.listForProject(projectId),
  });
  return { models: query.data ?? [], loading: !query.data && !query.isError };
}

/* ------------------------------------------------------------- Arquitectura */

export function ProjectArchitecturesTab({ project }: TabProps) {
  const catalog = useCatalog();
  const rows = catalog.architectures
    .filter((item) => item.projectId === project.id)
    .sort((a, b) => a.name.localeCompare(b.name) || b.version - a.version);

  if (catalog.status === 'loading') return <Loading />;
  if (rows.length === 0) {
    return (
      <Empty icon="layers" title="Sin arquitecturas" text="Diseña la red del proyecto en el M04; cada guardado crea una versión."
        action={<ModuleLink to="/architectures" label="Ir al diseñador" />} />
    );
  }
  return (
    <div className="pj-work">
      <div className="pj-block__head">
        <h3>{rows.length} {rows.length === 1 ? 'versión de arquitectura' : 'versiones de arquitectura'}</h3>
        <ModuleLink to="/architectures" label="Abrir el diseñador" />
      </div>
      <table className="table pj-work-table">
        <caption className="u-sr-only">Arquitecturas del proyecto con familia, capas, parámetros y estado de entrenamiento</caption>
        <thead>
          <tr>
            <th scope="col">Arquitectura</th>
            <th scope="col">Familia</th>
            <th scope="col">Capas</th>
            <th scope="col">Parámetros</th>
            <th scope="col">Entrenable</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((item) => (
            <tr key={item.id}>
              <td data-label="Arquitectura">
                <strong>{item.name} v{item.version}</strong>
                <span className="table__sub">{formatRelativeTime(item.createdAt)}</span>
              </td>
              <td data-label="Familia">{familyMeta[item.family].label}</td>
              <td data-label="Capas" data-numeric>{item.config.layers.length}</td>
              <td data-label="Parámetros" data-numeric>{formatNumber(item.summary.totalParams)}</td>
              <td data-label="Entrenable">
                {item.trainable ? <Chip tone="completed">Sí</Chip> : <Chip tone="outline">Documentada</Chip>}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/* ------------------------------------------------------------------ Dataset */

export function ProjectDatasetsTab({ project }: TabProps) {
  const catalog = useCatalog();
  const rows = catalog.datasetRows
    .filter((item) => item.projectId === project.id && item.status !== 'DELETED')
    .sort((a, b) => a.name.localeCompare(b.name) || b.version - a.version);

  if (catalog.status === 'loading') return <Loading />;
  if (rows.length === 0) {
    return (
      <Empty icon="dataset" title="Sin datasets" text="Registra un CSV en el M05 y declara sus particiones antes de entrenar."
        action={<ModuleLink to="/datasets" label="Ir a datasets" />} />
    );
  }
  return (
    <div className="pj-work">
      <div className="pj-block__head">
        <h3>{rows.length} {rows.length === 1 ? 'versión de dataset' : 'versiones de dataset'}</h3>
        <ModuleLink to="/datasets" label="Abrir datasets" />
      </div>
      <table className="table pj-work-table">
        <caption className="u-sr-only">Datasets del proyecto con filas, columnas, tamaño, particiones y estado</caption>
        <thead>
          <tr>
            <th scope="col">Dataset</th>
            <th scope="col">Filas × columnas</th>
            <th scope="col">Tamaño</th>
            <th scope="col">Particiones</th>
            <th scope="col">Estado</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((item) => (
            <tr key={item.id}>
              <td data-label="Dataset">
                <strong>{item.name} v{item.version}</strong>
                <span className="table__sub">{item.license || 'Sin licencia declarada'}</span>
              </td>
              <td data-label="Filas × columnas" data-numeric>{formatRows(item.rows)} × {item.columns}</td>
              <td data-label="Tamaño" data-numeric>{formatBytes(item.sizeBytes)}</td>
              <td data-label="Particiones" data-numeric>
                {Math.round(item.split.train * 100)} / {Math.round(item.split.validation * 100)} / {Math.round(item.split.test * 100)}
              </td>
              <td data-label="Estado">
                {item.status === 'READY' ? <Chip tone="completed">Listo</Chip> : <Chip tone="failed">Retenido</Chip>}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/* ----------------------------------------------------------- Entrenamientos */

export function ProjectTrainingTab({ project, permissions }: TabProps) {
  const { jobs, loading, error } = useProjectJobs(project.id);
  const active = jobs.filter((job) => ACTIVE.has(job.status));
  const finished = jobs.length - active.length;
  const canLaunch = permissions.includes('training.launch') && project.status !== 'ARCHIVED';

  if (loading) return <Loading />;
  if (error) return <p className="pj-muted" role="alert">{error}</p>;
  return (
    <div className="pj-work">
      <div className="pj-block__head">
        <h3>
          {active.length} {active.length === 1 ? 'entrenamiento activo' : 'entrenamientos activos'} · {finished}{' '}
          {finished === 1 ? 'terminado' : 'terminados'}
        </h3>
        <ModuleLink to="/training" label={canLaunch ? 'Encolar en M06' : 'Abrir entrenamientos'} />
      </div>
      {active.length === 0 ? (
        <Empty icon="training" title="Sin entrenamientos activos"
          text={finished > 0 ? 'Los trabajos terminados están en la pestaña Historial.' : 'Este proyecto aún no tiene entrenamientos.'} />
      ) : (
        <ul className="pj-run-list">
          {active.map((job) => (
            <li key={job.id} className="pj-run">
              <span className="pj-run__head">
                <strong>{job.architectureName}</strong>
                <StatusChip status={job.status} />
              </span>
              <span className="table__sub">
                {job.id} · {job.datasetName} · {job.owner}
              </span>
              <span className="pj-run__progress" aria-label={`Progreso ${Math.round(job.progress)} %`}>
                <span style={{ width: `${Math.min(100, job.progress)}%` }} />
              </span>
              <span className="table__sub">
                {job.status === 'QUEUED'
                  ? `En cola desde ${formatRelativeTime(job.queuedAt)}`
                  : `Época ${job.epoch} de ${job.epochs} · pérdida ${formatNumber(job.loss, 4)}`}
                {job.cancelRequested ? ' · cancelación solicitada' : ''}
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

/* ------------------------------------------------------------------ Modelos */

export function ProjectModelsTab({ project }: TabProps) {
  const { models, loading } = useProjectModels(project.id);
  const rows = [...models].sort((a, b) => Date.parse(b.createdAt) - Date.parse(a.createdAt));

  if (loading) return <Loading />;
  if (rows.length === 0) {
    return (
      <Empty icon="model" title="Sin versiones de modelo" text="Cada entrenamiento completado registra aquí una versión inmutable."
        action={<ModuleLink to="/models" label="Ir al registro" />} />
    );
  }
  return (
    <div className="pj-work">
      <div className="pj-block__head">
        <h3>{rows.length} {rows.length === 1 ? 'versión registrada' : 'versiones registradas'}</h3>
        <ModuleLink to="/models" label="Revisar en el registro" />
      </div>
      <table className="table pj-work-table">
        <caption className="u-sr-only">Versiones de modelo del proyecto con estado, métrica de prueba y fecha</caption>
        <thead>
          <tr>
            <th scope="col">Modelo</th>
            <th scope="col">Estado</th>
            <th scope="col">Métrica de prueba</th>
            <th scope="col" className="is-right">Registrado</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((model) => {
            const metric = headlineMetric(model.metrics);
            return (
              <tr key={model.id}>
                <td data-label="Modelo">
                  <strong>{model.name} {model.label}</strong>
                  <span className="table__sub">{model.jobId}</span>
                </td>
                <td data-label="Estado">
                  <Chip tone={STATUS_META[model.status].tone} dot>{STATUS_META[model.status].label}</Chip>
                </td>
                <td data-label="Métrica" data-numeric>
                  {metric ? (
                    <>
                      {metric.value}
                      <span className="metric-cell__label">{metric.label}</span>
                    </>
                  ) : '—'}
                </td>
                <td data-label="Registrado" className="is-right" data-numeric>{formatRelativeTime(model.createdAt)}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

/* ---------------------------------------------------------------- Historial */

function durationOf(job: TrainingJob): number {
  if (job.durationSeconds) return job.durationSeconds;
  if (job.startedAt && job.endedAt) return (Date.parse(job.endedAt) - Date.parse(job.startedAt)) / 1000;
  return 0;
}

export function ProjectHistoryTab({ project, permissions }: TabProps) {
  const { jobs, loading, error } = useProjectJobs(project.id);
  const { models } = useProjectModels(project.id);
  const [notice, setNotice] = useState<{ tone: 'success' | 'danger'; text: string } | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const versionOf = useMemo(() => new Map(models.map((model: ApiModelVersion) => [model.jobId, model])), [models]);
  const rows = jobs
    .filter((job) => !ACTIVE.has(job.status))
    .sort((a, b) => Date.parse(b.endedAt ?? b.queuedAt) - Date.parse(a.endedAt ?? a.queuedAt));
  const canRetry = permissions.includes('training.launch') && project.status !== 'ARCHIVED';
  const canExport = permissions.includes('report.export');

  async function retry(job: ApiTrainingJob) {
    setBusy(job.id);
    setNotice(null);
    try {
      const clone = await trainingApi.retry(job.id);
      setNotice({ tone: 'success', text: `Reintento encolado como ${clone.id}; síguelo en la pestaña Entrenamientos.` });
      await invalidateTraining();
    } catch (caught) {
      setNotice({ tone: 'danger', text: caught instanceof Error ? caught.message : 'La API rechazó el reintento.' });
    } finally {
      setBusy(null);
    }
  }

  async function exportCsv() {
    try {
      await trainingApi.historyCsv(project.id);
    } catch (caught) {
      setNotice({ tone: 'danger', text: caught instanceof Error ? caught.message : 'No fue posible exportar el historial.' });
    }
  }

  if (loading) return <Loading />;
  if (error) return <p className="pj-muted" role="alert">{error}</p>;
  if (rows.length === 0) {
    return <Empty icon="clock" title="Sin historial" text="Aquí aparecerá cada entrenamiento terminado del proyecto." />;
  }
  return (
    <div className="pj-work">
      <div className="pj-block__head">
        <h3>{rows.length} {rows.length === 1 ? 'ejecución terminada' : 'ejecuciones terminadas'}</h3>
        {canExport ? (
          <button type="button" className="btn btn--secondary btn--sm" onClick={() => void exportCsv()}>
            <Icon name="download" size={14} />
            Exportar CSV
          </button>
        ) : null}
      </div>
      {notice ? (
        <p className={`pj-work-notice pj-work-notice--${notice.tone}`} role={notice.tone === 'danger' ? 'alert' : 'status'}>
          {notice.text}
        </p>
      ) : null}
      <table className="table pj-work-table">
        <caption className="u-sr-only">
          Historial de entrenamientos con fecha, versión, duración, estado, parámetros principales y acciones autorizadas
        </caption>
        <thead>
          <tr>
            <th scope="col">Fecha</th>
            <th scope="col">Ejecución y versión</th>
            <th scope="col">Duración</th>
            <th scope="col">Estado</th>
            <th scope="col">Parámetros</th>
            <th scope="col" className="is-right">Acciones</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((job) => {
            const model = versionOf.get(job.id);
            const retryable = job.status === 'FAILED' || job.status === 'CANCELLED';
            return (
              <tr key={job.id}>
                <td data-label="Fecha" data-numeric>{formatDateTime(job.endedAt ?? job.queuedAt)}</td>
                <td data-label="Ejecución">
                  <strong>{job.architectureName} v{job.architectureVersion}</strong>
                  <span className="table__sub">
                    {job.id} · {model ? `modelo ${model.label}` : 'sin modelo'} · {job.datasetName} v{job.datasetVersion}
                  </span>
                </td>
                <td data-label="Duración" data-numeric>{formatDuration(durationOf(job))}</td>
                <td data-label="Estado">
                  <StatusChip status={job.status} />
                  {job.statusReason && job.status !== 'COMPLETED' ? (
                    <span className="table__sub">{job.statusReason}</span>
                  ) : null}
                </td>
                <td data-label="Parámetros">
                  <span className="table__sub pj-params">
                    {job.epoch}/{job.epochs} épocas · lote {job.batch} · {job.optimizer} · lr {job.learningRate} · semilla {job.seed}
                  </span>
                </td>
                <td data-label="Acciones" className="is-right">
                  <span className="pj-row-actions">
                    {job.status === 'COMPLETED' ? <ModuleLink to="/evaluation" label="Evaluación" /> : null}
                    {retryable && canRetry ? (
                      <button type="button" className="btn btn--ghost btn--sm" disabled={busy === job.id}
                        onClick={() => void retry(job)}>
                        <Icon name="refresh" size={13} />
                        {busy === job.id ? 'Encolando…' : 'Reintentar'}
                      </button>
                    ) : null}
                    {!retryable && job.status !== 'COMPLETED' ? '—' : null}
                  </span>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
