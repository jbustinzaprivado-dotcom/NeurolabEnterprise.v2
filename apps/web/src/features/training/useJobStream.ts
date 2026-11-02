import { useEffect, useMemo, useRef, useState } from 'react';
import type { EpochPoint, JobStatus } from '@/types/domain';
import { streamEvents } from '@/lib/api/client';
import type { LogLevel, RunLog } from '@/features/training/model';

/* Seguimiento en vivo de un trabajo por el canal SSE (§9). El servidor reenvía primero el
   historial persistido y luego cada evento nuevo, así que abrir un trabajo ya terminado
   también reconstruye su bitácora y su curva completas. */

const STATUS_SOURCE: Partial<Record<JobStatus, string>> = { QUEUED: 'api', PREPARING: 'scheduler' };
const STATUS_LEVEL: Partial<Record<JobStatus, LogLevel>> = {
  COMPLETED: 'success',
  FAILED: 'error',
  CANCELLED: 'warn',
};

const num = (value: unknown) => (typeof value === 'number' ? value : 0);

export interface JobStream {
  logs: RunLog[];
  points: EpochPoint[];
  /** true mientras el canal está abierto (el trabajo no ha cerrado). */
  live: boolean;
}

export function useJobStream(jobId: string | null, onTransition?: () => void): JobStream {
  const [logs, setLogs] = useState<RunLog[]>([]);
  const [points, setPoints] = useState<EpochPoint[]>([]);
  const [live, setLive] = useState(false);
  const onTransitionRef = useRef(onTransition);
  onTransitionRef.current = onTransition;

  useEffect(() => {
    setLogs([]);
    setPoints([]);
    if (!jobId) return undefined;

    const controller = new AbortController();
    let replaying = true;
    setLive(true);

    void streamEvents(
      `/training-jobs/${jobId}/events`,
      ({ event, data }) => {
        const at = typeof data.createdAt === 'string' ? Date.parse(data.createdAt) : Date.now();
        if (event === 'snapshot') return;
        if (event === 'end') {
          setLive(false);
          return;
        }
        if (event === 'metric') {
          const point: EpochPoint = {
            epoch: num(data.epoch),
            loss: num(data.loss),
            valLoss: num(data.val_loss),
            accuracy: num(data.accuracy),
            valAccuracy: num(data.val_accuracy),
          };
          setPoints((current) => [...current.filter((item) => item.epoch !== point.epoch), point]);
          const accuracy = data.val_accuracy !== undefined ? ` · val_acc ${(num(data.val_accuracy) * 100).toFixed(1)} %` : '';
          setLogs((current) => [
            ...current,
            { at, level: 'info', source: 'worker', text: `Época ${point.epoch}/${num(data.epochs)} · loss ${point.loss.toFixed(4)}${accuracy}` },
          ]);
          return;
        }
        if (event === 'status') {
          const statusValue = data.status as JobStatus;
          const reason = typeof data.reason === 'string' && data.reason ? `: ${data.reason}` : '';
          setLogs((current) => [
            ...current,
            {
              at,
              level: STATUS_LEVEL[statusValue] ?? 'info',
              source: STATUS_SOURCE[statusValue] ?? 'worker',
              text: `${data.previous ? `${String(data.previous)} → ` : ''}${statusValue}${reason}`,
            },
          ]);
          /* Tras reproducir el historial, cada cambio de estado refresca la cola y el panel. */
          if (!replaying) onTransitionRef.current?.();
          return;
        }
        if (event === 'log') {
          setLogs((current) => [
            ...current,
            { at, level: (data.level as LogLevel) ?? 'info', source: 'worker', text: String(data.message ?? '') },
          ]);
        }
      },
      controller.signal,
    )
      .catch(() => undefined)
      .finally(() => setLive(false));

    /* Los eventos del historial llegan en la primera ráfaga; los posteriores son en vivo. */
    const replayTimer = window.setTimeout(() => {
      replaying = false;
    }, 1500);

    return () => {
      controller.abort();
      window.clearTimeout(replayTimer);
    };
  }, [jobId]);

  const sorted = useMemo(() => [...points].sort((a, b) => a.epoch - b.epoch), [points]);
  return { logs, points: sorted, live };
}
