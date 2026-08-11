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
    _migrar_unicidade_de_url()


def _migrar_unicidade_de_url() -> None:
    """Troca a unicidade global de `url` por unicidade de (usuario_id, url).

    Necessário porque o `create_all` não altera tabelas que já existem: um banco
    criado antes do login continuaria com `uq_produto_url`, e aí o segundo
    usuário a cadastrar um link já monitorado levaria 409.

    Só roda no PostgreSQL. O SQLite não sabe remover constraint (exigiria
    recriar a tabela) e, sendo banco descartável de desenvolvimento, apagar o
    arquivo .db resolve.
    """
    from sqlalchemy import inspect, text

    if _e_sqlite:
        return

    inspetor = inspect(engine)
    if "produtos" not in set(inspetor.get_table_names()):
        return

    existentes = {r["name"] for r in inspetor.get_unique_constraints("produtos")}

    try:
        with engine.begin() as conexao:
            if "uq_produto_url" in existentes:
                conexao.execute(text("ALTER TABLE produtos DROP CONSTRAINT uq_produto_url"))
                logger.info("Restrição uq_produto_url removida.")
            if "uq_produto_usuario_url" not in existentes:
                conexao.execute(
                    text(
                        "ALTER TABLE produtos ADD CONSTRAINT uq_produto_usuario_url "
                        "UNIQUE (usuario_id, url)"
                    )
                )
                logger.info("Restrição uq_produto_usuario_url criada.")
    except Exception:
        # Um banco em estado inesperado não pode impedir a API de subir; o pior
        # caso é a unicidade continuar global, que é o comportamento antigo.
        logger.exception("Não foi possível migrar a unicidade de URL.")


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
