import { useEffect, useMemo, useState } from 'react';
import type { DatasetRecord } from '@/types/dataset';
import { useSession } from '@/app/session';
import { datasetsApi } from '@/lib/api/resources';
import type { DatasetView } from '@/lib/api/resources';
import { useCatalog } from '@/lib/api/useCatalog';
import { toneForUsage } from '@/lib/format';
import { Icon } from '@/components/ui/Icon';
import { Panel } from '@/components/ui/Panel';
import { Meter } from '@/components/ui/Progress';
import { formatBytes, isDatasetUsable, type DatasetFilter } from '@/features/datasets/model';
import { DatasetCatalog } from '@/features/datasets/DatasetCatalog';
import { DatasetDetail } from '@/features/datasets/DatasetDetail';
import { DatasetFormDialog, type DatasetFormPayload } from '@/features/datasets/DatasetFormDialog';
import { DeleteDatasetDialog } from '@/features/datasets/DeleteDatasetDialog';

const GB = 1024 ** 3;

type DialogState =
  | { kind: 'create' }
  | { kind: 'version'; dataset: DatasetView }
  | { kind: 'delete'; dataset: DatasetView }
  | null;

interface Notice {
  tone: 'success' | 'info' | 'danger';
  text: string;
}

function matches(dataset: DatasetRecord, term: string): boolean {
  if (!term.trim()) return true;
  const needle = term.trim().toLowerCase();
  return [dataset.name, dataset.id, dataset.project, dataset.format, dataset.owner, ...dataset.tags]
    .join(' ')
    .toLowerCase()
    .includes(needle);
}

export function DatasetsPage() {
  const { config } = useSession();
  const catalog = useCatalog();
  const { datasets, projects } = catalog;
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [filter, setFilter] = useState<DatasetFilter>('ALL');
  const [term, setTerm] = useState('');
  const [dialog, setDialog] = useState<DialogState>(null);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<Notice | null>(null);

  const storageLimitBytes = config.storageLimitGb * GB;
  const maxUploadBytes = config.maxUploadMb * 1024 ** 2;

  /* Proyectos donde el rol permite registrar datos (owner/engineer; admin en todos). */
  const writableProjects = useMemo(
    () =>
      projects
        .filter((project) => project.permissions.includes('dataset.write'))
        .map((project) => ({ id: project.id, name: project.name, status: project.status })),
    [projects],
  );
  const permissionsOf = (projectId: string) => projects.find((project) => project.id === projectId)?.permissions ?? [];

  useEffect(() => {
    if (selectedId && datasets.some((dataset) => dataset.id === selectedId)) return;
    setSelectedId(datasets[0]?.id ?? null);
  }, [datasets, selectedId]);

  const counts = useMemo<Record<DatasetFilter, number>>(
    () => ({
      ALL: datasets.length,
      READY: datasets.filter((dataset) => dataset.status === 'READY').length,
      VALIDATING: datasets.filter((dataset) => dataset.status === 'VALIDATING').length,
      DRAFT: datasets.filter((dataset) => dataset.status === 'DRAFT').length,
      QUARANTINED: datasets.filter((dataset) => dataset.status === 'QUARANTINED').length,
    }),
    [datasets],
  );

  const filtered = useMemo(
    () =>
      datasets.filter(
        (dataset) => (filter === 'ALL' || dataset.status === filter) && matches(dataset, term),
      ),
    [datasets, filter, term],
  );

  const selected = useMemo(
    () => datasets.find((dataset) => dataset.id === selectedId) ?? null,
    [datasets, selectedId],
  );

  const summary = useMemo(() => {
    const totalBytes = datasets.reduce(
      (acc, dataset) => acc + dataset.versions.reduce((sum, version) => sum + version.sizeBytes, 0),
      0,
    );
    const totalVersions = datasets.reduce((acc, dataset) => acc + dataset.versions.length, 0);
    const pending = datasets.filter(
      (dataset) => dataset.status === 'VALIDATING' || dataset.status === 'QUARANTINED',
    ).length;
    const usable = datasets.filter(isDatasetUsable).length;
    return {
      totalBytes,
      totalVersions,
      pending,
      usable,
      projects: new Set(datasets.map((dataset) => dataset.projectId)).size,
      quarantined: counts.QUARANTINED,
    };
  }, [datasets, counts.QUARANTINED]);

  const upload = async (payload: DatasetFormPayload, versionOf?: DatasetView) => {
    setBusy(true);
    try {
      const created = await datasetsApi.upload({
        projectId: payload.projectId,
        name: payload.name,
        file: payload.file,
        description: payload.description,
        privacy: payload.privacy,
        access: payload.access,
        license: payload.license,
        tags: payload.tags,
        split: payload.split,
      });
      await catalog.reload();
      setSelectedId(created.id);
      setFilter('ALL');
      setTerm('');
      setDialog(null);
      const warnings = created.warnings.length > 0 ? ` Avisos: ${created.warnings.join(' ')}` : '';
      setNotice({
        tone: 'success',
        text: versionOf
          ? `${created.name}: v${created.version} publicada con ${created.rows} filas verificadas. La v${versionOf.currentVersion} se conserva sin cambios.${warnings}`
          : `${created.id} · ${created.name} registrado como v${created.version}: ${created.rows} filas y ${created.columns} columnas verificadas.${warnings}`,
      });
    } catch (caught) {
      setNotice({ tone: 'danger', text: caught instanceof Error ? caught.message : 'La API rechazó el archivo.' });
    } finally {
      setBusy(false);
    }
  };

  const handleDelete = async (target: DatasetView) => {
    try {
      for (const id of target.versionIds) await datasetsApi.remove(id);
      await catalog.reload();
      setDialog(null);
      setNotice({
        tone: 'info',
        text: `${target.name} se retiró del catálogo. Si algún entrenamiento lo usó, el archivo se conserva para trazabilidad; la auditoría registra el evento.`,
      });
    } catch (caught) {
      setDialog(null);
      setNotice({ tone: 'danger', text: caught instanceof Error ? caught.message : 'No fue posible eliminar el dataset.' });
    }
  };

  const storageRatio = summary.totalBytes / storageLimitBytes;
  const selectedPermissions = selected ? permissionsOf(selected.projectId) : [];

  return (
    <>
      <div className="page-head">
        <div className="page-head__text">
          <p className="page-head__eyebrow">
            <Icon name="dataset" size={14} strokeWidth={2} />
            M05 · Datasets
          </p>
          <h1 className="page-head__title">Gobierno de datasets y versiones</h1>
          <p className="page-head__lede">
            Registro de metadatos, carga controlada y particiones de entrenamiento, validación y prueba.
            Los archivos permanecen en almacenamiento de objetos y nunca se ejecutan en el navegador ni
            en la API.
          </p>
        </div>
        <div className="page-head__actions">
          <button type="button" className="btn btn--secondary" onClick={() => void catalog.reload()}>
            <Icon name="refresh" size={16} />
            Actualizar
          </button>
          <button
            type="button"
            className="btn btn--primary"
            onClick={() => setDialog({ kind: 'create' })}
            disabled={writableProjects.length === 0}
            title={writableProjects.length === 0 ? 'Tu rol no permite registrar datos en ningún proyecto.' : undefined}
          >
            <Icon name="plus" size={16} />
            Registrar dataset
          </button>
        </div>
      </div>

      {notice || catalog.error ? (
        <div
          className="ds-notice"
          data-tone={notice?.tone ?? 'danger'}
          role={notice?.tone === 'danger' || !notice ? 'alert' : 'status'}
        >
          <Icon name={notice?.tone === 'success' ? 'checkCircle' : notice?.tone === 'info' ? 'info' : 'alertCircle'} size={16} />
          <p>{notice?.text ?? catalog.error}</p>
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
        <section className="kpi-grid" aria-label="Indicadores del catálogo de datasets" aria-busy={catalog.status === 'loading'}>
          <article className="kpi" data-accent="indigo">
            <div className="kpi__top">
              <h3 className="kpi__label">Datasets registrados</h3>
              <span className="kpi__icon">
                <Icon name="dataset" size={17} />
              </span>
            </div>
            <div className="kpi__value-row">
              <p className="kpi__value">{datasets.length}</p>
            </div>
            <div className="kpi__foot">
              <span>{summary.projects} proyectos con datos</span>
              <span>{summary.usable} listos</span>
            </div>
          </article>

          <article className="kpi" data-accent="emerald">
            <div className="kpi__top">
              <h3 className="kpi__label">Volumen gobernado</h3>
              <span className="kpi__icon">
                <Icon name="storage" size={17} />
              </span>
            </div>
            <div className="kpi__value-row">
              <p className="kpi__value">{formatBytes(summary.totalBytes)}</p>
            </div>
            <div className="kpi__foot">
              <span>Cuota de {formatBytes(storageLimitBytes)}</span>
              <span>{Math.round(storageRatio * 100)}&nbsp;% usado</span>
            </div>
          </article>

          <article className="kpi" data-accent="violet">
            <div className="kpi__top">
              <h3 className="kpi__label">Versiones trazadas</h3>
              <span className="kpi__icon">
                <Icon name="layers" size={17} />
              </span>
            </div>
            <div className="kpi__value-row">
              <p className="kpi__value">{summary.totalVersions}</p>
            </div>
            <div className="kpi__foot">
              <span>Inmutables por diseño</span>
              <span>checksum SHA-256</span>
            </div>
          </article>

          <article className="kpi" data-accent="amber">
            <div className="kpi__top">
              <h3 className="kpi__label">Pendientes de validación</h3>
              <span className="kpi__icon">
                <Icon name="alertTriangle" size={17} />
              </span>
            </div>
            <div className="kpi__value-row">
              <p className="kpi__value">{summary.pending}</p>
            </div>
            <div className="kpi__foot">
              <span>{counts.VALIDATING} en validación</span>
              <span>{summary.quarantined} retenidos</span>
            </div>
          </article>
        </section>

        <div className="ds-grid">
          <div className="ds-col">
            <DatasetCatalog
              datasets={filtered}
              total={datasets.length}
              selectedId={selectedId}
              filter={filter}
              counts={counts}
              term={term}
              onSelect={setSelectedId}
              onFilter={setFilter}
              onTerm={setTerm}
            />

            <Panel
              title="Política de ingesta"
              subtitle="Controles aplicados antes de publicar una versión."
              icon="shield"
            >
              <ul className="ds-policy">
                <li>
                  <Icon name="checkCircle" size={14} />
                  Solo CSV con encabezados explícitos, sin columnas duplicadas y con al menos dos columnas.
                </li>
                <li>
                  <Icon name="checkCircle" size={14} />
                  Tamaño máximo por archivo: {formatBytes(maxUploadBytes)} (configurable en M10).
                </li>
                <li>
                  <Icon name="checkCircle" size={14} />
                  Contenido inspeccionado: se rechazan binarios y archivos que no se pueden interpretar.
                </li>
                <li>
                  <Icon name="checkCircle" size={14} />
                  Particiones de entrenamiento, validación y prueba declaradas antes de publicar.
                </li>
                <li>
                  <Icon name="checkCircle" size={14} />
                  Eliminación con confirmación por nombre; bloqueada si un entrenamiento activo lo usa.
                </li>
              </ul>
              <p className="panel__note">
                Los archivos se validan por tipo, tamaño, permisos y contenido; nunca se ejecutan
                (RN-01). La base de datos conserva solo metadatos, checksums y trazabilidad.
              </p>
            </Panel>
          </div>

          <div className="ds-col">
            <DatasetDetail
              dataset={selected}
              maxUploadBytes={maxUploadBytes}
              canWrite={selectedPermissions.includes('dataset.write')}
              canDelete={selectedPermissions.includes('dataset.delete')}
              onNewVersion={() => selected && setDialog({ kind: 'version', dataset: selected })}
              onDelete={() => selected && setDialog({ kind: 'delete', dataset: selected })}
            />

            <Panel
              title="Almacenamiento y retención"
              subtitle="Cuota de objetos del catálogo."
              icon="storage"
            >
              <div className="meter-grid">
                <Meter
                  label="Objetos del catálogo"
                  detail={`${formatBytes(summary.totalBytes)} de ${formatBytes(storageLimitBytes)}`}
                  ratio={storageRatio}
                  tone={toneForUsage(storageRatio)}
                />
              </div>
              <p className="panel__note">
                Se conservan las {summary.totalVersions} versiones publicadas: ninguna se sobrescribe ni se
                borra por cuota (RN-04). Un dataset eliminado conserva su archivo si algún entrenamiento lo usó, para que el modelo
                resultante siga siendo trazable. Los retenidos ({counts.QUARANTINED}) no pueden usarse en
                entrenamientos.
              </p>
            </Panel>
          </div>
        </div>
      </div>

      {dialog?.kind === 'create' ? (
        <DatasetFormDialog
          mode="create"
          projects={writableProjects}
          maxBytes={maxUploadBytes}
          busy={busy}
          onClose={() => setDialog(null)}
          onSubmit={(payload) => void upload(payload)}
        />
      ) : null}

      {dialog?.kind === 'version' ? (
        <DatasetFormDialog
          mode="version"
          dataset={dialog.dataset}
          projects={writableProjects}
          maxBytes={maxUploadBytes}
          busy={busy}
          onClose={() => setDialog(null)}
          onSubmit={(payload) => void upload(payload, dialog.dataset)}
        />
      ) : null}

      {dialog?.kind === 'delete' ? (
        <DeleteDatasetDialog
          dataset={dialog.dataset}
          onClose={() => setDialog(null)}
          onConfirm={() => void handleDelete(dialog.dataset)}
        />
      ) : null}
    </>
  );
}
