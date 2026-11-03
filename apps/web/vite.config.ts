import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import { fileURLToPath, URL } from 'node:url';

/* Demostración pública con un túnel temporal de Cloudflare (infra/demo/exponer.ps1): Vite
   bloquea los dominios que no conoce, así que se admiten los de trycloudflare.com. */
const TUNNEL_HOSTS = ['.trycloudflare.com'];

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  server: {
    port: 5173,
    allowedHosts: TUNNEL_HOSTS,
    proxy: {
      '/api': {
        // NEUROLAB_API_PROXY permite apuntar a otra API (p. ej. un segundo arranque en :8001).
        target: process.env.NEUROLAB_API_PROXY ?? 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
  // `vite preview` reutiliza el proxy de `server`; solo hace falta admitir el túnel.
  preview: {
    port: 4173,
    allowedHosts: TUNNEL_HOSTS,
  },
});
