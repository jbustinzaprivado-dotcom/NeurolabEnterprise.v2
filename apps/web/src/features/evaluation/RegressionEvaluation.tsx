import type { EvaluationRun } from '@/types/evaluation';
import { formatNumber, formatRate } from '@/lib/format';
import { Icon } from '@/components/ui/Icon';
import { Sparkline } from '@/components/ui/DataViz';
import { formatError, formatR2 } from '@/features/model-registry/model';
import { signed } from '@/features/evaluation/model';

/* M07 para modelos de regresión. No hay clases ni matriz de confusión: la evaluación final
   se lee con R² (qué parte de la variación del objetivo explica el modelo) y con RMSE y MAE,
   que están en las unidades del objetivo. */

function Delta({ value, decimals, unit = '', good }: { value: number; decimals: number; unit?: string; good: boolean }) {
  return (
    <span className="ev-delta" data-good={good}>
      <Icon name={value >= 0 ? 'trendingUp' : 'trendingDown'} size={12} />
      {signed(value, decimals)}
      {unit}
    </span>
  );
}

function errorDelta(value: number): number {
  return Math.abs(value) >= 100 ? 0 : 3;
}

export function RegressionKpis({ run, previous }: { run: EvaluationRun; previous: EvaluationRun | null }) {
  const { r2, rmse, mae } = run.testMetrics;
  const before = previous?.testMetrics ?? null;
  const valMae = run.history.map((point) => point.valMae ?? 0);
  const valLoss = run.history.map((point) => point.valLoss);

  return (
    <section className="kpi-grid" aria-label="Indicadores de la evaluación">
      <article className="kpi" data-accent="indigo">
        <div className="kpi__top">
          <h3 className="kpi__label">R² de prueba</h3>
          <span className="kpi__icon"><Icon name="metrics" size={17} /></span>
        </div>
        <div className="kpi__value-row">
          <p className="kpi__value">{r2 !== undefined ? formatR2(r2) : '—'}</p>
          {r2 !== undefined && before?.r2 !== undefined ? (
            <Delta value={r2 - before.r2} decimals={3} good={r2 >= before.r2} />
          ) : null}
        </div>
        <div className="kpi__foot">
          <span>{r2 !== undefined ? `Explica el ${formatRate(Math.max(0, r2))} de la variación` : 'Sin dato'}</span>
        </div>
      </article>

      <article className="kpi" data-accent="emerald">
        <div className="kpi__top">
          <h3 className="kpi__label">RMSE · error típico</h3>
          <span className="kpi__icon"><Icon name="gauge" size={17} /></span>
        </div>
        <div className="kpi__value-row">
          <p className="kpi__value">{rmse !== undefined ? formatError(rmse) : '—'}</p>
          {rmse !== undefined && before?.rmse !== undefined ? (
            <Delta value={rmse - before.rmse} decimals={errorDelta(rmse)} good={rmse <= before.rmse} />
          ) : null}
        </div>
        <div className="kpi__foot">
          <span>En {run.target} · prueba · {formatNumber(run.samples)} filas</span>
          <Sparkline values={valLoss.map((value) => Math.sqrt(value))} color="var(--c-emerald-500)" />
        </div>
      </article>

      <article className="kpi" data-accent="amber">
        <div className="kpi__top">
          <h3 className="kpi__label">MAE · error absoluto medio</h3>
          <span className="kpi__icon"><Icon name="trendingDown" size={17} /></span>
        </div>
        <div className="kpi__value-row">
          <p className="kpi__value">{mae !== undefined ? formatError(mae) : '—'}</p>
          {mae !== undefined && before?.mae !== undefined ? (
            <Delta value={mae - before.mae} decimals={errorDelta(mae)} good={mae <= before.mae} />
          ) : null}
        </div>
        <div className="kpi__foot">
          <span>En {run.target} · MAE val final {formatError(valMae[valMae.length - 1] ?? 0)}</span>
          <Sparkline values={valMae} color="var(--c-amber-500)" />
        </div>
      </article>

      <article className="kpi" data-accent="violet">
        <div className="kpi__top">
          <h3 className="kpi__label">Latencia p95</h3>
          <span className="kpi__icon"><Icon name="clock" size={17} /></span>
        </div>
        <div className="kpi__value-row">
          <p className="kpi__value">
            {formatNumber(run.latencyP95Ms, 1)}
            <small>ms</small>
          </p>
          {previous ? (
            <Delta value={run.latencyP95Ms - previous.latencyP95Ms} decimals={0} unit=" ms"
              good={run.latencyP95Ms <= previous.latencyP95Ms} />
          ) : null}
        </div>
        <div className="kpi__foot">
          <span>Una fila por llamada · CPU del worker</span>
          <span className="ev-kpi-note">inferencia</span>
        </div>
      </article>
    </section>
  );
}

/** Reemplaza a la matriz de confusión: errores de prueba con su lectura. */
export function RegressionSummary({ run }: { run: EvaluationRun }) {
  const { r2, rmse, mae } = run.testMetrics;
  const ratio = rmse !== undefined && mae !== undefined && mae > 0 ? rmse / mae : null;
  return (
    <>
      <dl className="ev-facts ev-regression">
        <div>
          <dt>R²</dt>
          <dd>
            <strong>{r2 !== undefined ? formatR2(r2) : '—'}</strong>
            <span>1 = predicción perfecta · 0 = igual que predecir siempre el promedio</span>
          </dd>
        </div>
        <div>
          <dt>RMSE</dt>
          <dd>
            <strong>{rmse !== undefined ? `${formatError(rmse)} ${run.target}` : '—'}</strong>
            <span>Error típico de una predicción; castiga más los errores grandes</span>
          </dd>
        </div>
        <div>
          <dt>MAE</dt>
          <dd>
            <strong>{mae !== undefined ? `${formatError(mae)} ${run.target}` : '—'}</strong>
            <span>En promedio, cuánto se aleja la predicción del valor real</span>
          </dd>
        </div>
        <div>
          <dt>Pérdida (MSE)</dt>
          <dd>
            <strong>{formatError(run.testLoss)}</strong>
            <span>La que optimiza Keras; en unidades al cuadrado</span>
          </dd>
        </div>
      </dl>
      {ratio !== null ? (
        <p className="panel__note">
          RMSE / MAE = {formatNumber(ratio, 2)}.{' '}
          {ratio > 1.5
            ? 'Hay pocos errores muy grandes que pesan mucho: revise valores atípicos del objetivo.'
            : 'Los errores son parejos: no dominan unos pocos casos extremos.'}
        </p>
      ) : null}
    </>
  );
}
