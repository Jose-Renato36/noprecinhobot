// Gráfico de linha compacto, desenhado no próprio card.
//
// É a lição do Keepa: o histórico é o produto. Escondê-lo atrás de um botão
// "Histórico" obriga a pessoa a clicar em cada item para descobrir a única
// coisa que ela quer saber — está caindo ou não. Aqui a resposta é o formato
// da linha, sem clique nenhum.
//
// SVG escrito à mão, sem biblioteca de charts: são 30 linhas e evita somar
// ~200 KB ao bundle por causa de um traço.
export default function MiniGrafico({ serie = [], alvo, largura = 260, altura = 44 }) {
  // Menos de dois pontos não formam linha: não há o que mostrar ainda.
  if (!Array.isArray(serie) || serie.length < 2) {
    return (
      <p className="minigrafico__vazio">
        O gráfico aparece depois da segunda verificação de preço.
      </p>
    )
  }

  const alvoNum = Number(alvo)
  const temAlvo = Number.isFinite(alvoNum)

  // A escala sai só dos preços, nunca do alvo. Incluir o alvo parece correto,
  // mas quando ele está longe do preço atual toda a variação é espremida contra
  // a borda e a linha vira um traço reto — apaga exatamente o que o gráfico
  // existe para mostrar. O alvo, quando cai fora, é preso na borda: a linha
  // tracejada encostada no topo já diz "seu preço está bem abaixo daqui".
  const min = Math.min(...serie)
  const max = Math.max(...serie)
  // Preço estável deixaria max === min e faria uma divisão por zero.
  const amplitude = max - min || Math.max(max * 0.02, 1)

  const margem = 5
  const util = altura - margem * 2
  const y = (valor) => {
    const bruto = margem + (1 - (valor - min) / amplitude) * util
    return Math.min(altura - 1, Math.max(1, bruto))
  }
  const x = (i) => (i / (serie.length - 1)) * largura

  const pontos = serie.map((valor, i) => `${x(i).toFixed(1)},${y(valor).toFixed(1)}`).join(' ')
  const ultimo = serie[serie.length - 1]
  const subiu = ultimo > serie[0]
  const atingiu = temAlvo && ultimo <= alvoNum

  return (
    <svg
      className="minigrafico"
      viewBox={`0 0 ${largura} ${altura}`}
      preserveAspectRatio="none"
      role="img"
      aria-label={
        `Variação dos últimos ${serie.length} preços registrados. ` +
        (atingiu ? 'Está no preço que você quer.' : subiu ? 'Subiu no período.' : 'Caiu no período.')
      }
    >
      {temAlvo && (
        <line
          x1="0"
          y1={y(alvoNum)}
          x2={largura}
          y2={y(alvoNum)}
          className="minigrafico__alvo"
          strokeDasharray="4 4"
        />
      )}
      <polyline
        points={pontos}
        className={`minigrafico__linha ${atingiu ? 'minigrafico__linha--atingiu' : ''}`}
      />
      <circle
        cx={x(serie.length - 1)}
        cy={y(ultimo)}
        r="3"
        className={`minigrafico__ponta ${atingiu ? 'minigrafico__ponta--atingiu' : ''}`}
      />
    </svg>
  )
}
