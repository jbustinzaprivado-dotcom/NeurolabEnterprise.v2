import { defineConfig } from '@playwright/test';

/* Prueba end-to-end del flujo principal (§4.3, §15, §18) contra un backend aislado
   (e2e/start-backend.mjs) y la interfaz servida por Vite.

     npm run e2e

   En Windows usa el Microsoft Edge del sistema; en la CI, el Chromium que instala Playwright. */

const API_PORT = process.env.NEUROLAB_E2E_API_PORT ?? '8010';
const WEB_PORT = process.env.NEUROLAB_E2E_WEB_PORT ?? '5180';

export default defineConfig({
  testDir: './e2e',
  timeout: 240_000,
  expect: { timeout: 15_000 },
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: process.env.CI ? [['list'], ['html', { open: 'never' }]] : 'list',
  use: {
    baseURL: `http://localhost:${WEB_PORT}`,
    channel: process.env.CI ? undefined : 'msedge',
    locale: 'es-ES',
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
  },
  webServer: [
    {
      command: 'node e2e/start-backend.mjs',
      url: `http://127.0.0.1:${API_PORT}/api/v1/health`,
      env: { NEUROLAB_E2E_API_PORT: API_PORT },
      timeout: 180_000,
      reuseExistingServer: false,
      stdout: 'pipe',
    },
    {
      command: `npx vite --port ${WEB_PORT} --strictPort`,
      url: `http://localhost:${WEB_PORT}`,
      env: { NEUROLAB_API_PROXY: `http://127.0.0.1:${API_PORT}` },
      timeout: 60_000,
      reuseExistingServer: false,
    },
  ],
});
