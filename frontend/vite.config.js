import { defineConfig } from 'vite'
import { svelte } from '@sveltejs/vite-plugin-svelte'

// 构建产物落到 scripts/ui_dist/，由 dashboard.py 托管（见 Handler._static）。
// 开发态由 vite 直接服务，/api 与 /files 代理到本地跑着的 XGEO 服务。
export default defineConfig({
  plugins: [svelte()],
  build: {
    outDir: '../scripts/ui_dist',
    emptyOutDir: true,
  },
  server: {
    proxy: {
      '/api': 'http://127.0.0.1:8765',
      '/files': 'http://127.0.0.1:8765',
    },
  },
})
