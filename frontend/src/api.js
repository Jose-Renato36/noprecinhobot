// Camada única de acesso à API do NoPrecinhoBot.
// Em dev o Vite faz proxy de /api para o FastAPI (ver vite.config.js).

const BASE = import.meta.env.VITE_API_URL ?? ''
const CHAVE_TOKEN = 'noprecinho.token'

class ApiError extends Error {
  constructor(mensagem, status) {
    super(mensagem)
    this.name = 'ApiError'
    this.status = status
  }
}

// O token vive no localStorage para sobreviver ao F5. Quem precisa saber que ele
// caiu (token expirado, conta removida) se inscreve em `aoExpirar`, e o App usa
// isso para devolver o usuário à tela de login sem espalhar try/catch por tudo.
let aoExpirar = null

export const sessao = {
  token: () => localStorage.getItem(CHAVE_TOKEN),
  guardar: (token) => localStorage.setItem(CHAVE_TOKEN, token),
  limpar: () => localStorage.removeItem(CHAVE_TOKEN),
  aoExpirar: (callback) => {
    aoExpirar = callback
  },
}

async function pedir(caminho, { metodo = 'GET', corpo, publico = false, ...resto } = {}) {
  const cabecalhos = {}
  if (corpo !== undefined) cabecalhos['Content-Type'] = 'application/json'

  const token = sessao.token()
  if (token && !publico) cabecalhos.Authorization = `Bearer ${token}`

  let resposta
  try {
    resposta = await fetch(`${BASE}${caminho}`, {
      method: metodo,
      headers: cabecalhos,
      body: corpo !== undefined ? JSON.stringify(corpo) : undefined,
      ...resto,
    })
  } catch {
    throw new ApiError('Não foi possível falar com o servidor. Ele está rodando?', 0)
  }

  // 401 numa rota autenticada significa sessão morta: limpa e avisa o App. As
  // rotas públicas (login/registro) ficam de fora, senão errar a senha
  // dispararia um "sua sessão expirou" sem sentido.
  if (resposta.status === 401 && !publico) {
    sessao.limpar()
    aoExpirar?.()
  }

  if (resposta.status === 204) return null

  const texto = await resposta.text()
  let dados = null
  try {
    dados = texto ? JSON.parse(texto) : null
  } catch {
    dados = null
  }

  if (!resposta.ok) {
    throw new ApiError(extrairMensagem(dados) ?? `Erro ${resposta.status}`, resposta.status)
  }
  return dados
}

// O FastAPI devolve `detail` como string (HTTPException) ou como lista de erros
// de validação do Pydantic — os dois casos precisam virar texto legível.
function extrairMensagem(dados) {
  const detalhe = dados?.detail
  if (!detalhe) return null
  if (typeof detalhe === 'string') return detalhe
  if (Array.isArray(detalhe)) {
    return detalhe.map((e) => e.msg?.replace(/^Value error,\s*/, '') ?? String(e)).join(' • ')
  }
  return null
}

export const api = {
  registrar: (nome, email, senha) =>
    pedir('/api/auth/registrar', { metodo: 'POST', corpo: { nome, email, senha }, publico: true }),
  login: (email, senha) =>
    pedir('/api/auth/login', { metodo: 'POST', corpo: { email, senha }, publico: true }),
  eu: () => pedir('/api/auth/eu'),

  resumo: () => pedir('/api/resumo'),
  health: () => pedir('/api/health'),
  saudeLojas: () => pedir('/api/lojas'),

  listarProdutos: (filtros = {}) => {
    const busca = new URLSearchParams()
    if (filtros.status) busca.set('status', filtros.status)
    if (filtros.busca) busca.set('busca', filtros.busca)
    const qs = busca.toString()
    return pedir(`/api/produtos${qs ? `?${qs}` : ''}`)
  },
  cadastrarProduto: (url, precoAlvo) =>
    pedir('/api/produtos', { metodo: 'POST', corpo: { url, preco_alvo: precoAlvo } }),
  atualizarProduto: (id, dados) => pedir(`/api/produtos/${id}`, { metodo: 'PATCH', corpo: dados }),
  removerProduto: (id) => pedir(`/api/produtos/${id}`, { metodo: 'DELETE' }),
  pausarProduto: (id) => pedir(`/api/produtos/${id}/pausar`, { metodo: 'POST' }),
  retomarProduto: (id) => pedir(`/api/produtos/${id}/retomar`, { metodo: 'POST' }),
  coletarProduto: (id) => pedir(`/api/produtos/${id}/coletar`, { metodo: 'POST' }),
  historico: (id) => pedir(`/api/produtos/${id}/historico`),
  previa: (url) => pedir('/api/previa', { metodo: 'POST', corpo: { url } }),

  executarRodada: () => pedir('/api/coletas/executar', { metodo: 'POST' }),

  listarAlertas: (apenasNaoLidos = false) =>
    pedir(`/api/alertas?apenas_nao_lidos=${apenasNaoLidos}`),
  marcarAlertaLido: (id) => pedir(`/api/alertas/${id}/lido`, { metodo: 'POST' }),
  marcarTodosLidos: () => pedir('/api/alertas/marcar-todos-lidos', { metodo: 'POST' }),
  removerAlerta: (id) => pedir(`/api/alertas/${id}`, { metodo: 'DELETE' }),

  demoProdutos: () => pedir('/api/demo/produtos'),
  demoPromocao: (desconto = 0.35) =>
    pedir(`/api/demo/promocao?desconto=${desconto}`, { metodo: 'POST' }),
  demoNormalizar: () => pedir('/api/demo/normalizar', { metodo: 'POST' }),
}

export { ApiError }
