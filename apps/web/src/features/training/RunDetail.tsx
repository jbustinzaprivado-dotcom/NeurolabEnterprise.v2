import { useMemo } from 'react';
import type { Actor, JobStatus, TrainingJob } from '@/types/domain';
import { familyMeta, statusMeta } from '@/lib/nav';
import { formatCountdown, formatDateTime, formatDuration, formatNumber, formatRate } from '@/lib/format';
import { Panel } from '@/components/ui/Panel';
import { Chip, StatusChip } from '@/components/ui/Chip';
import { ProgressBar } from '@/components/ui/Progress';
import { Icon } from '@/components/ui/Icon';
import { LossGainChart, formatAxisAmount, secondaryFor } from '@/components/ui/DataViz';
import { epochMae, formatErrorAmount } from '@/lib/jobMetrics';
import { PRIORITY_LABEL, can, isActive, shortName } from '@/features/training/model';
import type { LogLevel, RunLog, RunRecord } from '@/features/training/model';
import { useJobStream } from '@/features/training/useJobStream';

/* §7 · pantalla de ejecución: estado visible de la máquina RN-02, progreso en tiempo
   real, métricas época a época y los logs recientes que publica el worker. */

const FLOW: JobStatus[] = ['QUEUED', 'PREPARING', 'RUNNING'];

function Machine({ job }: { job: TrainingJob }) {
  const final = !isActive(job.status);
  const reached = final ? FLOW.length : FLOW.indexOf(job.status);
  return (
    <ol className="tr-machine" aria-label={`Estado del trabajo ${job.id} en la máquina de estados RN-02`}>
      {FLOW.map((status, index) => (
        <li key={status} data-done={index < reached || undefined} data-current={index === reached || undefined}>
          <span className="tr-machine__dot" aria-hidden="true">
            {index < reached ? <Icon name="checkCircle" size={13} /> : <span className="tr-machine__num">{index + 1}</span>}
          </span>
          <span className="tr-machine__label">{statusMeta[status].label}</span>
        </li>
      ))}
      <li data-final data-done={final || undefined} data-current={final || undefined}>
        <span className="tr-machine__dot" aria-hidden="true">
          <Icon name={final ? 'checkCircle' : 'clock'} size={13} />
        </span>
        <span className="tr-machine__label">
          {final ? statusMeta[job.status].label : 'Estado final'}
        </span>
      </li>
    </ol>
  );
}

function Stat({ label, value, tone }: { label: string; value: string; tone?: string }) {
  return (
    <div className="metric" data-tone={tone}>
      <span className="metric__label">{label}</span>
      <span className="metric__value u-num">{value}</span>
    </div>
  );
}

const LEVEL_ICON: Record<LogLevel, 'info' | 'alertTriangle' | 'alertCircle' | 'checkCircle'> = {
  info: 'info',
  warn: 'alertTriangle',
  error: 'alertCircle',
  success: 'checkCircle',
};

function Logs({ logs }: { logs: RunLog[] }) {
  const entries = useMemo(() => [...logs].slice(-14).reverse(), [logs]);
  if (entries.length === 0) {
    return <p className="tr-detail__empty">El worker aún no publica eventos para este trabajo.</p>;
  }
  return (
    <div className="tr-log" role="log" aria-live="polite" aria-label="Bitácora reciente del worker">
      {entries.map((entry, index) => (
        <p className="tr-log__line" data-level={entry.level} key={`${entry.at}-${index}`}>
          <span className="tr-log__time u-mono">{formatDateTime(new Date(entry.at).toISOString())}</span>
          <span className="tr-log__source u-mono">{entry.source}</span>
          <Icon name={LEVEL_ICON[entry.level]} size={12} />
          <span className="tr-log__text u-truncate">{entry.text}</span>
        </p>
      ))}
    </div>
  );
}

interface RunDetailProps {
  job: TrainingJob | null;
  record: RunRecord | null;
  actor: Actor;
  actorFor: (projectId: string) => Actor;
  pendingCancellation: string | null;
  onSelectNeighbour: (direction: -1 | 1) => void;
  neighbours: number;
  onCancel: (job: TrainingJob) => void;
  onRetry: (job: TrainingJob) => void;
  /** Se llama cuando el canal SSE informa un cambio de estado, para refrescar la cola. */
  onTransition?: () => void;
}

export function RunDetail({
  job,
  record,
  actor,
  actorFor,
  pendingCancellation,
  onSelectNeighbour,
  neighbours,
  onCancel,
  onRetry,
  onTransition,
}: RunDetailProps) {
  /* Bitácora y curva llegan por SSE (`GET /training-jobs/{id}/events`): el historial
     persistido primero y luego cada época en vivo, sin sondeo. */
  const stream = useJobStream(job?.id ?? null, onTransition);

  if (!job || !record) {
    return (
      <Panel title="Progreso en tiempo real" icon="gauge" subtitle="Seleccione un trabajo de la cola o del historial.">
        <div className="empty">
          <Icon name="training" />
          <h3>Ningún trabajo seleccionado</h3>
          <p>Al encolar una ejecución quedará aquí su estado RN-02, su avance y su bitácora.</p>
        </div>
      </Panel>
    );
  }

  const perEpoch = job.epoch > 0 ? job.durationSeconds / job.epoch : null;
  const remaining = perEpoch !== null ? Math.max(0, (job.epochs - job.epoch) * perEpoch) : null;
  const mine = job.owner === shortName(actor.displayName);
  const points = stream.points;
  const finished = !isActive(job.status);
  /* La época del canal en vivo puede ir por delante del último sondeo de la cola. */
  const liveEpoch = Math.max(job.epoch, points[points.length - 1]?.epoch ?? 0);
  const lastPoint = points[points.length - 1];

  return (
    <Panel
      title={`Ejecución ${job.id}`}
      subtitle={
        <>
          {job.project} · <span className="u-mono">{job.datasetName}</span>
        </>
      }
      icon="gauge"
      actions={
        <>
          <StatusChip status={job.status} />
          <Chip
            tone="outline"
            dot={stream.live}
            pulse={stream.live}
            title={stream.live ? 'Canal SSE abierto: recibe cada época al instante' : 'Historial persistido en la API'}
          >
            {stream.live ? 'En vivo' : 'API'}
          </Chip>
        </>
      }
      footer={
        <>
          <span>
            {finished ? 'Cerrada' : 'En ciclo'} · {job.epoch}/{job.epochs} épocas · {PRIORITY_LABEL[record.priority]}
          </span>
          <a href="/evaluation">Evaluar en M07</a>
        </>
      }
    >
      <div className="tr-detail">
        <Machine job={job} />

        <div className="tr-detail__params">
          <span className="tr-param">
            <em>Arquitectura</em>
            <strong className="u-truncate">{job.architectureName}</strong>
          </span>
          <span className="tr-param">
            <em>Familia</em>
            <strong>{familyMeta[job.family].label}</strong>
          </span>
          <span className="tr-param">
            <em>Versión</em>
            <strong className="u-mono">{record.version}</strong>
          </span>
          <span className="tr-param">
            <em>Épocas</em>
            <strong className="u-num">{formatNumber(job.epochs)}</strong>
          </span>
          <span className="tr-param">
            <em>Lote</em>
            <strong className="u-num">{formatNumber(job.batch)}</strong>
          </span>
          <span className="tr-param">
            <em>Optimizador</em>
            <strong>{job.optimizer}</strong>
          </span>
          <span className="tr-param">
            <em>Tasa</em>
            <strong className="u-num">{formatNumber(record.learningRate, 4)}</strong>
          </span>
          <span className="tr-param">
            <em>Semilla</em>
            <strong className="u-num">{record.seed}</strong>
          </span>
          <span className="tr-param">
            <em>Responsable</em>
            <strong>{job.owner}</strong>
          </span>
        </div>

        <div className="tr-detail__progress">
          <ProgressBar
            value={finished ? job.progress : Math.max(job.progress, Math.min(99, (liveEpoch / job.epochs) * 100))}
            status={job.status}
            label={`Época ${liveEpoch} de ${job.epochs} · lote ${job.batch} · optimizador ${job.optimizer}`}
            aside={
              job.status === 'PREPARING'
                ? 'Preparando datos'
                : job.status === 'QUEUED'
                  ? 'Sin worker asignado'
                  : remaining !== null && job.status === 'RUNNING'
                    ? `Restante ${formatCountdown(remaining)}`
                    : job.durationSeconds > 0
                      ? `Duración ${formatDuration(job.durationSeconds)}`
                      : 'Sin tiempo de cómputo'
            }
            striped={job.status === 'RUNNING'}
          />
          {record.retryOf ? (
            <p className="tr-detail__trace">
              <Icon name="refresh" size={12} />
              Reintento de <strong className="u-mono">{record.retryOf}</strong>; el trabajo original conserva su registro (§10).
            </p>
          ) : null}
          {job.cancelRequested && !finished ? (
            <p className="tr-detail__trace" data-tone="warning">
              <Icon name="clock" size={12} />
              Cancelación solicitada; el worker la confirma al cerrar la época en curso (RN-05).
            </p>
          ) : null}
          {record.motivo && finished ? (
            <p className="tr-detail__trace" data-tone={job.status === 'FAILED' ? 'warning' : undefined}>
              <Icon name={job.status === 'COMPLETED' ? 'checkCircle' : 'alertCircle'} size={12} />
              {job.status === 'COMPLETED' ? record.motivo : `Motivo registrado: ${record.motivo}`}
            </p>
          ) : null}
        </div>

        <div className="tr-detail__metrics">
          <Stat label="loss" value={lastPoint ? formatAxisAmount(lastPoint.loss) : job.epoch > 0 ? formatAxisAmount(job.loss) : '—'} />
          {job.task === 'regression' ? (
            <Stat label="MAE" value={lastPoint ? formatErrorAmount(epochMae(lastPoint, 'train')) : job.mae !== null ? formatErrorAmount(job.mae) : '—'} />
          ) : (
            <Stat label="accuracy" value={lastPoint ? formatRate(lastPoint.accuracy) : job.epoch > 0 ? formatRate(job.accuracy) : '—'} />
          )}
          <Stat label="val loss" value={lastPoint ? formatAxisAmount(lastPoint.valLoss) : job.epoch > 0 ? formatAxisAmount(job.valLoss) : '—'} />
          {job.task === 'regression' ? (
            <Stat label="val MAE" value={lastPoint ? formatErrorAmount(epochMae(lastPoint, 'validation')) : job.valMae !== null ? formatErrorAmount(job.valMae) : '—'} />
          ) : (
            <Stat label="val accuracy" value={lastPoint ? formatRate(lastPoint.valAccuracy) : job.epoch > 0 ? formatRate(job.valAccuracy) : '—'} />
          )}
          <Stat label="época/seg" value={perEpoch !== null ? formatNumber(perEpoch, 1) : '—'} />
          <Stat label="duración" value={job.durationSeconds > 0 ? formatDuration(job.durationSeconds) : '—'} />
        </div>

        <div className="tr-detail__block">
          <p className="u-caps">Curva de pérdida y {job.task === 'regression' ? 'MAE' : 'ganancia'}</p>
          {points.length >= 2 ? (
            <LossGainChart points={points} model={`${job.architectureName} · ${job.optimizer}`} height={208}
              secondary={secondaryFor(job.task)} />
          ) : (
            <div className="skeleton tr-detail__skeleton" aria-hidden="true" />
          )}
          <p className="panel__note">
            <Icon name="info" size={12} />
            La red neuronal se entrena en el worker con TensorFlow/Keras; el navegador únicamente dibuja las
            épocas publicadas por <code>GET /training-jobs/{'{id}'}/events</code> (RN-03).
          </p>
        </div>

        <div className="tr-detail__block">
          <div className="tr-detail__block-head">
            <p className="u-caps">Logs recientes del worker</p>
            <div className="tr-detail__nav">
              <button type="button" className="btn btn--ghost btn--sm btn--icon" onClick={() => onSelectNeighbour(-1)} disabled={neighbours < 2} aria-label="Trabajo anterior">
                <Icon name="chevronDown" size={14} style={{ transform: 'rotate(90deg)' }} />
              </button>
              <button type="button" className="btn btn--ghost btn--sm btn--icon" onClick={() => onSelectNeighbour(1)} disabled={neighbours < 2} aria-label="Trabajo siguiente">
                <Icon name="chevronDown" size={14} style={{ transform: 'rotate(-90deg)' }} />
              </button>
            </div>
          </div>
          <Logs logs={stream.logs} />
        </div>

        <div className="tr-detail__actions">
          {isActive(job.status) ? (
            <button
              type="button"
              className="btn btn--secondary tr-btn-danger"
              onClick={() => onCancel(job)}
              disabled={job.cancelRequested || pendingCancellation === job.id || !can(actorFor(job.projectId), 'cancelar', { mine })}
              title={
                job.cancelRequested
                  ? 'Ya hay una cancelación en curso.'
                  : can(actorFor(job.projectId), 'cancelar', { mine })
                    ? 'Solicitar la interrupción con motivo (RN-05)'
                    : 'Su rol no permite cancelar este trabajo.'
              }
            >
              <Icon name="close" size={15} />
              {job.cancelRequested ? 'Cancelación en curso' : 'Solicitar cancelación'}
            </button>
          ) : job.status === 'FAILED' || job.status === 'CANCELLED' ? (
            <button
              type="button"
              className="btn btn--primary"
              onClick={() => onRetry(job)}
              disabled={!can(actorFor(job.projectId), 'reintentar', { mine })}
              title={can(actorFor(job.projectId), 'reintentar', { mine }) ? 'Encolar una ejecución nueva con estos parámetros' : 'Su rol no permite reintentar este trabajo.'}
            >
              <Icon name="refresh" size={15} />
              Reintentar
            </button>
          ) : null}

          {finished && job.status === 'COMPLETED' ? (
            <a className="btn btn--ghost" href="/models">
              <Icon name="model" size={15} />
              Registrar artefacto en M08
            </a>
          ) : null}
          {finished && job.status === 'FAILED' ? (
            <a className="btn btn--ghost" href="/fundamentals">
              <Icon name="neuron" size={15} />
              Repasar inicialización y tasa de aprendizaje
            </a>
          ) : null}
        </div>
      </div>
    </Panel>
  );
}
