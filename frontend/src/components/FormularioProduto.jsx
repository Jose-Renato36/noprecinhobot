import { useRef, useState } from 'react'
import { api } from '../api'
import { brl } from '../utils'

// Cadastro em um passo.
//
// Antes o fluxo era: colar a URL, clicar em "Testar link", esperar, preencher o
// preço e só então cadastrar. Pedir que o usuário "teste" o link é pedir que ele
// faça o QA do scraper — se o link não serve, quem tem que descobrir é o
// sistema, não a pessoa.
//
// Agora colar já busca o produto e sugere um preço 10% abaixo do atual. Resta
// um ajuste opcional e um botão.
export default function FormularioProduto({ aoCadastrar, avisar }) {
  const [url, setUrl] = useState('')
  const [precoAlvo, setPrecoAlvo] = useState('')
  const [previa, setPrevia] = useState(null)
  const [buscando, setBuscando] = useState(false)
  const [salvando, setSalvando] = useState(false)
  const [erro, setErro] = useState(null)

  // Evita que uma busca lenta e antiga sobrescreva o resultado de uma mais nova.
  const buscaAtual = useRef(0)

  function limpar() {
    setUrl('')
    setPrecoAlvo('')
    setPrevia(null)
    setErro(null)
  }

  async function buscarProduto(endereco) {
    const limpo = endereco.trim()
    if (!/^https?:\/\/\S+\.\S+/i.test(limpo)) return

    const minhaBusca = ++buscaAtual.current
    setBuscando(true)
    setErro(null)
    setPrevia(null)
    try {
      const resultado = await api.previa(limpo)
      if (minhaBusca !== buscaAtual.current) return
      setPrevia(resultado)
      if (resultado.preco) setPrecoAlvo((Number(resultado.preco) * 0.9).toFixed(2))
    } catch (e) {
      if (minhaBusca === buscaAtual.current) setErro(e.message)
    } finally {
      if (minhaBusca === buscaAtual.current) setBuscando(false)
    }
  }

  async function enviar(evento) {
    evento.preventDefault()
    setErro(null)

    const alvo = Number(String(precoAlvo).replace(',', '.'))
    if (!url.trim()) return setErro('Cole o link do produto.')
    if (!Number.isFinite(alvo) || alvo <= 0) return setErro('Informe quanto você quer pagar.')

    setSalvando(true)
    try {
      const produto = await api.cadastrarProduto(url.trim(), Number(alvo.toFixed(2)))
      limpar()
      avisar('sucesso', `"${produto.nome}" entrou na sua lista.`)
      aoCadastrar()
    } catch (e) {
      setErro(e.message)
    } finally {
      setSalvando(false)
    }
  }

  return (
    <section className="cartao formulario">
      <form onSubmit={enviar}>
        <div className="campo">
          <label htmlFor="url">Cole o link do produto</label>
          <input
            id="url"
            type="url"
            inputMode="url"
            placeholder="https://www.kabum.com.br/produto/..."
            value={url}
            onChange={(e) => {
              setUrl(e.target.value)
              setPrevia(null)
            }}
            // Colar e sair do campo já dispara a busca — sem botão intermediário.
            onPaste={(e) => {
              const colado = e.clipboardData.getData('text')
              setTimeout(() => buscarProduto(colado), 0)
            }}
            onBlur={(e) => !previa && buscarProduto(e.target.value)}
            disabled={salvando}
          />
        </div>

        {buscando && <p className="formulario__buscando">Procurando o produto…</p>}

        {previa && (
          <>
            <div className="previa">
              {previa.imagem_url && <img src={previa.imagem_url} alt="" />}
              <div>
                <strong>{previa.nome}</strong>
                <span className="previa__preco">{brl(previa.preco)}</span>
                <span className="previa__loja">{previa.loja}</span>
              </div>
            </div>

            <div className="campo">
              <label htmlFor="alvo">Me avise quando custar</label>
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
              <p className="campo__dica">Sugerimos 10% abaixo do preço de agora. Mude à vontade.</p>
            </div>
          </>
        )}

        {erro && <p className="erro">{erro}</p>}

        <div className="formulario__acoes">
          <button
            type="submit"
            className="botao botao--primario"
            disabled={salvando || buscando || !previa}
          >
            {salvando ? 'Adicionando…' : 'Adicionar à minha lista'}
          </button>
          {(url || previa) && (
            <button
              type="button"
              className="botao botao--texto"
              onClick={limpar}
              disabled={salvando}
            >
              Limpar
            </button>
          )}
        </div>
      </form>
    </section>
  )
}
