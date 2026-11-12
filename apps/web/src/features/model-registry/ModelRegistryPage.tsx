import { useCallback, useEffect, useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useSession } from '@/app/session';
import { queryClient, queryKeys } from '@/lib/api/queryClient';
import { modelsApi, projectsApi } from '@/lib/api/resources';
import type { ApiModelVersion, ModelStatus, ProjectView } from '@/lib/api/resources';
import { formatDateTime, formatLoss, formatNumber, formatRate, formatRelativeTime } from '@/lib/format';
import { Panel } from '@/components/ui/Panel';
import { Chip } from '@/components/ui/Chip';
import { Icon } from '@/components/ui/Icon';
import { STATUS_META, formatError, formatR2, isRegression } from '@/features/model-registry/model';

/* M08 · Registro de modelos. Cada entrenamiento COMPLETED deja una versión inmutable
   (pesos .keras, preprocesador .pkl y metadatos) con checksum. Aquí se revisa, aprueba o
   retira; la API aplica el rol del proyecto y la separación de funciones. */

const NEXT_ACTIONS: Record<ModelStatus, Array<{ to: ModelStatus; label: string; permission: string }>> = {
  DRAFT: [
    { to: 'REVIEWED', label: 'Marcar revisado', permission: 'model.review' },
    { to: 'RETIRED', label: 'Retirar', permission: 'model.retire' },
  ],
  REVIEWED: [
    { to: 'APPROVED', label: 'Aprobar', permission: 'model.review' },
    { to: 'RETIRED', label: 'Retirar', permission: 'model.retire' },
  ],
  APPROVED: [{ to: 'RETIRED', label: 'Retirar', permission: 'model.retire' }],
  RETIRED: [],
};

type ModelRow = ApiModelVersion & { project: ProjectView };

function TestMetric({ label, value }: { label: string; value: string | null }) {
  return (
    <>
      {value ?? '—'}
      {value ? <span className="metric-cell__label">{label}</span> : null}
    </>
  );
}

interface Notice {
  tone: 'success' | 'info' | 'danger';
  text: string;
}

export function ModelRegistryPage() {
  const { actor, users } = useSession();
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [filter, setFilter] = useState<ModelStatus | 'ALL'>('ALL');
  const [note, setNote] = useState('');
  const [notice, setNotice] = useState<Notice | null>(null);

  const query = useQuery({
    queryKey: queryKeys.models,
    queryFn: async (): Promise<ModelRow[]> => {
      const projects = await projectsApi.list();
      const lists = await Promise.all(projects.map((project) => modelsApi.listForProject(project.id)));
      return lists
        .flatMap((models, index) => models.map((model) => ({ ...model, project: projects[index] })))
        .sort((a, b) => b.createdAt.localeCompare(a.createdAt));
    },
  });
  const rows = useMemo(() => query.data ?? [], [query.data]);
  const status = query.isPending ? 'loading' : 'ready';
  const setRows = (update: (current: ModelRow[]) => ModelRow[]) =>
    queryClient.setQueryData<ModelRow[]>(queryKeys.models, (current) => update(current ?? []));

  useEffect(() => {
    if (query.error) setNotice({ tone: 'danger', text: query.error instanceof Error ? query.error.message : 'No fue posible leer el registro.' });
  }, [query.error]);

  const load = useCallback(() => queryClient.invalidateQueries({ queryKey: queryKeys.models }), []);

  const visible = useMemo(() => rows.filter((row) => filter === 'ALL' || row.status === filter), [rows, filter]);
  const selected = rows.find((row) => row.id === selectedId) ?? visible[0] ?? null;
  const nameOf = (userId: string | undefined) => users.find((user) => user.id === userId)?.displayName ?? userId ?? '—';

  const counts = useMemo(() => {
    const result: Record<ModelStatus | 'ALL', number> = { ALL: rows.length, DRAFT: 0, REVIEWED: 0, APPROVED: 0, RETIRED: 0 };
    rows.forEach((row) => {
      result[row.status] += 1;
    });
    return result;
  }, [rows]);

  const changeStatus = async (row: ModelRow, to: ModelStatus) => {
    try {
      const updated = await modelsApi.setStatus(row.id, to, note.trim());
      setRows((current) => current.map((item) => (item.id === row.id ? { ...updated, project: row.project } : item)));
      void queryClient.invalidateQueries({ queryKey: queryKeys.dashboard });
      setNote('');
      setNotice({ tone: 'success', text: `${row.name} ${row.label} pasa a ${STATUS_META[to].label.toLowerCase()}.` });
    } catch (caught) {
      setNotice({ tone: 'danger', text: caught instanceof Error ? caught.message : 'La API rechazó el cambio.' });
    }
  };

  const download = async (row: ModelRow) => {
    try {
      await modelsApi.download(row);
      setNotice({ tone: 'info', text: `Descarga de ${row.name} ${row.label} registrada en auditoría.` });
    } catch (caught) {
      setNotice({ tone: 'danger', text: caught instanceof Error ? caught.message : 'No fue posible descargar el modelo.' });
    }
  };

  const selfTrained = selected ? selected.metadata.trainedBy === actor.id && actor.role !== 'admin' : false;

  return (
    <>
      <div className="page-head">
        <div className="page-head__text">
          <p className="page-head__eyebrow">
            <Icon name="model" size={14} strokeWidth={2} />
            M08 · Registro de modelos
          </p>
          <h1 className="page-head__title">Versiones inmutables y aprobación</h1>
          <p className="page-head__lede">
            Cada entrenamiento completado registra una versión nueva con sus pesos, su preprocesador, sus
            métricas de prueba y un checksum. Las versiones nunca se sobrescriben (RN-04): se revisan,
            se aprueban o se retiran.
          </p>
        </div>
        <div className="page-head__actions">
          <button type="button" className="btn btn--secondary" onClick={() => void load()}>
            <Icon name="refresh" size={16} />
            Actualizar
          </button>
          <a className="btn btn--primary" href="/training">
            <Icon name="training" size={16} />
            Entrenar una versión
          </a>
        </div>
      </div>

      {notice ? (
        <div className="ds-notice" data-tone={notice.tone} role={notice.tone === 'danger' ? 'alert' : 'status'}>
          <Icon name={notice.tone === 'success' ? 'checkCircle' : notice.tone === 'danger' ? 'alertCircle' : 'info'} size={16} />
          <p>{notice.text}</p>
          <button type="button" className="ds-notice__close" aria-label="Cerrar aviso" onClick={() => setNotice(null)}>
            <Icon name="close" size={14} />
          </button>
        </div>
      ) : null}

      <div className="dash">
        <section className="kpi-grid" aria-label="Indicadores del registro" aria-busy={status === 'loading'}>
          {(['DRAFT', 'REVIEWED', 'APPROVED', 'RETIRED'] as ModelStatus[]).map((key, index) => (
            <article key={key} className="kpi" data-accent={(['indigo', 'amber', 'emerald', 'violet'] as const)[index]}>
              <div className="kpi__top">
                <h3 className="kpi__label">{STATUS_META[key].label}</h3>
                <span className="kpi__icon">
                  <Icon name="model" size={17} />
                </span>
              </div>
              <div className="kpi__value-row">
                <p className="kpi__value">{counts[key]}</p>
              </div>
              <div className="kpi__foot">
                <span>{STATUS_META[key].hint}</span>
              </div>
            </article>
          ))}
        </section>

        <div className="ev-grid">
          <div className="ev-col">
            <Panel
              title="Versiones registradas"
              icon="layers"
              body="tight"
              subtitle="Una fila por versión; el nombre es el de la arquitectura entrenada."
              actions={
                <div className="filters" role="group" aria-label="Filtrar por estado">
                  {(['ALL', 'DRAFT', 'REVIEWED', 'APPROVED', 'RETIRED'] as const).map((key) => (
                    <button
                      key={key}
                      type="button"
                      className="filter-btn"
                      aria-pressed={filter === key}
                      onClick={() => setFilter(key)}
                    >
                      {key === 'ALL' ? 'Todas' : STATUS_META[key].label} · {counts[key]}
                    </button>
                  ))}
                </div>
              }
            >
              <div className="table-wrap">
                {visible.length === 0 ? (
                  <div className="empty">
                    <Icon name="model" />
                    <h3>{status === 'loading' ? 'Cargando registro…' : 'Sin versiones en este estado'}</h3>
                    <p>Cuando un entrenamiento termina, el worker registra aquí su versión con métricas y checksum.</p>
                  </div>
                ) : (
                  <table className="table">
                    <caption className="u-sr-only">Versiones de modelo con estado, métricas de prueba y fecha</caption>
                    <thead>
                      <tr>
                        <th scope="col">Modelo</th>
                        <th scope="col">Estado</th>
                        <th scope="col">Métrica de prueba</th>
                        <th scope="col">Complementaria</th>
                        <th scope="col" className="is-right">
                          Registrado
                        </th>
                      </tr>
                    </thead>
                    <tbody>
                      {visible.map((row) => (
                        <tr key={row.id} data-selected={row.id === selected?.id || undefined}>
                          <td data-col="name" data-label="Modelo">
                            <button
                              type="button"
                              className="table__name tr-queue__pick"
                              onClick={() => setSelectedId(row.id)}
                              aria-pressed={row.id === selected?.id}
                            >
                              <span className="tr-queue__text">
                                <strong>
                                  {row.name} {row.label}
                                </strong>
                                <span className="table__sub">
                                  {row.project.name} · {row.jobId}
                                </span>
                              </span>
                            </button>
                          </td>
                          <td data-label="Estado">
                            <Chip tone={STATUS_META[row.status].tone} dot>
                              {STATUS_META[row.status].label}
                            </Chip>
                          </td>
                          {isRegression(row.metrics) ? (
                            <>
                              <td data-label="R²" data-numeric>
                                <TestMetric label="R²" value={row.metrics.r2 !== undefined ? formatR2(row.metrics.r2) : null} />
                              </td>
                              <td data-label="RMSE" data-numeric>
                                <TestMetric
                                  label={`RMSE · ${row.metadata.target ?? 'objetivo'}`}
                                  value={row.metrics.rmse !== undefined ? formatError(row.metrics.rmse) : null}
                                />
                              </td>
                            </>
                          ) : (
                            <>
                              <td data-label="Accuracy" data-numeric>
                                <TestMetric
                                  label="accuracy"
                                  value={row.metrics.accuracy !== undefined ? formatRate(row.metrics.accuracy) : null}
                                />
                              </td>
                              <td data-label="F1 macro" data-numeric>
                                <TestMetric
                                  label="F1 macro"
                                  value={row.metrics.macroF1 !== undefined ? formatRate(row.metrics.macroF1) : null}
                                />
                              </td>
                            </>
                          )}
                          <td data-col="meta" data-label="Registrado" className="is-right" data-numeric>
                            {formatRelativeTime(row.createdAt)}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )}
              </div>
            </Panel>
          </div>

          <div className="ev-col">
            {selected ? (
              <Panel
                title={`${selected.name} ${selected.label}`}
                icon="model"
                subtitle={`${selected.project.name} · ${selected.id}`}
                actions={
                  <Chip tone={STATUS_META[selected.status].tone} dot>
                    {STATUS_META[selected.status].label}
                  </Chip>
                }
              >
                <dl className="ev-facts">
                  <div>
                    <dt>Entrenamiento</dt>
                    <dd className="u-mono">{selected.jobId}</dd>
                  </div>
                  <div>
                    <dt>Dataset</dt>
                    <dd>
                      {selected.metadata.dataset?.name} v{selected.metadata.dataset?.version} · objetivo «
                      {selected.metadata.target}»
                    </dd>
                  </div>
                  <div>
                    <dt>Clases</dt>
                    <dd>{selected.metadata.classes?.length ? selected.metadata.classes.join(', ') : 'Regresión'}</dd>
                  </div>
                  <div>
                    <dt>Parámetros</dt>
                    <dd>
                      {selected.metadata.epochsRun} épocas · lote {selected.metadata.params?.batchSize} ·{' '}
                      {selected.metadata.params?.optimizer} · lr {selected.metadata.params ? formatNumber(selected.metadata.params.learningRate, 4) : '—'} · semilla{' '}
                      {selected.metadata.params?.seed}
                    </dd>
                  </div>
                  {isRegression(selected.metrics) ? (
                    <>
                      <div>
                        <dt>R² de prueba</dt>
                        <dd>
                          {selected.metrics.r2 !== undefined
                            ? `${formatR2(selected.metrics.r2)} · explica el ${formatRate(Math.max(0, selected.metrics.r2))} de la variación`
                            : '—'}
                        </dd>
                      </div>
                      <div>
                        <dt>RMSE (error típico)</dt>
                        <dd>
                          {selected.metrics.rmse !== undefined
                            ? `${formatError(selected.metrics.rmse)} en ${selected.metadata.target ?? 'el objetivo'}`
                            : '—'}
                        </dd>
                      </div>
                      <div>
                        <dt>MAE (error absoluto medio)</dt>
                        <dd>
                          {selected.metrics.mae !== undefined
                            ? `${formatError(selected.metrics.mae)} en ${selected.metadata.target ?? 'el objetivo'}`
                            : '—'}
                        </dd>
                      </div>
                      <div>
                        <dt>Pérdida de prueba (MSE)</dt>
                        <dd>{selected.metrics.loss !== undefined ? formatError(selected.metrics.loss) : '—'}</dd>
                      </div>
                    </>
                  ) : (
                    <div>
                      <dt>Pérdida de prueba</dt>
                      <dd>{selected.metrics.loss !== undefined ? formatLoss(selected.metrics.loss) : '—'}</dd>
                    </div>
                  )}
                  <div>
                    <dt>Entrenó</dt>
                    <dd>{nameOf(selected.metadata.trainedBy)}</dd>
                  </div>
                  <div>
                    <dt>Registrado</dt>
                    <dd>{formatDateTime(selected.createdAt)}</dd>
                  </div>
                  <div>
                    <dt>Checksum SHA-256</dt>
                    <dd className="u-mono" title={`${selected.checksum}\nCubre los archivos del modelo, no el ZIP: el ZIP se arma en cada descarga. Dentro va HUELLA.txt con la forma de comprobarla.`}>
                      {selected.checksum.slice(0, 16)}…{selected.checksum.slice(-8)}
                    </dd>
                  </div>
                </dl>

                {selected.metadata.reviewHistory?.length ? (
                  <ul className="ev-checks">
                    {selected.metadata.reviewHistory.map((step, index) => (
                      <li key={index} data-ok="true">
                        <Icon name="checkCircle" size={14} />
                        {STATUS_META[step.from as ModelStatus]?.label ?? step.from} →{' '}
                        {STATUS_META[step.to as ModelStatus]?.label ?? step.to} · {nameOf(step.by)}
                        {step.note ? ` · «${step.note}»` : ''}
                      </li>
                    ))}
                  </ul>
                ) : null}

                {NEXT_ACTIONS[selected.status].length > 0 ? (
                  <div className="ds-field">
                    <label htmlFor="model-note">Nota de revisión (opcional)</label>
                    <input
                      id="model-note"
                      className="ds-input"
                      value={note}
                      maxLength={300}
                      placeholder="p. ej. métricas comprobadas sobre la partición de prueba"
                      onChange={(event) => setNote(event.target.value)}
                    />
                  </div>
                ) : null}

                <div className="tr-detail__actions">
                  {NEXT_ACTIONS[selected.status].map((action) => {
                    const allowed = selected.project.permissions.includes(action.permission);
                    const blockedBySelf = action.to === 'APPROVED' && selfTrained;
                    return (
                      <button
                        key={action.to}
                        type="button"
                        className={action.to === 'RETIRED' ? 'btn btn--ghost tr-btn-danger' : 'btn btn--primary'}
                        disabled={!allowed || blockedBySelf}
                        title={
                          blockedBySelf
                            ? 'Quien entrenó el modelo no puede aprobarlo (separación de funciones).'
                            : allowed
                              ? undefined
                              : 'Tu rol en el proyecto no permite este cambio.'
                        }
                        onClick={() => void changeStatus(selected, action.to)}
                      >
                        {action.label}
                      </button>
                    );
                  })}
                  <button
                    type="button"
                    className="btn btn--secondary"
                    disabled={!selected.project.permissions.includes('model.download')}
                    title={
                      selected.project.permissions.includes('model.download')
                        ? 'ZIP con model.keras, preprocessor.pkl y metadata.json'
                        : 'Los lectores no descargan artefactos.'
                    }
                    onClick={() => void download(selected)}
                  >
                    <Icon name="download" size={15} />
                    Descargar
                  </button>
                </div>
                <p className="panel__note">
                  Cada cambio de estado y cada descarga quedan en la auditoría (M10) con actor, fecha y
                  nota.
                </p>
                <p className="panel__note">
                  El checksum cubre los archivos del modelo, no el ZIP: el ZIP se arma en cada descarga y su propia
                  huella cambia. Dentro va <span className="u-mono">HUELLA.txt</span> con la huella de cada archivo y
                  cómo comprobar la total.
                </p>
              </Panel>
            ) : (
              <Panel title="Detalle de la versión" icon="model">
                <div className="empty">
                  <Icon name="model" />
                  <h3>Ninguna versión seleccionada</h3>
                  <p>Elige una fila del registro para revisar su ficha y su historial de revisión.</p>
                </div>
              </Panel>
            )}
          </div>
        </div>
      </div>
    </>
  );
}
