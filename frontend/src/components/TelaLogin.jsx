import { useState } from 'react'
import { api } from '../api'

// A mesma tela serve para entrar e para criar conta: são os mesmos campos, menos
// o nome. Duas telas separadas só duplicariam formulário e validação.
export default function TelaLogin({ aoEntrar }) {
  const [modo, setModo] = useState('login')
  const [nome, setNome] = useState('')
  const [email, setEmail] = useState('')
  const [senha, setSenha] = useState('')
  const [erro, setErro] = useState(null)
  const [enviando, setEnviando] = useState(false)

  const criandoConta = modo === 'registro'

  async function enviar(evento) {
    evento.preventDefault()
    setErro(null)

    if (criandoConta && senha.length < 8) {
      setErro('A senha precisa de pelo menos 8 caracteres.')
      return
    }

    setEnviando(true)
    try {
      const resposta = criandoConta
        ? await api.registrar(nome.trim(), email.trim(), senha)
        : await api.login(email.trim(), senha)

      // O token vem no corpo, mas o painel o ignora: quem carrega a sessão é o
      // cookie httpOnly que o servidor acabou de gravar.
      aoEntrar(resposta.usuario)
    } catch (e) {
      setErro(e.message)
    } finally {
      setEnviando(false)
    }
  }

  function trocarModo() {
    setModo(criandoConta ? 'login' : 'registro')
    setErro(null)
    setSenha('')
  }

  return (
    <div className="login">
      <div className="login__cartao">
        <div className="login__marca">
          <span className="login__logo">🏷️</span>
          <h1>
            No<span>Precinho</span>Bot
          </h1>
          <p>Monitoramento automático de preços</p>
        </div>

        <form className="login__form" onSubmit={enviar}>
          <h2>{criandoConta ? 'Criar conta' : 'Entrar'}</h2>

          {criandoConta && (
            <div className="campo">
              <label htmlFor="login-nome">Nome</label>
              <input
                id="login-nome"
                type="text"
                value={nome}
                onChange={(e) => setNome(e.target.value)}
                placeholder="Como quer ser chamado"
                required
                maxLength={120}
                autoComplete="name"
              />
            </div>
          )}

          <div className="campo">
            <label htmlFor="login-email">E-mail</label>
            <input
              id="login-email"
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="voce@exemplo.com"
              required
              autoComplete="email"
            />
          </div>

          <div className="campo">
            <label htmlFor="login-senha">Senha</label>
            <input
              id="login-senha"
              type="password"
              value={senha}
              onChange={(e) => setSenha(e.target.value)}
              placeholder={criandoConta ? 'Mínimo de 8 caracteres' : '••••••••'}
              required
              maxLength={72}
              autoComplete={criandoConta ? 'new-password' : 'current-password'}
            />
          </div>

          {erro && <p className="login__erro">{erro}</p>}

          <button className="botao botao--primario login__enviar" type="submit" disabled={enviando}>
            {enviando ? 'Aguarde…' : criandoConta ? 'Criar conta e entrar' : 'Entrar'}
          </button>

          <p className="login__troca">
            {criandoConta ? 'Já tem conta?' : 'Ainda não tem conta?'}{' '}
            <button type="button" className="login__link" onClick={trocarModo}>
              {criandoConta ? 'Entrar' : 'Criar uma agora'}
            </button>
          </p>
        </form>

        <p className="login__nota">
          Cada conta enxerga apenas os próprios produtos, o próprio histórico e os próprios
          alertas. O e-mail cadastrado é o destinatário dos avisos de queda de preço.
        </p>
      </div>
    </div>
  )
}
