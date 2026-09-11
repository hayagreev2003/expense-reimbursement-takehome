import react from '@vitejs/plugin-react';
import { resolve } from 'node:path';
import { defineConfig } from 'vitest/config';

export default defineConfig({
  plugins: [react()],
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./vitest.setup.ts'],
    // Next's own build output and e2e fixtures are not unit tests.
    exclude: ['node_modules', '.next'],
  },
  resolve: {
    alias: { '@': resolve(import.meta.dirname, './src') },
  },
});
