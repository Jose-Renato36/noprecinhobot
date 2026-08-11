import { useEffect, useState } from 'react'
import { api } from '../api'
import { brl } from '../utils'

/**
 * Atalho para a loja fictícia servida pelo próprio backend. Existe porque as
 * lojas reais bloqueiam robôs (HTTP 403) e não dá para depender delas numa
 * apresentação ao vivo.
 */
export default function LojaDemo({ avisar, aoMudar }) {
  const [produtos, setProdutos] = useState([])
  const [copiado, setCopiado] = useState(null)
  const [ocupado, setOcupado] = useState(false)

  async function carregar() {
    try {
      setProdutos(await api.demoProdutos())
    } catch (e) {
      avisar('erro', e.message)
    }
  }

  useEffect(() => {
    carregar()
    const id = setInterval(carregar, 10000)
    return () => clearInterval(id)
  }, [])

  async function copiar(url) {
    try {
      await navigator.clipboard.writeText(url)
      setCopiado(url)
      setTimeout(() => setCopiado(null), 1800)
    } catch {
      avisar('info', 'Copie o link manualmente: ' + url)
    }
  }

  async function acao(fn, mensagem) {
    setOcupado(true)
    try {
      await fn()
      await carregar()
      avisar('sucesso', mensagem)
      aoMudar?.()
    } catch (e) {
      avisar('erro', e.message)
    } finally {
      setOcupado(false)
    }
  }

  return (
    <section className="cartao">
      <header className="secao__topo">
        <div>
          <h2>Loja de demonstração</h2>
          <p>
            Páginas HTML reais servidas pelo próprio backend, com preço oscilando sozinho. O
            scraper acessa por HTTP igual a qualquer loja — serve para demonstrar o sistema sem
            depender de sites que bloqueiam robôs.
          </p>
        </div>
      </header>

      <div className="demo__acoes">
        <button
          className="botao botao--primario"
          disabled={ocupado}
          onClick={() => acao(() => api.demoPromocao(0.4), 'Promoção de 40% aplicada na loja-demo.')}
        >
          Derrubar preços 40%
        </button>
        <button
          className="botao botao--suave"
          disabled={ocupado}
          onClick={() => acao(() => api.demoNormalizar(), 'Preços voltaram ao normal.')}
        >
          Voltar ao normal
        </button>
        <a className="botao botao--texto" href="/loja-demo" target="_blank" rel="noreferrer">
          Abrir a vitrine ↗
        </a>
      </div>

      <div className="demo__grade">
        {produtos.map((p) => (
          <div key={p.slug} className="demo__item">
            <img src={p.imagem_url} alt="" loading="lazy" />
            <strong>{p.nome}</strong>
            <span className={`demo__preco ${p.em_promocao ? 'demo__preco--promo' : ''}`}>
              {brl(p.preco_atual)}
            </span>
            <div className="demo__item-acoes">
              <button className="botao botao--mini botao--suave" onClick={() => copiar(p.url)}>
                {copiado === p.url ? '✓ copiado' : 'Copiar link'}
              </button>
              <a
                className="botao botao--mini botao--texto"
                href={p.url}
                target="_blank"
                rel="noreferrer"
              >
                abrir ↗
              </a>
            </div>
          </div>
        ))}
      </div>
    </section>
  )
}
