import { useEffect, useRef, useState } from 'react'
import { brl, tempoRelativo } from '../utils'
import MiniGrafico from './MiniGrafico'

// O card mostra o que quem compra quer saber: quanto custa, quanto você queria
// pagar, como vem variando e onde comprar.
//
// O que saiu daqui: fonte do preço, confiança do scraper, seletor CSS aprendido,
// perfil HTTP, contagem de coletas, maior preço. Nada disso significa algo para
// quem só quer um monitor mais barato — é diagnóstico do coletor, e agora vive
// na aba "Coletor", onde é útil sem atrapalhar.
export default function CardProduto({
  produto,
  aoPausar,
  aoRetomar,
  aoRemover,
  aoColetar,
  aoAbrirHistorico,
  aoSalvarAlvo,
  ocupado,
}) {
  const [editando, setEditando] = useState(false)
  const [novoAlvo, setNovoAlvo] = useState(produto.preco_alvo)
  const [menuAberto, setMenuAberto] = useState(false)
  const menuRef = useRef(null)

  const pausado = produto.status === 'pausado'
  const atingido = produto.status === 'alvo_atingido'
  const comErro = produto.status === 'erro'
  const variacao = produto.variacao_percentual
  const distancia = produto.distancia_do_alvo

  // Menu aberto precisa fechar ao clicar fora, senão fica preso na tela.
  useEffect(() => {
    if (!menuAberto) return
    function aoClicarFora(evento) {
      if (menuRef.current && !menuRef.current.contains(evento.target)) setMenuAberto(false)
    }
    document.addEventListener('mousedown', aoClicarFora)
    return () => document.removeEventListener('mousedown', aoClicarFora)
  }, [menuAberto])

  async function salvarAlvo(evento) {
    evento.preventDefault()
    const valor = Number(String(novoAlvo).replace(',', '.'))
    if (!Number.isFinite(valor) || valor <= 0) return
    await aoSalvarAlvo(produto.id, Number(valor.toFixed(2)))
    setEditando(false)
  }

  return (
    <article
      className={`produto ${atingido ? 'produto--atingido' : ''} ${pausado ? 'produto--pausado' : ''}`}
    >
      <div className="produto__foto">
        {produto.imagem_url ? (
          <img src={produto.imagem_url} alt="" loading="lazy" />
        ) : (
          <div className="produto__foto-vazia" aria-hidden />
        )}
      </div>

      <div className="produto__corpo">
        <h3 title={produto.nome}>
          <a href={produto.url} target="_blank" rel="noreferrer noopener">
            {produto.nome}
          </a>
        </h3>
        <p className="produto__loja">
          {produto.loja ?? 'Loja'}
          {pausado && <span className="produto__pausa">pausado</span>}
        </p>

        <div className="produto__preco-linha">
          <strong className={atingido ? 'preco preco--bom' : 'preco'}>
            {brl(produto.preco_atual)}
          </strong>
          {variacao !== null && variacao !== undefined && Math.abs(variacao) >= 0.1 && (
            <span className={`variacao ${variacao <= 0 ? 'variacao--queda' : 'variacao--alta'}`}>
              {variacao <= 0 ? '▼' : '▲'} {Math.abs(variacao).toFixed(1)}%
            </span>
          )}
        </div>

        <p className="produto__alvo-linha">
          {atingido ? (
            <strong className="produto__conquista">
              Chegou no seu preço — {brl(Math.abs(distancia ?? 0))} abaixo
            </strong>
          ) : editando ? (
            <form className="editar-alvo" onSubmit={salvarAlvo}>
              <span>Quero por</span>
              <input
                type="number"
                step="0.01"
                min="0.01"
                value={novoAlvo}
                onChange={(e) => setNovoAlvo(e.target.value)}
                autoFocus
              />
              <button type="submit" className="botao botao--mini botao--primario">
                ok
              </button>
              <button
                type="button"
                className="botao botao--mini"
                onClick={() => {
                  setNovoAlvo(produto.preco_alvo)
                  setEditando(false)
                }}
              >
                ×
              </button>
            </form>
          ) : (
            <>
              Você quer por{' '}
              <button
                className="alvo-editavel"
                onClick={() => setEditando(true)}
                title="Alterar o preço que você quer pagar"
              >
                {brl(produto.preco_alvo)}
              </button>
              {distancia !== null && distancia !== undefined && (
                <span className="produto__falta"> · falta cair {brl(distancia)}</span>
              )}
            </>
          )}
        </p>

        <MiniGrafico serie={produto.serie} alvo={produto.preco_alvo} />

        <p className="produto__rodape">
          {produto.serie?.length > 1 && <>menor visto {brl(produto.menor_preco)} · </>}
          verificado {tempoRelativo(produto.ultima_coleta_em)}
        </p>

        {comErro && (
          <p className="produto__erro">
            Não consegui ler o preço nesta loja na última tentativa.
          </p>
        )}

        <div className="produto__acoes">
          <a
            className="botao botao--primario"
            href={produto.url}
            target="_blank"
            rel="noreferrer noopener"
          >
            Ver na loja
          </a>
          <button
            className="botao botao--suave"
            onClick={() => aoAbrirHistorico(produto)}
            disabled={ocupado}
          >
            Histórico
          </button>

          <div className="menu" ref={menuRef}>
            <button
              className="botao botao--suave botao--icone"
              onClick={() => setMenuAberto((v) => !v)}
              disabled={ocupado}
              aria-label="Mais opções"
              aria-expanded={menuAberto}
            >
              ⋯
            </button>
            {menuAberto && (
              <div className="menu__lista" role="menu">
                <button
                  role="menuitem"
                  onClick={() => {
                    setMenuAberto(false)
                    aoColetar(produto)
                  }}
                >
                  Verificar agora
                </button>
                <button
                  role="menuitem"
                  onClick={() => {
                    setMenuAberto(false)
                    pausado ? aoRetomar(produto) : aoPausar(produto)
                  }}
                >
                  {pausado ? 'Retomar avisos' : 'Pausar avisos'}
                </button>
                <button
                  role="menuitem"
                  className="menu__perigo"
                  onClick={() => {
                    setMenuAberto(false)
                    aoRemover(produto)
                  }}
                >
                  Tirar da lista
                </button>
              </div>
            )}
          </div>
        </div>
      </div>
    </article>
  )
}
