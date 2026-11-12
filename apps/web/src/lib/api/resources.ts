import type { OidcConfig } from '@/lib/auth/oidc';
/* Contratos de la API (`services/api`) y adaptadores a los tipos que ya usa la interfaz.
   La API responde en camelCase; aquí se tipan sus respuestas y se agrupan las llamadas
   por recurso para que las pantallas no conozcan rutas ni formatos de transporte. */

import type { NetworkFamily, TrainingJob, UserRole } from '@/types/domain';
import type { DatasetRecord, DatasetVersion } from '@/types/dataset';
import type { DirectoryUser, ProjectMemberRole, ProjectRecord, ProjectStatus } from '@/types/project';
import type { AdministrationSnapshot, InviteDraft, SecuritySettings, ServiceHealth } from '@/types/administration';
import type { EvaluationRun, Observation, ObservationDraft } from '@/types/evaluation';
import type { ArchitectureConfig } from '@/features/architectures/model';
import { api, download } from '@/lib/api/client';

/* ------------------------------------------------------------------ sesión */

export interface ApiUser extends DirectoryUser {
  status: string;
}

export interface SessionToken {
  accessToken: string;
  expiresAt: number;
  user: ApiUser;
}

export interface ClientConfig {
  maxUploadMb: number;
  maxEpochs: number;
  maxBatchSize: number;
  maxJobMinutes: number;
  maxActiveJobsPerUser: number;
  storageLimitGb: number;
  trainingFamilies: NetworkFamily[];
  devLogin: boolean;
  version: string;
}

export type AuthConfig = { devLogin: boolean } & (
  | { provider: 'local' }
  | ({ provider: 'oidc' } & Omit<OidcConfig, 'provider'>)
);

export const sessionApi = {
  authConfig: () => api.get<AuthConfig>('/auth/config'),
  /** Tras volver del proveedor: la API registra el inicio de sesión (§11). */
  startSession: () => api.post<ApiUser>('/auth/session'),
  me: () => api.get<ApiUser>('/auth/me'),
  login: (email: string, password: string) => api.post<SessionToken>('/auth/login', { email, password }),
  devLogin: (userId: string) => api.post<SessionToken>('/auth/dev-login', { userId }),
  directory: () => api.get<ApiUser[]>('/users'),
  config: () => api.get<ClientConfig>('/config'),
};

/* ---------------------------------------------------------------- proyectos */

interface ApiProject extends Omit<ProjectRecord, 'members'> {
  members: Array<{ userId: string; displayName: string; role: ProjectMemberRole; addedAt: string }>;
  myRole: string;
  permissions: string[];
}

export type ProjectView = ProjectRecord & { myRole: string; permissions: string[] };

function toProject(raw: ApiProject): ProjectView {
  return {
    ...raw,
    members: raw.members.map(({ userId, role, addedAt }) => ({ userId, role, addedAt })),
  };
}

export interface ProjectPayload {
  name: string;
  description: string;
  family: NetworkFamily;
  status: ProjectStatus;
  tags: string[];
}

export const projectsApi = {
  list: async () => (await api.get<ApiProject[]>('/projects')).map(toProject),
  create: async (payload: ProjectPayload) => toProject(await api.post<ApiProject>('/projects', payload)),
  update: async (id: string, patch: Partial<ProjectPayload>) =>
    toProject(await api.patch<ApiProject>(`/projects/${id}`, patch)),
  upsertMember: async (id: string, userId: string, role: ProjectMemberRole) =>
    toProject(await api.post<ApiProject>(`/projects/${id}/members`, { userId, role })),
  removeMember: (id: string, userId: string) => api.delete<void>(`/projects/${id}/members/${userId}`),
  addDocument: async (id: string, title: string, body: string) =>
    toProject(await api.post<ApiProject>(`/projects/${id}/documents`, { title, body })),
  updateDocument: async (id: string, docId: string, title: string, body: string) =>
    toProject(await api.patch<ApiProject>(`/projects/${id}/documents/${docId}`, { title, body })),
  deleteDocument: async (id: string, docId: string) =>
    toProject(await api.delete<ApiProject>(`/projects/${id}/documents/${docId}`)),
};

/* ----------------------------------------------------------------- datasets */

export interface ApiColumn {
  name: string;
  kind: 'integer' | 'float' | 'boolean' | 'categorical';
  nulls: number;
  unique: number;
}

export interface ApiDataset {
  id: string;
  projectId: string;
  projectName: string;
  name: string;
  version: number;
  description: string;
  format: 'CSV';
  status: 'READY' | 'QUARANTINED' | 'DELETED';
  originalFilename: string;
  sizeBytes: number;
  rows: number;
  columns: number;
  checksum: string;
  privacy: DatasetRecord['privacy'];
  access: DatasetRecord['access'];
  tags: string[];
  license: string;
  split: { train: number; validation: number; test: number };
  columnSchema: ApiColumn[];
  warnings: string[];
  createdBy: string;
  createdByName: string;
  createdAt: string;
}

/** Ficha de M05: la API guarda cada versión como fila; la interfaz las agrupa por nombre. */
export type DatasetView = DatasetRecord & {
  /** Id de la fila de la versión vigente: es el que se usa para entrenar. */
  latestId: string;
  /** Ids de todas las versiones; borrar el dataset las retira todas. */
  versionIds: string[];
  columnSchema: ApiColumn[];
  warnings: string[];
};

const percent = (value: number) => Math.round(value * 100);

export function groupDatasets(rows: ApiDataset[]): DatasetView[] {
  const groups = new Map<string, ApiDataset[]>();
  rows.forEach((row) => {
    const key = `${row.projectId}::${row.name}`;
    groups.set(key, [...(groups.get(key) ?? []), row]);
  });
  return [...groups.values()]
    .map((versions) => {
      const sorted = [...versions].sort((a, b) => b.version - a.version);
      const latest = sorted[0];
      const history: DatasetVersion[] = sorted.map((row) => ({
        version: row.version,
        createdAt: row.createdAt,
        author: row.createdByName,
        sizeBytes: row.sizeBytes,
        rows: row.rows,
        status: row.status === 'QUARANTINED' ? 'QUARANTINED' : 'READY',
        note: `${row.version === 1 ? 'Carga inicial' : 'Nueva versión'} · ${row.originalFilename}`,
        checksum: row.checksum,
      }));
      return {
        id: latest.id,
        latestId: latest.id,
        versionIds: sorted.map((row) => row.id),
        name: latest.name,
        projectId: latest.projectId,
        project: latest.projectName,
        format: 'CSV' as const,
        description: latest.description || 'Sin descripción adicional.',
        tags: latest.tags,
        license: latest.license || 'Sin licencia',
        privacy: latest.privacy,
        access: latest.access,
        status: latest.status === 'QUARANTINED' ? ('QUARANTINED' as const) : ('READY' as const),
        currentVersion: latest.version,
        versions: history,
        split: { train: percent(latest.split.train), validation: percent(latest.split.validation), test: percent(latest.split.test) },
        rows: latest.rows,
        sizeBytes: latest.sizeBytes,
        updatedAt: latest.createdAt,
        owner: latest.createdByName,
        columnSchema: latest.columnSchema,
        warnings: latest.warnings,
      };
    })
    .sort((a, b) => b.updatedAt.localeCompare(a.updatedAt));
}

export interface DatasetUpload {
  projectId: string;
  name: string;
  file: File;
  description: string;
  privacy: DatasetRecord['privacy'];
  access: DatasetRecord['access'];
  license: string;
  tags: string[];
  split: { train: number; validation: number; test: number };
}

export const datasetsApi = {
  listForProject: (projectId: string) => api.get<ApiDataset[]>(`/projects/${projectId}/datasets`),
  upload: (payload: DatasetUpload) => {
    const form = new FormData();
    form.append('file', payload.file);
    form.append('name', payload.name);
    form.append('description', payload.description);
    form.append('privacy', payload.privacy);
    form.append('access', payload.access);
    form.append('license', payload.license);
    form.append('tags', payload.tags.join(','));
    form.append('train', String(payload.split.train / 100));
    form.append('validation', String(payload.split.validation / 100));
    form.append('test', String(payload.split.test / 100));
    return api.post<ApiDataset>(`/projects/${payload.projectId}/datasets`, form, { timeoutMs: 120_000 });
  },
  remove: (id: string) => api.delete<void>(`/datasets/${id}`),
};

/* ------------------------------------------------------------- arquitecturas */

export interface ApiArchitectureSummary {
  valid: boolean;
  inputShape: number[];
  outputShape: number[];
  totalParams: number;
  issues: Array<{ severity: 'error' | 'warning' | 'info'; message: string; layerIndex: number | null }>;
}

export interface ApiArchitecture {
  id: string;
  projectId: string;
  name: string;
  family: NetworkFamily;
  version: number;
  justification: string;
  config: Omit<ArchitectureConfig, 'name'>;
  summary: ApiArchitectureSummary;
  trainable: boolean;
  createdBy: string;
  createdAt: string;
}

export const architecturesApi = {
  listForProject: (projectId: string) => api.get<ApiArchitecture[]>(`/projects/${projectId}/architectures`),
  create: (projectId: string, config: ArchitectureConfig, justification: string) =>
    api.post<ApiArchitecture>(`/projects/${projectId}/architectures`, { ...config, justification }),
  validate: (config: ArchitectureConfig) => api.post<ApiArchitectureSummary>('/architectures/validate', config),
};

/* ----------------------------------------------------------- entrenamientos */

export type Priority = 'CRITICA' | 'ALTA' | 'NORMAL' | 'BAJA';

/** `TrainingJob` del frontend más la trazabilidad que guarda la API. */
export interface ApiTrainingJob extends TrainingJob {
  architectureId: string;
  architectureVersion: number;
  datasetId: string;
  datasetVersion: number;
  targetColumn: string;
  statusReason: string | null;
  priority: Priority;
  learningRate: number;
  seed: number;
  ownerId: string;
  attempt: number;
  retryOfId: string | null;
  codeVersion: string;
  modelVersionId: string | null;
}

export interface LaunchPayload {
  architectureId: string;
  datasetId: string;
  targetColumn: string;
  epochs: number;
  batchSize: number;
  optimizer: string;
  learningRate: number;
  seed: number;
  priority: Priority;
  classWeight?: 'none' | 'balanced';
  threshold?: number;
}

export interface ApiJobEvent {
  id: number;
  type: 'status' | 'metric' | 'log';
  payload: Record<string, unknown>;
  createdAt: string;
}

export const trainingApi = {
  list: () => api.get<ApiTrainingJob[]>('/training-jobs?limit=300'),
  get: (id: string) => api.get<ApiTrainingJob>(`/training-jobs/${id}`),
  launch: (projectId: string, payload: LaunchPayload) =>
    api.post<ApiTrainingJob>(`/projects/${projectId}/training-jobs`, payload),
  cancel: (id: string, reason: string) =>
    api.post<{ jobId: string; status: string; job: ApiTrainingJob }>(`/training-jobs/${id}/cancel`, { reason }),
  retry: (id: string) => api.post<ApiTrainingJob>(`/training-jobs/${id}/retry`),
  priority: (id: string, priority: Priority) => api.post<ApiTrainingJob>(`/training-jobs/${id}/priority`, { priority }),
  start: (id: string) => api.post<ApiTrainingJob>(`/training-jobs/${id}/start`),
  logs: (id: string) => api.get<ApiJobEvent[]>(`/training-jobs/${id}/logs`),
  historyCsv: (projectId: string) =>
    download(`/projects/${projectId}/reports/training-history.csv`, `historial-${projectId}.csv`),
};

/* --------------------------------------------------- evaluación y modelos */

export type ApiEvaluationRun = Omit<EvaluationRun, 'tone'> & {
  projectId: string;
  classes: Array<{ id: string; label: string; short: string }>;
  modelVersionId: string | null;
};

export type ModelStatus = 'DRAFT' | 'REVIEWED' | 'APPROVED' | 'RETIRED';

export interface ApiModelVersion {
  id: string;
  projectId: string;
  jobId: string;
  architectureId: string;
  name: string;
  version: number;
  label: string;
  status: ModelStatus;
  checksum: string;
  metrics: Record<string, number>;
  metadata: {
    dataset?: { name: string; version: number; checksum: string };
    target?: string;
    classes?: string[];
    params?: { epochs: number; batchSize: number; optimizer: string; learningRate: number; seed: number };
    epochsRun?: number;
    trainedBy?: string;
    kerasVersion?: string;
    inputColumns?: string[];
    reviewHistory?: Array<{ from: string; to: string; by: string; note: string }>;
  };
  createdAt: string;
  updatedAt: string;
}

export const evaluationApi = {
  runs: () => api.get<ApiEvaluationRun[]>('/evaluations'),
  observations: () => api.get<Observation[]>('/observations'),
  addObservation: (draft: ObservationDraft) =>
    api.post<Observation>(`/training-jobs/${draft.runId}/observations`, {
      kind: draft.kind,
      title: draft.title,
      body: draft.body,
    }),
  toggleReview: (id: string) => api.post<Observation>(`/observations/${id}/review`),
};

export const modelsApi = {
  listForProject: (projectId: string) => api.get<ApiModelVersion[]>(`/projects/${projectId}/models`),
  setStatus: (id: string, status: ModelStatus, note: string) =>
    api.post<ApiModelVersion>(`/models/${id}/status`, { status, note }),
  download: (model: ApiModelVersion) =>
    download(`/models/${model.id}/download`, `${model.name}-v${model.version}.zip`),
};

/* ------------------------------------------------------- informes (M09) */

export interface ReportExportPayload {
  format: 'CSV' | 'PDF';
  sections: string[];
  rows: number;
  bytes: number;
  fingerprint: string;
  masked: string[];
  scopeLabel: string;
  actor: { id: string; name: string; roleLabel: string; projectRoleLabel: string };
}

export const reportsApi = {
  exports: <T>() => api.get<T[]>('/reports/exports'),
  recordExport: <T>(projectId: string, payload: ReportExportPayload) =>
    api.post<T>(`/projects/${projectId}/reports/exports`, payload),
};

/* -------------------------------------------------- administración (M10) */

export type AdminSnapshot = AdministrationSnapshot & { health: ServiceHealth[] };

export const adminApi = {
  snapshot: () => api.get<AdminSnapshot>('/admin/snapshot'),
  invite: (draft: InviteDraft) => api.post<AdminSnapshot>('/admin/users', draft),
  changeRole: (userId: string, role: UserRole) => api.patch<AdminSnapshot>(`/admin/users/${userId}/role`, { role }),
  toggleStatus: (userId: string) => api.post<AdminSnapshot>(`/admin/users/${userId}/status`),
  setLimit: (id: string, value: number) => api.put<AdminSnapshot>(`/admin/limits/${id}`, { value }),
  saveSettings: (settings: SecuritySettings) => api.put<AdminSnapshot>('/admin/settings', settings),
  recordAuditExport: (events: number) => api.post<AdminSnapshot>('/admin/audit/export', { events }),
  runRetention: () =>
    api.post<AdminSnapshot & { retention: Record<'auditoria' | 'metricas' | 'eventos' | 'artefactos', number> }>(
      '/admin/retention/run',
    ),
};
