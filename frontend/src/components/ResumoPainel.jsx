import { brl, tempoRelativo } from '../utils'

// A pessoa abre o app com uma pergunta só: "já baixou?".
//
// Antes ela recebia seis cartões — Monitorando, Aguardando, Alvo atingido,
// Alertas novos, Coletas, Queda acumulada — e tinha que procurar a resposta no
// meio. "Coletas: 24" é um número sobre o funcionamento do coletor, não sobre a
// compra dela. Aqui a resposta vem primeiro e sozinha; o resto é rodapé.
export default function ResumoPainel({ resumo, aoColetarTudo, coletando }) {
  if (!resumo) return null

  const prontos = resumo.alvo_atingido
  const total = resumo.total_produtos

  let titulo
  let tom = 'neutro'

  if (total === 0) {
    titulo = 'Sua lista está vazia'
  } else if (prontos > 0) {
    titulo = prontos === 1 ? '1 produto chegou no seu preço' : `${prontos} produtos chegaram no seu preço`
    tom = 'bom'
  } else {
    titulo = 'Nada no seu preço ainda'
  }

  return (
    <section className={`resposta resposta--${tom}`}>
      <div className="resposta__texto">
        <h2>{titulo}</h2>
        <p>
          {total === 0 ? (
            'Cole o link de um produto abaixo para começar a acompanhar.'
          ) : (
            <>
              Acompanhando {total} {total === 1 ? 'produto' : 'produtos'}
              {resumo.economia_potencial > 0 && (
                <> · já caiu {brl(resumo.economia_potencial)} desde que você começou</>
              )}
              {' · '}
              {resumo.agendador_ativo
                ? `verifico sozinho ${intervaloEmPalavras(resumo.intervalo_minutos)}`
                : 'verificação automática desligada'}
              {resumo.ultima_coleta_em && <> · última {tempoRelativo(resumo.ultima_coleta_em)}</>}
            </>
          )}
        </p>
      </div>

      {total > 0 && (
        <button className="botao botao--suave" onClick={aoColetarTudo} disabled={coletando}>
          {coletando ? 'Verificando…' : 'Verificar agora'}
        </button>
      )}
    </section>
  )
}

// "coleta a cada 360 min" é como o servidor pensa. Ninguém fala assim.
function intervaloEmPalavras(minutos) {
  if (!minutos || minutos < 1) return 'de tempos em tempos'
  if (minutos < 60) return `a cada ${minutos} minutos`
  const horas = Math.round(minutos / 60)
  if (horas < 24) return horas === 1 ? 'de hora em hora' : `a cada ${horas} horas`
  const dias = Math.round(horas / 24)
  return dias === 1 ? 'uma vez por dia' : `a cada ${dias} dias`
}
