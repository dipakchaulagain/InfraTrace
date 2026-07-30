import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
// Single source of truth for the version shown in the UI footer — bump this
// alongside the git tag when cutting a release (see README).
import pkg from './package.json'

export default defineConfig({
  plugins: [react()],
  define: {
    __APP_VERSION__: JSON.stringify(pkg.version),
  },
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
  build: {
    chunkSizeWarningLimit: 800,
    rollupOptions: {
      output: {
        manualChunks: {
          'vendor-react':   ['react', 'react-dom', 'react-router-dom'],
          'vendor-query':   ['@tanstack/react-query'],
          'vendor-charts':  ['recharts'],
          'vendor-icons':   ['lucide-react'],
          'vendor-misc':    ['axios', 'date-fns', 'clsx'],
        },
      },
    },
  },
})
