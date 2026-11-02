import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { EvaluationMetric, EvaluationRun, Observation, ObservationDraft, ObservationKind, RunTone } from '@/types/evaluation';
import { useQuery } from '@tanstack/react-query';
import { queryClient, queryKeys } from '@/lib/api/queryClient';
import { evaluationApi } from '@/lib/api/resources';
import { familyMeta } from '@/lib/nav';
import { formatDateTime, formatDuration, formatLoss, formatNumber, formatRate } from '@/lib/format';
import { Icon } from '@/components/ui/Icon';
import { Panel } from '@/components/ui/Panel';
import { Chip, StatusChip } from '@/components/ui/Chip';
import { Sparkline } from '@/components/ui/DataViz';
import { LearningChart } from '@/features/evaluation/LearningChart';
import { ConfusionMatrix } from '@/features/evaluation/ConfusionMatrix';
import { ClassMetrics } from '@/features/evaluation/ClassMetrics';
import { ComparisonTable } from '@/features/evaluation/ComparisonTable';
import { ObservationLog } from '@/features/evaluation/ObservationLog';
import { RegressionKpis, RegressionSummary } from '@/features/evaluation/RegressionEvaluation';
import {
  CHART_METRICS_BY_TASK,
  classesOf,
  metricMeta,
  metricsFromConfusion,
  observationKindMeta,
  signed,
} from '@/features/evaluation/model';

const TONES: RunTone[] = ['indigo', 'sky', 'emerald', 'amber'];

interface Notice {
  tone: 'success' | 'info' | 'danger';
  text: string;
}

function Delta({
  value,
  unit = ' pts',
  decimals = 1,
  good,
}: {
  value: number;
  unit?: string;
  decimals?: number;
  good: boolean;
}) {
  return (
    <span className="ev-delta" data-good={good}>
      <Icon name={value >= 0 ? 'trendingUp' : 'trendingDown'} size={12} />
      {signed(value, decimals)}
      {unit}
    </span>
  );
}

export function EvaluationPage() {
  const [runId, setRunId] = useState('');
  const [metric, setMetric] = useState<EvaluationMetric>('loss');
  const [normalized, setNormalized] = useState(false);
  const [compareIds, setCompareIds] = useState<string[]>([]);
  const [observationFilter, setObservationFilter] = useState<ObservationKind | 'ALL'>('ALL');
  const [notice, setNotice] = useState<Notice | null>(null);
  const titleRef = useRef<HTMLInputElement>(null);

  /* Ejecuciones COMPLETED de clasificación y de regresión, evaluadas por el worker sobre la partición de prueba. */
  const runsQuery = useQuery({
    queryKey: queryKeys.evaluations,
    queryFn: async (): Promise<EvaluationRun[]> =>
      (await evaluationApi.runs()).map((run, index) => ({ ...run, tone: TONES[index % TONES.length] })),
  });
  const observationsQuery = useQuery({ queryKey: queryKeys.observations, queryFn: () => evaluationApi.observations() });
  const runs = useMemo(() => runsQuery.data ?? [], [runsQuery.data]);
  const observations = observationsQuery.data ?? [];
  const status = runsQuery.data ? 'ready' : runsQuery.isError ? 'error' : 'loading';
  const setObservations = (update: (items: Observation[]) => Observation[]) =>
    queryClient.setQueryData<Observation[]>(queryKeys.observations, (items) => update(items ?? []));

  useEffect(() => {
    const failed = runsQuery.error ?? observationsQuery.error;
    if (failed) setNotice({ tone: 'danger', text: failed instanceof Error ? failed.message : 'No fue posible leer las evaluaciones.' });
  }, [runsQuery.error, observationsQuery.error]);

  const load = useCallback(
    () =>
      Promise.all([
        queryClient.invalidateQueries({ queryKey: queryKeys.evaluations }),
        queryClient.invalidateQueries({ queryKey: queryKeys.observations }),
      ]),
    [],
  );

  const current = runs.find((run) => run.id === runId) ?? runs[0] ?? null;
  const regression = current?.task === 'regression';
  /* Solo se comparan ejecuciones de la misma tarea: accuracy y R² no se miden en la misma escala. */
  const peers = useMemo(() => runs.filter((run) => run.task === current?.task), [runs, current]);
  const currentIndex = current ? peers.findIndex((run) => run.id === current.id) : -1;
  /* La variación de los indicadores se mide contra la ejecución anterior del mismo proyecto:
     comparar Iris con sismos no dice nada sobre si el modelo mejoró. */
  const previous =
    currentIndex >= 0
      ? peers.slice(currentIndex + 1).find((run) => run.projectId === current?.projectId) ?? null
      : null;
  const chartMetrics = CHART_METRICS_BY_TASK[current?.task ?? 'classification'];
  const activeMetric: EvaluationMetric = chartMetrics.includes(metric) ? metric : 'loss';

  const { perClass, summary } = useMemo(
    () => metricsFromConfusion(current && !regression && current.confusion.length ? current.confusion : [[0]]),
    [current, regression],
  );
  const previousSummary = useMemo(
    () => (previous && !regression ? metricsFromConfusion(previous.confusion).summary : null),
    [previous, regression],
  );

  const chartRuns = useMemo(
    () => (current ? [current, ...peers.filter((run) => compareIds.includes(run.id) && run.id !== current.id)] : []),
    [current, peers, compareIds],
  );

  const selectRun = (nextId: string) => {
    const next = runs.find((run) => run.id === nextId);
    setRunId(nextId);
    setCompareIds((previousIds) =>
      previousIds.filter((id) => id !== nextId && runs.find((run) => run.id === id)?.task === next?.task),
    );
  };

  const toggleCompare = (id: string) => {
    if (id === current?.id) return;
    setCompareIds((previousIds) =>
      previousIds.includes(id)
        ? previousIds.filter((candidate) => candidate !== id)
        : previousIds.length >= 2
          ? previousIds
          : [...previousIds, id],
    );
  };

  const handleAddObservation = async (draft: ObservationDraft) => {
    try {
      const record = await evaluationApi.addObservation(draft);
      setObservations((items) => [record, ...items]);
      setObservationFilter('ALL');
      setNotice({
        tone: 'success',
        text: `${record.id} quedó registrado como ${observationKindMeta[record.kind].label.toLowerCase()} de ${record.runId}.`,
      });
    } catch (caught) {
      setNotice({ tone: 'danger', text: caught instanceof Error ? caught.message : 'La API rechazó la observación.' });
    }
  };

  const toggleReviewed = async (observationId: string) => {
    try {
      const updated = await evaluationApi.toggleReview(observationId);
      setObservations((items) => items.map((item) => (item.id === observationId ? updated : item)));
    } catch (caught) {
      setNotice({ tone: 'danger', text: caught instanceof Error ? caught.message : 'No fue posible marcar la observación.' });
    }
  };

  const focusObservationForm = () => {
    titleRef.current?.scrollIntoView({ block: 'center' });
    titleRef.current?.focus({ preventScroll: true });
  };

  const refresh = () => {
    setNotice(null);
    void load();
  };

  if (!current) {
    return (
      <>
        <div className="page-head">
          <div className="page-head__text">
            <p className="page-head__eyebrow">
              <Icon name="metrics" size={14} strokeWidth={2} />
              M07 · Evaluación y métricas
            </p>
            <h1 className="page-head__title">Evaluación final y comparación de ejecuciones</h1>
          </div>
          <div className="page-head__actions">
            <button type="button" className="btn btn--secondary" onClick={refresh}>
              <Icon name="refresh" size={16} />
              Actualizar
            </button>
          </div>
        </div>
        {notice ? (
          <div className="ds-notice" data-tone={notice.tone} role="alert">
            <Icon name="alertCircle" size={16} />
            <p>{notice.text}</p>
          </div>
        ) : null}
        <Panel title="Sin ejecuciones evaluadas" icon="metrics">
          <div className="empty">
            <Icon name="metrics" />
            <h3>{status === 'loading' ? 'Cargando evaluaciones…' : 'Aún no hay entrenamientos completados'}</h3>
            <p>
              Cuando un entrenamiento termina en M06, el worker lo evalúa sobre la partición de prueba y
              aparece aquí con sus curvas y su evaluación final: matriz de confusión en clasificación, o
              R², RMSE y MAE en regresión.
            </p>
            <a className="btn btn--primary" href="/training">
              <Icon name="training" size={16} />
              Ir a entrenamientos
            </a>
          </div>
        </Panel>
      </>
    );
  }

  const weakest = perClass[Number(summary.weakestClassId)];
  const weakestLabel = classesOf(current)[Number(summary.weakestClassId)]?.label ?? '—';
  const unreviewed = observations.filter((item) => !item.reviewed).length;
  const finalValLoss = current.history[current.history.length - 1]?.valLoss ?? 0;

  const f1Delta = previousSummary ? (summary.f1 - previousSummary.f1) * 100 : null;
  const balancedDelta = previousSummary
    ? (summary.balancedAccuracy - previousSummary.balancedAccuracy) * 100
    : null;
  const lossDelta = previous ? current.testLoss - previous.testLoss : null;
  const latencyDelta = previous ? current.latencyP95Ms - previous.latencyP95Ms : null;

  return (
    <>
      <div className="page-head">
        <div className="page-head__text">
          <p className="page-head__eyebrow">
            <Icon name="metrics" size={14} strokeWidth={2} />
            M07 · Evaluación y métricas
          </p>
          <h1 className="page-head__title">Evaluación final y comparación de ejecuciones</h1>
          <p className="page-head__lede">
            Consulte la pérdida y las métricas época a época, revise la evaluación final sobre la
            partición de prueba (matriz de confusión en clasificación; R², RMSE y MAE en regresión) y
            deje constancia de limitaciones antes de registrar una versión del modelo.
          </p>
        </div>
        <div className="page-head__actions">
          <button type="button" className="btn btn--secondary" onClick={refresh}>
            <Icon name="refresh" size={16} />
            Actualizar
          </button>
          <button type="button" className="btn btn--primary" onClick={focusObservationForm}>
            <Icon name="plus" size={16} />
            Registrar observación
          </button>
        </div>
      </div>

      {notice ? (
        <div className="ds-notice" data-tone={notice.tone} role={notice.tone === 'danger' ? 'alert' : 'status'}>
          <Icon name={notice.tone === 'success' ? 'checkCircle' : notice.tone === 'danger' ? 'alertCircle' : 'info'} size={16} />
          <p>{notice.text}</p>
          <button
            type="button"
            className="ds-notice__close"
            aria-label="Cerrar aviso"
            onClick={() => setNotice(null)}
          >
            <Icon name="close" size={14} />
          </button>
        </div>
      ) : null}

      <div className="dash">
        <section className="ev-runbar" aria-label="Ejecución evaluada">
          <label className="ev-runbar__field">
            <span>Ejecución evaluada</span>
            <select
              className="ev-input"
              value={current.id}
              onChange={(event) => selectRun(event.target.value)}
            >
              {runs.map((run) => (
                <option key={run.id} value={run.id}>
                  {run.id} · {run.name} · {run.project}
                </option>
              ))}
            </select>
          </label>
          <div className="ev-runbar__meta">
            <StatusChip status={current.status} />
            <Chip tone="outline">
              <Icon name="dataset" size={12} />
              {current.dataset} · {current.datasetVersion}
            </Chip>
            <Chip tone="outline">
              <Icon name="layers" size={12} />
              {familyMeta[current.family].label}
            </Chip>
            <Chip tone="outline">
              <Icon name="checkCircle" size={12} />
              Prueba · {formatNumber(current.samples)} muestras
            </Chip>
            <span className="ev-runbar__hint">
              Partición reservada; no intervino en el entrenamiento ni en la selección del
              checkpoint.
            </span>
          </div>
        </section>

        {regression ? <RegressionKpis run={current} previous={previous} /> : (
        <section className="kpi-grid" aria-label="Indicadores de la evaluación">
          <article className="kpi" data-accent="indigo">
            <div className="kpi__top">
              <h3 className="kpi__label">F1 macro</h3>
              <span className="kpi__icon">
                <Icon name="metrics" size={17} />
              </span>
            </div>
            <div className="kpi__value-row">
              <p className="kpi__value">{formatRate(summary.f1)}</p>
              {f1Delta !== null ? (
                <Delta value={f1Delta} good={f1Delta >= 0} />
              ) : null}
            </div>
            <div className="kpi__foot">
              <span>
                Clase más débil: {weakestLabel} · {formatRate(weakest.f1)}
              </span>
              <Sparkline values={current.history.map((point) => point.valF1)} />
            </div>
          </article>

          <article className="kpi" data-accent="emerald">
            <div className="kpi__top">
              <h3 className="kpi__label">Exactitud balanceada</h3>
              <span className="kpi__icon">
                <Icon name="gauge" size={17} />
              </span>
            </div>
            <div className="kpi__value-row">
              <p className="kpi__value">{formatRate(summary.balancedAccuracy)}</p>
              {balancedDelta !== null ? (
                <Delta value={balancedDelta} good={balancedDelta >= 0} />
              ) : null}
            </div>
            <div className="kpi__foot">
              <span>
                Prueba · {formatNumber(summary.total)} muestras
              </span>
              <Sparkline
                values={current.history.map((point) => point.valAccuracy)}
                color="var(--c-emerald-500)"
              />
            </div>
          </article>

          <article className="kpi" data-accent="amber">
            <div className="kpi__top">
              <h3 className="kpi__label">Pérdida de prueba</h3>
              <span className="kpi__icon">
                <Icon name="trendingDown" size={17} />
              </span>
            </div>
            <div className="kpi__value-row">
              <p className="kpi__value">{formatLoss(current.testLoss)}</p>
              {lossDelta !== null ? (
                <Delta
                  value={lossDelta}
                  unit=""
                  decimals={3}
                  good={lossDelta <= 0}
                />
              ) : null}
            </div>
            <div className="kpi__foot">
              <span>Pérdida val final {formatLoss(finalValLoss)}</span>
              <Sparkline
                values={current.history.map((point) => point.valLoss)}
                color="var(--c-amber-500)"
              />
            </div>
          </article>

          <article className="kpi" data-accent="violet">
            <div className="kpi__top">
              <h3 className="kpi__label">Latencia p95</h3>
              <span className="kpi__icon">
                <Icon name="clock" size={17} />
              </span>
            </div>
            <div className="kpi__value-row">
              <p className="kpi__value">
                {formatNumber(current.latencyP95Ms, 1)}
                <small>ms</small>
              </p>
              {latencyDelta !== null ? (
                <Delta value={latencyDelta} unit=" ms" decimals={0} good={latencyDelta <= 0} />
              ) : null}
            </div>
            <div className="kpi__foot">
              <span>Una fila por llamada · CPU del worker</span>
              <span className="ev-kpi-note">inferencia</span>
            </div>
          </article>
        </section>
        )}

        <div className="ev-grid">
          <div className="ev-col">
            <Panel
              title="Pérdida y métricas por época"
              subtitle="Línea continua = entrenamiento; discontinua = validación. Superponga hasta dos ejecuciones desde la comparación."
              icon="metrics"
              actions={
                <div className="filters" role="group" aria-label="Métrica de la gráfica">
                  {chartMetrics.map((option) => (
                    <button
                      key={option}
                      type="button"
                      className="filter-btn"
                      aria-pressed={activeMetric === option}
                      onClick={() => setMetric(option)}
                    >
                      {metricMeta[option].label}
                    </button>
                  ))}
                </div>
              }
            >
              <LearningChart runs={chartRuns} metric={activeMetric} />
              <div className="ev-chart-meta">
                <span>
                  <Icon name="clock" size={13} />
                  Mejor checkpoint · época {current.bestEpoch} de {current.epochs}
                </span>
                <span>
                  <Icon name="layers" size={13} />
                  {chartRuns.length} {chartRuns.length === 1 ? 'ejecución' : 'ejecuciones'} en la
                  gráfica
                </span>
              </div>
              <p className="panel__note">
                El historial llega de <code>GET /evaluations</code>:{' '}
                {regression ? 'pérdida (MSE) y MAE' : 'pérdida, exactitud y F1 macro'} que el worker calculó al
                cerrar cada época. El navegador solo dibuja la curva (RN-03).
              </p>
            </Panel>

            {regression ? (
              <Panel
                title="Evaluación final · errores de predicción"
                subtitle={`Partición de prueba · ${formatNumber(current.samples)} filas · objetivo «${current.target}»`}
                icon="dataset"
              >
                <RegressionSummary run={current} />
                <p className="panel__note">
                  RMSE y MAE están en las unidades de «{current.target}». La partición de prueba no participó
                  en el entrenamiento ni en la elección del checkpoint.
                </p>
              </Panel>
            ) : (
            <Panel
              title="Evaluación final · matriz de confusión"
              subtitle={`Partición de prueba · ${formatNumber(current.samples)} muestras · checkpoint ${current.bestEpoch}`}
              icon="dataset"
              actions={
                <>
                  <Chip tone="completed">Exactitud {formatRate(summary.accuracy)}</Chip>
                  <div className="filters" role="group" aria-label="Vista de la matriz">
                    <button
                      type="button"
                      className="filter-btn"
                      aria-pressed={!normalized}
                      onClick={() => setNormalized(false)}
                    >
                      Recuentos
                    </button>
                    <button
                      type="button"
                      className="filter-btn"
                      aria-pressed={normalized}
                      onClick={() => setNormalized(true)}
                    >
                      Normalizado
                    </button>
                  </div>
                </>
              }
            >
              <ConfusionMatrix run={current} normalized={normalized} />
              <p className="panel__note">
                Fila = clase real; columna = clase predicha. El porcentaje se calcula sobre el
                soporte de la fila. La partición de prueba no participó en el entrenamiento ni en la
                elección del checkpoint.
              </p>
            </Panel>
            )}
          </div>

          <div className="ev-col">
            <Panel
              title="Ficha de la ejecución"
              subtitle="Metadatos del entrenamiento evaluado."
              icon="model"
              actions={<StatusChip status={current.status} />}
            >
              <dl className="ev-facts">
                <div>
                  <dt>Ejecución</dt>
                  <dd className="u-mono">
                    {current.id} · {current.jobId}
                  </dd>
                </div>
                <div>
                  <dt>Proyecto</dt>
                  <dd>{current.project}</dd>
                </div>
                <div>
                  <dt>Dataset</dt>
                  <dd>
                    {current.dataset} · {current.datasetVersion}
                  </dd>
                </div>
                <div>
                  <dt>Arquitectura</dt>
                  <dd>
                    {current.architecture} · {familyMeta[current.family].label}
                  </dd>
                </div>
                <div>
                  <dt>Optimizador</dt>
                  <dd>
                    {current.optimizer} · lr {formatNumber(current.learningRate, 4)}
                  </dd>
                </div>
                <div>
                  <dt>Lote / semilla</dt>
                  <dd>
                    {formatNumber(current.batchSize)} · {current.seed}
                  </dd>
                </div>
                <div>
                  <dt>Épocas</dt>
                  <dd>
                    {current.epochs} · mejor {current.bestEpoch}
                  </dd>
                </div>
                <div>
                  <dt>Duración</dt>
                  <dd>{formatDuration(current.durationSeconds)}</dd>
                </div>
                <div>
                  <dt>Finalizada</dt>
                  <dd>{formatDateTime(current.finishedAt)}</dd>
                </div>
              </dl>

              <ul className="ev-checks">
                <li data-ok="true">
                  <Icon name="checkCircle" size={14} />
                  Partición de prueba sin fuga de datos
                </li>
                <li data-ok="true">
                  <Icon name="checkCircle" size={14} />
                  Checkpoint congelado en la época {current.bestEpoch}
                </li>
                <li data-ok="true">
                  <Icon name="checkCircle" size={14} />
                  Métrica primaria declarada: {regression ? 'R²' : 'F1 macro'}
                </li>
              </ul>
              <p className="panel__note">
                Las ejecuciones evaluadas con distintas versiones del dataset no son estrictamente
                comparables; consulte el registro de limitaciones antes de decidir la promoción.
              </p>
            </Panel>

            {regression ? null : (
            <Panel
              title="Métricas por clase"
              subtitle="Precisión, recall y F1 sobre la partición de prueba."
              icon="layers"
              actions={<Chip tone="outline">macro F1 {formatRate(summary.f1)}</Chip>}
            >
              <ClassMetrics run={current} />
            </Panel>
            )}
          </div>
        </div>

        <Panel
          title="Comparación de ejecuciones"
          subtitle={`Ejecuciones de ${regression ? 'regresión' : 'clasificación'} completadas. El Δ ${regression ? 'R²' : 'F1'} se mide contra la ejecución evaluada.`}
          icon="queue"
          actions={<Chip tone="outline">{peers.length} {peers.length === 1 ? 'ejecución' : 'ejecuciones'}</Chip>}
        >
          <ComparisonTable
            runs={peers}
            currentId={current.id}
            compareIds={compareIds}
            onSelect={selectRun}
            onToggleCompare={toggleCompare}
          />
        </Panel>

        <Panel
          title="Limitaciones y observaciones"
          subtitle="Registro acumulado por ejecución; acompaña la evaluación final y la futura versión del modelo."
          icon="report"
          actions={
            <Chip tone={unreviewed > 0 ? 'preparing' : 'completed'} dot>
              {unreviewed > 0 ? `${unreviewed} sin revisar` : 'Todo revisado'}
            </Chip>
          }
        >
          <ObservationLog
            runs={runs}
            observations={observations}
            currentRunId={current.id}
            filter={observationFilter}
            onFilter={setObservationFilter}
            onAdd={(draft) => void handleAddObservation(draft)}
            onToggleReviewed={(id) => void toggleReviewed(id)}
            titleRef={titleRef}
          />
        </Panel>
      </div>
    </>
  );
}
