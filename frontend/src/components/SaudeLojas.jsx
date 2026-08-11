import { ROTULOS_FONTE, tempoRelativo } from '../utils'

/**
 * Alarme de incêndio do scraper: quando uma loja muda o HTML, a taxa de sucesso
 * dela despenca. Sem esta tela, isso passaria semanas despercebido.
 */
export default function SaudeLojas({ lojas }) {
  if (!lojas?.length) return null

  return (
    <section className="cartao">
      <header className="secao__topo">
        <h2>Saúde das lojas</h2>
      </header>

      <div className="lojas">
        {lojas.map((loja) => {
          const pct = Math.round(loja.taxa_sucesso * 100)
          const tom = pct === 100 ? 'ok' : pct >= 50 ? 'atencao' : 'ruim'
          return (
            <div key={loja.loja} className={`loja loja--${tom}`}>
              <div className="loja__topo">
                <strong>{loja.loja}</strong>
                <span className={`loja__pct loja__pct--${tom}`}>{pct}%</span>
              </div>
              <div className="loja__barra">
                <span style={{ width: `${pct}%` }} />
              </div>
              <p className="loja__detalhe">
                {loja.total_produtos} produto{loja.total_produtos > 1 ? 's' : ''}
                {loja.com_erro > 0 && ` · ${loja.com_erro} com erro`}
                {loja.fonte_predominante &&
                  ` · via ${ROTULOS_FONTE[loja.fonte_predominante] ?? loja.fonte_predominante}`}
                {loja.confianca_media !== null &&
                  loja.confianca_media !== undefined &&
                  ` · confiança média ${Math.round(loja.confianca_media * 100)}%`}
                {` · última coleta ${tempoRelativo(loja.ultima_coleta_em)}`}
              </p>
            </div>
          )
        })}
      </div>
    </section>
  )
}
