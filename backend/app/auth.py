"""Autenticação: hash de senha, emissão de JWT e a dependência que protege as rotas.

O token é um JWT assinado com `SECRET_KEY` e carregado no cabeçalho
`Authorization: Bearer <token>`. Não há sessão no servidor: qualquer instância da
API valida o token sozinha, o que mantém o deploy simples.

A autorização de verdade não mora aqui — mora em `usuario_dono`, no main.py. Um
token válido diz *quem* é o usuário; dizer *a que ele tem direito* é
responsabilidade de cada rota, e é onde mora o risco real (ler ou apagar o
produto de outra pessoa trocando o id na URL).
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt
from fastapi import Depends, HTTPException, status
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


def _nao_autorizado(detalhe: str) -> HTTPException:
    return HTTPException(
        status.HTTP_401_UNAUTHORIZED,
        detalhe,
        headers={"WWW-Authenticate": "Bearer"},
    )


def usuario_atual(
    credencial: HTTPAuthorizationCredentials | None = Depends(esquema_bearer),
    db: Session = Depends(get_db),
) -> Usuario:
    """Dependência obrigatória: resolve o usuário do token ou devolve 401."""
    if credencial is None:
        raise _nao_autorizado("Autenticação necessária.")

    try:
        dados = jwt.decode(credencial.credentials, config.SECRET_KEY, algorithms=[ALGORITMO])
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
