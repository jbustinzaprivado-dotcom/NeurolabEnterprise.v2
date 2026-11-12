import { useEffect, useMemo, useRef, useState } from 'react';
import type { Actor, TrainingJob } from '@/types/domain';
import { familyMeta } from '@/lib/nav';
import { formatDuration, formatNumber } from '@/lib/format';
import { Panel } from '@/components/ui/Panel';
import { Chip } from '@/components/ui/Chip';
import { Icon } from '@/components/ui/Icon';
import {
  EMPTY_LAUNCH,
  LIMITS,
  OPTIMIZERS,
  PRIORITY_LABEL,
  PRIORITY_RANK,
  estimate,
  maxPriorityFor,
  validateLaunch,
} from '@/features/training/model';
import type { LaunchValues, ProjectOption } from '@/features/training/model';

/* §6 M06 · configuración del entrenamiento: épocas, batch size y optimizador, con
   validación en vivo y estimación de recursos antes de encolar. */

interface FieldProps {
  id: string;
  label: string;
  hint?: string;
  error?: string;
  warning?: string;
  wide?: boolean;
  children: React.ReactNode;
}

function Field({ id, label, hint, error, warning, wide, children }: FieldProps) {
  return (
    <div className={wide ? 'tr-field tr-field--wide' : 'tr-field'}>
      <label htmlFor={id}>{label}</label>
      {children}
      {error ? (
        <p className="tr-field__msg" data-tone="error" id={`${id}-error`}>
          <Icon name="alertCircle" size={12} />
          {error}
        </p>
      ) : warning ? (
        <p className="tr-field__msg" data-tone="warning" id={`${id}-error`}>
          <Icon name="alertTriangle" size={12} />
          {warning}
        </p>
      ) : hint ? (
        <p className="tr-field__hint">{hint}</p>
      ) : null}
    </div>
  );
}

interface LaunchPanelProps {
  actor: Actor;
  actorFor: (projectId: string) => Actor;
  projects: ProjectOption[];
  limits: { epochs: number; batch: number };
  values: LaunchValues;
  busy?: boolean;
  onChange: (patch: Partial<LaunchValues>) => void;
  onLaunch: () => void;
  /** Entrenamientos visibles: su duración real afina la estimación de tiempo. */
  history?: TrainingJob[];
}

const KIND_LABEL: Record<string, string> = {
  integer: 'entero',
  float: 'decimal',
  boolean: 'booleano',
  categorical: 'categórica',
};

/** Pista de la capa de salida esperada, como la valida la API antes de encolar. */
function headHint(column: { kind: string; unique: number } | undefined, outputUnits: number | null): string | undefined {
  if (!column) return undefined;
  const regression = column.kind === 'float' || (column.kind === 'integer' && column.unique > 50);
  const expected = regression
    ? 'Dense de 1 unidad con activación linear (regresión)'
    : column.unique === 2
      ? 'Dense de 1 unidad sigmoid o 2 unidades softmax (binaria)'
      : `Dense de ${column.unique} unidades softmax (${column.unique} clases)`;
  const matches =
    outputUnits === null
      ? null
      : regression
        ? outputUnits === 1
        : column.unique === 2
          ? outputUnits === 1 || outputUnits === 2
          : outputUnits === column.unique;
  return `${matches === false ? '⚠ La arquitectura no encaja: ' : 'Se espera '}${expected}.`;
}

/** RNN y CNN leen cada fila como secuencia o imagen: avisa si las columnas no cuadran. */
function shapeWarning(
  shape: number[] | null | undefined,
  columns: { name: string; kind: string }[] | undefined,
  target: string,
): string | undefined {
  if (!shape || !columns) return undefined;
  const expected = shape.reduce((total, size) => total * size, 1);
  const label =
    shape.length === 2 ? `secuencias de ${shape[0]} pasos × ${shape[1]} variables` : `imágenes de ${shape[0]}×${shape[1]}×${shape[2]}`;
  const features = columns.filter((column) => column.name !== target);
  const count = target ? features.length : columns.length - 1;
  if (count !== expected) {
    return `La arquitectura espera ${label} = ${expected} columnas numéricas además del objetivo; este dataset tiene ${count}.`;
  }
  if (target && features.some((column) => column.kind !== 'integer' && column.kind !== 'float')) {
    return `Para ${label} todas las columnas deben ser numéricas.`;
  }
  return undefined;
}

/* Cada campo del formulario y la clave de su error en validateLaunch. */
const FIELD_KEYS: Record<string, string> = {
  'tr-project': 'projectId',
  'tr-architecture': 'architecture',
  'tr-dataset': 'dataset',
  'tr-target': 'targetColumn',
  'tr-epochs': 'epochs',
  'tr-batch': 'batch',
  'tr-rate': 'learningRate',
  'tr-seed': 'seed',
  'tr-priority': 'priority',
};

export function LaunchPanel({ actor, actorFor, projects, limits, values, busy = false, onChange, onLaunch, history = [] }: LaunchPanelProps) {
  const launchable = projects.filter((item) => item.canLaunch);
  const project = launchable.find((item) => item.id === values.projectId);
  const architecture = project?.architectures.find((item) => item.id === values.architecture) ?? null;
  const dataset = project?.datasets.find((item) => item.id === values.dataset) ?? null;
  const target = dataset?.columns.find((column) => column.name === values.targetColumn);
  const issues = useMemo(() => validateLaunch(values, actor, limits), [values, actor, limits]);
  const optimizer = OPTIMIZERS.find((item) => item.id === values.optimizer);
  const ceiling = maxPriorityFor(values.projectId ? actorFor(values.projectId) : actor);

  const epochs = Number(values.epochs.replace(',', '.'));
  const batch = Number(values.batch.replace(',', '.'));
  const preview = architecture && Number.isFinite(epochs) && Number.isFinite(batch)
    ? estimate({ family: architecture.family, architectureName: architecture.name, projectId: values.projectId }, batch, epochs, history)
    : null;

  const blocked = Object.keys(issues.errors).length > 0 || !project || Boolean(architecture && !architecture.trainable) || busy;

  /* Los errores aparecen al salir de un campo que se tocó o al intentar encolar, no antes. */
  const formRef = useRef<HTMLFormElement>(null);
  const [touched, setTouched] = useState<ReadonlySet<string>>(() => new Set());
  const [attempted, setAttempted] = useState(false);
  const touch = (target: EventTarget) => {
    const key = FIELD_KEYS[(target as HTMLElement).id];
    if (key && !touched.has(key)) setTouched(new Set(touched).add(key));
  };
  useEffect(() => {
    // Formulario vacío otra vez (tras encolar o restablecer): vuelve a empezar limpio.
    if (!values.projectId) {
      setTouched(new Set());
      setAttempted(false);
    }
  }, [values.projectId]);
  const errors: Partial<Record<string, string>> = attempted
    ? issues.errors
    : Object.fromEntries(Object.entries(issues.errors).filter(([key]) => touched.has(key)));

  return (
    <Panel
      title="Configurar y encolar entrenamiento"
      subtitle="Épocas, tamaño de lote y optimizador definen el grafo que compila el worker; la prioridad decide cuándo lo atiende."
      icon="training"
      actions={
        architecture ? (
          <Chip tone="neutral" title={`Familia ${familyMeta[architecture.family].label}`}>
            {familyMeta[architecture.family].glyph} · v{architecture.version}
          </Chip>
        ) : (
          <Chip tone="neutral">Sin arquitectura seleccionada</Chip>
        )
      }
      footer={
        <>
          <span>
            El reintento de un trabajo crea uno nuevo y conserva la trazabilidad de origen (§10).
          </span>
          <a href="/architectures">Diseñar arquitectura</a>
        </>
      }
    >
      <form
        className="tr-form"
        ref={formRef}
        onBlur={(event) => touch(event.target)}
        onChange={(event) => touch(event.target)}
        onSubmit={(event) => {
          event.preventDefault();
          if (!blocked) {
            onLaunch();
            return;
          }
          setAttempted(true);
          requestAnimationFrame(() => formRef.current?.querySelector<HTMLElement>('[aria-invalid="true"]')?.focus());
        }}
        noValidate
      >
        <fieldset className="tr-form__section">
          <legend>Qué se entrena</legend>
          <div className="tr-form__grid">
            <Field
              id="tr-project"
              label="Proyecto"
              error={errors.projectId}
              wide
            >
              <select
                id="tr-project"
                className="tr-input"
                value={values.projectId}
                aria-invalid={Boolean(errors.projectId)}
                onChange={(event) =>
                  onChange({ projectId: event.target.value, architecture: '', dataset: '', targetColumn: '' })
                }
              >
                <option value="">
                  {launchable.length === 0 ? 'Su rol no permite entrenar en ningún proyecto' : 'Seleccione un proyecto…'}
                </option>
                {launchable.map((item) => (
                  <option key={item.id} value={item.id}>
                    {item.name} · {item.id}
                  </option>
                ))}
              </select>
            </Field>

            <Field
              id="tr-architecture"
              label="Arquitectura"
              error={errors.architecture}
              warning={
                architecture && !architecture.trainable
                  ? `${familyMeta[architecture.family].label} está documentada pero aún no habilitada para entrenar (§18).`
                  : undefined
              }
              hint={
                project && project.architectures.length > 0
                  ? `${project.architectures.length} versión${project.architectures.length === 1 ? '' : 'es'} guardada${project.architectures.length === 1 ? '' : 's'} en ${project.id}.`
                  : undefined
              }
            >
              <select
                id="tr-architecture"
                className="tr-input"
                value={values.architecture}
                disabled={!project || project.architectures.length === 0}
                aria-invalid={Boolean(errors.architecture)}
                onChange={(event) => onChange({ architecture: event.target.value })}
              >
                <option value="">
                  {project && project.architectures.length === 0 ? 'Sin arquitecturas validadas' : 'Seleccione…'}
                </option>
                {project?.architectures.map((item) => (
                  <option key={item.id} value={item.id}>
                    {item.name} v{item.version} · {familyMeta[item.family].label}
                    {item.trainable ? '' : ' (documentada)'}
                  </option>
                ))}
              </select>
            </Field>

            <Field
              id="tr-dataset"
              label="Dataset"
              error={errors.dataset}
              warning={shapeWarning(architecture?.inputShape, dataset?.columns, values.targetColumn)}
              hint={
                project && project.datasets.length > 0
                  ? `${project.datasets.length} dataset${project.datasets.length === 1 ? '' : 's'} publicado${project.datasets.length === 1 ? '' : 's'} por M05.`
                  : undefined
              }
            >
              <select
                id="tr-dataset"
                className="tr-input"
                value={values.dataset}
                disabled={!project || project.datasets.length === 0}
                aria-invalid={Boolean(errors.dataset)}
                onChange={(event) => onChange({ dataset: event.target.value, targetColumn: '' })}
              >
                <option value="">
                  {project && project.datasets.length === 0 ? 'Sin datasets registrados' : 'Seleccione…'}
                </option>
                {project?.datasets.map((item) => (
                  <option key={item.id} value={item.id}>
                    {item.name} v{item.version}
                  </option>
                ))}
              </select>
            </Field>

            <Field
              id="tr-target"
              label="Columna objetivo"
              error={errors.targetColumn}
              hint={headHint(target, architecture?.outputUnits ?? null)}
            >
              <select
                id="tr-target"
                className="tr-input"
                value={values.targetColumn}
                disabled={!dataset}
                aria-invalid={Boolean(errors.targetColumn)}
                onChange={(event) => onChange({ targetColumn: event.target.value })}
              >
                <option value="">{dataset ? 'Seleccione qué debe predecir…' : 'Elija antes un dataset'}</option>
                {dataset?.columns.map((column) => (
                  <option key={column.name} value={column.name}>
                    {column.name} · {KIND_LABEL[column.kind] ?? column.kind} · {column.unique} valores
                  </option>
                ))}
              </select>
            </Field>

            {project && (project.architectures.length === 0 || project.datasets.length === 0) ? (
              <p className="tr-form__notice" data-tone="warning">
                <Icon name="alertTriangle" size={14} />
                <span>
                  {project.architectures.length === 0 ? (
                    <>
                      Este proyecto no tiene arquitectura validada. Cree el grafo en{' '}
                      <a href="/architectures">M04 · Diseñador de arquitecturas</a> antes de entrenar.
                    </>
                  ) : (
                    <>
                      Este proyecto no tiene dataset publicado. Cárguelo y divídalo en{' '}
                      <a href="/datasets">M05 · Datasets</a> antes de entrenar.
                    </>
                  )}
                </span>
              </p>
            ) : null}
          </div>
        </fieldset>

        <fieldset className="tr-form__section">
          <legend>Ciclo de entrenamiento</legend>
          <div className="tr-form__grid">
            <Field
              id="tr-epochs"
              label="Épocas"
              hint={`Entre ${LIMITS.epochs.min} y ${limits.epochs} (límite vigente de M10).`}
              error={errors.epochs}
            >
              <input
                id="tr-epochs"
                className="tr-input"
                type="number"
                inputMode="numeric"
                min={LIMITS.epochs.min}
                max={limits.epochs}
                step={1}
                value={values.epochs}
                aria-invalid={Boolean(errors.epochs)}
                onChange={(event) => onChange({ epochs: event.target.value })}
              />
            </Field>

            <Field
              id="tr-batch"
              label="Tamaño de lote"
              hint={`Entre ${LIMITS.batch.min} y ${limits.batch} muestras.`}
              error={errors.batch}
              warning={issues.warnings.batch}
            >
              <input
                id="tr-batch"
                className="tr-input"
                type="number"
                inputMode="numeric"
                min={LIMITS.batch.min}
                max={limits.batch}
                step={1}
                value={values.batch}
                aria-invalid={Boolean(errors.batch || issues.warnings.batch)}
                onChange={(event) => onChange({ batch: event.target.value })}
              />
            </Field>

            <Field
              id="tr-optimizer"
              label="Optimizador"
              hint={optimizer?.hint}
            >
              <select
                id="tr-optimizer"
                className="tr-input"
                value={values.optimizer}
                onChange={(event) => onChange({ optimizer: event.target.value })}
              >
                {OPTIMIZERS.map((item) => (
                  <option key={item.id} value={item.id}>
                    {item.label}
                  </option>
                ))}
              </select>
            </Field>

            <Field
              id="tr-rate"
              label="Tasa de aprendizaje"
              hint="Acepta coma decimal; el worker la registra en la semilla del experimento."
              error={errors.learningRate}
              warning={issues.warnings.learningRate}
            >
              <input
                id="tr-rate"
                className="tr-input"
                type="text"
                inputMode="decimal"
                placeholder="0,001"
                value={values.learningRate}
                aria-invalid={Boolean(errors.learningRate || issues.warnings.learningRate)}
                onChange={(event) => onChange({ learningRate: event.target.value })}
              />
            </Field>

            <Field
              id="tr-seed"
              label="Semilla"
              error={errors.seed}
              hint="Determinismo del experimento: la misma semilla reproduce la misma curva."
            >
              <input
                id="tr-seed"
                className="tr-input"
                type="number"
                inputMode="numeric"
                min={0}
                step={1}
                value={values.seed}
                aria-invalid={Boolean(errors.seed)}
                onChange={(event) => onChange({ seed: event.target.value })}
              />
            </Field>

            <Field
              id="tr-priority"
              label="Prioridad en cola"
              error={errors.priority}
              hint={`Su rol permite hasta ${PRIORITY_LABEL[ceiling].toLowerCase()}.`}
            >
              <select
                id="tr-priority"
                className="tr-input"
                value={values.priority}
                aria-invalid={Boolean(errors.priority)}
                onChange={(event) => onChange({ priority: event.target.value as LaunchValues['priority'] })}
              >
                {(Object.keys(PRIORITY_LABEL) as (keyof typeof PRIORITY_LABEL)[]).map((key) => (
                  <option key={key} value={key} disabled={PRIORITY_RANK[key] < PRIORITY_RANK[ceiling]}>
                    {PRIORITY_LABEL[key]}
                  </option>
                ))}
              </select>
            </Field>
          </div>
        </fieldset>

        <div className="tr-forecast">
          <p className="u-caps">Estimación de recursos</p>
          {preview ? (
            <dl className="tr-forecast__grid">
              <div>
                <dt>Ritmo por época</dt>
                <dd className="u-num">{formatNumber(preview.epochSeconds, 1)}&nbsp;s</dd>
              </div>
              <div>
                <dt>Duración total</dt>
                <dd className="u-num">{formatDuration(preview.totalSeconds)}</dd>
              </div>
              <div>
                <dt>Horas de GPU</dt>
                <dd className="u-num">{formatNumber(preview.gpuHours, 2)}</dd>
              </div>
              <div>
                <dt>Muestra por paso</dt>
                <dd className="u-num">{formatNumber(batch)}</dd>
              </div>
            </dl>
          ) : (
            <p className="tr-forecast__empty">
              Seleccione arquitectura y escriba épocas y lote válidos para calcular el coste.
            </p>
          )}
          {preview ? (
            <p className="tr-forecast__basis">
              Estimación {preview.basis.startsWith('según') ? '' : 'con '}{preview.basis}.
            </p>
          ) : null}
          {preview?.overLimit ? (
            <p className="tr-form__notice" data-tone="error">
              <Icon name="alertTriangle" size={14} />
              <span>
                Supera el tope de {LIMITS.maxGpuHours}&nbsp;h de GPU por trabajo; el scheduler lo detendrá
                a mitad de ciclo. Reduzca épocas o lote.
              </span>
            </p>
          ) : null}

          <div className="tr-form__actions">
            <button type="submit" className="btn btn--primary" disabled={busy}>
              <Icon name={busy ? 'clock' : 'zap'} size={15} />
              {busy ? 'Validando en la API…' : 'Encolar ejecución'}
            </button>
            <button type="button" className="btn btn--ghost" onClick={() => onChangeReset(onChange)}>
              <Icon name="refresh" size={15} />
              Restablecer
            </button>
          </div>
        </div>
      </form>
    </Panel>
  );
}

function onChangeReset(onChange: (patch: Partial<LaunchValues>) => void) {
  onChange({
    epochs: EMPTY_LAUNCH.epochs,
    batch: EMPTY_LAUNCH.batch,
    optimizer: EMPTY_LAUNCH.optimizer,
    learningRate: EMPTY_LAUNCH.learningRate,
    seed: EMPTY_LAUNCH.seed,
    priority: EMPTY_LAUNCH.priority,
  });
}
