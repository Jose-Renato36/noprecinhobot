"""Conexão com o banco e sessão do SQLAlchemy."""

from __future__ import annotations

import logging
import warnings
from collections.abc import Iterator

from sqlalchemy import create_engine, event
from sqlalchemy.exc import SAWarning
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import config

logger = logging.getLogger(__name__)

# O SQLite não tem tipo decimal nativo; o SQLAlchemy avisa sobre isso a cada boot.
# Os valores continuam corretos (2 casas), então silenciamos só esse aviso.
warnings.filterwarnings("ignore", r".*does \*not\* support Decimal objects natively.*", SAWarning)

_e_sqlite = config.DATABASE_URL.startswith("sqlite")

engine = create_engine(
    config.DATABASE_URL,
    echo=False,
    future=True,
    pool_pre_ping=not _e_sqlite,
    connect_args={"check_same_thread": False} if _e_sqlite else {},
)

if _e_sqlite:

    @event.listens_for(engine, "connect")
    def _ativar_foreign_keys(dbapi_connection, _registro) -> None:
        """O SQLite ignora ON DELETE CASCADE a menos que as FKs sejam ligadas
        em cada conexão. Sem isto, apagar um produto deixaria histórico e
        alertas órfãos (no PostgreSQL isso já é o comportamento padrão)."""
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


class Base(DeclarativeBase):
    pass


def get_db() -> Iterator[Session]:
    """Dependência do FastAPI: entrega uma sessão e garante o fechamento."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def criar_tabelas() -> None:
    from . import models  # noqa: F401  (registra os modelos no metadata)

    Base.metadata.create_all(bind=engine)
    _adicionar_colunas_novas()


def _adicionar_colunas_novas() -> None:
    """Migração mínima, só aditiva: cria colunas novas em tabelas que já existem.

    O `create_all` cria tabelas mas nunca altera as existentes, então um banco
    criado por uma versão anterior ficaria sem as colunas novas. Um Alembic
    completo seria exagero aqui; isto resolve o caso real (adicionar coluna
    anulável) e não toca em nada que já esteja no banco.
    """
    from sqlalchemy import inspect, text

    inspetor = inspect(engine)
    tabelas_existentes = set(inspetor.get_table_names())

    with engine.begin() as conexao:
        for tabela in Base.metadata.sorted_tables:
            if tabela.name not in tabelas_existentes:
                continue
            atuais = {c["name"] for c in inspetor.get_columns(tabela.name)}
            for coluna in tabela.columns:
                if coluna.name in atuais or not coluna.nullable:
                    continue
                tipo = coluna.type.compile(dialect=engine.dialect)
                conexao.execute(
                    text(f'ALTER TABLE "{tabela.name}" ADD COLUMN "{coluna.name}" {tipo}')
                )
                logger.info("Coluna %s.%s adicionada.", tabela.name, coluna.name)
