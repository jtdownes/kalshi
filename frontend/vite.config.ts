import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    host: true,
    port: 5173,
    watch: { usePolling: true },
    proxy: {
      '/api/events': {
        target: 'http://kalshi-api:8820',
        changeOrigin: true,
        proxyTimeout: 0,
        timeout: 0,
      },
      '/api': {
        target: 'http://kalshi-api:8820',
        changeOrigin: true,
      },
    },
  },
})
