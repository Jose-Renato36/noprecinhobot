import { brl, contagemRegressiva, tempoRelativo } from '../utils'

export default function ResumoPainel({ resumo, aoColetarTudo, coletando }) {
  if (!resumo) return null

  const cartoes = [
    { rotulo: 'Monitorando', valor: resumo.total_produtos, dica: 'produtos cadastrados' },
    { rotulo: 'Aguardando', valor: resumo.aguardando, dica: 'ainda acima do alvo', tom: 'neutro' },
    { rotulo: 'Alvo atingido', valor: resumo.alvo_atingido, dica: 'prontos para comprar', tom: 'bom' },
    { rotulo: 'Alertas novos', valor: resumo.alertas_nao_lidos, dica: 'não lidos', tom: resumo.alertas_nao_lidos ? 'destaque' : 'neutro' },
    { rotulo: 'Coletas', valor: resumo.total_coletas, dica: 'registros no histórico' },
    { rotulo: 'Queda acumulada', valor: brl(resumo.economia_potencial), dica: 'desde o cadastro', tom: 'bom' },
  ]

  return (
    <section className="resumo">
      <div className="resumo__cartoes">
        {cartoes.map((c) => (
          <div key={c.rotulo} className={`resumo__cartao resumo__cartao--${c.tom ?? 'neutro'}`}>
            <span className="resumo__valor">{c.valor}</span>
            <span className="resumo__rotulo">{c.rotulo}</span>
            <span className="resumo__dica">{c.dica}</span>
          </div>
        ))}
      </div>

      <div className="resumo__agendador">
        <div>
          <span className={`ponto ${resumo.agendador_ativo ? 'ponto--vivo' : 'ponto--morto'}`} />
          <strong>Agendador {resumo.agendador_ativo ? 'ativo' : 'desligado'}</strong>
          <span className="resumo__dica">
            coleta a cada {resumo.intervalo_minutos} min
            {resumo.proxima_coleta_em && ` · próxima ${contagemRegressiva(resumo.proxima_coleta_em)}`}
            {' · última coleta '}
            {tempoRelativo(resumo.ultima_coleta_em)}
          </span>
        </div>
        <button className="botao botao--primario" onClick={aoColetarTudo} disabled={coletando}>
          {coletando ? 'Coletando…' : '⚡ Coletar tudo agora'}
        </button>
      </div>
    </section>
  )
}
