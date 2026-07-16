/// <reference types="vitest" />
import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { resolve } from 'path'

// Keep the default compatible with the documented local backend while allowing
// deployed/dev environments (for example the :8889 container port) to smoke
// test the same frontend without editing this file.
const backendProxyTarget = process.env.VITE_BACKEND_PROXY_TARGET || 'http://localhost:8000'
const websocketProxyTarget = backendProxyTarget.replace(/^http/, 'ws')

export default defineConfig({
  plugins: [
    vue(),
  ],
  test: {
    environment: 'happy-dom',
    globals: true,
    setupFiles: ['tests/setup.ts'],
    include: ['tests/**/*.spec.ts'],
    coverage: {
      provider: 'v8',
      reporter: ['text', 'json', 'html'],
    },
  },
  resolve: {
    alias: {
      '@': resolve(__dirname, 'src'),
    },
  },
  build: {
    outDir: 'dist',
    assetsDir: 'assets',
    sourcemap: false,
    emptyOutDir: true,
    chunkSizeWarningLimit: 500,
    // ponytail: 关闭 build 报告的 gzip 体积计算——vite 在此阶段为每个 chunk 算 gzip，内存峰值在低内存机器上会 OOM (EXIT 137)。产物不受影响。
    reportCompressedSize: false,
    rollupOptions: {
      output: {
        manualChunks: {
          'vue-vendor': ['vue', 'vue-router', 'pinia'],
          'axios': ['axios'],
        },
      },
    },
  },
  server: {
    port: 3000,
    proxy: {
      '/api': {
        target: backendProxyTarget,
        changeOrigin: true,
      },
      '/ws': {
        target: websocketProxyTarget,
        ws: true,
        changeOrigin: true,
        rewrite: (path) => path,
      },
    },
  },
})
