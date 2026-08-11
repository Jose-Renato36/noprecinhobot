// Camada única de acesso à API do NoPrecinhoBot.
// Em dev o Vite faz proxy de /api para o FastAPI (ver vite.config.js).

const BASE = import.meta.env.VITE_API_URL ?? ''

class ApiError extends Error {
  constructor(mensagem, status) {
    super(mensagem)
    this.name = 'ApiError'
    this.status = status
  }
}

// Não há token guardado aqui de propósito. A sessão vive num cookie httpOnly,
// que este código não consegue ler nem escrever — é o ponto: um XSS nesta página
// também não conseguiria. Quem gerencia o cookie é o navegador, e o servidor o
// apaga em /api/auth/sair.
//
// O App se inscreve em `aoExpirar` para voltar à tela de login quando a sessão
// morre, sem espalhar try/catch por toda parte.
let aoExpirar = null

export const sessao = {
  aoExpirar: (callback) => {
    aoExpirar = callback
  },
}

async function pedir(
  caminho,
  { metodo = 'GET', corpo, publico = false, silencioso = false, ...resto } = {},
) {
  const cabecalhos = {}
  if (corpo !== undefined) cabecalhos['Content-Type'] = 'application/json'

  let resposta
  try {
    resposta = await fetch(`${BASE}${caminho}`, {
      method: metodo,
      headers: cabecalhos,
      // Painel e API são servidos pela mesma origem, então same-origin basta e
      // é mais restritivo que 'include'.
      credentials: 'same-origin',
      body: corpo !== undefined ? JSON.stringify(corpo) : undefined,
      ...resto,
    })
  } catch {
    throw new ApiError('Não foi possível falar com o servidor. Ele está rodando?', 0)
  }

  // 401 numa rota autenticada significa sessão morta. Ficam de fora as rotas
  // públicas (errar a senha não é sessão expirada) e as silenciosas — a
  // checagem de boot leva 401 legítimo de quem nunca entrou, e avisar "sua
  // sessão expirou" a um visitante novo não faria sentido.
  if (resposta.status === 401 && !publico && !silencioso) {
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
  // Silenciosa: é a checagem de boot, e 401 aqui é o caso normal de quem chega
  // deslogado, não uma sessão que caiu.
  eu: () => pedir('/api/auth/eu', { silencioso: true }),
  // O cookie é httpOnly: só o servidor consegue apagá-lo.
  sair: () => pedir('/api/auth/sair', { metodo: 'POST', publico: true }),

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
