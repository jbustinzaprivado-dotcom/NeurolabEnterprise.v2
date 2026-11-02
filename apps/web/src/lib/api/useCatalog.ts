import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  architecturesApi,
  datasetsApi,
  groupDatasets,
  projectsApi,
} from '@/lib/api/resources';
import type { ApiArchitecture, ApiDataset, DatasetView, ProjectView } from '@/lib/api/resources';

/* Catálogo de trabajo del usuario: proyectos accesibles con sus datasets y arquitecturas
   versionadas. Lo comparten M05 (datasets), M06 (lanzar entrenamientos) y M09 (informes). */

export interface Catalog {
  projects: ProjectView[];
  datasets: DatasetView[];
  /** Filas crudas por versión: M06 necesita el esquema y el id exacto de cada una. */
  datasetRows: ApiDataset[];
  architectures: ApiArchitecture[];
  status: 'loading' | 'ready' | 'error';
  error: string | null;
  reload: () => Promise<void>;
}

export function useCatalog(): Catalog {
  const [projects, setProjects] = useState<ProjectView[]>([]);
  const [datasetRows, setDatasetRows] = useState<ApiDataset[]>([]);
  const [architectures, setArchitectures] = useState<ApiArchitecture[]>([]);
  const [status, setStatus] = useState<Catalog['status']>('loading');
  const [error, setError] = useState<string | null>(null);

  const reload = useCallback(async () => {
    try {
      const accessible = await projectsApi.list();
      const [datasetLists, architectureLists] = await Promise.all([
        Promise.all(accessible.map((project) => datasetsApi.listForProject(project.id))),
        Promise.all(accessible.map((project) => architecturesApi.listForProject(project.id))),
      ]);
      setProjects(accessible);
      setDatasetRows(datasetLists.flat());
      setArchitectures(architectureLists.flat());
      setError(null);
      setStatus('ready');
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'No fue posible cargar el catálogo.');
      setStatus((current) => (current === 'ready' ? 'ready' : 'error'));
    }
  }, []);

  useEffect(() => {
    void reload();
  }, [reload]);

  const datasets = useMemo(() => groupDatasets(datasetRows), [datasetRows]);

  return {
    projects,
    datasets,
    datasetRows,
    architectures,
    status,
    error,
    reload,
  };
}
