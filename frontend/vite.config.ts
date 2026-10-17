import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// In development, Vite forwards /api to the FastAPI backend, so the browser sees one address.
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/api': process.env.API_URL ?? 'http://localhost:8000',
    },
  },
})
