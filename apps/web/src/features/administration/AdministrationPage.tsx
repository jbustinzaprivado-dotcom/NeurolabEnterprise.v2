import { useCallback, useEffect, useMemo, useState } from 'react';
import type {
  AdministrationSnapshot,
  AuditEvent,
  InviteDraft,
  ResourceLimitId,
  SecuritySettings,
  ServiceHealth,
} from '@/types/administration';
import type { UserRole } from '@/types/domain';
import { useSession } from '@/app/session';
import { adminApi } from '@/lib/api/resources';
import { roleLabels } from '@/lib/nav';
import { formatNumber, formatRelativeTime, percentage } from '@/lib/format';
import { Chip } from '@/components/ui/Chip';
import { Icon } from '@/components/ui/Icon';
import { Panel } from '@/components/ui/Panel';
import { UsersPanel } from '@/features/administration/UsersPanel';
import { PermissionMatrix } from '@/features/administration/PermissionMatrix';
import { AuditPanel } from '@/features/administration/AuditPanel';
import { LimitsPanel } from '@/features/administration/LimitsPanel';
import { PolicyPanel } from '@/features/administration/PolicyPanel';
import { HealthPanel } from '@/features/administration/HealthPanel';
import { InviteDialog } from '@/features/administration/InviteDialog';
import { AdminModal } from '@/features/administration/AdminModal';
import {
  auditCsv,
  mfaPolicyLabels,
  roleDefinitions,
  statusActionMeta,
} from '@/features/administration/model';

type AdminDialog = 'matrix' | 'health' | 'audit' | 'limits' | 'policy';

interface Notice {
  tone: 'success' | 'info' | 'danger';
  text: string;
}

const SETTING_LABELS: Record<keyof SecuritySettings, string> = {
  sessionMinutes: 'sesión',
  mfaPolicy: 'MFA',
  auditRetentionDays: 'retención de auditoría',
  artifactRetentionDays: 'retención de artefactos',
  metricsRetentionDays: 'retención de métricas',
  exportRequiresReview: 'revisión de exportaciones',
};

type Snapshot = AdministrationSnapshot & { health: ServiceHealth[] };

export function AdministrationPage() {
  const { actor } = useSession();
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [checkedAt, setCheckedAt] = useState(() => new Date().toISOString());
  const [inviteOpen, setInviteOpen] = useState(false);
  const [openDialog, setOpenDialog] = useState<AdminDialog | null>(null);
  const [notice, setNotice] = useState<Notice | null>(null);

  const load = useCallback(async () => {
    try {
      setSnapshot(await adminApi.snapshot());
      setCheckedAt(new Date().toISOString());
      setLoadError(null);
    } catch (caught) {
      setLoadError(caught instanceof Error ? caught.message : 'No fue posible abrir la consola de gobierno.');
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  /** Toda acción la aplica la API, que devuelve la foto actualizada (incluida su auditoría). */
  const apply = async (action: () => Promise<Snapshot>, success: string, after?: () => void): Promise<boolean> => {
    try {
      setSnapshot(await action());
      setNotice({ tone: 'success', text: success });
      after?.();
      return true;
    } catch (caught) {
      setNotice({ tone: 'danger', text: caught instanceof Error ? caught.message : 'La API rechazó el cambio.' });
      return false;
    }
  };

  const metrics = useMemo(() => {
    if (!snapshot) return null;
    const total = snapshot.users.length;
    const active = snapshot.users.filter((user) => user.status === 'ACTIVE').length;
    const mfa = snapshot.users.filter((user) => user.status === 'ACTIVE' && user.mfaEnabled).length;
    const critical = snapshot.audit.filter((event) => event.severity === 'critical').length;
    const warnings = snapshot.audit.filter((event) => event.severity === 'warning').length;
    const concurrency = snapshot.limits.find((limit) => limit.id === 'concurrency') ?? snapshot.limits[0];
    return { total, active, mfa, critical, warnings, concurrency };
  }, [snapshot]);

  const health = useMemo(() => {
    const services = snapshot?.health ?? [];
    const degraded = services.filter((service) => service.status !== 'HEALTHY').length;
    return { healthy: services.length - degraded, degraded };
  }, [snapshot]);

  const assignments = useMemo(
    () => roleDefinitions.reduce((total, role) => total + role.permissions.length, 0),
    [],
  );

  if (!snapshot || !metrics) {
    return (
      <Panel title="Administración y seguridad" icon="shield" subtitle="M10 · consola de gobierno">
        <div className="empty">
          <Icon name={loadError ? 'lock' : 'shield'} />
          <h3>{loadError ? 'Acceso restringido' : 'Cargando consola…'}</h3>
          <p>
            {loadError ??
              'Leyendo cuentas, auditoría, límites y políticas desde la API.'}
          </p>
          {loadError && actor.role !== 'admin' ? (
            <p className="panel__note">
              Tu rol global es {roleLabels[actor.role].toLowerCase()}. En desarrollo puedes cambiar a la
              administradora demo desde el menú de perfil.
            </p>
          ) : null}
        </div>
      </Panel>
    );
  }

  const handleRoleChange = (userId: string, role: UserRole) => {
    const user = snapshot.users.find((item) => item.id === userId);
    if (!user || user.role === role) return;
    void apply(
      () => adminApi.changeRole(userId, role),
      `${user.displayName} ahora tiene el rol ${roleLabels[role].toLowerCase()}.`,
    );
  };

  const handleToggleStatus = (userId: string) => {
    const user = snapshot.users.find((item) => item.id === userId);
    if (!user) return;
    void apply(
      () => adminApi.toggleStatus(userId),
      `${user.displayName}: ${statusActionMeta[user.status].auditLabel.toLowerCase()}.`,
    );
  };

  const handleInvite = (draft: InviteDraft) => {
    void apply(
      () => adminApi.invite(draft),
      `Invitación registrada para ${draft.email}. La cuenta se activa en su primer inicio de sesión.`,
      () => setInviteOpen(false),
    );
  };

  const handleApplyLimit = (id: ResourceLimitId, value: number) => {
    const limit = snapshot.limits.find((item) => item.id === id);
    if (!limit || value === limit.limit) return;
    void apply(
      () => adminApi.setLimit(id, value),
      `${limit.label}: ${formatNumber(value)} ${limit.unit} (antes ${formatNumber(limit.limit)}). Rige desde el próximo trabajo.`,
    );
  };

  const handleSaveSettings = (next: SecuritySettings) => {
    const changed = (Object.keys(next) as (keyof SecuritySettings)[]).filter(
      (key) => snapshot.settings[key] !== next[key],
    );
    if (changed.length === 0) {
      setNotice({ tone: 'info', text: 'No hay cambios pendientes en las políticas.' });
      return;
    }
    void apply(
      () => adminApi.saveSettings(next),
      `Políticas actualizadas: ${changed.map((key) => SETTING_LABELS[key]).join(', ')}.`,
      () => setOpenDialog(null),
    );
  };

  const handleExportAudit = (events: AuditEvent[]) => {
    const csv = auditCsv(events);
    const blob = new Blob(['﻿', csv], { type: 'text/csv;charset=utf-8;' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = `auditoria-neurolab-${new Date().toISOString().slice(0, 10)}.csv`;
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);

    void apply(
      () => adminApi.recordAuditExport(events.length),
      `Se descargaron ${events.length} eventos en CSV. La exportación quedó registrada.`,
      () => setOpenDialog(null),
    );
  };

  const handleRefreshHealth = () => {
    void load().then(() =>
      setNotice({
        tone: 'info',
        text: `Salud verificada contra la API: ${health.healthy} servicios operativos y ${health.degraded} con avisos.`,
      }),
    );
  };

  const self = snapshot.users.find((user) => user.id === actor.id);

  return (
    <>
      <div className="page-head">
        <div className="page-head__text">
          <p className="page-head__eyebrow">
            <Icon name="shield" size={14} strokeWidth={2} />
            M10 · Administración y seguridad
          </p>
          <h1 className="page-head__title">Gobierno de cuentas, permisos y operación</h1>
          <p className="page-head__lede">
            Administre altas y roles globales, revise la matriz RBAC y la auditoría de acciones,
            ajuste los límites de recursos y las políticas de retención. Toda modificación queda
            trazada con actor, objetivo y origen.
          </p>
        </div>
        <div className="page-head__actions">
          <button type="button" className="btn btn--secondary" onClick={() => void load()}>
            <Icon name="refresh" size={16} />
            Actualizar
          </button>
          <button type="button" className="btn btn--primary" onClick={() => setInviteOpen(true)}>
            <Icon name="userPlus" size={16} />
            Invitar usuario
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

      <div className="dash adm-page">
        <section className="adm-quick" aria-label="Vistas de gobierno">
          <button
            type="button"
            className="adm-quick__item"
            onClick={() => setOpenDialog('matrix')}
          >
            <span className="adm-quick__icon">
              <Icon name="shield" size={18} strokeWidth={1.9} />
            </span>
            <span className="adm-quick__text">
              <strong>Matriz de permisos</strong>
              <span>
                {assignments} asignaciones en 5 roles · política RBAC vigente
              </span>
            </span>
            <Icon name="chevronRight" size={16} className="adm-quick__chevron" />
          </button>

          <button
            type="button"
            className="adm-quick__item"
            onClick={() => setOpenDialog('health')}
          >
            <span className="adm-quick__icon">
              <Icon name="gauge" size={18} strokeWidth={1.9} />
            </span>
            <span className="adm-quick__text">
              <strong>Salud del sistema</strong>
              <span>
                {health.healthy} operativos · {health.degraded} con avisos ·{' '}
                {formatRelativeTime(checkedAt)}
              </span>
            </span>
            <Chip tone={health.degraded > 0 ? 'preparing' : 'completed'} dot>
              {health.degraded > 0 ? 'Con avisos' : 'Operativo'}
            </Chip>
            <Icon name="chevronRight" size={16} className="adm-quick__chevron" />
          </button>

          <button
            type="button"
            className="adm-quick__item"
            onClick={() => setOpenDialog('audit')}
          >
            <span className="adm-quick__icon">
              <Icon name="fileText" size={18} strokeWidth={1.9} />
            </span>
            <span className="adm-quick__text">
              <strong>Auditoría de acciones</strong>
              <span>
                {snapshot.audit.length} eventos · {metrics.warnings} advertencias · retención{' '}
                {snapshot.settings.auditRetentionDays} días
              </span>
            </span>
            <Icon name="chevronRight" size={16} className="adm-quick__chevron" />
          </button>

          <button
            type="button"
            className="adm-quick__item"
            onClick={() => setOpenDialog('limits')}
          >
            <span className="adm-quick__icon">
              <Icon name="server" size={18} strokeWidth={1.9} />
            </span>
            <span className="adm-quick__text">
              <strong>Límites de recursos</strong>
              <span>
                {metrics.concurrency.used}/{metrics.concurrency.limit} trabajos activos por usuario ·{' '}
                {snapshot.limits.length} cuotas vigentes
              </span>
            </span>
            <Icon name="chevronRight" size={16} className="adm-quick__chevron" />
          </button>

          <button
            type="button"
            className="adm-quick__item"
            onClick={() => setOpenDialog('policy')}
          >
            <span className="adm-quick__icon">
              <Icon name="settings" size={18} strokeWidth={1.9} />
            </span>
            <span className="adm-quick__text">
              <strong>Políticas de seguridad</strong>
              <span>
                Sesión {snapshot.settings.sessionMinutes} min ·{' '}
                {mfaPolicyLabels[snapshot.settings.mfaPolicy]} · retención{' '}
                {snapshot.settings.auditRetentionDays} días
              </span>
            </span>
            <Icon name="chevronRight" size={16} className="adm-quick__chevron" />
          </button>
        </section>

        <section className="adm-session" aria-label="Sesión de administración">
          <span className="avatar avatar--lg" aria-hidden="true">
            {actor.initials}
          </span>
          <div className="adm-session__identity">
            <strong>{actor.displayName}</strong>
            <span>
              {self?.title ?? roleLabels[actor.role]} · <span className="u-mono">{actor.id}</span>
            </span>
          </div>
          <div className="adm-session__chips">
            <Chip tone="completed" dot>
              {roleLabels[actor.role]}
            </Chip>
            <Chip tone="outline">
              <Icon name="lock" size={12} />
              {self?.mfaEnabled ? 'MFA registrado' : 'MFA no registrado'}
            </Chip>
            <Chip tone="outline">
              <Icon name="clock" size={12} />
              Sesión {snapshot.settings.sessionMinutes} min
            </Chip>
            <Chip tone="outline">
              <Icon name="server" size={12} />
              Último acceso {self?.lastAccessAt ? formatRelativeTime(self.lastAccessAt) : '—'}
            </Chip>
          </div>
          <p className="adm-session__note">
            <Icon name="info" size={13} />
            Los cambios se aplican en la API y quedan en la auditoría con tu identidad y la IP de origen.
            Los límites rigen desde el próximo trabajo; la duración de sesión, desde el próximo inicio de
            sesión.
          </p>
        </section>

        <section className="kpi-grid" aria-label="Indicadores de administración">
          <article className="kpi" data-accent="indigo">
            <div className="kpi__top">
              <h3 className="kpi__label">Cuentas activas</h3>
              <span className="kpi__icon">
                <Icon name="users" size={17} />
              </span>
            </div>
            <div className="kpi__value-row">
              <p className="kpi__value">
                {metrics.active}
                <small> / {metrics.total}</small>
              </p>
            </div>
            <div className="kpi__foot">
              <span>{metrics.total - metrics.active} sin acceso vigente</span>
            </div>
          </article>

          <article className="kpi" data-accent="emerald">
            <div className="kpi__top">
              <h3 className="kpi__label">Cobertura MFA</h3>
              <span className="kpi__icon">
                <Icon name="lock" size={17} />
              </span>
            </div>
            <div className="kpi__value-row">
              <p className="kpi__value">
                {percentage(metrics.mfa, metrics.active)}
                <small> %</small>
              </p>
            </div>
            <div className="kpi__foot">
              <span>
                {metrics.mfa} de {metrics.active} cuentas activas
              </span>
            </div>
          </article>

          <article className="kpi" data-accent="amber">
            <div className="kpi__top">
              <h3 className="kpi__label">Eventos auditados</h3>
              <span className="kpi__icon">
                <Icon name="fileText" size={17} />
              </span>
            </div>
            <div className="kpi__value-row">
              <p className="kpi__value">{snapshot.audit.length}</p>
            </div>
            <div className="kpi__foot">
              <span>
                {metrics.critical} críticos · {metrics.warnings} advertencias
              </span>
            </div>
          </article>

          <article className="kpi" data-accent="violet">
            <div className="kpi__top">
              <h3 className="kpi__label">Trabajos activos por usuario</h3>
              <span className="kpi__icon">
                <Icon name="server" size={17} />
              </span>
            </div>
            <div className="kpi__value-row">
              <p className="kpi__value">
                {metrics.concurrency.used}
                <small> / {metrics.concurrency.limit}</small>
              </p>
            </div>
            <div className="kpi__foot">
              <span>{percentage(metrics.concurrency.used, metrics.concurrency.limit)} % del cupo más usado</span>
            </div>
          </article>
        </section>

        <UsersPanel
          users={snapshot.users}
          currentUserId={actor.id}
          onRoleChange={handleRoleChange}
          onToggleStatus={handleToggleStatus}
        />
      </div>

      {openDialog === 'matrix' ? (
        <AdminModal
          title="Matriz de permisos (RBAC)"
          lede="Política vigente por rol global. Los permisos de proyecto siguen dependiendo de la pertenencia al proyecto."
          size="xl"
          onClose={() => setOpenDialog(null)}
        >
          <PermissionMatrix />
        </AdminModal>
      ) : null}

      {openDialog === 'health' ? (
        <AdminModal
          title="Salud del sistema"
          lede="Sondas de la API, la base de datos, los workers y el almacenamiento."
          size="lg"
          onClose={() => setOpenDialog(null)}
        >
          <HealthPanel
            services={snapshot.health}
            checkedAt={checkedAt}
            onRefresh={handleRefreshHealth}
          />
        </AdminModal>
      ) : null}

      {openDialog === 'audit' ? (
        <AdminModal
          title="Auditoría de acciones"
          lede="Trazabilidad de accesos, permisos, recursos, datasets, entrenamientos, modelos y exportaciones."
          size="xl"
          onClose={() => setOpenDialog(null)}
        >
          <AuditPanel
            events={snapshot.audit}
            retentionDays={snapshot.settings.auditRetentionDays}
            onExport={handleExportAudit}
          />
        </AdminModal>
      ) : null}

      {openDialog === 'limits' ? (
        <AdminModal
          title="Límites de recursos"
          lede="Cuotas que la API y el worker aplican de verdad: cola por usuario y proyecto, duración, épocas, carga y almacenamiento."
          size="xl"
          onClose={() => setOpenDialog(null)}
        >
          <LimitsPanel limits={snapshot.limits} onApply={handleApplyLimit} />
        </AdminModal>
      ) : null}

      {openDialog === 'policy' ? (
        <AdminModal
          title="Políticas de seguridad"
          lede="Sesión, autenticación multifactor y plazos de conservación. Los cambios rigen para todas las cuentas."
          size="lg"
          onClose={() => setOpenDialog(null)}
        >
          <PolicyPanel settings={snapshot.settings} onSave={handleSaveSettings} />
        </AdminModal>
      ) : null}

      {inviteOpen ? (
        <InviteDialog
          existingEmails={snapshot.users.map((user) => user.email)}
          onClose={() => setInviteOpen(false)}
          onSubmit={handleInvite}
        />
      ) : null}
    </>
  );
}
