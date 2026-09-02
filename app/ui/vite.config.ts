import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  const apiUrl = env.VITE_API_URL || 'http://localhost:__BACKEND_PORT__'
  const port = parseInt(env.VITE_PORT || '__FRONTEND_PORT__', 10)

  return {
    plugins: [react()],
    server: {
      port,
      proxy: {
        '/api': { target: apiUrl, changeOrigin: true },
      },
    },
  }
})
