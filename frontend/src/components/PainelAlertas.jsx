import { brl, dataHora } from '../utils'

export default function PainelAlertas({
  alertas,
  aoMarcarLido,
  aoMarcarTodos,
  aoRemover,
  emailAtivo = false,
}) {
  const naoLidos = alertas.filter((a) => !a.lido).length

  return (
    <section className="cartao">
      <header className="secao__topo">
        <div>
          <h2>Alertas de queda de preço</h2>
          <p>
            Um alerta nasce quando o preço coletado fica igual ou abaixo do alvo que você definiu.
          </p>
        </div>
        {naoLidos > 0 && (
          <button className="botao botao--suave" onClick={aoMarcarTodos}>
            Marcar todos como lidos ({naoLidos})
          </button>
        )}
      </header>

      {alertas.length === 0 ? (
        <p className="vazio">
          Nenhum alerta ainda. Assim que um produto atingir o preço-alvo, ele aparece aqui.
        </p>
      ) : (
        <ul className="alertas">
          {alertas.map((alerta) => (
            <li key={alerta.id} className={`alerta ${alerta.lido ? 'alerta--lido' : ''}`}>
              {alerta.produto?.imagem_url && (
                <img src={alerta.produto.imagem_url} alt="" loading="lazy" />
              )}
              <div className="alerta__texto">
                <p className="alerta__mensagem">{alerta.mensagem}</p>
                <p className="alerta__detalhe">
                  {dataHora(alerta.criado_em)} · disparou em {brl(alerta.preco_disparo)} · alvo{' '}
                  {brl(alerta.preco_alvo)}
                  {/* Com o envio desligado, "e-mail não enviado" seria ruído
                      passando por defeito — o alerta no painel é o canal. */}
                  {emailAtivo && (alerta.email_enviado ? ' · ✉ e-mail enviado' : ' · ✉ e-mail falhou')}
                </p>
              </div>
              <div className="alerta__acoes">
                {alerta.produto && (
                  <a
                    className="botao botao--mini botao--suave"
                    href={alerta.produto.url}
                    target="_blank"
                    rel="noreferrer noopener"
                  >
                    Abrir loja
                  </a>
                )}
                {!alerta.lido && (
                  <button
                    className="botao botao--mini botao--suave"
                    onClick={() => aoMarcarLido(alerta.id)}
                  >
                    Marcar lido
                  </button>
                )}
                <button
                  className="botao botao--mini botao--perigo"
                  onClick={() => aoRemover(alerta.id)}
                  aria-label="Remover alerta"
                >
                  ×
                </button>
              </div>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}
