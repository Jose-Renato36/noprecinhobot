"""Autenticação: hash de senha, emissão de JWT e a dependência que protege as rotas.

O token é um JWT assinado com `SECRET_KEY`. Não há sessão no servidor: qualquer
instância da API valida o token sozinha, o que mantém o deploy simples.

Ele chega por duas vias, nesta ordem:

1. **Cookie httpOnly** — é o que o painel usa. Sendo httpOnly, o JavaScript da
   página não consegue lê-lo; um XSS não tem como copiar o token e reusá-lo
   depois de outro lugar, que é justamente o que `localStorage` e
   `sessionStorage` permitiriam (os dois são legíveis por script).
2. **`Authorization: Bearer`** — para clientes que não são navegador: o `/docs`,
   curl, scripts. Aceitar o cabeçalho não enfraquece o cookie, porque quem não
   tem credencial continua não conseguindo emitir token.

A autorização de verdade não mora aqui — mora nas checagens de dono do main.py.
Um token válido diz *quem* é o usuário; dizer *a que ele tem direito* é
responsabilidade de cada rota, e é onde mora o risco real (ler ou apagar o
produto de outra pessoa trocando o id na URL).
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt
from fastapi import Depends, HTTPException, Request, Response, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from .config import config
from .database import get_db
from .models import Usuario

logger = logging.getLogger(__name__)

ALGORITMO = "HS256"

# auto_error=False para devolvermos uma mensagem em português em vez do 403 seco
# que o HTTPBearer levanta sozinho quando o cabeçalho falta.
esquema_bearer = HTTPBearer(auto_error=False)

# O bcrypt só considera os primeiros 72 bytes e, desde a versão 4, levanta erro
# se receber mais que isso. Truncar aqui (nos dois caminhos, hash e conferência)
# mantém o comportamento consistente.
LIMITE_BCRYPT = 72


def _preparar(senha: str) -> bytes:
    return senha.encode("utf-8")[:LIMITE_BCRYPT]


def hash_senha(senha: str) -> str:
    return bcrypt.hashpw(_preparar(senha), bcrypt.gensalt()).decode("utf-8")


def conferir_senha(senha: str, hash_armazenado: str | None) -> bool:
    """Compara senha e hash. Nunca levanta exceção — devolve False e pronto.

    `hash_armazenado` pode ser None para usuários criados antes do login existir;
    esses simplesmente não conseguem entrar até definirem uma senha.
    """
    if not hash_armazenado:
        return False
    try:
        return bcrypt.checkpw(_preparar(senha), hash_armazenado.encode("utf-8"))
    except (ValueError, TypeError):
        return False


def criar_token(usuario: Usuario) -> str:
    agora = datetime.now(timezone.utc)
    return jwt.encode(
        {
            "sub": str(usuario.id),
            "email": usuario.email,
            "iat": agora,
            "exp": agora + timedelta(minutes=config.JWT_EXPIRA_MINUTOS),
        },
        config.SECRET_KEY,
        algorithm=ALGORITMO,
    )


def gravar_cookie(resposta: Response, token: str) -> None:
    """Entrega o token num cookie que o JavaScript da página não enxerga."""
    resposta.set_cookie(
        key=config.COOKIE_NOME,
        value=token,
        httponly=True,
        secure=config.COOKIE_SEGURO,
        samesite=config.COOKIE_SAMESITE,
        # Sem max_age o navegador trata como cookie de sessão e o descarta ao
        # fechar. Com COOKIE_PERSISTENTE, dura o mesmo que o token.
        max_age=config.JWT_EXPIRA_MINUTOS * 60 if config.COOKIE_PERSISTENTE else None,
        path="/",
    )


def apagar_cookie(resposta: Response) -> None:
    """Os atributos precisam bater com os da gravação, senão o navegador
    entende que é outro cookie e mantém o original."""
    resposta.delete_cookie(
        key=config.COOKIE_NOME,
        path="/",
        httponly=True,
        secure=config.COOKIE_SEGURO,
        samesite=config.COOKIE_SAMESITE,
    )


def _nao_autorizado(detalhe: str) -> HTTPException:
    return HTTPException(
        status.HTTP_401_UNAUTHORIZED,
        detalhe,
        headers={"WWW-Authenticate": "Bearer"},
    )


def usuario_atual(
    request: Request,
    credencial: HTTPAuthorizationCredentials | None = Depends(esquema_bearer),
    db: Session = Depends(get_db),
) -> Usuario:
    """Dependência obrigatória: resolve o usuário do token ou devolve 401."""
    # O cookie tem precedência: é o caminho do navegador, e o único em que o
    # token não fica exposto a script na página.
    token = request.cookies.get(config.COOKIE_NOME)
    if not token and credencial is not None:
        token = credencial.credentials
    if not token:
        raise _nao_autorizado("Autenticação necessária.")

    try:
        dados = jwt.decode(token, config.SECRET_KEY, algorithms=[ALGORITMO])
    except jwt.ExpiredSignatureError:
        raise _nao_autorizado("Sessão expirada. Entre novamente.") from None
    except jwt.PyJWTError:
        raise _nao_autorizado("Token inválido.") from None

    try:
        usuario_id = int(dados.get("sub", ""))
    except (TypeError, ValueError):
        raise _nao_autorizado("Token inválido.") from None

    usuario = db.get(Usuario, usuario_id)
    if usuario is None:
        # Token bem assinado mas o usuário sumiu (conta removida, banco trocado).
        raise _nao_autorizado("Usuário não encontrado.")
    return usuario
