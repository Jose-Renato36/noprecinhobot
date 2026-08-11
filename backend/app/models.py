"""Entidades do sistema: Usuário, Produto, Histórico de Preço, Alerta."""

from __future__ import annotations

import enum
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


def agora() -> datetime:
    return datetime.now(timezone.utc)


class StatusProduto(str, enum.Enum):
    AGUARDANDO = "aguardando"
    ALVO_ATINGIDO = "alvo_atingido"
    PAUSADO = "pausado"
    ERRO = "erro"


class Usuario(Base):
    """Dono dos produtos monitorados e destinatário dos alertas por e-mail."""

    __tablename__ = "usuarios"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    nome: Mapped[str] = mapped_column(String(120), nullable=False)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    # Anulável de propósito: contas criadas antes do login existir ficam sem hash
    # e simplesmente não conseguem entrar, em vez de quebrarem a migração.
    senha_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=agora)

    produtos: Mapped[list["Produto"]] = relationship(back_populates="usuario")


class Produto(Base):
    __tablename__ = "produtos"
    # A unicidade é por usuário, não global: duas pessoas precisam poder
    # monitorar o mesmo produto. Antes do login, isto era só `url`, o que faria
    # o segundo usuário receber 409 ao cadastrar um link que outro já seguia.
    __table_args__ = (UniqueConstraint("usuario_id", "url", name="uq_produto_usuario_url"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    nome: Mapped[str] = mapped_column(String(300), nullable=False)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    imagem_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    loja: Mapped[str | None] = mapped_column(String(120), nullable=True)

    preco_alvo: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    preco_atual: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    preco_inicial: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    moeda: Mapped[str] = mapped_column(String(8), default="BRL")

    status: Mapped[StatusProduto] = mapped_column(
        Enum(StatusProduto, native_enum=False, length=20),
        default=StatusProduto.AGUARDANDO,
        nullable=False,
    )
    ultimo_erro: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Memória do scraper: o que funcionou na última coleta bem-sucedida.
    # É isto que permite ao scraper se reconfigurar sozinho quando a loja muda.
    seletor_preco: Mapped[str | None] = mapped_column(Text, nullable=True)
    fonte_preco: Mapped[str | None] = mapped_column(String(30), nullable=True)
    perfil_http: Mapped[str | None] = mapped_column(String(20), nullable=True)
    confianca: Mapped[float | None] = mapped_column(Numeric(4, 3), nullable=True)

    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=agora)
    atualizado_em: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=agora, onupdate=agora
    )
    ultima_coleta_em: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    usuario_id: Mapped[int | None] = mapped_column(
        ForeignKey("usuarios.id", ondelete="SET NULL"), nullable=True
    )
    usuario: Mapped["Usuario | None"] = relationship(back_populates="produtos")

    historico: Mapped[list["HistoricoPreco"]] = relationship(
        back_populates="produto",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="HistoricoPreco.coletado_em",
    )
    alertas: Mapped[list["Alerta"]] = relationship(
        back_populates="produto",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="Alerta.criado_em.desc()",
    )

    @property
    def monitorando(self) -> bool:
        return self.status != StatusProduto.PAUSADO


class HistoricoPreco(Base):
    """Um registro por coleta: produto, preço e data/hora."""

    __tablename__ = "historico_precos"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    produto_id: Mapped[int] = mapped_column(
        ForeignKey("produtos.id", ondelete="CASCADE"), nullable=False, index=True
    )
    preco: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    disponivel: Mapped[bool] = mapped_column(Boolean, default=True)
    coletado_em: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=agora, index=True
    )

    produto: Mapped["Produto"] = relationship(back_populates="historico")


class Alerta(Base):
    """Gerado quando o preço coletado atinge (ou fica abaixo do) preço-alvo."""

    __tablename__ = "alertas"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    produto_id: Mapped[int] = mapped_column(
        ForeignKey("produtos.id", ondelete="CASCADE"), nullable=False, index=True
    )
    preco_disparo: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    preco_alvo: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    mensagem: Mapped[str] = mapped_column(Text, nullable=False)
    lido: Mapped[bool] = mapped_column(Boolean, default=False)
    email_enviado: Mapped[bool] = mapped_column(Boolean, default=False)
    criado_em: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=agora, index=True
    )

    produto: Mapped["Produto"] = relationship(back_populates="alertas")


class DemoProduto(Base):
    """Catálogo da loja de demonstração servida pela própria API.

    Não faz parte do domínio do NoPrecinhoBot: existe só para que o scraper tenha
    páginas HTML reais para raspar durante a apresentação, sem depender de sites
    externos que bloqueiam robôs.
    """

    __tablename__ = "demo_produtos"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    slug: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)
    nome: Mapped[str] = mapped_column(String(300), nullable=False)
    descricao: Mapped[str] = mapped_column(Text, default="")
    imagem_url: Mapped[str] = mapped_column(Text, default="")
    preco_base: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    fator_promocao: Mapped[float] = mapped_column(Numeric(6, 3), default=1.0)
