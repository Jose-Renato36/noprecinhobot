import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from './api'
import { ROTULOS_STATUS } from './utils'
import CardProduto from './components/CardProduto'
import FormularioProduto from './components/FormularioProduto'
import LojaDemo from './components/LojaDemo'
import ModalHistorico from './components/ModalHistorico'
import PainelAlertas from './components/PainelAlertas'
import ResumoPainel from './components/ResumoPainel'
import SaudeLojas from './components/SaudeLojas'
import Toasts from './components/Toasts'

const ABAS = [
  { id: 'painel', rotulo: 'Painel' },
  { id: 'alertas', rotulo: 'Alertas' },
  { id: 'demo', rotulo: 'Loja de teste' },
]

const FILTROS = [
  { id: '', rotulo: 'Todos' },
  { id: 'aguardando', rotulo: ROTULOS_STATUS.aguardando },
  { id: 'alvo_atingido', rotulo: ROTULOS_STATUS.alvo_atingido },
  { id: 'pausado', rotulo: ROTULOS_STATUS.pausado },
  { id: 'erro', rotulo: ROTULOS_STATUS.erro },
]

export default function App() {
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

  useEffect(() => {
    carregar()
  }, [carregar])

  // O agendador trabalha em segundo plano; o painel se atualiza sozinho
  // para refletir coletas e alertas que aconteceram sem o usuário pedir.
  useEffect(() => {
    const id = setInterval(carregar, 15000)
    return () => clearInterval(id)
  }, [carregar])

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
        avisar('info', `Monitoramento de "${p.nome}" pausado.`)
      }),
    retomar: (p) =>
      comOcupado(p, async () => {
        await api.retomarProduto(p.id)
        avisar('sucesso', `Monitoramento de "${p.nome}" retomado.`)
      }),
    remover: (p) => {
      if (!window.confirm(`Remover "${p.nome}"? O histórico e os alertas dele também somem.`)) return
      return comOcupado(p, async () => {
        await api.removerProduto(p.id)
        avisar('info', 'Produto removido do monitoramento.')
      })
    },
    coletar: (p) =>
      comOcupado(p, async () => {
        const resultado = await api.coletarProduto(p.id)
        if (!resultado.sucesso) return avisar('erro', resultado.erro ?? 'A coleta falhou.')
        avisar(
          resultado.alerta_gerado ? 'sucesso' : 'info',
          resultado.alerta_gerado
            ? `🎯 Alvo atingido! ${p.nome} está por R$ ${resultado.preco.toFixed(2)}.`
            : `Preço coletado: R$ ${resultado.preco.toFixed(2)}.`,
        )
      }),
    salvarAlvo: async (id, valor) => {
      try {
        await api.atualizarProduto(id, { preco_alvo: valor })
        await carregar()
        avisar('sucesso', 'Preço-alvo atualizado.')
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
      const partes = [`${rodada.sucessos} coleta(s) com sucesso`]
      if (rodada.falhas) partes.push(`${rodada.falhas} falha(s)`)
      if (rodada.alertas_gerados) partes.push(`${rodada.alertas_gerados} alerta(s) novo(s)`)
      avisar(rodada.alertas_gerados ? 'sucesso' : 'info', partes.join(' · '))
    } catch (e) {
      avisar('erro', e.message)
    } finally {
      setColetando(false)
    }
  }

  const naoLidos = alertas.filter((a) => !a.lido).length

  return (
    <div className="app">
      <header className="topo">
        <div className="topo__marca">
          <span className="topo__logo">🏷️</span>
          <div>
            <h1>
              No<span>Precinho</span>Bot
            </h1>
            <p>Monitoramento automático de preços</p>
          </div>
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
            <strong>Sem conexão com a API.</strong> {falhaConexao} Verifique se o backend está
            rodando em <code>http://127.0.0.1:8000</code>.
          </div>
        )}

        {aba === 'painel' && (
          <>
            <ResumoPainel resumo={resumo} aoColetarTudo={coletarTudo} coletando={coletando} />
            <FormularioProduto aoCadastrar={carregar} avisar={avisar} />

            <section className="cartao">
              <header className="secao__topo">
                <div>
                  <h2>Produtos monitorados</h2>
                  <p>
                    Preço atual, preço-alvo e situação de cada item. Você pode pausar ou remover o
                    monitoramento a qualquer momento.
                  </p>
                </div>
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
                  placeholder="Buscar pelo nome…"
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
                    : 'Nenhum produto monitorado ainda. Cadastre o primeiro usando o formulário acima — ou pegue um link na aba "Loja de teste".'}
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

            <SaudeLojas lojas={lojas} />
          </>
        )}

        {aba === 'alertas' && (
          <PainelAlertas
            alertas={alertas}
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
