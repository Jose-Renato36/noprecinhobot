import { useCallback, useEffect, useRef, useState } from 'react'
import { api, sessao } from './api'
import CardProduto from './components/CardProduto'
import Etiqueta from './components/Etiqueta'
import FormularioProduto from './components/FormularioProduto'
import LojaDemo from './components/LojaDemo'
import ModalHistorico from './components/ModalHistorico'
import PainelAlertas from './components/PainelAlertas'
import ResumoPainel from './components/ResumoPainel'
import SaudeLojas from './components/SaudeLojas'
import TelaLogin from './components/TelaLogin'
import Toasts from './components/Toasts'

const ABAS = [
  { id: 'painel', rotulo: 'Minha lista' },
  { id: 'alertas', rotulo: 'Avisos' },
  { id: 'demo', rotulo: 'Loja de teste' },
  { id: 'coletor', rotulo: 'Coletor' },
]

const FILTROS = [
  { id: '', rotulo: 'Todos' },
  { id: 'alvo_atingido', rotulo: 'No meu preço' },
  { id: 'aguardando', rotulo: 'Esperando' },
  { id: 'pausado', rotulo: 'Pausados' },
]

export default function App() {
  const [usuario, setUsuario] = useState(null)
  // Terceiro estado além de "entrou"/"não entrou": ainda conferindo o token
  // guardado. Sem ele, quem tem sessão válida vê a tela de login piscar a cada F5.
  const [verificandoSessao, setVerificandoSessao] = useState(true)

  const [aba, setAba] = useState('painel')
  const [produtos, setProdutos] = useState([])
  const [alertas, setAlertas] = useState([])
  const [resumo, setResumo] = useState(null)
  const [lojas, setLojas] = useState([])
  const [filtro, setFiltro] = useState('')
  const [busca, setBusca] = useState('')
  const [carregando, setCarregando] = useState(true)
  const [coletando, setColetando] = useState(false)
  const [ocupados, setOcupados] = useState(() => new Set())
  const [historicoAberto, setHistoricoAberto] = useState(null)
  const [falhaConexao, setFalhaConexao] = useState(null)
  const [avisos, setAvisos] = useState([])

  const proximoAviso = useRef(0)

  const avisar = useCallback((tipo, texto) => {
    const id = ++proximoAviso.current
    setAvisos((atuais) => [...atuais, { id, tipo, texto }])
    setTimeout(() => setAvisos((atuais) => atuais.filter((a) => a.id !== id)), 5000)
  }, [])

  const fecharAviso = useCallback(
    (id) => setAvisos((atuais) => atuais.filter((a) => a.id !== id)),
    [],
  )

  const carregar = useCallback(async () => {
    try {
      const [listaProdutos, listaAlertas, dadosResumo, saude] = await Promise.all([
        api.listarProdutos({ status: filtro, busca }),
        api.listarAlertas(),
        api.resumo(),
        api.saudeLojas(),
      ])
      setProdutos(listaProdutos)
      setAlertas(listaAlertas)
      setResumo(dadosResumo)
      setLojas(saude)
      setFalhaConexao(null)
    } catch (e) {
      setFalhaConexao(e.message)
    } finally {
      setCarregando(false)
    }
  }, [filtro, busca])

  const sair = useCallback(async () => {
    // O cookie é httpOnly, então quem o apaga é o servidor. Se a chamada falhar
    // (rede fora), a sessão local cai do mesmo jeito — deixar o painel aberto
    // depois de um "Sair" seria pior que a inconsistência.
    try {
      await api.sair()
    } catch {
      /* ignorado de propósito */
    }
    setUsuario(null)
    setProdutos([])
    setAlertas([])
    setResumo(null)
    setLojas([])
    setAba('painel')
  }, [])

  // Token expirado no meio do uso: a camada de API avisa e a sessão cai aqui,
  // em vez de o painel ficar mostrando erro em toda requisição.
  useEffect(() => {
    sessao.aoExpirar(() => {
      setUsuario(null)
      avisar('info', 'Sua sessão expirou. Entre novamente.')
    })
  }, [avisar])

  // No boot, pergunta ao servidor se o cookie de sessão ainda vale. Não dá para
  // checar isso no cliente: sendo httpOnly, o cookie é invisível aqui.
  useEffect(() => {
    api
      .eu()
      .then(setUsuario)
      .catch(() => setUsuario(null))
      .finally(() => setVerificandoSessao(false))
  }, [])

  useEffect(() => {
    if (usuario) carregar()
  }, [usuario, carregar])

  // O agendador trabalha em segundo plano; o painel se atualiza sozinho
  // para refletir coletas e alertas que aconteceram sem o usuário pedir.
  useEffect(() => {
    if (!usuario) return
    const id = setInterval(carregar, 15000)
    return () => clearInterval(id)
  }, [usuario, carregar])

  function marcarOcupado(id, ocupado) {
    setOcupados((atuais) => {
      const copia = new Set(atuais)
      ocupado ? copia.add(id) : copia.delete(id)
      return copia
    })
  }

  async function comOcupado(produto, fn) {
    marcarOcupado(produto.id, true)
    try {
      await fn()
      await carregar()
    } catch (e) {
      avisar('erro', e.message)
    } finally {
      marcarOcupado(produto.id, false)
    }
  }

  const acoes = {
    pausar: (p) =>
      comOcupado(p, async () => {
        await api.pausarProduto(p.id)
        avisar('info', `Avisos de "${p.nome}" pausados.`)
      }),
    retomar: (p) =>
      comOcupado(p, async () => {
        await api.retomarProduto(p.id)
        avisar('sucesso', `Voltei a acompanhar "${p.nome}".`)
      }),
    remover: (p) => {
      if (!window.confirm(`Tirar "${p.nome}" da lista? O histórico de preços dele some junto.`)) return
      return comOcupado(p, async () => {
        await api.removerProduto(p.id)
        avisar('info', 'Tirei da sua lista.')
      })
    },
    coletar: (p) =>
      comOcupado(p, async () => {
        const resultado = await api.coletarProduto(p.id)
        if (!resultado.sucesso) return avisar('erro', 'Não consegui ler o preço nesta loja agora.')
        avisar(
          resultado.alerta_gerado ? 'sucesso' : 'info',
          resultado.alerta_gerado
            ? `Chegou no seu preço: ${p.nome} está por R$ ${resultado.preco.toFixed(2)}.`
            : `Ainda em R$ ${resultado.preco.toFixed(2)}.`,
        )
      }),
    salvarAlvo: async (id, valor) => {
      try {
        await api.atualizarProduto(id, { preco_alvo: valor })
        await carregar()
        avisar('sucesso', 'Pronto, anotei o novo preço.')
      } catch (e) {
        avisar('erro', e.message)
      }
    },
  }

  async function coletarTudo() {
    setColetando(true)
    try {
      const rodada = await api.executarRodada()
      await carregar()
      if (rodada.alertas_gerados) {
        avisar('sucesso', `${rodada.alertas_gerados} produto(s) chegaram no seu preço!`)
      } else {
        avisar('info', `Verifiquei ${rodada.sucessos} produto(s). Nada no seu preço ainda.`)
      }
    } catch (e) {
      avisar('erro', e.message)
    } finally {
      setColetando(false)
    }
  }

  const naoLidos = alertas.filter((a) => !a.lido).length

  if (verificandoSessao) {
    return <div className="login login--aguardando">Carregando…</div>
  }

  if (!usuario) {
    return <TelaLogin aoEntrar={setUsuario} />
  }

  return (
    <div className="app">
      <header className="topo">
        <div className="topo__marca">
          <Etiqueta />
          <div>
            <h1>
              No<span>Precinho</span>Bot
            </h1>
            <p>Caça-preço</p>
          </div>
        </div>

        <div className="topo__conta">
          <span className="topo__usuario" title={usuario.email}>
            {usuario.nome}
          </span>
          <button className="topo__sair" onClick={sair}>
            Sair
          </button>
        </div>

        <nav className="abas">
          {ABAS.map((item) => (
            <button
              key={item.id}
              className={`abas__item ${aba === item.id ? 'abas__item--ativa' : ''}`}
              onClick={() => setAba(item.id)}
            >
              {item.rotulo}
              {item.id === 'alertas' && naoLidos > 0 && <span className="abas__selo">{naoLidos}</span>}
            </button>
          ))}
        </nav>
      </header>

      <main className="conteudo">
        {falhaConexao && (
          <div className="banner banner--erro">
            <strong>Sem conexão com o servidor.</strong> {falhaConexao}
          </div>
        )}

        {aba === 'painel' && (
          <>
            <ResumoPainel resumo={resumo} aoColetarTudo={coletarTudo} coletando={coletando} />
            <FormularioProduto aoCadastrar={carregar} avisar={avisar} />

            <section className="cartao">
              <header className="secao__topo">
                <h2>
                  Monitorando
                  {produtos.length > 0 && <em className="secao__contagem">{produtos.length}</em>}
                </h2>
              </header>

              <div className="filtros">
                <div className="filtros__grupo">
                  {FILTROS.map((f) => (
                    <button
                      key={f.id}
                      className={`filtro ${filtro === f.id ? 'filtro--ativo' : ''}`}
                      onClick={() => setFiltro(f.id)}
                    >
                      {f.rotulo}
                    </button>
                  ))}
                </div>
                <input
                  className="filtros__busca"
                  type="search"
                  placeholder="Buscar na minha lista…"
                  value={busca}
                  onChange={(e) => setBusca(e.target.value)}
                />
              </div>

              {carregando ? (
                <p className="vazio">Carregando…</p>
              ) : produtos.length === 0 ? (
                <p className="vazio">
                  {filtro || busca
                    ? 'Nenhum produto com esse filtro.'
                    : 'Cole o link de algo que você quer comprar e eu aviso quando baixar.'}
                </p>
              ) : (
                <div className="produtos">
                  {produtos.map((produto) => (
                    <CardProduto
                      key={produto.id}
                      produto={produto}
                      ocupado={ocupados.has(produto.id)}
                      aoPausar={acoes.pausar}
                      aoRetomar={acoes.retomar}
                      aoRemover={acoes.remover}
                      aoColetar={acoes.coletar}
                      aoSalvarAlvo={acoes.salvarAlvo}
                      aoAbrirHistorico={setHistoricoAberto}
                    />
                  ))}
                </div>
              )}
            </section>

          </>
        )}

        {aba === 'alertas' && (
          <PainelAlertas
            alertas={alertas}
            emailAtivo={resumo?.email_ativo ?? false}
            aoMarcarLido={async (id) => {
              await api.marcarAlertaLido(id)
              carregar()
            }}
            aoMarcarTodos={async () => {
              await api.marcarTodosLidos()
              carregar()
            }}
            aoRemover={async (id) => {
              await api.removerAlerta(id)
              carregar()
            }}
          />
        )}

        {aba === 'demo' && <LojaDemo avisar={avisar} aoMudar={carregar} />}

        {aba === 'coletor' && <SaudeLojas lojas={lojas} resumo={resumo} />}
      </main>

      <footer className="rodape">
        NoPrecinhoBot · React + FastAPI + BeautifulSoup + PostgreSQL · José Renato, João Pedro,
        Tiago Ferrari, Jean Lucas e Pedro Henrique
      </footer>

      {historicoAberto && (
        <ModalHistorico produto={historicoAberto} aoFechar={() => setHistoricoAberto(null)} />
      )}
      <Toasts avisos={avisos} aoFechar={fecharAviso} />
    </div>
  )
}
