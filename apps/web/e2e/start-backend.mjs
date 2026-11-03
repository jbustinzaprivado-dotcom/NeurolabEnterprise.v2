// Backend aislado para la prueba end-to-end (§15): API + worker sobre una base SQLite temporal,
// con autenticación local (correo y contraseña demo) en lugar de Keycloak. No toca la base de
// trabajo, el almacén ni el proveedor de identidad de la máquina. Lo lanza playwright.config.ts.
import { spawn, spawnSync } from 'node:child_process';
import { existsSync, mkdtempSync, readdirSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '../../..');
const venvPython = process.platform === 'win32' ? join(root, 'venv', 'Scripts', 'python.exe') : join(root, 'venv', 'bin', 'python');
const python = process.env.NEUROLAB_PYTHON ?? (existsSync(venvPython) ? venvPython : 'python');
const port = process.env.NEUROLAB_E2E_API_PORT ?? '8010';
// Playwright detiene este proceso a la fuerza al terminar y no siempre alcanza a limpiar:
// las carpetas de corridas anteriores se borran al empezar.
for (const name of readdirSync(tmpdir())) {
  if (name.startsWith('neurolab-e2e-')) {
    try {
      rmSync(join(tmpdir(), name), { recursive: true, force: true });
    } catch {
      /* En uso por otra corrida: se deja. */
    }
  }
}
const data = mkdtempSync(join(tmpdir(), 'neurolab-e2e-'));

const env = {
  ...process.env,
  NEUROLAB_ENV: 'test',
  NEUROLAB_HOST: '127.0.0.1',
  NEUROLAB_PORT: port,
  NEUROLAB_DATABASE_URL: `sqlite:///${data.replace(/\\/g, '/')}/e2e.db`,
  NEUROLAB_DATA_DIR: data,
  NEUROLAB_STORAGE_BACKEND: 'local',
  NEUROLAB_AUTH_PROVIDER: 'local',
  NEUROLAB_AUTH_DEV_BYPASS: 'false',
  NEUROLAB_SEED_DEMO: 'true',
  NEUROLAB_SEED_HISTORY: 'false',
  NEUROLAB_WORKER_POLL_SECONDS: '0.5',
  NEUROLAB_LOG_FORMAT: 'text',
  NEUROLAB_LOG_LEVEL: 'WARNING',
  TF_CPP_MIN_LOG_LEVEL: '2',
};

const children = [
  spawn(python, ['services/api/app/main.py'], { cwd: root, env, stdio: 'inherit' }),
  // El worker espera solo a que la API cree el esquema.
  spawn(python, ['workers/training/main.py'], { cwd: root, env, stdio: 'inherit' }),
];

let stopping = false;
function stop(code = 0) {
  if (stopping) return;
  stopping = true;
  for (const child of children) {
    if (child.exitCode !== null) continue;
    if (process.platform === 'win32') spawnSync('taskkill', ['/pid', String(child.pid), '/T', '/F'], { stdio: 'ignore' });
    else child.kill('SIGTERM');
  }
  rmSync(data, { recursive: true, force: true });
  process.exit(code);
}

for (const child of children) {
  child.on('exit', (code) => {
    if (!stopping) {
      console.error(`[e2e] un proceso del backend terminó con código ${code}`);
      stop(1);
    }
  });
}
for (const signal of ['SIGINT', 'SIGTERM', 'SIGHUP']) process.on(signal, () => stop(0));
process.on('exit', () => stop(0));
