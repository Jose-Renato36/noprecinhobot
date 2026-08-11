import { useState } from 'react'
import { api } from '../api'
import { brl, ROTULOS_FONTE } from '../utils'

/**
 * Cadastro de produto monitorado: o usuário informa a URL e o preço-alvo.
 * O botão "testar" chama /api/previa, que roda o scraper sem gravar nada —
 * assim dá para conferir se o link é válido antes de cadastrar.
 */
export default function FormularioProduto({ aoCadastrar, avisar }) {
  const [url, setUrl] = useState('')
  const [precoAlvo, setPrecoAlvo] = useState('')
  const [previa, setPrevia] = useState(null)
  const [testando, setTestando] = useState(false)
  const [salvando, setSalvando] = useState(false)
  const [erro, setErro] = useState(null)

  function limpar() {
    setUrl('')
    setPrecoAlvo('')
    setPrevia(null)
    setErro(null)
  }

  async function testarUrl() {
    if (!url.trim()) {
      setErro('Cole a URL do produto primeiro.')
      return
    }
    setTestando(true)
    setErro(null)
    setPrevia(null)
    try {
      const resultado = await api.previa(url.trim())
      setPrevia(resultado)
      // Sugere um alvo 10% abaixo do preço encontrado, se ainda não houver um.
      if (!precoAlvo && resultado.preco) {
        setPrecoAlvo((Number(resultado.preco) * 0.9).toFixed(2))
      }
    } catch (e) {
      setErro(e.message)
    } finally {
      setTestando(false)
    }
  }

  async function enviar(evento) {
    evento.preventDefault()
    setErro(null)

    const alvo = Number(String(precoAlvo).replace(',', '.'))
    if (!url.trim()) return setErro('Informe a URL do produto.')
    if (!Number.isFinite(alvo) || alvo <= 0) return setErro('Informe um preço-alvo maior que zero.')

    setSalvando(true)
    try {
      const produto = await api.cadastrarProduto(url.trim(), Number(alvo.toFixed(2)))
      limpar()
      avisar('sucesso', `"${produto.nome}" entrou no monitoramento.`)
      aoCadastrar()
    } catch (e) {
      setErro(e.message)
    } finally {
      setSalvando(false)
    }
  }

  return (
    <section className="cartao formulario">
      <header className="formulario__topo">
        <h2>Novo produto</h2>
      </header>

      <form onSubmit={enviar}>
        <div className="campo">
          <label htmlFor="url">URL do produto</label>
          <div className="campo__linha">
            <input
              id="url"
              type="url"
              inputMode="url"
              placeholder="https://loja.com.br/produto/..."
              value={url}
              onChange={(e) => {
                setUrl(e.target.value)
                setPrevia(null)
              }}
              disabled={salvando}
            />
            <button
              type="button"
              className="botao botao--suave"
              onClick={testarUrl}
              disabled={testando || salvando}
            >
              {testando ? 'Testando…' : 'Testar link'}
            </button>
          </div>
        </div>

        <div className="campo">
          <label htmlFor="alvo">Avisar quando o preço ficar igual ou abaixo de</label>
          <div className="campo__moeda">
            <span>R$</span>
            <input
              id="alvo"
              type="number"
              step="0.01"
              min="0.01"
              placeholder="0,00"
              value={precoAlvo}
              onChange={(e) => setPrecoAlvo(e.target.value)}
              disabled={salvando}
            />
          </div>
        </div>

        {previa && (
          <div className="previa">
            {previa.imagem_url && <img src={previa.imagem_url} alt="" />}
            <div>
              <strong>{previa.nome}</strong>
              <span className="previa__preco">{brl(previa.preco)}</span>
              <span className="previa__loja">
                {previa.loja} · link válido, pode cadastrar
              </span>
              <span className="previa__fonte">
                Preço lido de <b>{ROTULOS_FONTE[previa.fonte] ?? previa.fonte}</b>
                {previa.fontes_concordantes > 1 &&
                  ` · ${previa.fontes_concordantes} fontes concordam`}
                {` · confiança ${Math.round((previa.confianca ?? 0) * 100)}%`}
                {previa.perfil && ` · navegador ${previa.perfil}`}
              </span>
            </div>
          </div>
        )}

        {erro && <p className="erro">{erro}</p>}

        <div className="formulario__acoes">
          <button type="submit" className="botao botao--primario" disabled={salvando}>
            {salvando ? 'Cadastrando…' : 'Começar a monitorar'}
          </button>
          <button type="button" className="botao botao--texto" onClick={limpar} disabled={salvando}>
            Limpar
          </button>
        </div>
      </form>
    </section>
  )
}
