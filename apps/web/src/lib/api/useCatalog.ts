import { useCallback, useMemo } from 'react';
import { useQuery } from '@tanstack/react-query';
import { queryKeys } from '@/lib/api/queryClient';
import {
  architecturesApi,
  datasetsApi,
  groupDatasets,
  projectsApi,
} from '@/lib/api/resources';
import type { ApiArchitecture, ApiDataset, DatasetView, ProjectView } from '@/lib/api/resources';

/* Catálogo de trabajo del usuario: proyectos accesibles con sus datasets y arquitecturas
   versionadas. Lo comparten M04, M05, M06 y M09 a través de una sola entrada de caché. */

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

async function fetchCatalog() {
  const projects = await projectsApi.list();
  const [datasetLists, architectureLists] = await Promise.all([
    Promise.all(projects.map((project) => datasetsApi.listForProject(project.id))),
    Promise.all(projects.map((project) => architecturesApi.listForProject(project.id))),
  ]);
  return { projects, datasetRows: datasetLists.flat(), architectures: architectureLists.flat() };
}

const EMPTY = { projects: [] as ProjectView[], datasetRows: [] as ApiDataset[], architectures: [] as ApiArchitecture[] };

export function useCatalog(): Catalog {
  const query = useQuery({ queryKey: queryKeys.catalog, queryFn: fetchCatalog });
  const data = query.data ?? EMPTY;
  const datasets = useMemo(() => groupDatasets(data.datasetRows), [data.datasetRows]);

  const refetch = query.refetch;
  const reload = useCallback(async () => {
    await refetch();
  }, [refetch]);

  return {
    projects: data.projects,
    datasets,
    datasetRows: data.datasetRows,
    architectures: data.architectures,
    status: query.data ? 'ready' : query.isError ? 'error' : 'loading',
    error: query.error instanceof Error ? query.error.message : null,
    reload,
  };
}
