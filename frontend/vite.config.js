import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// O front fala com a API por caminhos relativos (/api/...). Em desenvolvimento
// o proxy abaixo repassa para o FastAPI; em produção os dois são servidos pela
// mesma origem, então nada muda.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': { target: 'http://127.0.0.1:8000', changeOrigin: true },
      '/loja-demo': { target: 'http://127.0.0.1:8000', changeOrigin: true },
    },
  },
  build: { outDir: 'dist', emptyOutDir: true },
})
