import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { resolve } from 'path'

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      '@': resolve(__dirname, 'src'),
    },
  },
  server: {
    port: 3000,
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
  build: {
    outDir: 'dist',
    sourcemap: false,
    chunkSizeWarningLimit: 1500,
    rollupOptions: {
      output: {
        // 按依赖拆分 vendor chunk：echarts/antd/react 体积大且版本稳定，
        // 独立分包后业务代码改动不会使它们缓存失效
        manualChunks(id: string) {
          if (!id.includes('node_modules')) return
          if (id.includes('echarts') || id.includes('zrender')) return 'echarts'
          if (id.includes('antd') || id.includes('@ant-design') || id.includes('rc-')) return 'antd'
          // mermaid 及其大体积传递依赖（elkjs/katex 仅在 VibeAgent 动态加载 mermaid 时用到，
          // 归入 mermaid chunk 后 vendor 从 2.1MB 降到 ~390KB）。注意 dompurify 等若再并入
          // 会使该 chunk 超过 Vite 构建解析上限触发 Parse error，故保留在 vendor
          if (id.includes('mermaid') || id.includes('dagre') || id.includes('cytoscape') || id.includes('elkjs') || id.includes('katex')) return 'mermaid'
          // @remix-run/react-router 依赖链并入 react chunk，避免 vendor<->react 循环引用告警
          if (id.includes('react') || id.includes('scheduler') || id.includes('@remix-run')) return 'react'
          return 'vendor'
        },
      },
    },
  },
})
