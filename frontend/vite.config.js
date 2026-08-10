import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// O front fala com a API por caminhos relativos (/api/...). Em desenvolvimento
// o proxy abaixo repassa para o FastAPI; em produção os dois são servidos pela
// mesma origem, então nada muda.
// A partir do Vite 5.4.12 o servidor recusa requisições cujo Host não seja
// conhecido (proteção contra DNS rebinding). Em produção isso significa que o
// domínio da Railway precisa ser liberado, senão toda requisição volta como
// "Blocked request. This host is not allowed.". A Railway publica o domínio do
// serviço em RAILWAY_PUBLIC_DOMAIN, então usamos ele quando existir; fora da
// Railway não há domínio a liberar e o padrão do Vite já resolve.
const dominioPublico = process.env.RAILWAY_PUBLIC_DOMAIN

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': { target: 'http://127.0.0.1:8000', changeOrigin: true },
      '/loja-demo': { target: 'http://127.0.0.1:8000', changeOrigin: true },
    },
  },
  preview: {
    port: Number(process.env.PORT) || 4173,
    host: true,
    ...(dominioPublico ? { allowedHosts: [dominioPublico] } : {}),
  },
  build: { outDir: 'dist', emptyOutDir: true },
})
