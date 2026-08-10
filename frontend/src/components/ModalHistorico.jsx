import { useEffect, useState } from 'react'
import { api } from '../api'
import { brl, dataHora } from '../utils'
import GraficoHistorico from './GraficoHistorico'

export default function ModalHistorico({ produto, aoFechar }) {
  const [dados, setDados] = useState(null)
  const [erro, setErro] = useState(null)

  useEffect(() => {
    let cancelado = false
    api
      .historico(produto.id)
      .then((r) => !cancelado && setDados(r))
      .catch((e) => !cancelado && setErro(e.message))
    return () => {
      cancelado = true
    }
  }, [produto.id])

  useEffect(() => {
    const aoTeclar = (e) => e.key === 'Escape' && aoFechar()
    window.addEventListener('keydown', aoTeclar)
    return () => window.removeEventListener('keydown', aoTeclar)
  }, [aoFechar])

  return (
    <div className="modal-fundo" onClick={aoFechar}>
      <div
        className="modal"
        role="dialog"
        aria-modal="true"
        aria-label={`Histórico de preço de ${produto.nome}`}
        onClick={(e) => e.stopPropagation()}
      >
        <header className="modal__topo">
          <div>
            <span className="rotulo">Histórico de preço</span>
            <h2>{produto.nome}</h2>
          </div>
          <button className="modal__fechar" onClick={aoFechar} aria-label="Fechar">
            ×
          </button>
        </header>

        {erro && <p className="erro">{erro}</p>}
        {!dados && !erro && <p className="vazio vazio--pequeno">Carregando histórico…</p>}

        {dados && (
          <>
            <div className="modal__numeros">
              <div>
                <span className="rotulo">Menor</span>
                <strong className="preco preco--bom">{brl(dados.menor_preco)}</strong>
              </div>
              <div>
                <span className="rotulo">Médio</span>
                <strong>{brl(dados.preco_medio)}</strong>
              </div>
              <div>
                <span className="rotulo">Maior</span>
                <strong>{brl(dados.maior_preco)}</strong>
              </div>
              <div>
                <span className="rotulo">Alvo</span>
                <strong className="preco--alvo">{brl(dados.preco_alvo)}</strong>
              </div>
            </div>

            <GraficoHistorico pontos={dados.pontos} precoAlvo={dados.preco_alvo} />

            <details className="modal__tabela">
              <summary>Ver os {dados.pontos.length} registros em tabela</summary>
              <table>
                <thead>
                  <tr>
                    <th>Data / hora da coleta</th>
                    <th>Preço</th>
                    <th>Situação</th>
                  </tr>
                </thead>
                <tbody>
                  {[...dados.pontos].reverse().map((ponto) => (
                    <tr key={ponto.id}>
                      <td>{dataHora(ponto.coletado_em)}</td>
                      <td>{brl(ponto.preco)}</td>
                      <td>
                        {Number(ponto.preco) <= Number(dados.preco_alvo) ? (
                          <span className="etiqueta etiqueta--alvo_atingido">abaixo do alvo</span>
                        ) : (
                          <span className="etiqueta etiqueta--aguardando">acima do alvo</span>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </details>
          </>
        )}
      </div>
    </div>
  )
}
