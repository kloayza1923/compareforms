import { defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  // deploy_front.sh supplies a versioned, same-origin asset base when publishing.
  base: process.env.FRONTEND_BASE_PATH || '/',
  server: {
    port: 5173,
    strictPort: true,
    proxy: { '/api': { target: process.env.COMPAREFORMS_API_TARGET || 'http://127.0.0.1:8015', changeOrigin: false } },
  },
  build: { sourcemap: false, manifest: true, target: 'es2022' },
  test: { environment: 'jsdom', setupFiles: ['./src/test-setup.ts'], restoreMocks: true },
});
