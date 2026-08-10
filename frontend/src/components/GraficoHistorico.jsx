import { useMemo, useState } from 'react'
import { brl, dataHora } from '../utils'

const LARGURA = 720
const ALTURA = 260
const MARGEM = { topo: 18, direita: 16, baixo: 30, esquerda: 68 }

/**
 * Gráfico de linha em SVG puro (sem biblioteca externa) mostrando a variação
 * do preço ao longo do tempo, com a linha do preço-alvo em destaque.
 */
export default function GraficoHistorico({ pontos, precoAlvo }) {
  const [ativo, setAtivo] = useState(null)

  const grafico = useMemo(() => {
    if (!pontos?.length) return null

    const valores = pontos.map((p) => Number(p.preco))
    const alvo = Number(precoAlvo)
    const min = Math.min(...valores, alvo)
    const max = Math.max(...valores, alvo)
    // Uma folga de 8% evita que a linha encoste nas bordas.
    const folga = (max - min) * 0.08 || Math.max(max * 0.05, 1)
    const baixo = min - folga
    const alto = max + folga

    const largura = LARGURA - MARGEM.esquerda - MARGEM.direita
    const altura = ALTURA - MARGEM.topo - MARGEM.baixo

    const x = (i) =>
      MARGEM.esquerda + (pontos.length === 1 ? largura / 2 : (i / (pontos.length - 1)) * largura)
    const y = (v) => MARGEM.topo + altura - ((v - baixo) / (alto - baixo)) * altura

    const coordenadas = pontos.map((p, i) => ({
      x: x(i),
      y: y(Number(p.preco)),
      preco: Number(p.preco),
      data: p.coletado_em,
    }))

    const linha = coordenadas.map((c, i) => `${i === 0 ? 'M' : 'L'} ${c.x} ${c.y}`).join(' ')
    const area = `${linha} L ${coordenadas.at(-1).x} ${MARGEM.topo + altura} L ${coordenadas[0].x} ${
      MARGEM.topo + altura
    } Z`

    const marcas = [alto, (alto + baixo) / 2, baixo].map((v) => ({ valor: v, y: y(v) }))

    return { coordenadas, linha, area, yAlvo: y(alvo), marcas, largura, altura }
  }, [pontos, precoAlvo])

  if (!grafico) {
    return <p className="vazio vazio--pequeno">Ainda não há coletas suficientes para o gráfico.</p>
  }

  const { coordenadas, linha, area, yAlvo, marcas, largura, altura } = grafico
  const ultimo = coordenadas.at(-1)
  const abaixoDoAlvo = ultimo.preco <= Number(precoAlvo)

  return (
    <figure className="grafico">
      <svg
        viewBox={`0 0 ${LARGURA} ${ALTURA}`}
        role="img"
        aria-label={`Variação do preço em ${pontos.length} coletas`}
        onMouseLeave={() => setAtivo(null)}
      >
        {marcas.map((marca) => (
          <g key={marca.valor}>
            <line
              className="grafico__grade"
              x1={MARGEM.esquerda}
              x2={MARGEM.esquerda + largura}
              y1={marca.y}
              y2={marca.y}
            />
            <text className="grafico__rotulo" x={MARGEM.esquerda - 10} y={marca.y + 4}>
              {brl(marca.valor).replace('R$', '').trim()}
            </text>
          </g>
        ))}

        <line
          className="grafico__alvo"
          x1={MARGEM.esquerda}
          x2={MARGEM.esquerda + largura}
          y1={yAlvo}
          y2={yAlvo}
        />
        <text className="grafico__alvo-texto" x={MARGEM.esquerda + largura} y={yAlvo - 7}>
          alvo {brl(precoAlvo)}
        </text>

        <path className="grafico__area" d={area} />
        <path
          className={`grafico__linha ${abaixoDoAlvo ? 'grafico__linha--alvo' : ''}`}
          d={linha}
        />

        {coordenadas.map((c, i) => (
          <circle
            key={i}
            className={`grafico__ponto ${ativo === i ? 'grafico__ponto--ativo' : ''}`}
            cx={c.x}
            cy={c.y}
            r={ativo === i ? 5 : 3}
            onMouseEnter={() => setAtivo(i)}
          />
        ))}

        {ativo !== null && (
          <g transform={`translate(${coordenadas[ativo].x}, ${coordenadas[ativo].y})`}>
            <line className="grafico__guia" y1={0} y2={MARGEM.topo + altura - coordenadas[ativo].y} />
          </g>
        )}
      </svg>

      <figcaption>
        {ativo !== null ? (
          <>
            <strong>{brl(coordenadas[ativo].preco)}</strong> em{' '}
            {dataHora(coordenadas[ativo].data)}
          </>
        ) : (
          <>
            {pontos.length} coleta{pontos.length > 1 ? 's' : ''} · última em{' '}
            {dataHora(ultimo.data)} · passe o mouse nos pontos
          </>
        )}
      </figcaption>
    </figure>
  )
}
