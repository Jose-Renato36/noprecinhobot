"""Contratos de entrada e saída da API (Pydantic v2)."""

from __future__ import annotations

import re
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from .models import StatusProduto


class Base(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# --------------------------------------------------------------------------- #
# Usuário
# --------------------------------------------------------------------------- #
class UsuarioResumo(Base):
    id: int
    nome: str
    email: EmailStr


# O bcrypt ignora o que passar de 72 bytes; limitar aqui evita a falsa impressão
# de que uma senha muito longa está sendo usada por inteiro.
SENHA = Field(min_length=8, max_length=72)


class UsuarioCriar(BaseModel):
    nome: str = Field(min_length=1, max_length=120)
    email: EmailStr
    senha: str = SENHA


class LoginPedido(BaseModel):
    email: EmailStr
    senha: str = Field(min_length=1, max_length=72)


class TokenResposta(BaseModel):
    token: str
    tipo: str = "bearer"
    expira_em_minutos: int
    usuario: UsuarioResumo


# --------------------------------------------------------------------------- #
# Produto
# --------------------------------------------------------------------------- #
class ProdutoCriar(BaseModel):
    url: str = Field(min_length=8, max_length=2000)
    preco_alvo: Decimal = Field(gt=0, le=Decimal("9999999.99"))
    # O dono sai do token, nunca do corpo da requisição: aceitar `usuario_id`
    # aqui permitiria cadastrar produto na conta de outra pessoa.

    @field_validator("url")
    @classmethod
    def validar_url(cls, valor: str) -> str:
        valor = valor.strip()
        if not re.match(r"^https?://\S+\.\S+", valor, re.I):
            raise ValueError("Informe uma URL completa, começando com http:// ou https://")
        return valor

    @field_validator("preco_alvo")
    @classmethod
    def duas_casas(cls, valor: Decimal) -> Decimal:
        return valor.quantize(Decimal("0.01"))


class ProdutoAtualizar(BaseModel):
    preco_alvo: Decimal | None = Field(default=None, gt=0, le=Decimal("9999999.99"))
    nome: str | None = Field(default=None, min_length=1, max_length=290)

    @field_validator("preco_alvo")
    @classmethod
    def duas_casas(cls, valor: Decimal | None) -> Decimal | None:
        return valor.quantize(Decimal("0.01")) if valor is not None else None


class ProdutoResposta(Base):
    id: int
    nome: str
    url: str
    imagem_url: str | None
    loja: str | None
    preco_alvo: Decimal
    preco_atual: Decimal | None
    preco_inicial: Decimal | None
    moeda: str
    status: StatusProduto
    ultimo_erro: str | None
    criado_em: datetime
    ultima_coleta_em: datetime | None
    usuario: UsuarioResumo | None = None

    # Memória do scraper adaptativo — mostrada no painel para dar visibilidade
    # de *como* aquele preço foi obtido.
    fonte_preco: str | None = None
    seletor_preco: str | None = None
    perfil_http: str | None = None
    confianca: float | None = None

    # Campos derivados, preenchidos pela API para o painel não precisar calcular.
    variacao_percentual: float | None = None
    distancia_do_alvo: Decimal | None = None
    total_coletas: int = 0
    menor_preco: Decimal | None = None
    maior_preco: Decimal | None = None


# --------------------------------------------------------------------------- #
# Histórico
# --------------------------------------------------------------------------- #
class PontoHistorico(Base):
    id: int
    preco: Decimal
    disponivel: bool
    coletado_em: datetime


class HistoricoResposta(BaseModel):
    produto_id: int
    preco_alvo: Decimal
    pontos: list[PontoHistorico]
    menor_preco: Decimal | None = None
    maior_preco: Decimal | None = None
    preco_medio: Decimal | None = None


# --------------------------------------------------------------------------- #
# Alerta
# --------------------------------------------------------------------------- #
class ProdutoMini(Base):
    id: int
    nome: str
    url: str
    imagem_url: str | None


class AlertaResposta(Base):
    id: int
    produto_id: int
    preco_disparo: Decimal
    preco_alvo: Decimal
    mensagem: str
    lido: bool
    email_enviado: bool
    criado_em: datetime
    produto: ProdutoMini | None = None


# --------------------------------------------------------------------------- #
# Painel / operações
# --------------------------------------------------------------------------- #
class Resumo(BaseModel):
    total_produtos: int
    aguardando: int
    alvo_atingido: int
    pausados: int
    com_erro: int
    alertas_nao_lidos: int
    total_coletas: int
    economia_potencial: Decimal
    ultima_coleta_em: datetime | None
    proxima_coleta_em: datetime | None
    intervalo_minutos: int
    agendador_ativo: bool
    # O painel usa isto para não anunciar "e-mail não enviado" em cada alerta
    # quando o envio está desligado de propósito.
    email_ativo: bool = False


class ResultadoColetaResposta(BaseModel):
    produto_id: int
    nome: str
    sucesso: bool
    preco: float | None
    alerta_gerado: bool
    email_enviado: bool
    erro: str | None


class RodadaResposta(BaseModel):
    iniciada_em: str
    total: int
    sucessos: int
    falhas: int
    alertas_gerados: int
    resultados: list[ResultadoColetaResposta]


class PreviaProduto(BaseModel):
    """Resultado de um teste de URL, antes de cadastrar."""

    nome: str | None
    preco: Decimal | None
    imagem_url: str | None
    loja: str | None
    moeda: str
    disponivel: bool
    fonte: str | None = None
    confianca: float = 0.0
    fontes_concordantes: int = 0
    perfil: str | None = None


class SaudeLoja(BaseModel):
    """Diagnóstico por loja: serve para detectar quando um site mudou de layout."""

    loja: str
    total_produtos: int
    com_erro: int
    taxa_sucesso: float
    fonte_predominante: str | None
    confianca_media: float | None
    ultima_coleta_em: datetime | None
