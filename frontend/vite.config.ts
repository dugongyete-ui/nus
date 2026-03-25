import { defineConfig } from 'vite';
import vue from '@vitejs/plugin-vue';
import monacoEditorPlugin from 'vite-plugin-monaco-editor';
import { resolve } from 'path';
import topLevelAwait from 'vite-plugin-top-level-await';

// https://vitejs.dev/config/
export default defineConfig({
  build: {
    target: 'es2022'
  },
  optimizeDeps: {
    esbuildOptions: {
      target: 'es2022'
    },
    exclude: ['lucide-vue-next'],
  },
  plugins: [
    vue(),
    topLevelAwait(),
    (monacoEditorPlugin as any).default({})
  ],
  resolve: {
    alias: {
      '@': resolve(__dirname, 'src')
    }
  },
  server: {
    host: true,
    port: 5173,
    allowedHosts: ['5173-i0fgsnbgdpwdu4yajg36f-cc60360d.sg1.manus.computer', 'localhost', '127.0.0.1'],
    middlewareMode: false,
    ...(process.env.BACKEND_URL && {
      proxy: {
        '/api': {
          target: process.env.BACKEND_URL,
          changeOrigin: true,
          ws: true,
        },
      },
    }),
  },
});
