import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import { fileURLToPath, URL } from 'node:url';

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  server: {
    port: 5173,
    proxy: {
      '/api': {
        // NEUROLAB_API_PROXY permite apuntar a otra API (p. ej. un segundo arranque en :8001).
        target: process.env.NEUROLAB_API_PROXY ?? 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
});
