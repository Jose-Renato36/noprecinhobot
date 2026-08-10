import { useState } from 'react'
import {
  brl,
  dataHora,
  nivelConfianca,
  tempoRelativo,
  ROTULOS_FONTE,
  ROTULOS_STATUS,
} from '../utils'

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

  const pausado = produto.status === 'pausado'
  const atingido = produto.status === 'alvo_atingido'
  const comErro = produto.status === 'erro'
  const variacao = produto.variacao_percentual
  const distancia = produto.distancia_do_alvo
  const nivel = nivelConfianca(produto.confianca)

  async function salvarAlvo(evento) {
    evento.preventDefault()
    const valor = Number(String(novoAlvo).replace(',', '.'))
    if (!Number.isFinite(valor) || valor <= 0) return
    await aoSalvarAlvo(produto.id, Number(valor.toFixed(2)))
    setEditando(false)
  }

  return (
    <article className={`produto ${atingido ? 'produto--atingido' : ''} ${pausado ? 'produto--pausado' : ''}`}>
      <div className="produto__foto">
        {produto.imagem_url ? (
          <img src={produto.imagem_url} alt="" loading="lazy" />
        ) : (
          <div className="produto__foto-vazia">📦</div>
        )}
      </div>

      <div className="produto__corpo">
        <div className="produto__cabecalho">
          <span className={`etiqueta etiqueta--${produto.status}`}>
            {ROTULOS_STATUS[produto.status] ?? produto.status}
          </span>
          {produto.loja && <span className="produto__loja">{produto.loja}</span>}
          {produto.fonte_preco && (
            <span
              className={`fonte fonte--${nivel ?? 'media'}`}
              title={
                `Preço obtido via ${ROTULOS_FONTE[produto.fonte_preco] ?? produto.fonte_preco}` +
                (produto.confianca !== null && produto.confianca !== undefined
                  ? ` · confiança ${Math.round(produto.confianca * 100)}%`
                  : '') +
                (produto.perfil_http ? ` · navegador emulado: ${produto.perfil_http}` : '') +
                (produto.seletor_preco ? `\nSeletor aprendido: ${produto.seletor_preco}` : '')
              }
            >
              {ROTULOS_FONTE[produto.fonte_preco] ?? produto.fonte_preco}
              {produto.confianca !== null && produto.confianca !== undefined && (
                <b> {Math.round(produto.confianca * 100)}%</b>
              )}
            </span>
          )}
        </div>

        <h3 title={produto.nome}>
          <a href={produto.url} target="_blank" rel="noreferrer noopener">
            {produto.nome}
          </a>
        </h3>

        <div className="produto__precos">
          <div>
            <span className="rotulo">Preço atual</span>
            <strong className={atingido ? 'preco preco--bom' : 'preco'}>
              {brl(produto.preco_atual)}
            </strong>
            {variacao !== null && variacao !== undefined && (
              <span className={`variacao ${variacao <= 0 ? 'variacao--queda' : 'variacao--alta'}`}>
                {variacao <= 0 ? '▼' : '▲'} {Math.abs(variacao).toFixed(1)}%
              </span>
            )}
          </div>

          <div>
            <span className="rotulo">Preço-alvo</span>
            {editando ? (
              <form className="editar-alvo" onSubmit={salvarAlvo}>
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
              <button className="alvo-editavel" onClick={() => setEditando(true)} title="Alterar preço-alvo">
                {brl(produto.preco_alvo)} <span aria-hidden>✎</span>
              </button>
            )}
          </div>
        </div>

        {!atingido && distancia !== null && distancia !== undefined && (
          <p className="produto__distancia">
            Falta cair <strong>{brl(distancia)}</strong> para atingir o alvo.
          </p>
        )}
        {atingido && (
          <p className="produto__distancia produto__distancia--bom">
            🎯 Alvo atingido — está {brl(Math.abs(distancia ?? 0))} abaixo do que você pediu.
          </p>
        )}
        {comErro && produto.ultimo_erro && (
          <p className="produto__erro" title={produto.ultimo_erro}>
            ⚠ {produto.ultimo_erro}
          </p>
        )}

        <dl className="produto__meta">
          <div>
            <dt>Coletas</dt>
            <dd>{produto.total_coletas}</dd>
          </div>
          <div>
            <dt>Menor preço</dt>
            <dd>{brl(produto.menor_preco)}</dd>
          </div>
          <div>
            <dt>Maior preço</dt>
            <dd>{brl(produto.maior_preco)}</dd>
          </div>
          <div>
            <dt>Última coleta</dt>
            <dd title={dataHora(produto.ultima_coleta_em)}>
              {tempoRelativo(produto.ultima_coleta_em)}
            </dd>
          </div>
        </dl>

        <div className="produto__acoes">
          <button
            className="botao botao--suave"
            onClick={() => aoAbrirHistorico(produto)}
            disabled={ocupado}
          >
            📈 Histórico
          </button>
          <button className="botao botao--suave" onClick={() => aoColetar(produto)} disabled={ocupado}>
            {ocupado ? '…' : '🔄 Coletar agora'}
          </button>
          <button
            className="botao botao--suave"
            onClick={() => (pausado ? aoRetomar(produto) : aoPausar(produto))}
            disabled={ocupado}
          >
            {pausado ? '▶ Retomar' : '⏸ Pausar'}
          </button>
          <button
            className="botao botao--perigo"
            onClick={() => aoRemover(produto)}
            disabled={ocupado}
          >
            🗑 Remover
          </button>
        </div>
      </div>
    </article>
  )
}
