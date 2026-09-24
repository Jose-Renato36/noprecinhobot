import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// O painel fala com a API por caminhos relativos (/api/...). O proxy abaixo
// repassa essas chamadas para o FastAPI em http://127.0.0.1:8000, então não há
// URL de API para configurar nem CORS para resolver.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': { target: 'http://127.0.0.1:8000', changeOrigin: true },
      '/loja-demo': { target: 'http://127.0.0.1:8000', changeOrigin: true },
    },
  },
})
