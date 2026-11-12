import type { BinaryEvaluation } from '@/types/evaluation';
import { formatNumber } from '@/lib/format';

/** Matriz 2×2 (filas = real, columnas = predicho) con las mismas predicciones y otro umbral. */
export function confusionAt(scores: [number, number][], cut: number): number[][] {
  const matrix = [
    [0, 0],
    [0, 0],
  ];
  for (const [real, score] of scores) matrix[real][score >= cut ? 1 : 0] += 1;
  return matrix;
}

interface ThresholdExplorerProps {
  binary: BinaryEvaluation;
  negativeClass: string;
  cut: number;
  onChange: (cut: number) => void;
}

const pct = (part: number, whole: number) => (whole ? `${formatNumber((part / whole) * 100, 0)} %` : '—');

/**
 * Explorador del umbral de alerta en clasificación binaria. No reentrena ni recalcula la red:
 * reclasifica las probabilidades que el worker guardó para cada fila de prueba.
 */
export function ThresholdExplorer({ binary, negativeClass, cut, onChange }: ThresholdExplorerProps) {
  const [[tn, fp], [fn, tp]] = confusionAt(binary.scores, cut);
  const trained = binary.threshold;
  const moved = Math.abs(cut - trained) > 1e-9;
  return (
    <div className="ev-threshold">
      <div className="ev-threshold__head">
        <label htmlFor="ev-threshold-range">
          Umbral de alerta: predecir «{binary.positiveClass}» desde <strong className="u-num">{formatNumber(cut * 100, 0)} %</strong>
        </label>
        {moved ? (
          <button type="button" className="btn btn--ghost btn--sm" onClick={() => onChange(trained)}>
            Volver al entrenado ({formatNumber(trained * 100, 0)} %)
          </button>
        ) : (
          <span className="ev-threshold__tag">Umbral del entrenamiento</span>
        )}
      </div>
      <input
        id="ev-threshold-range"
        type="range"
        min={0.05}
        max={0.95}
        step={0.05}
        value={cut}
        onChange={(event) => onChange(Number(event.target.value))}
      />
      <dl className="ev-threshold__stats">
        <div>
          <dt>Detecta «{binary.positiveClass}»</dt>
          <dd className="u-num">
            {tp} de {tp + fn} <small>({pct(tp, tp + fn)})</small>
          </dd>
        </div>
        <div>
          <dt>Falsas alarmas</dt>
          <dd className="u-num">
            {fp} <small>de {tn + fp} «{negativeClass}»</small>
          </dd>
        </div>
        <div>
          <dt>Cuando avisa, acierta</dt>
          <dd className="u-num">{pct(tp, tp + fp)}</dd>
        </div>
      </dl>
      <p className="ev-threshold__note">
        Reclasifica las mismas predicciones de la partición de prueba, sin reentrenar. La matriz, el F1 y las
        métricas por clase de esta pantalla siguen al umbral elegido; la versión registrada conserva el umbral
        con que se entrenó.
      </p>
    </div>
  );
}
