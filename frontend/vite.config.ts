import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// In dev, /api is proxied to FastAPI so the browser sees one origin (no CORS needed).
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5173,
    proxy: Object.fromEntries(
      ['/api', '/docs', '/redoc', '/openapi.json'].map((path) => [
        path,
        { target: process.env.VITE_API_PROXY_TARGET ?? 'http://localhost:8000', changeOrigin: true },
      ]),
    ),
  },
})
